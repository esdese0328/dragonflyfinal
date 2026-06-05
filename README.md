# Dragonfly 容錯式分散式下載排程與監控系統

本專案為基於 Dragonfly 的分散式下載與監控系統，目前整合了**第 3 人 (API Server)** 與 **第 6 人 (Dashboard)** 的部分，並提供了一支測試模擬腳本，可以在缺少真實 Worker 的情況下獨立運行與展示畫面。

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

## 專案待辦事項與交接清單 (To-Do)

目前的 Dashboard 呈現的是由模擬器產生的假數據。接下來要將系統推向完成，還需要依賴以下組員的進度，請各負責人進行後續開發與對接：

### 第 1 人 (系統架構與分散式模式設計)
- [ ] 負責整體架構圖與報告主軸。
- [ ] 準備期末 Demo 劇本與簡報故事線。

### 第 2 人 (Artifact Repository & Adapter)
- [ ] 建立 File Server 與真實的 100MB / 500MB / 1GB 測試檔案。
- [ ] 撰寫 `download_adapter.py` 並支援 curl 與 dfget 下載模式。

### 第 4 人 (Scheduler 排程器)
- [ ] 取代模擬器的任務分配功能，實作掃描 pending 任務並分配給 idle Worker 的邏輯。
- [ ] **與 Dashboard 的交接點**：需實作偵測 Worker Heartbeat timeout。當 Worker 死亡時，請確實讓任務的 `retry_count + 1` 並設回 `pending`，Dashboard 才能正確畫出**「故障恢復紀錄」**。

### 第 5 人 (Worker / Downloader)
- [ ] 實作真正的 Worker：向 API 註冊 ID，並實際呼叫第 2 人的 Adapter 下載檔案。
- [ ] **與 Dashboard 的交接點**：請務必定時呼叫 `PUT /workers/{worker_id}/heartbeat` 更新存活狀態，並在下載過程中不斷呼叫 `PUT /tasks/{task_id}/progress` 推進進度條。

### 第 7 人 (Benchmark 與 Fault Recovery 實驗)
- [ ] 設計測速腳本與故障注入測試（例如故意 kill worker 來測試第 4 人的機制）。
- [ ] **與 Dashboard 的交接點**：在使用 API 建立測試任務時，請務必在 `task_name` 中包含 **`[curl]`** 或是 **`[dfget]`** 關鍵字（例如：`[curl] 500MB 測試`）。如此一來 Dashboard 才能在圖表區自動幫你畫出「效能比較箱型圖」！
