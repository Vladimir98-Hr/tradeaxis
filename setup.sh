#!/bin/bash
set -e

# Nginx конфиг
cat > /etc/nginx/sites-available/tradeaxis << 'NGINX'
server {
    listen 80;
    server_name _;
    client_max_body_size 10M;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX

ln -sf /etc/nginx/sites-available/tradeaxis /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
service nginx start
nginx -t && service nginx reload

echo "=== Nginx OK ==="
echo "=== Сайт доступен на http://186.246.13.52/ ==="
