#!/bin/bash
set -e

cat > /etc/nginx/sites-available/tradeaxis << 'NGINX'
server {
    listen 80;
    server_name tradeaxis.ru www.tradeaxis.ru _;
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
NGINX

nginx -t && service nginx reload
echo "=== Nginx OK (HTTP mode for Cloudflare) ==="
