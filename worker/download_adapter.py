"""download_adapter.py — 第 2 人: 統一下載介面 (curl / dfget)

對接第 5 人 worker/downloader.py 的介面契約:

    download(url, output, mode, progress_callback) -> bool   # 成功回傳 True

worker 會 `import download_adapter` 並呼叫 download(...)。
把本檔放進 repo 的 worker/ 目錄即會被自動採用 (worker 的 Dockerfile 是 COPY . .)。

mode:
    "curl"  -> 直接 GET origin file server (無 P2P)
    "dfget" -> 走 Dragonfly P2P (需已安裝 dfget + Dragonfly 叢集)

另提供 download_file() 回傳含計時/checksum 的 dict, 給第 7 人 benchmark 與自我測試。
"""
import os
import time
import shutil
import hashlib
import subprocess
import urllib.request


def sha256sum(path, chunk=1 << 20):
    """算檔案的 SHA-256 指紋。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def _content_length(url, timeout=10):
    """用 HEAD 取得檔案大小, 算進度用; 取不到回傳 None。"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except Exception:
        return None


def _build_cmd(url, output, mode):
    if mode == "dfget":
        return [os.getenv("DFGET_BIN", "dfget"), "-O", output, url]
    if mode == "curl":
        return ["curl", "-fSL", "-o", output, url]
    raise ValueError(f"unsupported mode: {mode}")


def download(url, output, mode="curl", progress_callback=None, timeout=1800):
    """下載一個檔案。成功回傳 True, 失敗回傳 False。

    參數 (與第 5 人 worker 的呼叫一致):
        url               : 檔案來源 (curl/dfget 都用同一個 origin URL)
        output            : 下載後存檔路徑
        mode              : "curl" 或 "dfget"
        progress_callback : 可選, callback(pct:int)，下載中回報 0~100 給 Dashboard 進度條
        timeout           : 逾時秒數
    """
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    real_bin = os.getenv("DFGET_BIN", "dfget") if mode == "dfget" else "curl"
    if shutil.which(real_bin) is None:
        # 該模式的工具不存在 (例如尚未安裝 Dragonfly dfget)
        return False

    try:
        cmd = _build_cmd(url, output, mode)
    except ValueError:
        return False

    total = _content_length(url)
    start = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return False

    last = 0.0
    while proc.poll() is None:
        time.sleep(0.3)
        now = time.time()
        if progress_callback and total and now - last >= 1.0 and os.path.exists(output):
            last = now
            pct = int(os.path.getsize(output) / total * 100)
            progress_callback(max(1, min(99, pct)))
        if now - start > timeout:
            proc.kill()
            return False

    ok = (proc.returncode == 0 and os.path.exists(output))
    if ok and progress_callback:
        progress_callback(100)
    return ok


def download_file(url, output, mode="curl", expected_sha256=None, timeout=1800):
    """給 benchmark / 自我測試用: 回傳含 duration / checksum 的 dict。"""
    start = time.time()
    ok = download(url, output, mode=mode, timeout=timeout)
    res = {
        "url": url,
        "mode": mode,
        "success": ok,
        "duration_sec": round(time.time() - start, 3),
        "size_bytes": os.path.getsize(output) if ok and os.path.exists(output) else 0,
    }
    if ok and expected_sha256:
        actual = sha256sum(output)
        res["sha256"] = actual
        res["checksum_ok"] = (actual == expected_sha256)
    return res


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 3:
        print("usage: python download_adapter.py <url> <output> [mode] [expected_sha256]")
        sys.exit(1)
    url = sys.argv[1]
    out = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "curl"
    exp = sys.argv[4] if len(sys.argv) > 4 else None
    print(json.dumps(download_file(url, out, mode, exp), indent=2))
