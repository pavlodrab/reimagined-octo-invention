#!/bin/bash
# deploy.sh — быстрый деплой на свой сервер
# Использование: ./deploy.sh user@your-server.com

set -e

SERVER="${1:?Usage: ./deploy.sh user@server.com}"
DOMAIN="${2:-chelsea-bot.com}"

echo "🚀 Deploying to $SERVER ..."

# Копируем файлы на сервер
rsync -avz --exclude='venv' --exclude='__pycache__' --exclude='*.db' \
    --exclude='.env' --exclude='data/' \
    ./ "$SERVER:~/chelsea-bot/"

ssh "$SERVER" << REMOTE
    cd ~/chelsea-bot

    # Если нет .env — создаём шаблон
    if [ ! -f .env ]; then
        cp .env.example .env
        echo "⚠️  Edit .env with your tokens!"
    fi

    # Загружаем переменные из .env
    export \$(grep -v '^#' .env | xargs)

    # Собираем и запускаем
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d

    # Получаем SSL (первый раз)
    if [ ! -d certbot/conf ]; then
        mkdir -p certbot/conf certbot/www
        docker-compose run --rm certbot certonly \
            --webroot -w /var/www/certbot \
            --email your@email.com \
            -d \$DOMAIN -d www.\$DOMAIN \
            --agree-tos --no-eff-email
        docker-compose restart nginx
    fi

    echo "✅ Deployed! https://\$DOMAIN
    echo "📋 Set Mini App URL in @BotFather: https://\$DOMAIN"
REMOTE

echo "✅ Done!"
