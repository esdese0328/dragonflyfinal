# Dragonfly 分散式下載監控系統 - 執行與測試指南

這份指南將引導你如何在本機啟動 API Server 與 Dashboard，並啟動測試用的模擬腳本，讓 Dashboard 看起來像是有真實資料在流動一樣。

##  1. 啟動系統基礎服務

1. 請確保你的電腦已經啟動了 **Docker Desktop**。
2. 開啟終端機 (Terminal / PowerShell)，確保你目前已經切換到專案的根目錄（包含 `docker-compose.yml` 的資料夾）。如果是從 VSCode 打開專案，通常預設就會在根目錄：
   ```powershell
   # 確保你在 dragonflyfinal-main 資料夾下
   ```
3. 執行以下指令來建置並啟動 API 與 Dashboard 容器：
   ```powershell
   docker-compose up -d --build
   ```

> [!NOTE]
> 看到 `Container dashboard Started` 即代表啟動完成。
> - **Dashboard (監控介面)**: [http://localhost:9000](http://localhost:9000)
> - **API Server (Swagger測試)**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

##  2. 啟動測試模擬

目前的系統啟動後，資料庫預設是空的（這代表 Dashboard 上面會顯示 0 與查無資料）。

為了測試 Dashboard 的圖表、進度條與自動更新功能，我們準備了一支名為 `simulate_worker.py` 的腳本。它會自動呼叫 API 來「註冊假 Worker」、「定期發送心跳」，並且把任務的「下載進度」一路推進到 100%。

**如何啟動模擬測試：**
你不需要在自己的電腦安裝 Python，我們可以直接透過剛才啟動的 API 容器來在背景執行這個腳本。請在終端機輸入：

```powershell
docker-compose exec -d api_server python simulate_worker.py
```

> [!TIP]
> 加上 `-d` 代表這隻腳本會在容器背景默默執行，你就可以把終端機關掉了。

---

##  3. 觀看測試成果

1. 模擬腳本啟動後，請打開瀏覽器前往 Dashboard: **[http://localhost:9000](http://localhost:9000)**
2. 點開左上角的側邊欄（如果有隱藏請展開），勾選「**自動更新 (每2秒)**」。
3. 接著，你就會在網頁上看到：
   - **任務清單**：生出新任務、狀態從 `pending` 變為 `downloading`，並出現開始跑動的**視覺化進度條**。
   - **Worker 狀態**：出現 3 個 `SimWorker-Node`，且 `last_heartbeat` 時間一直維持在最新。
   - **圖表分析**：當任務進度跑到 100% 後變成 `completed`，圖表會立刻長出該任務的下載耗時長條圖

---

##  4. 關閉系統與清除資料

如果你測試完畢，想要關閉整個系統並且清除所有測試資料：

```powershell
docker-compose down
Remove-Item api_server\scheduler.db -ErrorAction SilentlyContinue
```
