#!/bin/bash

# ═══════════════════════════════════════════════════════════════════════════
# Скрипт для сборки и публикации Docker-образа Apache Spark в Docker Hub
# ═══════════════════════════════════════════════════════════════════════════
# Репозиторий: https://hub.docker.com/repository/docker/felixneko/spark
#
# Использование:
#   ./build_and_push.sh [--python-version=X.Y] [--pyspark-version=X.Y.Z]
#
# Примеры:
#   ./build_and_push.sh                                          # Использует версии по умолчанию
#   ./build_and_push.sh --python-version=3.9                     # Python 3.9 + Spark по умолчанию
#   ./build_and_push.sh --pyspark-version=3.4.4                  # Spark 3.4.4 + Python по умолчанию
#   ./build_and_push.sh --python-version=3.7 --pyspark-version=3.4.4  # Кастомные версии обоих
#
# Примечания:
#   - Для Python 3.7 и других EOL-версий сборка займёт ~5-10 минут (компиляция через pyenv)
#   - Для Python 3.8+ сборка займёт ~30 секунд (установка из deadsnakes PPA)
#   - Требуется авторизация в Docker Hub (docker login)
# ═══════════════════════════════════════════════════════════════════════════

# Прерывать выполнение скрипта при любой ошибке
set -e

# ═══════════════════════════════════════════════════════════════════════════
# Версии по умолчанию
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_PYTHON_VERSION="3.8"      # Python 3.8 - стабильная версия с хорошей поддержкой
DEFAULT_PYSPARK_VERSION="3.5.8"  # Последняя стабильная версия PySpark на момент создания скрипта

# ═══════════════════════════════════════════════════════════════════════════
# Разбор аргументов командной строки
# ═══════════════════════════════════════════════════════════════════════════
# Инициализируем переменные значениями по умолчанию
PYTHON_VERSION="$DEFAULT_PYTHON_VERSION"
PYSPARK_VERSION="$DEFAULT_PYSPARK_VERSION"

# Обрабатываем аргументы командной строки
while [[ $# -gt 0 ]]; do
    case $1 in
        --python-version=*)
            # Извлекаем значение после знака "="
            PYTHON_VERSION="${1#*=}"
            shift
            ;;
        --pyspark-version=*)
            # Извлекаем значение после знака "="
            PYSPARK_VERSION="${1#*=}"
            shift
            ;;
        *)
            # Неизвестный аргумент - выводим ошибку и справку
            echo "Неизвестный аргумент: $1"
            echo "Использование: $0 [--python-version=X.Y] [--pyspark-version=X.Y.Z]"
            exit 1
            ;;
    esac
done

# ═══════════════════════════════════════════════════════════════════════════
# Настройки и переменные окружения
# ═══════════════════════════════════════════════════════════════════════════
# Формируем имя образа в формате: felixneko/spark:spark-X.Y.Z-python-X.Y-ping
IMAGE_NAME="felixneko/spark:spark-${PYSPARK_VERSION}-python-${PYTHON_VERSION}-ping"

# Путь к конфигурации Docker (для проверки авторизации)
DOCKER_CONFIG="$HOME/.docker/config.json"

# Определяем директорию, где находится этот скрипт (там же лежит Dockerfile)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Выводим информацию о параметрах сборки
echo "═══════════════════════════════════════════════════════════════════════════"
echo "Параметры сборки Docker-образа:"
echo "═══════════════════════════════════════════════════════════════════════════"
echo "Python версия : ${PYTHON_VERSION}"
echo "PySpark версия: ${PYSPARK_VERSION}"
echo "Образ         : ${IMAGE_NAME}"
echo "Директория    : ${SCRIPT_DIR}"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

echo "Начинаем сборку и публикацию образа ${IMAGE_NAME} в Docker Hub..."
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Этап 1: Сборка Docker-образа
# ═══════════════════════════════════════════════════════════════════════════
echo "[1/3] Сборка Docker-образа..."
echo "      Это может занять от 30 секунд до 10 минут в зависимости от версии Python"
echo ""

# Запускаем сборку с передачей build-аргументов:
#   --build-arg PYTHON_VERSION - передаём версию Python в Dockerfile
#   --build-arg SPARK_VERSION  - передаём версию Spark в Dockerfile
#   -t                         - тег образа
#   последний аргумент         - контекст сборки (директория с Dockerfile)
if ! docker build \
    --build-arg PYTHON_VERSION="${PYTHON_VERSION}" \
    --build-arg SPARK_VERSION="${PYSPARK_VERSION}" \
    -t "${IMAGE_NAME}" \
    "${SCRIPT_DIR}"; then
    echo "✗ Ошибка при сборке образа"
    exit 1
fi

echo ""
echo "✓ Образ ${IMAGE_NAME} успешно собран"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Этап 2: Проверка авторизации в Docker Hub
# ═══════════════════════════════════════════════════════════════════════════
echo "[2/3] Проверка авторизации в Docker Hub..."

# Workaround для проблемы с credsStore в Docker Desktop
# credsStore может вызывать ошибки при push, поэтому временно отключаем его
CREDS_STORE_BACKUP=""
if [ -f "$DOCKER_CONFIG" ]; then
    if grep -q '"credsStore"' "$DOCKER_CONFIG"; then
        echo "      Обнаружен credsStore, временно отключаем для избежания проблем с авторизацией..."
        # Создаём backup оригинального config.json
        cp "$DOCKER_CONFIG" "${DOCKER_CONFIG}.backup"
        CREDS_STORE_BACKUP="${DOCKER_CONFIG}.backup"
        # Удаляем поле credsStore из конфигурации с помощью jq
        jq 'del(.credsStore)' "${DOCKER_CONFIG}.backup" > "$DOCKER_CONFIG"
    fi
fi

# Проверяем, есть ли в конфигурации токен авторизации для Docker Hub
if ! grep -q '"https://index.docker.io/v1/"' "$DOCKER_CONFIG" 2>/dev/null; then
    echo "✗ Не найдена авторизация в Docker Hub"
    echo "   Выполните: docker login"
    echo "   Затем повторите запуск этого скрипта"
    exit 1
fi

echo "✓ Авторизация в Docker Hub найдена"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# Этап 3: Публикация образа в Docker Hub
# ═══════════════════════════════════════════════════════════════════════════
echo "[3/3] Отправка образа в Docker Hub..."
echo "      Это может занять несколько минут в зависимости от скорости интернета"
echo ""

# Отправляем образ в Docker Hub
if docker push "${IMAGE_NAME}"; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "✓ Образ ${IMAGE_NAME} успешно опубликован в Docker Hub"
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "Доступен по адресу: https://hub.docker.com/repository/docker/felixneko/spark"
    echo ""
    echo "Использование:"
    echo "  docker pull ${IMAGE_NAME}"
    echo "  docker run -it ${IMAGE_NAME} /bin/bash"
    echo "═══════════════════════════════════════════════════════════════════════════"

    # Восстанавливаем backup конфигурации Docker, если он был создан
    if [ -n "$CREDS_STORE_BACKUP" ] && [ -f "$CREDS_STORE_BACKUP" ]; then
        echo "Восстанавливаем оригинальную конфигурацию Docker..."
        mv "$CREDS_STORE_BACKUP" "$DOCKER_CONFIG"
    fi

    exit 0
else
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "✗ Ошибка при публикации образа"
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "Возможные причины:"
    echo "  1. Проблемы с сетевым подключением"
    echo "  2. Недостаточно прав для публикации в репозиторий felixneko/spark"
    echo "  3. Истёк срок действия токена авторизации (выполните: docker login)"
    echo "═══════════════════════════════════════════════════════════════════════════"

    # Восстанавливаем backup конфигурации Docker, если он был создан
    if [ -n "$CREDS_STORE_BACKUP" ] && [ -f "$CREDS_STORE_BACKUP" ]; then
        mv "$CREDS_STORE_BACKUP" "$DOCKER_CONFIG"
    fi

    exit 1
fi
