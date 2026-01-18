#!/bin/bash

# Скрипт для запуска PySpark-приложения в кластерном режиме на Kubernetes (minikube)
# В cluster mode и driver, и executors запускаются внутри Kubernetes

set -e

# ============================================================================
# АКТИВАЦИЯ ВИРТУАЛЬНОГО ОКРУЖЕНИЯ
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PATH="${PROJECT_ROOT}/.venv"

if [ -f "${VENV_PATH}/bin/activate" ]; then
    echo "Активация виртуального окружения: ${VENV_PATH}"
    source "${VENV_PATH}/bin/activate"
else
    echo "✗ Виртуальное окружение не найдено: ${VENV_PATH}"
    echo "Создайте его командой: uv venv"
    exit 1
fi

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

# URL Kubernetes API server (получить: kubectl cluster-info)
K8S_MASTER="k8s://https://192.168.85.2:8443"

# Docker-образ с Spark и Python 3.8
EXECUTOR_IMAGE="felixneko/spark:spark-3.5.8-python-3.8"

# Namespace в Kubernetes
NAMESPACE="spark"

# Путь к сертификатам minikube для аутентификации
CA_CERT="/home/felix/.minikube/ca.crt"
CLIENT_KEY="/home/felix/.minikube/profiles/minikube/client.key"
CLIENT_CERT="/home/felix/.minikube/profiles/minikube/client.crt"

# Путь к приложению
APP_FILE="${SCRIPT_DIR}/app.py"

# ============================================================================
# ПРОВЕРКИ
# ============================================================================

echo "Проверка окружения..."

# Проверяем наличие приложения
if [ ! -f "$APP_FILE" ]; then
    echo "✗ Файл приложения не найден: $APP_FILE"
    exit 1
fi
echo "✓ Файл приложения найден: $APP_FILE"

# Проверяем наличие сертификатов
if [ ! -f "$CA_CERT" ]; then
    echo "✗ CA сертификат не найден: $CA_CERT"
    exit 1
fi
echo "✓ CA сертификат найден"

# Проверяем доступность Kubernetes API
if ! kubectl cluster-info &>/dev/null; then
    echo "✗ Kubernetes API недоступен. Проверьте подключение к кластеру."
    exit 1
fi
echo "✓ Kubernetes API доступен"

# Проверяем наличие namespace
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "✗ Namespace '$NAMESPACE' не существует"
    echo "Создайте его командой: kubectl create namespace $NAMESPACE"
    exit 1
fi
echo "✓ Namespace '$NAMESPACE' существует"

# Проверяем наличие ServiceAccount
if ! kubectl get serviceaccount spark-client -n "$NAMESPACE" &>/dev/null; then
    echo "⚠ ServiceAccount 'spark-client' не найден в namespace '$NAMESPACE'"
    echo "Приложение может не запуститься без правильных RBAC-прав"
fi

echo ""
echo "=" * 80
echo "ЗАПУСК PYSPARK-ПРИЛОЖЕНИЯ В КЛАСТЕРНОМ РЕЖИМЕ"
echo "=" * 80
echo ""

# ============================================================================
# ОЧИСТКА СТАРЫХ ПОДОВ
# ============================================================================

echo "Удаление старого driver-пода (если существует)..."
kubectl delete pod spark-driver-cluster-demo -n "$NAMESPACE" --ignore-not-found=true

# ============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# ============================================================================

spark-submit \
    --master "$K8S_MASTER" \
    --deploy-mode cluster \
    --name "cluster-mode-custom-image-demo" \
    --conf spark.kubernetes.namespace="$NAMESPACE" \
    --conf spark.kubernetes.container.image="$EXECUTOR_IMAGE" \
    --conf spark.kubernetes.driver.pod.name="spark-driver-cluster-demo" \
    --conf spark.kubernetes.authenticate.driver.serviceAccountName="spark-client" \
    --conf spark.kubernetes.authenticate.submission.caCertFile="$CA_CERT" \
    --conf spark.kubernetes.authenticate.submission.clientKeyFile="$CLIENT_KEY" \
    --conf spark.kubernetes.authenticate.submission.clientCertFile="$CLIENT_CERT" \
    --conf spark.kubernetes.driverEnv.PYSPARK_PYTHON=python3.8 \
    --conf spark.kubernetes.driverEnv.PYSPARK_DRIVER_PYTHON=python3.8 \
    --conf spark.executorEnv.PYSPARK_PYTHON=python3.8 \
    --conf spark.pyspark.python=python3.8 \
    --conf spark.pyspark.driver.python=python3.8 \
    --conf spark.executor.instances=2 \
    --conf spark.executor.memory=1g \
    --conf spark.executor.cores=1 \
    --conf spark.driver.memory=1g \
    --conf spark.driver.cores=1 \
    --conf spark.network.timeout=600s \
    --conf spark.executor.heartbeatInterval=60s \
    --conf spark.kubernetes.submission.waitAppCompletion=true \
    --conf spark.kubernetes.driver.limit.cores=1 \
    --conf spark.kubernetes.executor.limit.cores=1 \
    --verbose \
    "$APP_FILE"

echo ""
echo "=" * 80
echo "ПРИЛОЖЕНИЕ ЗАВЕРШЕНО"
echo "=" * 80
echo ""
echo "Для просмотра логов driver'а выполните:"
echo "  kubectl logs -n $NAMESPACE spark-driver-cluster-demo"
echo ""
echo "Для просмотра всех подов Spark:"
echo "  kubectl get pods -n $NAMESPACE"
