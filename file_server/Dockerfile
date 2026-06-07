# file server: 用 nginx 提供原始檔案 (Dragonfly seed peer 回源的對象)
FROM nginx:alpine

# 開啟目錄瀏覽，方便確認叢集裡有哪些檔可下載 (可選)
RUN sed -i 's#location / {#location / {\n        autoindex on;#' /etc/nginx/conf.d/default.conf

# 把測試檔烤進 image (build 前請先跑 ./gen_files.sh 產生 files/)
COPY files/ /usr/share/nginx/html/

EXPOSE 80
