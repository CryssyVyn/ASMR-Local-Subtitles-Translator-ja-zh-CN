"""Build a source-and-installer ZIP from an explicit public-file allowlist."""
import hashlib
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parent
PUBLIC_FILES = (
    '.gitattributes', '.gitignore', 'VERSION', 'LICENSE', 'README.md',
    '使用说明.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'RELEASE_NOTES.md',
    'app.py', 'realtime_core.py', 'asmr_chinese_plugin.py', 'alpha_subtitles.py',
    'glossary.py', 'requirements-lock.txt', 'setup_runtime.py',
    'setup_latency_runtime.py', 'release_setup.py', 'install.ps1',
    'build_release.py', 'test_core.py', 'test_glossary.py', 'test_release.py',
    '词库_保守版_ja_zh.json', '安装环境与模型.cmd', '启动本地字幕.cmd',
    '继续下载模型.cmd', 'ASMR本地字幕.exe', 'launcher/Launcher.cs',
    'launcher/build.ps1', 'launcher/ASMR.ico', 'runtime/whisper-checksums.json',
    'vendor/whispering_tiger/__init__.py',
    'vendor/whispering_tiger/transcription_queue.py',
    'vendor/whispering_tiger/LICENSE', 'vendor/whispering_tiger/SOURCE.txt',
)


def build():
    version = (BASE / 'VERSION').read_text(encoding='utf-8').strip()
    name = f'ASMR-Local-Subtitles-v{version}'
    destination = BASE / 'dist'
    destination.mkdir(exist_ok=True)
    archive = destination / f'{name}.zip'
    for item in PUBLIC_FILES:
        if not (BASE / item).is_file():
            raise FileNotFoundError(item)
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for item in PUBLIC_FILES:
            output.write(BASE / item, f'{name}/{item}')
    with zipfile.ZipFile(archive) as output:
        if output.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'{archive.name}: {archive.stat().st_size:,} bytes; {len(PUBLIC_FILES)} public files')
    print(f'SHA256 {digest}')
    return archive


if __name__ == '__main__':
    build()
