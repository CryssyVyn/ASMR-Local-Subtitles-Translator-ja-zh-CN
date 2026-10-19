"""Optional NVIDIA CUDA runtime, pinned to the same llama.cpp release."""
import concurrent.futures as cf
import json
import urllib.request
import urllib.parse
from setup_runtime import BASE, download, safe_extract

CUDA_SPECS = [
    {'name': 'llama-b11515-cuda12.zip', 'size': 265197186,
     'sha256': '9381b20187aef342cf45b8f1a8605e66c244fc0a33176a2406655221522d992e',
     'url': 'https://github.com/ggml-org/llama.cpp/releases/download/b11515/llama-b11515-bin-win-cuda-12.4-x64.zip',
     'chunk_size': 1048576, 'workers': 32},
    {'name': 'llama-b11515-cudart12.zip', 'size': 391443627,
     'sha256': '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6',
     'url': 'https://github.com/ggml-org/llama.cpp/releases/download/b11515/cudart-llama-bin-win-cuda-12.4-x64.zip',
     'chunk_size': 1048576, 'workers': 32},
]

def main():
    # Resolve each official release asset once, then fetch ranges from the
    # signed blob URL without consuming the GitHub API rate limit.
    specs = []
    for original in CUDA_SPECS:
        spec = dict(original)
        request = urllib.request.Request(spec['url'],
            headers={'Accept': 'application/octet-stream', 'Range': 'bytes=0-0',
                     'User-Agent': 'ASMRRealtime-Local/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            resolved = response.geturl()
        if urllib.parse.urlsplit(resolved).hostname != 'release-assets.githubusercontent.com':
            raise RuntimeError('GitHub did not resolve to the official release asset host')
        spec.update(url=resolved, range_query=True, workers=16)
        specs.append(spec)
    results = {}
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        pending = {pool.submit(download, spec): spec for spec in specs}
        for future in cf.as_completed(pending):
            spec = pending[future]
            path = future.result()
            safe_extract(path, BASE / 'llama-cuda')
            results[spec['name']] = {'path': str(path), 'sha256': spec['sha256']}
    (BASE / 'cuda_ready.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('CUDA runtime ready; no system CUDA installation changed.', flush=True)

if __name__ == '__main__':
    main()
