#!/bin/bash
set -e  # Прерывать выполнение при ошибках

BASEDIR=$(dirname "$0")

echo "=== Создание namespace spark ==="
kubectl create namespace spark --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "=== Применение RBAC и proxy для Spark ==="
kubectl apply -f $BASEDIR/driver-proxy.yaml -n spark
kubectl apply -f $BASEDIR/spark-rbac.yaml -n spark

echo ""
echo "=== Установка MinIO ==="
# Добавляем Helm-репозиторий MinIO
helm repo add minio https://charts.min.io/
helm repo update

# Устанавливаем MinIO с простейшей конфигурацией (1 нода, режим standalone)
# Проверяем, установлен ли уже MinIO
if helm list -n spark | grep -q minio; then
    echo "MinIO уже установлен, пропускаем установку"
else
    echo "Устанавливаем MinIO..."
    helm install minio minio/minio \
        --namespace spark \
        --set mode=standalone \
        --set replicas=1 \
        --set persistence.enabled=false \
        --set resources.requests.memory=512Mi \
        --set rootUser=minioadmin \
        --set rootPassword=minioadmin123 \
        --set consoleService.type=ClusterIP \
        --set service.type=ClusterIP
    
    echo "Ожидание готовности MinIO..."
    # Проверяем готовность MinIO (раз в 2 секунды, до 30 попыток)
    for i in {1..30}; do
        if kubectl get pods -n spark -l app=minio -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q "Running"; then
            echo "✓ MinIO готов к работе (попытка $i)"
            sleep 2
            break
        fi
        echo "Ожидание MinIO... (попытка $i/30)"
        sleep 2
    done
    
    # Финальная проверка
    if ! kubectl get pods -n spark -l app=minio -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q "Running"; then
        echo "✗ MinIO не запустился за 60 секунд"
        exit 1
    fi
fi

echo ""
echo "=== Применение NodePort для MinIO ==="
kubectl apply -f $BASEDIR/minio-nodeport.yaml

echo ""
echo "=== Установка Kyverno ==="
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
kubectl create namespace kyverno --dry-run=client -o yaml | kubectl apply -f -

if helm list -n kyverno | grep -q "^kyverno\s"; then
    echo "Kyverno уже установлен, пропускаем установку"
else
    helm install kyverno kyverno/kyverno -n kyverno
fi

if helm list -n kyverno | grep -q kyverno-policies; then
    echo "Kyverno policies уже установлены, пропускаем установку"
else
    helm install kyverno-policies kyverno/kyverno-policies -n kyverno
fi

echo ""
echo "=== Установка Policy Reporter ==="
helm repo add policy-reporter https://kyverno.github.io/policy-reporter
helm repo update

if helm list -n kyverno | grep -q policy-reporter; then
    echo "Policy Reporter уже установлен, пропускаем установку"
else
    helm install policy-reporter policy-reporter/policy-reporter -n kyverno \
        --set ui.enabled=true \
        --set kyverno-plugin.enabled=true
fi

echo ""
echo "==================================================================="
echo "✓ Установка завершена!"
echo "==================================================================="
echo ""
echo "MinIO доступен:"
echo "  - API (S3):     http://$(minikube ip):30900"
echo "  - Console (UI): http://$(minikube ip):30901"
echo "  - Credentials:  minioadmin / minioadmin123"
echo ""
echo "Policy Reporter UI:"
echo "  Запустите: kubectl port-forward service/policy-reporter-ui 8082:8080 -n kyverno"
echo "  Откройте:  http://localhost:8082"
echo "==================================================================="