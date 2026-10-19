"""Local glossary import and bounded, source-specific translation references."""
import json
import re
import unicodedata
from pathlib import Path

MAX_GLOSSARY_TERMS = 5000
MAX_PROMPT_TERMS = 8
MAX_PROMPT_CHARS = 800
MAX_IMPORT_BYTES = 8 * 1024 * 1024


def validate_glossary(glossary):
    if not isinstance(glossary, list) or len(glossary) > MAX_GLOSSARY_TERMS:
        raise ValueError(f'术语表应为最多 {MAX_GLOSSARY_TERMS} 项的 JSON 数组')
    clean = []
    for index, item in enumerate(glossary, 1):
        if not isinstance(item, dict):
            raise ValueError(f'第 {index} 项需要 ja（日文）和 zh（中文）字段')
        term = {}
        for key, limit in (('ja', 120), ('zh', 240), ('usage_note', 600)):
            if key == 'usage_note' and key not in item:
                continue
            value = item.get(key)
            if not isinstance(value, str):
                raise ValueError(f'第 {index} 项的 {key} 必须是字符串')
            value = value.strip()
            if not value and key != 'usage_note':
                raise ValueError(f'第 {index} 项的 {key} 不能为空')
            if len(value) > limit:
                raise ValueError(f'第 {index} 项的 {key} 最多 {limit} 个字符')
            if value:
                term[key] = value
        clean.append(term)
    return clean


def merge_glossaries(existing, incoming):
    """Merge by Japanese key; an annotated reading takes priority in either order."""
    merged = {}
    for term in validate_glossary(existing) + validate_glossary(incoming):
        key = unicodedata.normalize('NFKC', term['ja'])
        previous = merged.get(key)
        if previous and previous.get('usage_note') and not term.get('usage_note'):
            continue
        merged[key] = term
    return validate_glossary(list(merged.values()))


def read_glossary_files(paths):
    """Read every file before the caller changes its editor or saved settings."""
    merged = []
    for filename in paths:
        path = Path(filename)
        try:
            # Read at most the allowed size even if the file grows during import.
            with path.open('rb') as stream:
                raw = stream.read(MAX_IMPORT_BYTES + 1)
            if len(raw) > MAX_IMPORT_BYTES:
                raise ValueError('词库文件不能超过 8 MB')
            incoming = json.loads(raw.decode('utf-8-sig'))
            merged = merge_glossaries(merged, incoming)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f'{path.name}：{exc}') from exc
    return merged


def matching_spans(source, key):
    katakana = re.fullmatch(r'[\u30a1-\u30fa\u30fc]+', key) is not None
    position = 0
    while True:
        start = source.find(key, position)
        if start < 0:
            return
        end = start + len(key)
        position = end
        if katakana:
            # E.g. イク must not fire inside マイク. Inflected/missed forms
            # remain for the model to translate normally, without a false hint.
            before = source[start - 1:start] if start else ''
            after = source[end:end + 1]
            if ((before and re.fullmatch(r'[\u30a1-\u30fa\u30fc]', before)) or
                    (after and re.fullmatch(r'[\u30a1-\u30fa\u30fc]', after))):
                continue
        yield start, end


def select_glossary(source, glossary, char_budget=MAX_PROMPT_CHARS):
    """Prefer complete longer matches; never inject the entire library or history."""
    source = unicodedata.normalize('NFKC', source)
    candidates = []
    for index, term in enumerate(glossary):
        key = unicodedata.normalize('NFKC', term['ja'])
        spans = list(matching_spans(source, key))
        if spans:
            candidates.append((-len(key), spans[0][0], index, term, spans))
    selected, covered = [], []
    used = 2  # JSON array brackets.
    for _, _, _, term, spans in sorted(candidates, key=lambda row: row[:3]):
        if all(any(left <= a and b <= right for left, right in covered) for a, b in spans):
            continue
        size = len(json.dumps(term, ensure_ascii=False)) + (2 if selected else 0)
        if used + size > min(char_budget, MAX_PROMPT_CHARS):
            continue
        selected.append(term)
        covered.extend(spans)
        used += size
        if len(selected) == MAX_PROMPT_TERMS:
            break
    return selected
