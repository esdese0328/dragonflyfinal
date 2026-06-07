# Dragonfly 容錯式分散式下載排程與監控系統

目前已整合 **第 2 人 (File Server / Download Adapter)**、**第 3 人 (API Server)**、**第 4 人 (Scheduler)**、**第 5 人 (Worker / Downloader)** 與 **第 6 人 (Dashboard)** 的部分。系統已能用真實 Worker 端到端運作；同時仍保留一支測試模擬腳本，可在不啟動 Worker 的情況下獨立展示畫面。

---

## 執行與測試指南

這份指南將引導你如何在本機啟動 API Server 與 Dashboard，並啟動測試用的模擬腳本。

### 1. 啟動系統基礎服務

1. 請確保你的電腦已經啟動了 **Docker Desktop**。
2. 開啟終端機 (Terminal / PowerShell)，確保你目前已經切換到專案的根目錄（包含 `docker-compose.yml` 的資料夾）。
3. 執行以下指令來建置並啟動 API 與 Dashboard 容器：
   ```powershell
   docker-compose up -d --build
   ```

> [!NOTE]
> 看到啟動成功的訊息後，即可前往以下網址：
> - **Dashboard (監控介面)**: [http://localhost:9000](http://localhost:9000)
> - **API Server (Swagger測試)**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 2. 啟動測試模擬

目前的系統啟動後，資料庫預設是空的（Dashboard 上面會顯示查無資料）。
為了測試 Dashboard 的圖表、進度條與故障恢復功能，我們準備了一支名為 `simulate_worker.py` 的腳本。它會自動呼叫 API 來註冊假 Worker，並且推進任務下載進度（甚至包含隨機的失敗重試）。

請在終端機輸入以下指令，在背景執行腳本：
```powershell
docker-compose exec -d api_server python simulate_worker.py
```
*(加上 `-d` 代表腳本會在容器背景默默執行，你現在可以把終端機關掉了)*

### 3. 觀看測試成果
<img width="1913" height="896" alt="image" src="https://github.com/user-attachments/assets/b332c1c5-c7fd-4a62-ab64-3afb286d4d79" />


1. 模擬腳本啟動後，請前往 Dashboard: **[http://localhost:9000](http://localhost:9000)**
2. 點開左上角的側邊欄（如果有隱藏請展開），勾選「**自動更新 (每2秒)**」。
3. 接著，你就會在網頁上看到：
   - **任務清單**：狀態從 `pending` 變為 `downloading`，並有視覺化進度條。
   - **Worker 狀態**：出現 `SimWorker-Node`，且 `last_heartbeat` 時間一直維持在最新。
   - **圖表分析**：當任務進度跑到 100% 後，會立刻長出該任務的下載耗時長條圖；若任務名稱有 `[curl]` 或 `[dfget]`，則會產出效能比較箱型圖。
   - **故障恢復紀錄**：模擬過程中偶爾會發生隨機失敗，觸發 Retry 後會顯示在該分頁中。

### 4. 關閉系統與清除資料

測試完畢後，想關閉系統並清除測試資料庫，請執行：
```powershell
docker-compose down
Remove-Item api_server\scheduler.db -ErrorAction SilentlyContinue
```

---

## Worker / Downloader (第 5 人)

負責實際執行下載任務的節點，原始碼位於 [`worker/`](worker/)。整套系統用
`docker-compose up -d --build` 啟動後，Worker 會自動運作，無需額外操作。

### 運作流程
1. **註冊**：啟動後呼叫 `POST /create_worker` 取得 `worker_id`。
2. **心跳**：背景執行緒每隔數秒呼叫 `PUT /workers/{worker_id}/heartbeat`，
   讓 Scheduler 與 Dashboard 知道自己存活。
3. **查任務**：輪詢 `GET /get_tasks`，撿出「指派給自己、狀態為 `downloading`」的任務。
4. **下載**：呼叫第 2 人的 `download_adapter.py`，用 **curl** 或 **dfget** 下載檔案，
   下載過程中持續呼叫 `PUT /tasks/{task_id}/progress` 推進度條。
5. **回報結果**：
   - 成功 → 進度推到 100 並帶上 `duration`，API 自動標記 `completed`。
   - 失敗 → 呼叫 `PUT /tasks/{task_id}/retry`，交還給 Scheduler 重新排程
     （retry 次數上限與永久 `failed` 的判斷由 Scheduler 統一負責）。
6. **容錯重生**：若 Worker 被刪除（資料列被移除），心跳時會偵測到自己已不在
   `GET /get_workers` 名單中，並自動重新註冊加入。

### 檔案
| 檔案 | 說明 |
|---|---|
| `worker/worker.py` | 主程式：註冊、心跳、輪詢、結果回報 |
| `worker/downloader.py` | 下載整合層：優先用第 2 人 adapter，否則內建 curl/dfget，再不行退回模擬 |
| `worker/Dockerfile` / `worker/requirements.txt` | 容器化設定 |

### 模擬多個 Worker
想觀察 Scheduler 把任務分配給不同節點，可同時起多個 Worker：
```powershell
docker-compose up -d --build --scale worker=3
```

### 不用 Docker，單機快速測試
在 API Server 已啟動的前提下，可直接跑 Worker（無檔案伺服器 / dfget 時會自動退回
「模擬下載」，仍可在 Dashboard 看到心跳與進度）：
```powershell
cd worker
pip install -r requirements.txt
$env:API_URL="http://localhost:8000"; $env:DOWNLOAD_MODE="simulate"; python worker.py
```

### 主要環境變數
| 變數 | 預設 | 說明 |
|---|---|---|
| `API_URL` | `http://api_server:8000` | API Server 位址 |
| `WORKER_NAME` | `Worker-Node` | 註冊用名稱 |
| `DOWNLOAD_MODE` | `auto` | `auto`/`curl`/`dfget`/`simulate`；auto 依任務名 `[curl]`/`[dfget]` 關鍵字決定 |
| `SELF_ASSIGN` | `0` | 是否自我指派任務。整合 Scheduler 後設 `0`；單機無 Scheduler 測試時可設 `1` |
| `HEARTBEAT_INTERVAL` | `5` | 心跳間隔（秒） |
| `POLL_INTERVAL` | `3` | 查任務間隔（秒） |

---

## 專案待辦事項與交接清單 (To-Do)

目前的 Dashboard 呈現的是由模擬器產生的假數據。接下來要將系統推向完成，還需要依賴以下組員的進度，請各負責人進行後續開發與對接：

### 第 1 人 (系統架構與分散式模式設計)
- 負責整體架構圖與報告主軸。
-  準備期末 Demo 劇本與簡報故事線。

### 第 2 人 (Artifact Repository & Adapter)
-  建立 File Server 與真實的 100MB / 500MB / 1GB 測試檔案。
- 撰寫 `download_adapter.py` 並支援 curl 與 dfget 下載模式。

### 第 4 人 (Scheduler 排程器)
-  取代模擬器的任務分配功能，實作掃描 pending 任務並分配給 idle Worker 的邏輯。
-  **與 Dashboard 的交接點**：需實作偵測 Worker Heartbeat timeout。當 Worker 死亡時，請確實讓任務的 `retry_count + 1` 並設回 `pending`，Dashboard 才能正確畫出**「故障恢復紀錄」**。

### 第 5 人 (Worker / Downloader) ✅ 已完成
- ✅ 已實作真正的 Worker：向 API 註冊 ID、定時送 heartbeat、查詢自己的任務、呼叫第 2 人的 Adapter 以 curl/dfget 下載、回報 success/failed/duration，並支援被刪除後自動重新加入。
- ✅ **與 Dashboard 的交接點**：下載過程持續呼叫 `PUT /tasks/{task_id}/progress` 推進度條、定時呼叫 `PUT /workers/{worker_id}/heartbeat` 更新存活狀態。
- 詳細說明見上方 [Worker / Downloader (第 5 人)](#worker--downloader-第-5-人) 章節與 [`worker/`](worker/) 原始碼。

### 第 7 人 (Benchmark 與 Fault Recovery 實驗)
-  設計測速腳本與故障注入測試（例如故意 kill worker 來測試第 4 人的機制）。
-  **與 Dashboard 的交接點**：在使用 API 建立測試任務時，請務必在 `task_name` 中包含 **`[curl]`** 或是 **`[dfget]`** 關鍵字（例如：`[curl] 500MB 測試`）。
