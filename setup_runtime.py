"""Pinned, resumable runtime download. Only downloads software/model bytes."""
from pathlib import Path
import concurrent.futures as cf
import hashlib
import json
import os
import time
import threading
import urllib.request
import zipfile
import zlib

BASE = Path(__file__).resolve().parent
CHUNK = 16 * 1024 * 1024
SPECS = [
    {
      "name": "llama-b11515-vulkan.zip", "size": 33444820,
      "sha256": "013275bb02719d6de02107d0e1daca91462bfc6385ac56712f43db8418690358",
      "url": "https://api.github.com/repos/ggml-org/llama.cpp/releases/assets/623714589?download=1",
      "extract": "llama", "chunk_size": 1048576, "workers": 32,
    },
    {
      "name": "asmr-zh-cn-q4_k_m.gguf", "size": 5629108768,
      "sha256": "e107f59596e9dfb6bd7d35611c1f49340223f675efa92a8b7f89bd28f94f5e47",
      "url": "https://huggingface.co/mmis1000/asmr-qwen3.5-9b-zh-cn-echo-gguf-v0.1/resolve/0a8504759b493c53bc7a8d57b4ae6b9d00d13b7e/asmr-qwen3.5-9b-zh-cn-echo-gguf-v0.1-q4_k_m.gguf",
      "model": True, "workers": 48,
    },
    {
      "name": "whisper-small-model.bin", "size": 483546902,
      "sha256": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
      "url": "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/model.bin",
      "model": True, "workers": 24, "folder": "models/whisper-small", "filename": "model.bin",
    },
]
def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4*1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def download(spec):
    folder = BASE / (spec.get("folder") or ("models" if spec.get("model") else "downloads"))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / spec.get("filename", spec["name"])
    if target.exists() and target.stat().st_size == spec["size"]:
        if sha256(target) == spec["sha256"]:
            print(spec["name"], "已校验，跳过下载。", flush=True)
            return target
        raise RuntimeError(f"{target.name} 已存在但校验不通过，请保留并更名后重试。")
    chunk = spec.get("chunk_size", CHUNK)
    suffix = ".parts" if chunk == CHUNK else f".parts-{chunk}"
    parts = BASE / "downloads" / (spec["name"] + suffix)
    parts.mkdir(parents=True, exist_ok=True)
    total = (spec["size"] + chunk - 1) // chunk
    stop = threading.Event()
    def fetch(i):
        first = i * chunk
        last = min(spec["size"], first + chunk) - 1
        expected = last - first + 1
        path = parts / f"{i:05}.part"
        temp = parts / f"{i:05}.tmp"
        if path.exists() and path.stat().st_size == expected:
            return i
        if temp.exists() and temp.stat().st_size > expected:
            raise RuntimeError("分段长度异常，保留临时文件供核对")
        errors = []
        for attempt in range(10):
            if stop.is_set():
                raise RuntimeError("下载已停止")
            offset = temp.stat().st_size if temp.exists() else 0
            if offset == expected:
                temp.replace(path)
                return i
            begin = first + offset
            try:
                url = spec["url"]
                if "api.github.com" in url:
                    url += f"&range_start={begin}&range_end={last}"
                elif spec.get('range_query'):
                    url += f"&range_start={begin}&range_end={last}"
                request = urllib.request.Request(url, headers={
                    "Range": f"bytes={begin}-{last}", "User-Agent": "ASMRRealtime-Local/1.0",
                    "Accept": "application/octet-stream"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    if response.status != 206 or response.headers.get("Content-Range", "") != f"bytes {begin}-{last}/{spec['size']}":
                        raise RuntimeError("服务器返回的分段范围不匹配")
                    size = offset
                    with temp.open("ab", buffering=0) as output:
                        while size < expected:
                            if stop.is_set():
                                raise RuntimeError("下载已停止")
                            block = response.read(min(65536, expected-size))
                            if not block:
                                break
                            output.write(block)
                            size += len(block)
                    if size != expected:
                        raise RuntimeError("分段下载中断，将从已有字节继续")
                temp.replace(path)
                return i
            except Exception as exc:
                errors.append(str(exc))
                if stop.wait(min(5, 1 + attempt)):
                    break
        raise RuntimeError(f"{spec['name']} 第 {i} 段失败：{errors[-1]}")
    start = time.monotonic()
    print(f"开始/恢复下载 {spec['name']} · {spec['size']/1e9:.2f} GB", flush=True)
    pool = cf.ThreadPoolExecutor(max_workers=spec.get("workers", 10))
    pending = {pool.submit(fetch, i) for i in range(total)}
    try:
        while pending:
            done, pending = cf.wait(pending, timeout=10, return_when=cf.FIRST_EXCEPTION)
            for future in done:
                future.result()
            downloaded = sum(p.stat().st_size for p in parts.iterdir() if p.suffix in (".part", ".tmp"))
            elapsed = max(1, time.monotonic()-start)
            print(f"{spec['name']}  {downloaded/1024/1024:.1f} MiB / {spec['size']/1024/1024:.1f} MiB ({downloaded/spec['size']:.1%})  已用 {elapsed:.0f} 秒", flush=True)
    except BaseException:
        stop.set()
        for f in pending:
            f.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    temp = target.with_suffix(target.suffix + ".assembling")
    digest = hashlib.sha256()
    with temp.open("wb") as output:
        for i in range(total):
            with (parts / f"{i:05}.part").open("rb") as source:
                for block in iter(lambda: source.read(4*1024*1024), b""):
                    digest.update(block)
                    output.write(block)
    if digest.hexdigest() != spec["sha256"]:
        raise RuntimeError(f"{spec['name']} 完整性校验失败；文件未启用。")
    temp.replace(target)
    print(spec["name"], "SHA256 校验通过。", flush=True)
    # Parts are retained for diagnosis. The user may remove downloads after successful setup.
    return target

def safe_extract(archive, destination):
    destination.mkdir(exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path = (root / info.filename).resolve()
            if not path.is_relative_to(root):
                raise RuntimeError("压缩包路径超出运行目录")
        for info in z.infolist():
            path = root / info.filename
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            if path.is_file() and path.stat().st_size == info.file_size:
                crc = 0
                with path.open("rb") as existing:
                    for block in iter(lambda: existing.read(1024*1024), b""):
                        crc = zlib.crc32(block, crc)
                if crc & 0xffffffff == info.CRC:
                    continue
            z.extract(info, destination)

def main():
    (BASE / 'downloads').mkdir(exist_ok=True)
    (BASE / 'work').mkdir(exist_ok=True)
    # Small tokenizer files are fixed to the same upstream revision.
    whisper = BASE / "models" / "whisper-small"
    whisper.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((BASE / "runtime" / "whisper-checksums.json").read_text(encoding="utf-8"))
    for name, info in metadata.items():
        path = whisper / name
        if path.exists() and sha256(path) == info["sha256"]:
            continue
        url = "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/" + name
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        if len(data) != info["bytes"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise RuntimeError("Whisper 词表校验失败")
        path.write_bytes(data)
    results = {}
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(download, spec): spec for spec in SPECS}
        for task in cf.as_completed(pending):
            spec = pending[task]
            path = task.result()
            if spec.get("extract"):
                print("正在解压", spec["name"], flush=True)
                safe_extract(path, BASE / spec["extract"])
                print("解压完成", spec["extract"], flush=True)
            results[spec["name"]] = {"sha256": spec["sha256"], "path": str(path)}
    (BASE / "runtime_ready.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("核心运行时与识别、翻译模型准备完成。", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("准备失败：", exc, flush=True)
        raise

