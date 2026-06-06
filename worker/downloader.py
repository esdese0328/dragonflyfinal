"""
downloader.py — 下載整合層 (第 5 人 Worker 負責)

這一層的目的：把「實際怎麼下載檔案」這件事跟 worker.py 的排程邏輯隔開。
優先順序：
  1. 如果第 2 人的 download_adapter.py 存在，就用他的 (真正的 curl / dfget)。
  2. 否則使用本檔內建的 curl / dfget 直接呼叫。
  3. 如果連檔案伺服器 / dfget / curl 都沒有 (例如還在本機測試)，
     就退回「模擬下載」模式，讓整條流程 (心跳 -> 進度 -> 完成) 仍可端到端跑起來。

對外只提供一個函式：download(task, progress_cb) -> DownloadResult
"""

import os
import re
import time
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# 設定 (全部可用環境變數覆蓋，方便 Docker / 不同同學的環境)
# ---------------------------------------------------------------------------

# 第 2 人的檔案伺服器位址。實際對接時改成他的 File Server。
FILE_SERVER = os.getenv("FILE_SERVER", "http://file-server")

# 下載模式: "auto" / "dfget" / "curl" / "simulate"
#   auto = 依任務名稱中的 [dfget] / [curl] 關鍵字決定，找不到就用預設
DOWNLOAD_MODE = os.getenv("DOWNLOAD_MODE", "auto").lower()
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "curl").lower()

# 下載暫存目錄
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/dragonfly_downloads")

# dfget 執行檔路徑 (Dragonfly client)
DFGET_BIN = os.getenv("DFGET_BIN", "dfget")

# 進度回報的最小間隔 (秒)，避免太頻繁打 API
PROGRESS_INTERVAL = float(os.getenv("PROGRESS_INTERVAL", "1.5"))


# 常見測試檔大小對照 (用來估算下載進度 %)。單位: bytes
SIZE_TABLE = {
    "100MB": 100 * 1024 * 1024,
    "500MB": 500 * 1024 * 1024,
    "1GB": 1024 * 1024 * 1024,
    "5GB": 5 * 1024 * 1024 * 1024,
    "10GB": 10 * 1024 * 1024 * 1024,
}


@dataclass
class DownloadResult:
    success: bool
    duration: float          # 秒
    message: str = ""
    mode: str = ""           # 實際使用的下載方式


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _parse_size(task_name: str) -> Optional[int]:
    """從任務名稱解析出檔案大小 (bytes)，解析不到回傳 None。"""
    m = re.search(r"(\d+\s*(?:MB|GB))", task_name, re.IGNORECASE)
    if not m:
        return None
    key = m.group(1).replace(" ", "").upper()
    return SIZE_TABLE.get(key)


def _decide_mode(task_name: str) -> str:
    """決定這個任務要用哪種方式下載。"""
    if DOWNLOAD_MODE in ("dfget", "curl", "simulate"):
        return DOWNLOAD_MODE
    # auto: 看任務名稱關鍵字
    low = task_name.lower()
    if "[dfget]" in low:
        return "dfget"
    if "[curl]" in low:
        return "curl"
    return DEFAULT_MODE


def _resolve_url(task: dict) -> str:
    """
    推導出要下載的 URL。
    對接第 2 人時，可改成查 artifacts.json，或讓 API 的 task 直接帶 url 欄位。
    這裡先用「檔案大小」當檔名的慣例。
    """
    # 若未來 API 的 task 物件帶有 url 欄位，優先使用
    if task.get("url"):
        return task["url"]
    m = re.search(r"(\d+\s*(?:MB|GB))", task.get("task_name", ""), re.IGNORECASE)
    fname = (m.group(1).replace(" ", "").upper() if m else "100MB") + ".bin"
    return f"{FILE_SERVER}/{fname}"


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


# ---------------------------------------------------------------------------
# 嘗試載入第 2 人的 adapter
# ---------------------------------------------------------------------------

def _try_external_adapter(task, mode, url, out_path, progress_cb) -> Optional[DownloadResult]:
    """
    若第 2 人的 download_adapter.py 存在，優先使用。
    我們對它的期望介面 (請第 2 人配合)：

        download_adapter.download(url=str, output=str, mode=str,
                                  progress_callback=callable) -> bool/None  (成功為真)

    若簽名不同，這裡會盡量降級嘗試；都失敗就回 None 交回後備流程。
    """
    try:
        import download_adapter  # noqa
    except Exception:
        return None

    func = getattr(download_adapter, "download", None)
    if not callable(func):
        return None

    start = time.time()
    try:
        try:
            ret = func(url=url, output=out_path, mode=mode, progress_callback=progress_cb)
        except TypeError:
            # 退一步用最精簡的簽名
            ret = func(url, out_path)
        ok = True if ret is None else bool(ret)
        return DownloadResult(ok, round(time.time() - start, 2),
                              "via download_adapter", f"adapter/{mode}")
    except Exception as e:
        return DownloadResult(False, round(time.time() - start, 2),
                              f"adapter error: {e}", f"adapter/{mode}")


# ---------------------------------------------------------------------------
# 內建 curl / dfget：用子程序下載，並用「已下載檔案大小 / 預期大小」回報進度
# ---------------------------------------------------------------------------

def _run_with_progress(cmd, out_path, total_size, progress_cb) -> DownloadResult:
    start = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        return DownloadResult(False, 0.0, f"binary not found: {e}", "")

    last_report = 0.0
    while proc.poll() is None:
        time.sleep(0.3)
        now = time.time()
        if now - last_report >= PROGRESS_INTERVAL:
            last_report = now
            if total_size and os.path.exists(out_path):
                pct = int(os.path.getsize(out_path) / total_size * 100)
                pct = max(1, min(99, pct))      # 中途不報 0、也不提早報 100
                progress_cb(pct)

    duration = round(time.time() - start, 2)
    if proc.returncode == 0:
        return DownloadResult(True, duration, "download ok", "")
    err = (proc.stderr.read().decode(errors="ignore") if proc.stderr else "")[:200]
    return DownloadResult(False, duration, f"exit={proc.returncode} {err}", "")


def _download_curl(url, out_path, total_size, progress_cb) -> DownloadResult:
    cmd = ["curl", "-fSL", "-o", out_path, url]
    r = _run_with_progress(cmd, out_path, total_size, progress_cb)
    r.mode = "curl"
    return r


def _download_dfget(url, out_path, total_size, progress_cb) -> DownloadResult:
    # dfget 基本用法：dfget -O <output> <url>
    cmd = [DFGET_BIN, "-O", out_path, url]
    r = _run_with_progress(cmd, out_path, total_size, progress_cb)
    r.mode = "dfget"
    return r


def _download_simulate(task, total_size, progress_cb) -> DownloadResult:
    """
    後備模擬：沒有檔案伺服器 / dfget / curl 時，讓整條流程仍可展示。
    依檔案大小給一個合理的「假耗時」，並平滑推進進度。
    """
    size = total_size or (100 * 1024 * 1024)
    # 假設約 50MB/s，並加一點隨機性
    fake_total = max(3.0, size / (50 * 1024 * 1024))
    start = time.time()
    steps = 20
    for i in range(1, steps):
        time.sleep(fake_total / steps)
        progress_cb(int(i / steps * 100))
    return DownloadResult(True, round(time.time() - start, 2),
                          "simulated download", "simulate")


# ---------------------------------------------------------------------------
# 對外主要入口
# ---------------------------------------------------------------------------

def download(task: dict, progress_cb: Callable[[int], None]) -> DownloadResult:
    """
    下載一個任務。
    task: API 回傳的任務 dict (至少含 task_id, task_name)
    progress_cb: 收到 0~100 整數時，由 worker.py 負責打進度 API
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    mode = _decide_mode(task.get("task_name", ""))
    url = _resolve_url(task)
    out_path = os.path.join(DOWNLOAD_DIR, str(task.get("task_id", "out")) + ".bin")
    total_size = _parse_size(task.get("task_name", ""))

    # 開始下載前先報一個起步進度，讓 Dashboard 立刻有反應
    progress_cb(1)

    # 1) 優先用第 2 人的 adapter
    ext = _try_external_adapter(task, mode, url, out_path, progress_cb)
    if ext is not None:
        return ext

    # 2) 內建 curl / dfget；缺工具或非模擬模式失敗時，退回模擬
    if mode == "simulate":
        return _download_simulate(task, total_size, progress_cb)

    if mode == "dfget":
        if _have(DFGET_BIN):
            return _download_dfget(url, out_path, total_size, progress_cb)
    elif mode == "curl":
        if _have("curl"):
            return _download_curl(url, out_path, total_size, progress_cb)

    # 工具不存在 → 模擬，確保 demo 流程不中斷
    return _download_simulate(task, total_size, progress_cb)
