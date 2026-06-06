"""
seed.py — 現場 Demo 任務產生器 (第 5 人附帶的展示工具)

目的：示範時不用手動建任務。這支程式會持續監看任務數量，
只要「進行中的任務」少於設定值，就自動補上新任務，
讓 Dashboard 永遠有東西在跑。

它「只負責建立任務」，實際的指派與下載由真正的 Scheduler + Worker 完成，
所以展示的是真實系統流程，只是 Worker 跑在模擬下載模式 (不需 file-server)。
"""
import os
import time
import random
import requests

API_URL = os.getenv("API_URL", "http://api_server:8000")
TARGET_ACTIVE = int(os.getenv("TARGET_ACTIVE", "6"))   # 維持多少個進行中的任務
SEED_INTERVAL = float(os.getenv("SEED_INTERVAL", "8"))  # 每隔幾秒檢查一次

# 可用環境變數覆蓋: TOOLS / SIZES (逗號分隔)
# 真實 curl 模式請設 TOOLS="[curl]"、SIZES 設為 file-server 上實際存在的檔案大小
TOOLS = os.getenv("TOOLS", "[curl],[dfget]").split(",")     # 帶關鍵字, Dashboard 才會畫效能比較圖
SIZES = os.getenv("SIZES", "100MB,500MB,1GB").split(",")


def active_count():
    try:
        r = requests.get(f"{API_URL}/get_tasks", timeout=5)
        tasks = r.json()
        return sum(1 for t in tasks if t.get("status") in ("pending", "downloading"))
    except Exception:
        return -1  # API 還沒起來


def create(name):
    try:
        requests.post(f"{API_URL}/create_task", json={"task_name": name}, timeout=5)
        print(f"[seed] 建立任務: {name}", flush=True)
    except Exception as e:
        print(f"[seed] 建立失敗: {e}", flush=True)


def main():
    print(f"[seed] 啟動，目標維持 {TARGET_ACTIVE} 個進行中任務", flush=True)
    # 等 API Server 就緒
    while active_count() < 0:
        print("[seed] 等待 API Server…", flush=True)
        time.sleep(2)

    while True:
        n = active_count()
        while 0 <= n < TARGET_ACTIVE:
            create(f"{random.choice(TOOLS)} {random.choice(SIZES)} Demo {random.randint(100, 999)}")
            n += 1
        time.sleep(SEED_INTERVAL)


if __name__ == "__main__":
    main()
