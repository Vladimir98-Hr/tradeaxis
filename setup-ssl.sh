#!/bin/bash
set -e
cat > /etc/nginx/sites-available/tradeaxis << 'NGINX'
server {
    listen 80;
    server_name tradeaxis.ru www.tradeaxis.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name tradeaxis.ru www.tradeaxis.ru;

    ssl_certificate /etc/letsencrypt/live/tradeaxis.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tradeaxis.ru/privkey.pem;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
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
echo "=== HTTPS готов: https://tradeaxis.ru ==="
