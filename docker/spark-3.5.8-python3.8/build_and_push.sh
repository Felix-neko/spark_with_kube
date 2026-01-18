#!/bin/bash

# Скрипт для публикации Docker-образа в Docker Hub
# Репозиторий: https://hub.docker.com/repository/docker/felixneko/spark
# Тег: spark-3.5.8-python-3.8

set -e

IMAGE_NAME="felixneko/spark:spark-3.5.8-python-3.8"
DOCKER_CONFIG="$HOME/.docker/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Сборка и публикация образа ${IMAGE_NAME} в Docker Hub..."

# Собираем образ
echo "Сборка Docker-образа..."
if ! docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"; then
    echo "✗ Ошибка при сборке образа"
    exit 1
fi

echo "✓ Образ ${IMAGE_NAME} успешно собран"

# Проверяем наличие проблемного credsStore и временно отключаем его
CREDS_STORE_BACKUP=""
if [ -f "$DOCKER_CONFIG" ]; then
    if grep -q '"credsStore"' "$DOCKER_CONFIG"; then
        echo "Обнаружен credsStore, временно отключаем для избежания проблем с авторизацией..."
        cp "$DOCKER_CONFIG" "${DOCKER_CONFIG}.backup"
        CREDS_STORE_BACKUP="${DOCKER_CONFIG}.backup"
        jq 'del(.credsStore)' "${DOCKER_CONFIG}.backup" > "$DOCKER_CONFIG"
    fi
fi

# Проверяем авторизацию в Docker Hub
if ! grep -q '"https://index.docker.io/v1/"' "$DOCKER_CONFIG" 2>/dev/null; then
    echo "✗ Не найдена авторизация в Docker Hub"
    echo "Выполните: docker login"
    exit 1
fi

echo "✓ Авторизация в Docker Hub найдена"

# Публикуем образ в Docker Hub
echo "Отправка образа в Docker Hub..."
if docker push "${IMAGE_NAME}"; then
    echo "✓ Образ ${IMAGE_NAME} успешно опубликован в Docker Hub"
    echo "Доступен по адресу: https://hub.docker.com/repository/docker/felixneko/spark"
    
    # Восстанавливаем backup, если он был создан
    if [ -n "$CREDS_STORE_BACKUP" ] && [ -f "$CREDS_STORE_BACKUP" ]; then
        echo "Восстанавливаем оригинальную конфигурацию Docker..."
        mv "$CREDS_STORE_BACKUP" "$DOCKER_CONFIG"
    fi
    
    exit 0
else
    echo "✗ Ошибка при публикации образа"
    
    # Восстанавливаем backup, если он был создан
    if [ -n "$CREDS_STORE_BACKUP" ] && [ -f "$CREDS_STORE_BACKUP" ]; then
        mv "$CREDS_STORE_BACKUP" "$DOCKER_CONFIG"
    fi
    
    exit 1
fi
