"""Initialize first-run settings without importing audio/GPU dependencies."""
import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def initialize_settings(base=BASE, backend='Auto'):
    base = Path(base)
    path = base / '作品设置.json'
    if path.exists():
        print('Existing settings preserved.')
        return False
    glossary = json.loads((base / '词库_保守版_ja_zh.json').read_text(encoding='utf-8-sig'))
    if len(glossary) != 312:
        raise ValueError('The bundled glossary must contain 312 entries.')
    device = {'Auto': 'auto', 'CUDA': 'cuda', 'Vulkan': 'vulkan', 'CPU': 'cpu'}[backend]
    settings = {'glossary': glossary, 'translation_backend': device, 'cpu_llm_threads': 8}
    # Exclusive creation prevents overwriting settings created during setup.
    with path.open('x', encoding='utf-8') as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print('Initialized settings with the 312-entry glossary.')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('Auto', 'CUDA', 'Vulkan', 'CPU'), default='Auto')
    initialize_settings(backend=parser.parse_args().backend)
