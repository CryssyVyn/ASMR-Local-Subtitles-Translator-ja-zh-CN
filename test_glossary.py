import json
import tempfile
import unittest
from pathlib import Path

from glossary import (validate_glossary, merge_glossaries, read_glossary_files,
                      select_glossary, MAX_PROMPT_CHARS, MAX_PROMPT_TERMS)


class GlossaryTests(unittest.TestCase):
    def test_large_library_and_usage_notes_survive_json_roundtrip(self):
        terms=[{'ja':f'用語{i}','zh':f'词条{i}'} for i in range(326)]
        terms.append({'ja':'僕','zh':'我 / 你','usage_note':'根据说话者和上下文判断。'})
        clean=validate_glossary(terms)
        self.assertEqual(json.loads(json.dumps(clean,ensure_ascii=False)),terms)
        for invalid in ([{'ja':'','zh':'甲'}], [{'ja':'甲','zh':'乙','usage_note':1}],
                        [{'ja':'甲','zh':'乙','usage_note':'说'*601}]):
            with self.assertRaises(ValueError):validate_glossary(invalid)

    def test_annotation_overrides_fixed_translation_in_either_import_order(self):
        core=[{'ja':'旦那様','zh':'老爷'}]
        note=[{'ja':'旦那様','zh':'老爷 / 老公','usage_note':'根据角色关系选择。'}]
        self.assertEqual(merge_glossaries(core,note),note)
        self.assertEqual(merge_glossaries(note,core),note)
        self.assertEqual(merge_glossaries(note,note),note)
        self.assertEqual(merge_glossaries(core,[{'ja':'旦那様','zh':'先生'}]),
                         [{'ja':'旦那様','zh':'先生'}])

    def test_multi_file_import_with_bom_and_rejection_of_invalid_file(self):
        with tempfile.TemporaryDirectory() as folder:
            first=Path(folder)/'core.json';second=Path(folder)/'notes.json'
            core=[{'ja':'先輩','zh':'前辈'}]
            note=[{'ja':'僕','zh':'我 / 你','usage_note':'结合语境。'}]
            first.write_text(json.dumps(core,ensure_ascii=False),encoding='utf-8-sig')
            second.write_text(json.dumps(note,ensure_ascii=False),encoding='utf-8')
            self.assertEqual(read_glossary_files([first,second]),core+note)
            second.write_text('{invalid',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'notes.json'):
                read_glossary_files([first,second])

    def test_longer_phrase_wins_but_separate_short_occurrence_is_kept(self):
        terms=[{'ja':'兄','zh':'兄长'}, {'ja':'お兄ちゃん','zh':'哥哥'},
               {'ja':'先輩','zh':'前辈'}]
        self.assertEqual(select_glossary('お兄ちゃん、休んで。',terms),[terms[1]])
        self.assertEqual(select_glossary('お兄ちゃんと兄。',terms),[terms[1],terms[0]])
        self.assertEqual(select_glossary('今日は休みです。',terms),[])

    def test_width_normalization_and_prompt_limits(self):
        term={'ja':'マッサージ','zh':'按摩'}
        self.assertEqual(select_glossary('ﾏｯｻｰｼﾞです。',[term]),[term])
        terms=[{'ja':str(i),'zh':'释义','usage_note':'说明'*100} for i in range(12)]
        selected=select_glossary(' '.join(str(i) for i in range(12)),terms)
        self.assertLessEqual(len(selected),MAX_PROMPT_TERMS)
        self.assertLessEqual(len(json.dumps(selected,ensure_ascii=False)),MAX_PROMPT_CHARS)
        self.assertEqual(select_glossary('マッサージ',[term],0),[])

    def test_short_katakana_does_not_match_inside_a_different_word(self):
        term={'ja':'イク','zh':'候选译法'}
        self.assertEqual(select_glossary('マイクを調整します。',[term]),[])
        self.assertEqual(select_glossary('イク。',[term]),[term])
        self.assertEqual(select_glossary('マイク。イク。',[term]),[term])


if __name__=='__main__':
    unittest.main()
