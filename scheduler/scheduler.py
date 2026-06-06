import time
import requests
import os
from datetime import datetime, timezone, timedelta

# ===== 可調參數 =====
API_URL = os.getenv("API_URL", "http://localhost:8000")     # API Server 位址
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "3"))        # 每幾秒掃描排程一次
HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", "15"))  # Worker 幾秒沒心跳就視為死亡
MAX_RETRY = int(os.getenv("MAX_RETRY", "3"))               # 一個任務最多重試幾次，超過就標記 failed
STRATEGY = os.getenv("STRATEGY", "round-robin")            # 排程策略：round-robin 或 least-busy

# 與 API Server 一致使用 UTC+8 的時間格式
TZ = timezone(timedelta(hours=8))
TIME_FMT = "%Y-%m-%d %H:%M:%S"


# ===================================================================
# API 呼叫包裝（Scheduler 是獨立程序，只透過 HTTP 與 API Server 溝通）
# ===================================================================
def get_tasks():
    try:
        r = requests.get(f"{API_URL}/get_tasks", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[WARN] 取得任務失敗: {e}")
    return []


def get_workers():
    try:
        r = requests.get(f"{API_URL}/get_workers", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[WARN] 取得 Worker 失敗: {e}")
    return []


def assign_task(task_id, worker_id):
    try:
        requests.put(f"{API_URL}/tasks/{task_id}/assign",
                     json={"worker_id": worker_id}, timeout=3)
        print(f"[ASSIGN]  任務 {task_id[:8]} -> Worker {worker_id[:8]}")
    except Exception as e:
        print(f"[WARN] 指派任務失敗: {e}")


def retry_task(task_id):
    # 呼叫後 API 會：retry_count + 1、status 設回 pending、清空 worker_id
    try:
        requests.put(f"{API_URL}/tasks/{task_id}/retry", timeout=3)
        print(f"[RETRY]   任務 {task_id[:8]} 重新排入待辦 (retry_count + 1)")
    except Exception as e:
        print(f"[WARN] 重試任務失敗: {e}")


def fail_task(task_id):
    # 重試次數用盡，標記為永久失敗
    try:
        requests.put(f"{API_URL}/tasks/{task_id}/fail", timeout=3)
        print(f"[FAIL]    任務 {task_id[:8]} 重試次數用盡，標記為 failed")
    except Exception as e:
        print(f"[WARN] 標記失敗任務失敗: {e}")


# ===================================================================
# 工具函式
# ===================================================================
def is_online(worker):
    """依 last_heartbeat 判斷 Worker 是否存活（心跳是否在 timeout 時間內）。"""
    try:
        last = datetime.strptime(worker["last_heartbeat"], TIME_FMT).replace(tzinfo=TZ)
    except (ValueError, KeyError, TypeError):
        return False
    return (datetime.now(TZ) - last).total_seconds() <= HEARTBEAT_TIMEOUT


def pick_worker(idle_workers, all_tasks, rr_counter):
    """從 idle Worker 中依策略挑一個出來。"""
    if not idle_workers:
        return None

    if STRATEGY == "least-busy":
        # least-busy：挑「歷來被分配任務數」最少的 idle Worker，達到長期負載平衡
        def load(w):
            return sum(1 for t in all_tasks if t.get("worker_id") == w["worker_id"])
        return min(idle_workers, key=load)

    # round-robin（預設）：輪流分配，避免任務集中在同一個 Worker
    worker = idle_workers[rr_counter[0] % len(idle_workers)]
    rr_counter[0] += 1
    return worker


# ===================================================================
# 一次完整的排程循環
# ===================================================================
def schedule_once(rr_counter):
    tasks = get_tasks()
    workers = get_workers()

    # 找出目前存活（心跳未逾時）的 Worker
    online_workers = [w for w in workers if is_online(w)]
    online_ids = {w["worker_id"] for w in online_workers}

    # ---- 步驟 1：偵測 Heartbeat Timeout，回收死亡 Worker 手上的任務 ----
    # 若一個任務還在 downloading，但它的 Worker 已經不在存活清單裡 → Worker 死了
    for t in tasks:
        if t["status"] == "downloading" and t.get("worker_id") not in online_ids:
            print(f"[DEAD]    偵測到 Worker {str(t.get('worker_id'))[:8]} 心跳逾時，"
                  f"其任務 {t['task_id'][:8]} 需要恢復")
            if t.get("retry_count", 0) >= MAX_RETRY:
                fail_task(t["task_id"])     # 重試太多次，放棄
            else:
                retry_task(t["task_id"])    # 重排回 pending，交給下一輪重新分配

    # 上一步可能改了任務狀態，重新抓一次最新資料再做分配
    tasks = get_tasks()

    # ---- 步驟 2：算出哪些 online Worker 是 idle（手上沒有 downloading 任務）----
    busy_ids = {t["worker_id"] for t in tasks if t["status"] == "downloading"}
    idle_workers = [w for w in online_workers if w["worker_id"] not in busy_ids]

    # ---- 步驟 3：掃描 pending 任務並分配給 idle Worker ----
    pending = [t for t in tasks if t["status"] == "pending"]
    for t in pending:
        # retry 次數用盡的任務不再分配，直接標記失敗
        if t.get("retry_count", 0) >= MAX_RETRY:
            fail_task(t["task_id"])
            continue

        worker = pick_worker(idle_workers, tasks, rr_counter)
        if worker is None:
            # 沒有空閒 Worker 了，剩下的 pending 任務留到下一輪
            break

        assign_task(t["task_id"], worker["worker_id"])
        idle_workers.remove(worker)   # 分配後該 Worker 即視為忙碌，本輪不再分給它


def main():
    print("=" * 60)
    print(" Dragonfly Scheduler 啟動")
    print(f"  API_URL           = {API_URL}")
    print(f"  掃描間隔           = {SCAN_INTERVAL}s")
    print(f"  Heartbeat timeout = {HEARTBEAT_TIMEOUT}s")
    print(f"  最大重試次數       = {MAX_RETRY}")
    print(f"  排程策略           = {STRATEGY}")
    print("=" * 60)

    rr_counter = [0]   # round-robin 的輪詢計數器（用 list 包起來方便在函式間共用狀態）
    while True:
        try:
            schedule_once(rr_counter)
        except Exception as e:
            print(f"[ERROR] 排程循環發生例外: {e}")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
