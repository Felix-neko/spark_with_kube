FROM apache/spark:3.5.8-python3

# Переключаемся на root для установки пакетов
USER root

# Устанавливаем software-properties-common для работы с PPA
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Добавляем PPA deadsnakes и устанавливаем Python 3.8
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.8 python3.8-venv python3.8-dev python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Устанавливаем pip для Python 3.8
RUN python3.8 -m ensurepip --upgrade || \
    (apt-get update && apt-get install -y python3.8-distutils curl && \
     curl -sS https://bootstrap.pypa.io/get-pip.py | python3.8 && \
     apt-get clean && rm -rf /var/lib/apt/lists/*)

# Устанавливаем необходимые Python-библиотеки для Python 3.8
RUN python3.8 -m pip install --no-cache-dir \
    dill==0.3.5.1 \
    'pandas<2' \
    pyarrow==8

# Возвращаемся к пользователю spark (если он был в базовом образе)
USER ${spark_uid}
