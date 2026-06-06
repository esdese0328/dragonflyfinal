# File Server 使用說明（第 2 人）

提供測試檔給 worker 下載的 nginx 伺服器，docker-compose 服務名稱為 `file-server`。
其他組員（特別是第 5、7 人）可依本說明使用。

---

## 1. 先產生測試檔（必做，每台機器都要）

測試檔很大、不會放進 git，所以每個人 clone 專案後要**自己先產生**。
這一步一定要在啟動前做，否則 build 出來的伺服器是空的。

```bash
cd file_server
./gen_files.sh        # 產生 100MB / 500MB / 1GB 三個檔
cd ..
```
想自訂大小：
```bash
SPEC="2GB=2G:model" ./gen_files.sh
```
跑完 `file_server/files/` 底下就會有 `.bin` 檔，同時產生 `checksums.txt` 與 `artifacts.json`（內含各檔 SHA-256，供第 7 人查）。

## 2. 啟動

檔案備好後，跟整套系統一起啟動（file-server 已寫進 `docker-compose.yml`）：

```bash
docker compose up -d --build
```

啟動後，叢集內其他容器（如 worker）可用服務名稱連線：
```
http://file-server/100MB.bin
```
本機（你的電腦）測試則用對外埠 8080：
```
http://localhost:8080/100MB.bin
```

---

## 3. 有哪些檔案可以下載

| 檔名 | 大小 | 叢集內 URL |
|------|------|-----------|
| `100MB.bin` | 100 MB | `http://file-server/100MB.bin` |
| `500MB.bin` | 500 MB | `http://file-server/500MB.bin` |
| `1GB.bin` | 1 GB | `http://file-server/1GB.bin` |

> 檔案是隨機內容（不可壓縮），benchmark 比較才公平。

---

## 4. 確認伺服器正常

```bash
curl -I http://localhost:8080/100MB.bin
```
看到 `HTTP/1.1 200 OK` 與 `Content-Length: 104857600` 就表示正常。

---

## 5. 用 Download Adapter 下載（第 5 人）

下載介面在 `worker/download_adapter.py`。worker 不需自己處理 curl / dfget 差異，呼叫一個函式即可：

```python
from download_adapter import download

# mode 用 "curl"(直連) 或 "dfget"(P2P)
ok = download(
    url="http://file-server/500MB.bin",
    output="/tmp/500MB.bin",
    mode="curl",
    progress_callback=lambda pct: print(f"進度 {pct}%"),
)
print("下載成功" if ok else "下載失敗")
```

- `download(...)` 成功回傳 `True`、失敗回傳 `False`
- `progress_callback(pct)` 會在下載過程中被呼叫（0~100），直接拿去更新 Dashboard 進度條

---

## 6. 量測 / 驗證 checksum（第 7 人 benchmark）

要計時與驗證檔案完整性，改用 `download_file(...)`，它回傳一個 dict：

```python
from download_adapter import download_file

r = download_file(
    url="http://file-server/500MB.bin",
    output="/tmp/500MB.bin",
    mode="curl",
    expected_sha256="b77711fe8798948fddcb0962aedde919ab40a8bd8212e2b398cb4dc5019c9d9d",
)
print(r)
# {'mode': 'curl', 'success': True, 'duration_sec': 3.42,
#  'size_bytes': 524288000, 'checksum_ok': True, ...}
```

也可以直接從命令列跑：
```bash
python3 worker/download_adapter.py http://localhost:8080/500MB.bin /tmp/out.bin curl
```

curl vs dfget 的比較，就是把 `mode` 換成 `"dfget"` 再跑一次，比較 `duration_sec`。

---

## 注意事項

- **dfget 模式需要 Dragonfly**：worker 的 Dockerfile 裡 dfget 安裝目前是註解掉的。沒有安裝 dfget 時，`mode="dfget"` 會回傳失敗。要測 P2P 請先安裝 dfget client 並部署 Dragonfly；在那之前用 `mode="curl"`。
- 測試檔很大、不進 git，每台機器各自用 `gen_files.sh` 產生。
