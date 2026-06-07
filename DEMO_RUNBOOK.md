# Dragonflyfinal 完整 Demo 1-3 操作手冊

本手冊涵蓋從 Windows 環境安裝、Dragonfly 部署、專案啟動，到 Demo 1、Demo 2、
Demo 3 的完整操作流程。

除非特別標註為 WSL，所有指令皆在 Windows PowerShell 執行，工作目錄為：

```powershell
cd D:\dragonflyfinal
```

## 系統架構

```text
Dashboard : http://localhost:9001
API       : http://localhost:8000
File      : http://localhost:8800
Manager   : http://localhost:8080

Dashboard/API
    |
Task Scheduler
    |
Project Worker
    |-- [curl]  -> File Server
    `-- [dfget] -> Dragonfly client proxy:4001 -> P2P/cache -> File Server
```

注意：

- 專案的 `scheduler` 是任務分配排程器。
- 官方 Dragonfly 的 `scheduler` 是 P2P 排程器。
- 專案任務狀態使用 `pending`、`downloading`、`completed`、`failed`。
- Demo 中的 success 對應資料庫狀態 `completed`。
- 重試時狀態會短暫回到 `pending`，以 `retry_count` 證明發生重試。

---

## 1. 安裝需求

### 1.1 確認硬體虛擬化

開啟：

```text
工作管理員 -> 效能 -> CPU -> 虛擬化
```

必須顯示「已啟用」。

### 1.2 安裝 WSL 2

使用系統管理員 PowerShell：

```powershell
wsl --install
```

重新啟動 Windows 後：

```powershell
wsl --update
wsl --set-default-version 2
wsl --status
wsl --version
```

### 1.3 安裝 Docker Desktop

```powershell
winget install -e --id Docker.DockerDesktop
```

啟動 Docker Desktop，確認：

```text
Settings -> General -> Use the WSL 2 based engine
```

驗證：

```powershell
docker version
docker compose version
docker run --rm hello-world
```

### 1.4 安裝 Git

```powershell
winget install -e --id Git.Git
git --version
```

---

## 2. 一次性建立測試檔案

專案儲存庫預設沒有大型測試檔案。在 PowerShell 執行：

```powershell
cd D:\dragonflyfinal

$dir = Join-Path $PWD "file_server\files"
New-Item -ItemType Directory -Force $dir | Out-Null

$files = @{
    "100MB.bin" = 100MB
    "500MB.bin" = 500MB
    "1GB.bin"   = 1GB
}

foreach ($entry in $files.GetEnumerator()) {
    $path = Join-Path $dir $entry.Key
    $stream = [System.IO.File]::Open(
        $path,
        [System.IO.FileMode]::Create,
        [System.IO.FileAccess]::Write
    )
    $stream.SetLength([int64]$entry.Value)
    $stream.Dispose()
}

Get-ChildItem file_server\files | Select-Object Name, Length
```

建立後除非要換檔案內容，後續 Demo 不需要重建或刪除。

---

## 3. 一次性部署官方 Dragonfly

### 3.1 Clone Dragonfly

從 PowerShell 進入 WSL：

```powershell
wsl
```

以下指令在 WSL 執行：

```bash
sudo apt update
sudo apt install -y git curl

cd ~
git clone --branch v2.3.3 --recurse-submodules \
  https://github.com/dragonflyoss/dragonfly.git

cd ~/dragonfly/deploy/docker-compose
```

### 3.2 使用正確 WSL IP 啟動

官方 `run.sh` 預設使用 `hostname -i`。部分 WSL 環境會得到錯誤的
`127.0.1.1`，造成 Manager、Scheduler、Client 持續 Restarting。

每次重新產生設定時都必須使用：

```bash
cd ~/dragonfly/deploy/docker-compose

export IP=$(hostname -I | awk '{print $1}')
echo "$IP"

IP=$IP ./run.sh
```

確認設定沒有錯誤 loopback：

```bash
grep -R "127.0.1.1" config
```

正常情況下不應有輸出。

確認服務：

```bash
docker compose ps
```

預期以下服務皆為 `healthy`：

```text
dragonfly-mysql
dragonfly-redis
manager
scheduler
client
seed-client
```

這個版本的一般 dfdaemon 服務名稱是 `client`，不是 `dfdaemon`：

```bash
docker compose exec client dfget --version
```

Manager Console：

```text
http://localhost:8080
帳號：root
密碼：dragonfly
```

完成後可離開 WSL：

```bash
exit
```

Dragonfly 容器仍會在 Docker Desktop 中執行。

---

## 4. 全新重現 Demo 1-3 的清理流程

此流程會清除：

- Dashboard 舊任務紀錄
- API 中的舊 Worker 註冊紀錄
- 舊 Worker 容器
- Dragonfly Client 與 Seed Client 快取

不會刪除測試檔案、Docker images、Manager、Dragonfly Scheduler、MySQL 或 Redis。

### 4.1 清除專案資料

PowerShell：

```powershell
cd D:\dragonflyfinal

docker rm -f worker-a worker-b worker-c 2>$null
docker compose down --remove-orphans

Remove-Item api_server\scheduler.db, `
            api_server\scheduler.db-shm, `
            api_server\scheduler.db-wal `
    -Force -ErrorAction SilentlyContinue
```

### 4.2 清除 Dragonfly 快取

仍在 PowerShell 執行：

```powershell
wsl bash -lc "cd ~/dragonfly/deploy/docker-compose && docker compose stop client seed-client && docker compose rm -f client seed-client && docker compose up -d seed-client client"

Start-Sleep 20

docker ps --filter "name=client" `
    --format "table {{.Names}}\t{{.Status}}"
```

確認 `client` 與 `seed-client` 都為 `healthy`。

### 4.3 啟動專案核心服務

第一次或程式碼修改後建議使用 `--build`：

```powershell
docker compose up -d --build api_server file-server scheduler dashboard
```

確認：

```powershell
docker compose ps
Invoke-WebRequest http://localhost:8800/100MB.bin -Method Head
```

Dashboard：

```text
http://localhost:9001
```

---

## 5. Demo 1：正常任務下載

目的：

1. 建立三個任務。
2. Scheduler 分配給三個 Worker。
3. Worker 使用真實 curl 下載。
4. Dashboard 顯示 completed、進度與耗時。

### 5.1 啟動三個具名 Worker

```powershell
docker compose run -d --name worker-a -e WORKER_NAME=Worker-A worker
docker compose run -d --name worker-b -e WORKER_NAME=Worker-B worker
docker compose run -d --name worker-c -e WORKER_NAME=Worker-C worker

Start-Sleep 8
```

`docker compose ps` 不一定顯示用 `compose run` 建立的 one-off Worker。使用：

```powershell
docker ps --filter "name=worker-" `
    --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
```

### 5.2 建立三個 curl 任務

```powershell
$names = @(
    "[curl] 100MB normal-demo-A"
    "[curl] 500MB normal-demo-B"
    "[curl] 1GB normal-demo-C"
)

foreach ($name in $names) {
    Invoke-RestMethod -Method Post `
        -Uri http://localhost:8000/create_task `
        -ContentType "application/json" `
        -Body (@{task_name=$name} | ConvertTo-Json)
}
```

### 5.3 觀察 Scheduler

另開 PowerShell：

```powershell
cd D:\dragonflyfinal
docker compose logs -f scheduler
```

預期看到三筆 `[ASSIGN]`，且 Worker ID 不同。

啟動初期出現少量 `Connection refused` 是因 API 尚未完成啟動；後續能正常
`[ASSIGN]` 即可。

### 5.4 監控任務

Windows PowerShell 對 `Invoke-RestMethod` JSON 陣列的管線行為可能導致空白欄位，
因此使用 `Invoke-WebRequest + ConvertFrom-Json`：

```powershell
while ($true) {
    Clear-Host

    $tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
        ConvertFrom-Json

    @($tasks) | ForEach-Object {
        [pscustomobject]@{
            task_name = $_.task_name
            status    = $_.status
            worker_id = $_.worker_id
            progress  = $_.progress
            duration  = $_.duration
        }
    } | Format-Table -AutoSize

    Start-Sleep 2
}
```

三個任務都為 `completed` 後按 `Ctrl+C`。

### 5.5 確認 Worker

```powershell
docker logs worker-a --tail 30
docker logs worker-b --tail 30
docker logs worker-c --tail 30
```

預期顯示：

```text
完成 (adapter/curl) 耗時 ...
```

Demo 1 完成後不要清除資料，直接進行 Demo 2，Dashboard 才會保留 Demo 1 結果。

---

## 6. Demo 2：Dragonfly 快取加速

目的：

1. 第一次 `[dfget]` 下載相同來源檔案。
2. 第二次透過 Dragonfly cache 下載。
3. Worker 將 duration 回報 API。
4. Dashboard 顯示 first-download 與 cached-download 比較。

專案 Worker 使用：

```text
DFGET_PROXY=http://host.docker.internal:4001
```

`[dfget]` 任務會由 Worker 透過 Dragonfly `client` HTTP proxy 下載，並保留 Dashboard
任務追蹤。

### 6.1 Demo 2 前清除 Dragonfly 快取

Demo 1 的 curl 不會寫入 Dragonfly cache，但為確保 Demo 2 第一次是 cold download，
執行：

```powershell
wsl bash -lc "cd ~/dragonfly/deploy/docker-compose && docker compose stop client seed-client && docker compose rm -f client seed-client && docker compose up -d seed-client client"

Start-Sleep 20

docker ps --filter "name=client" `
    --format "table {{.Names}}\t{{.Status}}"
```

確認 `client` 與 `seed-client` 為 `healthy`。

### 6.2 建立第一次下載

```powershell
$first = Invoke-RestMethod -Method Post `
    -Uri http://localhost:8000/create_task `
    -ContentType "application/json" `
    -Body (@{
        task_name="[dfget] 500MB model-medium first-download"
    } | ConvertTo-Json)
```

等待第一次完成：

```powershell
do {
    Start-Sleep 2

    $tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
        ConvertFrom-Json

    $firstTask = @($tasks) |
        Where-Object task_id -EQ $first.task_id

    $firstTask |
        Select-Object task_name, status, progress, duration |
        Format-Table
} until ($firstTask.status -eq "completed")
```

必須等 first-download 完成後，才能建立 cached-download。

### 6.3 建立第二次快取下載

```powershell
$cached = Invoke-RestMethod -Method Post `
    -Uri http://localhost:8000/create_task `
    -ContentType "application/json" `
    -Body (@{
        task_name="[dfget] 500MB model-medium cached-download"
    } | ConvertTo-Json)
```

等待第二次完成：

```powershell
do {
    Start-Sleep 2

    $tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
        ConvertFrom-Json

    $cachedTask = @($tasks) |
        Where-Object task_id -EQ $cached.task_id

    $cachedTask |
        Select-Object task_name, status, progress, duration |
        Format-Table
} until ($cachedTask.status -eq "completed")
```

### 6.4 顯示比較

```powershell
$tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
    ConvertFrom-Json

$result = @($tasks) |
    Where-Object task_name -Match "model-medium" |
    Select-Object task_name, status, duration

$result | Format-Table -AutoSize

$firstDuration = ($result |
    Where-Object task_name -Match "first-download").duration

$cachedDuration = ($result |
    Where-Object task_name -Match "cached-download").duration

[pscustomobject]@{
    first_seconds  = $firstDuration
    cached_seconds = $cachedDuration
    speedup        = "{0:N2}x" -f ($firstDuration / $cachedDuration)
    reduced        = "{0:N1}%" -f (
        ($firstDuration - $cachedDuration) / $firstDuration * 100
    )
} | Format-List
```

### 6.5 證明 Dragonfly 參與下載

Worker log 應顯示：

```powershell
docker logs worker-a --tail 50
docker logs worker-b --tail 50
docker logs worker-c --tail 50
```

預期：

```text
完成 (adapter/dfget) 耗時 ...
```

Dragonfly Client log：

```powershell
docker logs client --since 10m |
    Select-String "finished piece.*from (source|local)"
```

判讀：

- `from source`：從 File Server 取得。
- `from local`：從 Dragonfly 本機快取取得。

在同一台 Docker Desktop 上，curl 直連通常比 dfget 快，這是正常現象。Demo 2 應比較
第一次 dfget 與第二次 dfget，而不是宣稱 dfget 單次一定比 curl 快。

Dashboard「圖表分析」會顯示 Dragonfly 快取下載比較與加速倍數：

```text
http://localhost:9001
```

---

## 7. Demo 3：Worker 故障恢復

目的：

1. 任務先分配給 Worker B。
2. 停止 Worker B。
3. Scheduler 在 heartbeat timeout 後 retry。
4. 任務重新分配給 Worker C。
5. Worker C 完成任務，Dashboard 顯示 retry_count。

Demo 3 使用 `DOWNLOAD_MODE=simulate`，避免真實 5GB 下載過快或檔案不存在。Scheduler
heartbeat timeout 與重新分配流程仍是真實運作。

### 7.1 清理 Demo 3 Worker 與舊 Worker 註冊

保留 Demo 1、Demo 2 任務資料，只清除舊 Worker 註冊與舊 Demo 3 任務：

```powershell
docker rm -f worker-a worker-b worker-c 2>$null
docker compose stop scheduler

@'
import sqlite3

conn = sqlite3.connect('/app/scheduler.db')
conn.execute("DELETE FROM tasks WHERE task_name LIKE '5GB fault-recovery%'")
conn.execute("DELETE FROM workers")
conn.commit()
conn.close()
'@ | docker exec -i api_server python -

docker compose start scheduler
```

### 7.2 只啟動 Worker B

```powershell
docker compose run -d `
    --name worker-b `
    -e WORKER_NAME=Worker-B-FaultDemo `
    -e DOWNLOAD_MODE=simulate `
    worker

Start-Sleep 8
```

取得 Worker B ID：

```powershell
$workers = (Invoke-WebRequest http://localhost:8000/get_workers).Content |
    ConvertFrom-Json

$b = @($workers) |
    Where-Object worker_name -EQ "Worker-B-FaultDemo" |
    Select-Object -Last 1

$bId = $b.worker_id
$b | Format-List
```

### 7.3 建立故障恢復任務

```powershell
$target = Invoke-RestMethod -Method Post `
    -Uri http://localhost:8000/create_task `
    -ContentType "application/json" `
    -Body (@{
        task_name="5GB fault-recovery target"
    } | ConvertTo-Json)
```

等待任務分配給 Worker B：

```powershell
do {
    Start-Sleep 1

    $tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
        ConvertFrom-Json

    $targetState = @($tasks) |
        Where-Object task_id -EQ $target.task_id

    $targetState |
        Select-Object task_name, status, worker_id, progress, retry_count |
        Format-Table
} until (
    $targetState.worker_id -eq $bId -and
    $targetState.status -eq "downloading"
)
```

確認 Worker B 進度持續增加：

```powershell
docker logs worker-b --tail 30
```

應看到：

```text
進度 -> 5%
進度 -> 10%
進度 -> 15%
```

若顯示 `下載失敗: via download_adapter`，表示 Worker 使用舊版程式。重新執行：

```powershell
docker rm -f worker-b
docker compose run -d `
    --name worker-b `
    -e WORKER_NAME=Worker-B-FaultDemo `
    -e DOWNLOAD_MODE=simulate `
    worker
```

### 7.4 啟動備援 Worker C

```powershell
docker compose run -d `
    --name worker-c `
    -e WORKER_NAME=Worker-C-Recovery `
    -e DOWNLOAD_MODE=simulate `
    worker

Start-Sleep 8
```

確認 Worker C：

```powershell
docker logs worker-c --tail 10
```

### 7.5 模擬 Worker B 故障

先確認 Worker B 正在下載，再停止：

```powershell
docker logs worker-b --tail 20
docker stop worker-b
```

不要立即移除 Worker B，保留故障前日誌作展示。

### 7.6 觀察 Scheduler 故障偵測

另開 PowerShell：

```powershell
cd D:\dragonflyfinal
docker compose logs -f scheduler
```

Scheduler 每 3 秒掃描，15 秒未收到 heartbeat 後，預期顯示：

```text
[DEAD]  偵測到 Worker ...
[RETRY] 任務 ... 重新排入待辦
[ASSIGN] 任務 ... -> Worker C
```

### 7.7 監控恢復結果

原本 PowerShell：

```powershell
do {
    Clear-Host

    $tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
        ConvertFrom-Json

    $workers = (Invoke-WebRequest http://localhost:8000/get_workers).Content |
        ConvertFrom-Json

    $task = @($tasks) |
        Where-Object task_id -EQ $target.task_id

    $assignedWorker = @($workers) |
        Where-Object worker_id -EQ $task.worker_id |
        Select-Object -Last 1

    [pscustomobject]@{
        task        = $task.task_name
        status      = $task.status
        assigned_to = $assignedWorker.worker_name
        progress    = $task.progress
        retry_count = $task.retry_count
        duration    = $task.duration
    } | Format-List

    Start-Sleep 2
} until ($task.status -in @("completed", "failed"))
```

最終預期：

```text
status      : completed
assigned_to : Worker-C-Recovery
progress    : 100
retry_count : 1
```

確認 Worker C：

```powershell
docker logs worker-c --tail 100
```

Dashboard「任務清單」與「故障恢復紀錄」應保留 Demo 1、Demo 2，並顯示 Demo 3 最終
完成且 `retry_count = 1`。

---

## 8. 常用檢查與排錯

### 8.1 查看所有相關容器

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### 8.2 查看專案核心服務

```powershell
docker compose ps
```

### 8.3 查看 one-off Worker

```powershell
docker ps --filter "name=worker-" `
    --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
```

### 8.4 查看 API 任務

```powershell
$tasks = (Invoke-WebRequest http://localhost:8000/get_tasks).Content |
    ConvertFrom-Json

@($tasks) |
    Select-Object task_name, status, worker_id, progress, retry_count, duration |
    Format-Table -AutoSize
```

### 8.5 Dragonfly 容器 Restarting

若 Manager、Scheduler、Client 持續 Restarting，通常是設定使用了 `127.0.1.1`：

```powershell
wsl bash -lc 'cd ~/dragonfly/deploy/docker-compose && export IP=$(hostname -I) && IP=${IP%% *} && IP=$IP ./run.sh'
```

### 8.6 dfget 服務名稱錯誤

本手冊使用的 Dragonfly Compose 版本沒有 `dfdaemon` service。使用：

```powershell
docker exec client dfget --version
```

而不是：

```text
docker compose exec dfdaemon ...
```

### 8.7 dfget 比 curl 慢

在同一台電腦上是正常現象。curl 路徑短，Dragonfly 會額外執行排程、分片、校驗、
快取與 proxy 傳輸。Demo 2 的重點是：

- 第一次 dfget 與第二次 dfget 的差異。
- Dragonfly log 中的 `from source` 與 `from local`。
- 降低 Origin Server 流量，而非保證單機單次下載一定更快。

---

## 9. 收尾

停止專案與 Worker：

```powershell
cd D:\dragonflyfinal
docker rm -f worker-a worker-b worker-c 2>$null
docker compose down --remove-orphans
```

停止官方 Dragonfly：

```powershell
wsl bash -lc "cd ~/dragonfly/deploy/docker-compose && docker compose down"
```
