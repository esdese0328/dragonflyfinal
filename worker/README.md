# Worker / Downloader (第 5 人)

負責實際執行下載任務的節點。對接第 3 人的 API Server。

## 產出對照
| 分工要求 | 實作位置 |
|---|---|
| 1. 啟動後註冊 worker_id | `worker.py` → `Worker.register()` |
| 2. 定期送 heartbeat | `worker.py` → `_heartbeat_loop()` (背景執行緒) |
| 3. 查詢自己是否有任務 | `worker.py` → `_fetch_my_tasks()` |
| 4. 呼叫第 2 人 download_adapter | `downloader.py` → `_try_external_adapter()` |
| 5. 使用 dfget 下載 | `downloader.py` → `_download_dfget()` / `_download_curl()` |
| 6. 回報 success / failed / duration | `worker.py` → `_report_progress()` / `_report_failed()` |
| 7. 被刪除後重新加入 | `worker.py` → `_is_still_registered()` + 重新 `register()` |
| Worker Dockerfile | `Dockerfile` |

## 檔案
- `worker.py` — 主程式：註冊、心跳、輪詢、回報。
- `downloader.py` — 下載整合層：優先用第 2 人 adapter，否則 dfget/curl，再不行就模擬。
- `Dockerfile` / `requirements.txt`

## 本機快速測試 (不需 Docker)
```powershell
# 先確定 API Server 已啟動 (docker-compose up -d --build api_server)
cd worker
pip install -r requirements.txt
$env:API_URL="http://localhost:8000"; python worker.py
```
沒有檔案伺服器 / dfget / curl 時會自動跑「模擬下載」，仍可在 Dashboard 看到
心跳更新與進度條推進，方便獨立 demo。

## 用 Docker 跑 (含整套系統)
```powershell
docker-compose up -d --build
# 模擬多個 worker：
docker-compose up -d --build --scale worker=3
```

## 重要環境變數
| 變數 | 預設 | 說明 |
|---|---|---|
| `API_URL` | `http://localhost:8000` | API Server 位址 |
| `WORKER_NAME` | `Worker-Node` | 註冊用名稱 |
| `HEARTBEAT_INTERVAL` | `5` | 心跳間隔(秒) |
| `POLL_INTERVAL` | `3` | 查任務間隔(秒) |
| `DOWNLOAD_MODE` | `auto` | `auto`/`dfget`/`curl`/`simulate`；auto 依任務名 `[dfget]`/`[curl]` 決定 |
| `SELF_ASSIGN` | `1` | 無 Scheduler 時自我指派；對接第 4 人後設 `0` |
| `FILE_SERVER` | `http://file-server` | 第 2 人的檔案伺服器 |
| `DFGET_BIN` | `dfget` | dfget 執行檔路徑 |
| `MAX_RETRY` | `3` | 達上限後不再 retry |

## 後續對接 (給第 2 / 4 人的接口約定)
- **第 2 人**：請讓 `download_adapter.py` 提供
  `download(url, output, mode, progress_callback)`，回傳成功與否。
  放進 worker 目錄即會被自動採用，無需改 worker.py。
- **第 4 人**：Scheduler 完成後，把 `SELF_ASSIGN=0`，由 Scheduler 透過
  `PUT /tasks/{id}/assign` 指派任務，Worker 即會自動接手。
