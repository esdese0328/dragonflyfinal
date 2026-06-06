"""
worker.py — Worker / Downloader (第 5 人)

職責 (對應分工表 1~7):
  1. 啟動後向 API 註冊，取得 worker_id
  2. 背景執行緒定期送 heartbeat
  3. 輪詢 API 查詢「指派給自己」的任務
  4. 呼叫 downloader.py (內部會優先用第 2 人的 download_adapter)
  5. 使用 dfget / curl 下載檔案
  6. 回報結果：成功 -> progress=100 + duration；失敗 -> 觸發 retry
  7. 支援 Worker 被刪除後自動重新註冊加入

與第 3 人 API 的對接點 (已實際存在於 api_server/main.py):
  POST /create_worker            註冊
  PUT  /workers/{id}/heartbeat   心跳
  GET  /get_workers              確認自己是否還在 (偵測被刪除)
  GET  /get_tasks                查任務
  PUT  /tasks/{id}/assign        (測試模式) 自我指派
  PUT  /tasks/{id}/progress      推進度 / 完成
  PUT  /tasks/{id}/retry         回報失敗
"""

import os
import time
import threading
import requests

import downloader


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
API_URL = os.getenv("API_URL", "http://localhost:8000")
WORKER_NAME = os.getenv("WORKER_NAME", "Worker-Node")
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "5"))   # 心跳間隔(秒)
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3"))            # 查任務間隔(秒)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))

# 測試模式：沒有第 4 人 Scheduler 時，Worker 自己撿 pending 任務指派給自己。
# 正式整合時設成 "0"，把指派交給 Scheduler。
SELF_ASSIGN = os.getenv("SELF_ASSIGN", "1") == "1"
# 註: retry 次數上限 / 永久 failed 的判斷由 Scheduler 統一負責，worker 不自行控制。


class Worker:
    def __init__(self):
        self.worker_id = None
        self._stop = threading.Event()

    # ---- API 呼叫小工具 -------------------------------------------------
    def _post(self, path, json=None):
        return requests.post(f"{API_URL}{path}", json=json, timeout=REQUEST_TIMEOUT)

    def _put(self, path, json=None):
        return requests.put(f"{API_URL}{path}", json=json, timeout=REQUEST_TIMEOUT)

    def _get(self, path, params=None):
        return requests.get(f"{API_URL}{path}", params=params, timeout=REQUEST_TIMEOUT)

    # ---- 1. 註冊 -------------------------------------------------------
    def register(self):
        while not self._stop.is_set():
            try:
                r = self._post("/create_worker", {"worker_name": WORKER_NAME})
                r.raise_for_status()
                self.worker_id = r.json()["worker_id"]
                print(f"[register] 註冊成功 worker_id={self.worker_id}")
                return
            except Exception as e:
                print(f"[register] 註冊失敗，2 秒後重試: {e}")
                time.sleep(2)

    # ---- 7. 偵測自己是否被刪除 ----------------------------------------
    def _is_still_registered(self) -> bool:
        try:
            r = self._get("/get_workers")
            r.raise_for_status()
            ids = [w["worker_id"] for w in r.json()]
            return self.worker_id in ids
        except Exception:
            # 查不到 (例如 API 暫時掛掉) 時，先當作還在，避免誤判狂註冊
            return True

    # ---- 2. 心跳 (背景執行緒) -----------------------------------------
    def _heartbeat_loop(self):
        while not self._stop.is_set():
            try:
                self._put(f"/workers/{self.worker_id}/heartbeat")
                # 順便檢查自己是否被刪除，被刪除就重新註冊 (對應第 7 點)
                if not self._is_still_registered():
                    print("[heartbeat] 偵測到自己已被刪除，重新註冊…")
                    self.register()
            except Exception as e:
                print(f"[heartbeat] 失敗: {e}")
            self._stop.wait(HEARTBEAT_INTERVAL)

    # ---- 3. 查任務 -----------------------------------------------------
    def _fetch_my_tasks(self):
        """回傳指派給自己、且還在下載中(未完成)的任務清單。"""
        try:
            r = self._get("/get_tasks")
            r.raise_for_status()
            tasks = r.json()
        except Exception as e:
            print(f"[tasks] 查詢失敗: {e}")
            return []

        mine = [
            t for t in tasks
            if t.get("worker_id") == self.worker_id
            and t.get("status") == "downloading"
            and (t.get("progress") or 0) < 100
        ]

        # 測試模式：沒有 Scheduler 時自己撿一個 pending 任務指派給自己
        if not mine and SELF_ASSIGN:
            pending = [t for t in tasks if t.get("status") == "pending"]
            if pending:
                t = pending[0]
                try:
                    self._put(f"/tasks/{t['task_id']}/assign",
                              {"worker_id": self.worker_id})
                    print(f"[self-assign] 自我指派任務 {t['task_id']}")
                except Exception as e:
                    print(f"[self-assign] 失敗: {e}")
        return mine

    # ---- 5/6. 進度與結果回報 ------------------------------------------
    def _report_progress(self, task_id, progress, duration=None):
        payload = {"progress": progress}
        if duration is not None:
            payload["duration"] = duration
        try:
            self._put(f"/tasks/{task_id}/progress", payload)
        except Exception as e:
            print(f"[progress] 回報失敗 {task_id}: {e}")

    def _report_failed(self, task_id):
        """失敗 -> 呼叫 retry，讓 retry_count+1 並設回 pending。"""
        try:
            self._put(f"/tasks/{task_id}/retry")
            print(f"[failed] 任務 {task_id} 失敗，已觸發 retry")
        except Exception as e:
            print(f"[failed] 回報失敗 {task_id}: {e}")

    # ---- 4/5/6. 執行單一任務 ------------------------------------------
    def _handle_task(self, task):
        task_id = task["task_id"]
        name = task.get("task_name", "")
        retry_count = task.get("retry_count", 0) or 0
        print(f"[task] 開始處理 {task_id} ({name}) retry={retry_count}")

        # progress callback：交給 downloader 在下載過程中呼叫
        def on_progress(pct):
            self._report_progress(task_id, pct)
            print(f"[task] {task_id} 進度 -> {pct}%")

        result = downloader.download(task, on_progress)

        if result.success:
            self._report_progress(task_id, 100, duration=result.duration)
            print(f"[task] {task_id} 完成 ({result.mode}) 耗時 {result.duration}s")
        else:
            # 下載失敗一律呼叫 /retry，把任務交還給 Scheduler 重新排程。
            # 「retry 次數是否用盡 / 是否標記 failed」由 Scheduler 統一決定
            # (見 api /tasks/{id}/fail 的註解與 scheduler.py)，
            # worker 不可自行放棄，否則任務會卡在 downloading 變殭屍任務。
            print(f"[task] {task_id} 下載失敗: {result.message}")
            self._report_failed(task_id)

    # ---- 主迴圈 --------------------------------------------------------
    def run(self):
        self.register()
        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()
        print(f"[run] Worker 啟動完成 (SELF_ASSIGN={SELF_ASSIGN})，開始輪詢任務…")

        while not self._stop.is_set():
            for task in self._fetch_my_tasks():
                self._handle_task(task)
            self._stop.wait(POLL_INTERVAL)

    def stop(self):
        self._stop.set()


if __name__ == "__main__":
    w = Worker()
    try:
        w.run()
    except KeyboardInterrupt:
        print("\n[main] 收到中止訊號，關閉 Worker。")
        w.stop()
