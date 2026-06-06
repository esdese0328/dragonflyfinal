# =====================================================================
# worker_sim.py  —  DEMO 用的測試 Worker（暫代第 5 人的真 Worker）
#
# 它只做「真 Worker」該做的兩件事：
#   1. 定時送 heartbeat（讓 Scheduler 知道我還活著）
#   2. 把分配到自己手上的 downloading 任務逐步推進度，完成時回報耗時
# 它「不會」自己去分配任務 —— 分配是 Scheduler(第 4 人) 的職責。
#
# 一個 process = 一個 Worker。要演「故障恢復」時，直接 Ctrl+C 關掉它，
# 心跳就會停止，Scheduler 在 HEARTBEAT_TIMEOUT 後就會回收它手上的任務。
# =====================================================================
import time
import random
import requests
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")
WORKER_NAME = os.getenv("WORKER_NAME", "Worker-A")
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "1.5"))  # 幾秒送一次心跳


def find_or_create_worker(name):
    """若已存在同名 Worker 就沿用其 id（模擬「重新加入」），否則新建一個。"""
    try:
        r = requests.get(f"{API_URL}/get_workers", timeout=3)
        for w in r.json():
            if w["worker_name"] == name:
                print(f"[{name}] 沿用既有 Worker id={w['worker_id'][:8]}（重新加入）")
                return w["worker_id"]
    except Exception:
        pass
    r = requests.post(f"{API_URL}/create_worker", json={"worker_name": name}, timeout=3)
    wid = r.json()["worker_id"]
    print(f"[{name}] 註冊新 Worker id={wid[:8]}")
    return wid


def heartbeat(wid):
    try:
        requests.put(f"{API_URL}/workers/{wid}/heartbeat", timeout=3)
    except Exception:
        pass


def get_tasks():
    try:
        return requests.get(f"{API_URL}/get_tasks", timeout=3).json()
    except Exception:
        return []


def push_progress(task_id, progress, duration=None):
    payload = {"progress": progress}
    if duration is not None:
        payload["duration"] = duration
    try:
        requests.put(f"{API_URL}/tasks/{task_id}/progress", json=payload, timeout=3)
    except Exception:
        pass


def main():
    wid = find_or_create_worker(WORKER_NAME)
    start_times = {}        # 記錄每個任務開始下載的時間，用來算真實耗時
    last_heartbeat = 0.0

    print(f"[{WORKER_NAME}] 開始工作，等待 Scheduler 派任務… (Ctrl+C 可模擬當機)")
    while True:
        now = time.monotonic()

        # 定時送心跳
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            heartbeat(wid)
            last_heartbeat = now

        # 找出 Scheduler 分配到我手上、且還在下載中的任務，推進它的進度
        for t in get_tasks():
            if t.get("worker_id") == wid and t["status"] == "downloading":
                task_id = t["task_id"]
                if task_id not in start_times:
                    start_times[task_id] = now
                    print(f"[{WORKER_NAME}] 接到任務 {task_id[:8]}「{t['task_name']}」開始下載")

                new_progress = min(100, t.get("progress", 0) + random.randint(8, 20))
                if new_progress >= 100:
                    duration = round(now - start_times.pop(task_id, now), 1)
                    push_progress(task_id, 100, duration=duration)
                    print(f"[{WORKER_NAME}] 任務 {task_id[:8]} 下載完成，耗時 {duration}s")
                else:
                    push_progress(task_id, new_progress)

        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n[{WORKER_NAME}] 收到中斷訊號，Worker 當機離線！")
