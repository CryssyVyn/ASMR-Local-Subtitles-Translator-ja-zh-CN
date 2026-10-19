"""First-install behavior independent of local models and personal settings."""
import json
import tempfile
import unittest
from pathlib import Path
from release_setup import initialize_settings


class FirstInstallTests(unittest.TestCase):
    def test_fresh_install_uses_bundled_glossary_and_selected_device(self):
        source = Path(__file__).parent / '词库_保守版_ja_zh.json'
        glossary = json.loads(source.read_text(encoding='utf-8-sig'))
        self.assertEqual(len(glossary), 312)
        self.assertTrue(all(set(item) == {'ja', 'zh'} for item in glossary))
        for selected, expected in [('Auto', 'auto'), ('CUDA', 'cuda'), ('Vulkan', 'vulkan'), ('CPU', 'cpu')]:
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                (base / source.name).write_bytes(source.read_bytes())
                self.assertTrue(initialize_settings(base, selected))
                settings = json.loads((base / '作品设置.json').read_text(encoding='utf-8'))
                self.assertEqual(settings['glossary'], glossary)
                self.assertEqual(settings['translation_backend'], expected)

    def test_reinstall_preserves_personal_settings_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            path = base / '作品设置.json'
            original = b'{"scene":"custom","glossary":[],"translation_backend":"cpu"}\n'
            path.write_bytes(original)
            self.assertFalse(initialize_settings(base, 'CUDA'))
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
