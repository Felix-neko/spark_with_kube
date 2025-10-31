#!/bin/bash
# Скрипт для применения политики бана Spark-приложения в указанном namespace
# Использует namespaced версию политики (Policy вместо ClusterPolicy)

set -e

# Параметры по умолчанию
NAMESPACE="${1:-spark}"
POLICY_FILE="spark-app-banning-policy-namespaced.yaml"

echo "=========================================="
echo "Применение политики бана Spark-приложения"
echo "=========================================="
echo ""
echo "📦 Target namespace: $NAMESPACE"
echo "📄 Policy file: $POLICY_FILE"
echo ""

# Проверяем, что файл существует
if [ ! -f "$POLICY_FILE" ]; then
    echo "❌ Ошибка: файл $POLICY_FILE не найден"
    echo ""
    echo "Использование:"
    echo "  $0 [namespace]"
    echo ""
    echo "Примеры:"
    echo "  $0              # Использует namespace 'spark' по умолчанию"
    echo "  $0 spark        # Явно указываем namespace 'spark'"
    echo "  $0 production   # Применяем в namespace 'production'"
    exit 1
fi

# Проверяем, существует ли namespace
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "⚠️  Namespace '$NAMESPACE' не существует"
    read -p "Создать namespace '$NAMESPACE'? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kubectl create namespace "$NAMESPACE"
        echo "✅ Namespace '$NAMESPACE' создан"
    else
        echo "❌ Отменено"
        exit 1
    fi
fi

echo ""
echo "📋 Применяем политику в namespace '$NAMESPACE'..."
kubectl apply -f "$POLICY_FILE" -n "$NAMESPACE"

echo ""
echo "✅ Политика применена!"
echo ""

# Ждем 3 секунды для инициализации Job
echo "⏳ Ожидание запуска Job для немедленного удаления подов..."
sleep 3

# Проверяем статус Job
echo ""
echo "📊 Статус Job:"
kubectl get job cleanup-banned-pods-immediate -n "$NAMESPACE" 2>/dev/null || echo "  Job еще не создан или уже завершен"

echo ""
echo "📝 Логи Job (последние 30 строк):"
kubectl logs -n "$NAMESPACE" job/cleanup-banned-pods-immediate --tail=30 2>/dev/null || {
    echo "  Логи еще недоступны. Подождите несколько секунд и выполните:"
    echo "  kubectl logs -n $NAMESPACE job/cleanup-banned-pods-immediate"
}

echo ""
echo "🔍 Проверка подов с запрещенной меткой:"
BANNED_PODS=$(kubectl get pods -n "$NAMESPACE" -l spark-app-name=pyspark-k8s-client -o name 2>/dev/null || true)
if [ -z "$BANNED_PODS" ]; then
    echo "  ✓ Подов с меткой spark-app-name=pyspark-k8s-client не найдено"
else
    echo "  ⚠️  Найдены поды (возможно, в процессе удаления):"
    echo "$BANNED_PODS" | sed 's/^/    /'
fi

echo ""
echo "=========================================="
echo "Политика применена"
echo "=========================================="
echo ""
echo "Что произошло:"
echo "  1. ✅ Policy блокирует создание новых подов в namespace '$NAMESPACE'"
echo "  2. ✅ Job немедленно удалил существующие поды"
echo ""
echo "⚠️  ВАЖНО: Автоматическое удаление политики отключено"
echo "   (Job блокируется самой политикой из-за Kyverno autogen)"
echo ""
echo "Для удаления политики через 15 минут выполните в фоне:"
echo "  (sleep 900 && kubectl delete policy deny-spark-app-pyspark-k8s-client -n $NAMESPACE) &"
echo ""
read -p "Запустить таймер удаления на 15 минут? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    (sleep 900 && kubectl delete policy deny-spark-app-pyspark-k8s-client -n "$NAMESPACE" && echo "✅ Policy deleted after 15 minutes") &
    TIMER_PID=$!
    echo "✅ Таймер запущен (PID: $TIMER_PID)"
    echo "   Политика будет удалена через 15 минут"
    echo "   Для отмены: kill $TIMER_PID"
else
    echo "⏭️  Таймер не запущен. Удалите политику вручную когда нужно."
fi
echo ""
echo "Полезные команды:"
echo "  # Просмотр политики"
echo "  kubectl get policy -n $NAMESPACE"
echo ""
echo "  # Просмотр подов"
echo "  kubectl get pods -n $NAMESPACE"
echo ""
echo "  # Ручное удаление политики"
echo "  kubectl delete policy deny-spark-app-pyspark-k8s-client -n $NAMESPACE"
echo ""
echo "  # Удаление всех ресурсов"
echo "  kubectl delete -f $POLICY_FILE -n $NAMESPACE"
echo ""
