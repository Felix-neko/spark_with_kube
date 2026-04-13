# ═══════════════════════════════════════════════════════════════════════════
# Базовый образ Apache Spark с возможностью выбора версии
# ═══════════════════════════════════════════════════════════════════════════
ARG SPARK_VERSION=3.5.8
FROM apache/spark:${SPARK_VERSION}-python3

# Build args (повторно объявляем после FROM, т.к. ARG до FROM не виден после него)
ARG PYTHON_VERSION=3.8

# Используем bash для более читаемых скриптов (вместо sh по умолчанию)
SHELL ["/bin/bash", "-c"]

# Переключаемся на root для установки пакетов (базовый образ использует пользователя spark)
USER root

# ═══════════════════════════════════════════════════════════════════════════
# Установка Python нужной версии с двумя стратегиями:
#   1. Быстрый путь: deadsnakes PPA (работает для 3.8, 3.9+ на Ubuntu jammy/focal)
#      Время установки: ~30 секунд
#   2. Медленный fallback: pyenv (сборка из исходников)
#      Время установки: ~5-10 минут
#      Используется для EOL-версий (например, Python 3.7) и других версий,
#      недоступных в deadsnakes PPA
# ═══════════════════════════════════════════════════════════════════════════
ENV PYENV_ROOT=/opt/pyenv
RUN apt-get update && \
    # Устанавливаем базовые инструменты для добавления PPA и скачивания файлов
    apt-get install -y software-properties-common curl && \
    # Добавляем deadsnakes PPA (репозиторий с новыми версиями Python для Ubuntu)
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    # Пытаемся установить Python из PPA (|| true игнорирует ошибку, если версия недоступна)
    apt-get install -y "python${PYTHON_VERSION}" 2>/dev/null || true; \
    # Проверяем, установился ли Python; если нет - используем pyenv
    if ! command -v "python${PYTHON_VERSION}" &>/dev/null; then \
        echo "=== python${PYTHON_VERSION} недоступен через apt, собираем через pyenv ===" && \
        # Устанавливаем зависимости для сборки Python из исходников
        apt-get install -y --no-install-recommends \
            git build-essential libssl-dev zlib1g-dev libbz2-dev \
            libreadline-dev libsqlite3-dev libffi-dev liblzma-dev && \
        # Скачиваем и устанавливаем pyenv
        curl -fsSL https://pyenv.run | bash && \
        # Устанавливаем Python через pyenv (компиляция из исходников)
        /opt/pyenv/bin/pyenv install "${PYTHON_VERSION}" && \
        # Получаем полную версию Python, установленную pyenv (например, 3.7.17 вместо 3.7)
        PYENV_FULL_VERSION=$(/opt/pyenv/bin/pyenv versions --bare | grep "^${PYTHON_VERSION}" | head -n1) && \
        echo "=== Установлена версия: ${PYENV_FULL_VERSION} ===" && \
        # Создаём символическую ссылку python3.7 -> /opt/pyenv/versions/3.7.17/bin/python3
        ln -sf "/opt/pyenv/versions/${PYENV_FULL_VERSION}/bin/python3" \
               "/usr/local/bin/python${PYTHON_VERSION}" && \
        # Создаём символическую ссылку python3 -> /opt/pyenv/versions/3.7.17/bin/python3
        ln -sf "/opt/pyenv/versions/${PYENV_FULL_VERSION}/bin/python3" \
               "/usr/local/bin/python3" && \
        # Извлекаем мажорную версию (например, "3" из "3.7") и создаём ссылку python3 -> python3.7
        PYTHON_MAJOR=$(echo "${PYTHON_VERSION}" | cut -d. -f1) && \
        ln -sf "/opt/pyenv/versions/${PYENV_FULL_VERSION}/bin/python3" \
               "/usr/local/bin/python${PYTHON_MAJOR}" && \
        # Проверяем, что Python доступен и работает
        /usr/local/bin/python${PYTHON_VERSION} --version && \
        echo "=== pyenv: Python ${PYTHON_VERSION} установлен ==="; \
    fi && \
    # Пытаемся установить venv и dev-пакеты (|| true игнорирует ошибки для pyenv-версий)
    (apt-get install -y "python${PYTHON_VERSION}-venv" || true) && \
    (apt-get install -y "python${PYTHON_VERSION}-dev"  || true) && \
    # Финальная проверка версии Python
    python${PYTHON_VERSION} --version && \
    # Очищаем apt-кэш для уменьшения размера образа
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ═══════════════════════════════════════════════════════════════════════════
# Установка pip с несколькими fallback-стратегиями:
#   1. Проверяем, установлен ли pip уже (для pyenv-версий)
#   2. Используем ensurepip (встроенный модуль Python для установки pip)
#   3. Скачиваем версионированный get-pip.py (для EOL-версий типа Python 3.7)
#   4. Скачиваем универсальный get-pip.py (последний fallback)
# ═══════════════════════════════════════════════════════════════════════════
RUN python${PYTHON_VERSION} -m pip --version 2>/dev/null || \
    python${PYTHON_VERSION} -m ensurepip --upgrade 2>/dev/null || \
    curl -sSL "https://bootstrap.pypa.io/pip/${PYTHON_VERSION}/get-pip.py" | python${PYTHON_VERSION} || \
    curl -sSL "https://bootstrap.pypa.io/get-pip.py" | python${PYTHON_VERSION}

# ═══════════════════════════════════════════════════════════════════════════
# Установка необходимых Python-библиотек для работы с PySpark:
#   - dill==0.3.5.1  : Сериализация Python-объектов для передачи между узлами Spark
#   - pandas<2       : Работа с DataFrame (версия <2 для совместимости)
#   - pyarrow==8     : Оптимизированная сериализация данных между Spark и Pandas
# ═══════════════════════════════════════════════════════════════════════════
RUN python${PYTHON_VERSION} -m pip install --no-cache-dir \
    dill==0.3.5.1 \
    'pandas<2' \
    pyarrow==8

# ═══════════════════════════════════════════════════════════════════════════
# Установка утилит для отладки:
#   - iputils-ping : утилита ping для проверки сетевой связности между узлами
# ═══════════════════════════════════════════════════════════════════════════
RUN apt-get update -y && \
    apt install -y iputils-ping && \
    apt-get clean

# ═══════════════════════════════════════════════════════════════════════════
# Возвращаемся к пользователю spark (безопасность: не запускаем Spark под root)
# ═══════════════════════════════════════════════════════════════════════════
USER ${spark_uid}
