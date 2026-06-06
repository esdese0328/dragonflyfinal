#!/usr/bin/env bash
# gen_files.sh
# 一鍵：產生測試檔(隨機內容) + 計算 SHA-256 + 產生 artifacts.json
#
# 用法:
#   ./gen_files.sh                      # 用預設大小產生全部檔案
#   SPEC="model-small=10M:model" ./gen_files.sh   # 自訂(測試用小檔)
#   BASE_URL=http://localhost:8000 ./gen_files.sh # 自訂 URL host
#
set -euo pipefail
cd "$(dirname "$0")"

FILES_DIR="files"
# docker-compose service 名稱 (port 80); 本機測試可改成 http://localhost:8080
BASE_URL="${BASE_URL:-http://file-server}"

# 格式: 名稱=大小:類型 (空白分隔多筆)。名稱要跟 worker 解析的檔名一致: 100MB/500MB/1GB
DEFAULT_SPEC="100MB=100M:model 500MB=500M:model 1GB=1G:model"
SPEC="${SPEC:-$DEFAULT_SPEC}"

mkdir -p "$FILES_DIR"

echo "==> [1/3] 產生測試檔 (隨機內容, 不可壓縮)"
for entry in $SPEC; do
  name="${entry%%=*}"
  rest="${entry#*=}"
  size="${rest%%:*}"
  echo "    - $name.bin ($size)"
  head -c "$size" /dev/urandom > "$FILES_DIR/$name.bin"
done

echo "==> [2/3] 計算 SHA-256 -> checksums.txt"
( cd "$FILES_DIR" && sha256sum -- * 2>/dev/null | grep -v '\.gitkeep' ) > checksums.txt
cat checksums.txt

echo "==> [3/3] 產生 artifacts.json"
python3 - "$BASE_URL" "$SPEC" <<'PY'
import sys, os, json, hashlib

base_url, spec = sys.argv[1], sys.argv[2].split()

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()

arts = []
for e in spec:
    name, rest = e.split("=", 1)
    size, typ = rest.split(":")
    path = f"files/{name}.bin"
    arts.append({
        "name": name,
        "url": f"{base_url}/{name}.bin",
        "size": size,
        "size_bytes": os.path.getsize(path),
        "type": typ,
        "sha256": sha256(path),
    })

with open("artifacts.json", "w") as f:
    json.dump(arts, f, indent=2)
print(json.dumps(arts, indent=2))
PY

echo "==> 完成。檔案在 $FILES_DIR/，清單在 artifacts.json"
