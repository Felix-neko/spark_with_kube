# Namespaced версия политики бана

## Отличия от cluster-scoped версии

| Аспект | Cluster-scoped | Namespaced |
|--------|----------------|------------|
| **Файл** | `spark-app-banning-policy.yaml` | `spark-app-banning-policy-namespaced.yaml` |
| **Скрипт** | `apply-ban-policy.sh` | `apply-ban-policy-namespaced.sh` |
| **Policy** | `ClusterPolicy` | `Policy` |
| **CleanupPolicy** | `ClusterCleanupPolicy` | `CleanupPolicy` |
| **RBAC** | `ClusterRole` + `ClusterRoleBinding` | `Role` + `RoleBinding` |
| **Scope** | Все namespaces | Один namespace |
| **Применение** | `kubectl apply -f file.yaml` | `kubectl apply -f file.yaml -n <namespace>` |
| **Namespace в YAML** | Явно указан | Не указан (задается в команде) |

## Преимущества namespaced версии

✅ **Гибкость:** Namespace задается в скрипте, не в YAML  
✅ **Переиспользование:** Один YAML для разных namespaces  
✅ **Изоляция:** Политика действует только в одном namespace  
✅ **Безопасность:** Меньше прав (Role вместо ClusterRole)  
✅ **Простота:** Все ресурсы в одном namespace  

## Использование

### Быстрый старт

```bash
# Применить в namespace 'spark' (по умолчанию)
./apply-ban-policy-namespaced.sh

# Применить в другом namespace
./apply-ban-policy-namespaced.sh production

# Применить в namespace 'dev'
./apply-ban-policy-namespaced.sh dev
```

### Ручное применение

```bash
# Применить в namespace 'spark'
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n spark

# Применить в namespace 'production'
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n production

# Применить в namespace 'dev'
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n dev
```

## Как это работает

### 1. Namespace определяется при применении

```bash
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n spark
#                                                           ^^^^^^^^
#                                                           Namespace задается здесь
```

### 2. Все ресурсы создаются в указанном namespace

```yaml
apiVersion: kyverno.io/v1
kind: Policy  # ← Namespaced ресурс
metadata:
  name: deny-spark-app-pyspark-k8s-client
  # namespace НЕ указан в YAML
  # будет взят из команды kubectl apply -n <namespace>
```

### 3. Job использует Downward API для получения namespace

```yaml
env:
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace  # ← Автоматически получаем namespace
```

```bash
# В скрипте Job
kubectl delete -n "$POD_NAMESPACE" -l spark-app-name=pyspark-k8s-client pods
#                 ^^^^^^^^^^^^^^^^
#                 Namespace берется из переменной окружения
```

## Примеры использования

### Пример 1: Разработка и продакшн

```bash
# Забанить приложение в dev
./apply-ban-policy-namespaced.sh dev

# Забанить приложение в production
./apply-ban-policy-namespaced.sh production
```

### Пример 2: Множественные Spark кластеры

```bash
# Spark кластер 1
./apply-ban-policy-namespaced.sh spark-cluster-1

# Spark кластер 2
./apply-ban-policy-namespaced.sh spark-cluster-2

# Spark кластер 3
./apply-ban-policy-namespaced.sh spark-cluster-3
```

### Пример 3: Временные namespace для тестов

```bash
# Создать временный namespace
kubectl create namespace spark-test-123

# Применить политику
./apply-ban-policy-namespaced.sh spark-test-123

# Удалить все после тестов
kubectl delete namespace spark-test-123
```

## Проверка

### Проверить, в каких namespaces активна политика

```bash
# Список всех Policy
kubectl get policy --all-namespaces | grep deny-spark-app

# Список всех CleanupPolicy
kubectl get cleanuppolicy --all-namespaces | grep cleanup-banned-spark-app
```

### Проверить ресурсы в конкретном namespace

```bash
NAMESPACE=spark

# Политики
kubectl get policy -n $NAMESPACE
kubectl get cleanuppolicy -n $NAMESPACE

# Jobs
kubectl get job -n $NAMESPACE

# ServiceAccounts и RBAC
kubectl get sa,role,rolebinding -n $NAMESPACE | grep -E "(spark-pod-cleaner|policy-cleanup)"
```

## Миграция с cluster-scoped на namespaced

### Шаг 1: Удалить старую cluster-scoped политику

```bash
kubectl delete -f spark-app-banning-policy.yaml
```

### Шаг 2: Применить новую namespaced политику

```bash
./apply-ban-policy-namespaced.sh spark
```

### Шаг 3: Проверить

```bash
# Старые ресурсы должны быть удалены
kubectl get clusterpolicy deny-spark-app-pyspark-k8s-client  # Должно быть пусто

# Новые ресурсы должны быть созданы
kubectl get policy deny-spark-app-pyspark-k8s-client -n spark  # Должно быть найдено
```

## Ограничения namespaced версии

⚠️ **Policy действует только в одном namespace**

Если у вас Spark executor'ы в разных namespaces, нужно применить политику в каждом:

```bash
./apply-ban-policy-namespaced.sh spark-ns-1
./apply-ban-policy-namespaced.sh spark-ns-2
./apply-ban-policy-namespaced.sh spark-ns-3
```

⚠️ **Нельзя блокировать поды во всех namespaces сразу**

Для этого используйте cluster-scoped версию:
```bash
./apply-ban-policy.sh
```

## Когда использовать какую версию?

### Используйте **namespaced** версию если:
- ✅ Spark executor'ы запускаются в одном namespace
- ✅ Нужна изоляция между окружениями (dev/staging/prod)
- ✅ Хотите минимальные RBAC права
- ✅ Хотите гибко задавать namespace в скрипте

### Используйте **cluster-scoped** версию если:
- ✅ Spark executor'ы в разных namespaces
- ✅ Нужно заблокировать приложение во всем кластере
- ✅ Хотите централизованное управление политиками

## Troubleshooting

### Политика не применяется

```bash
# Проверить, что namespace существует
kubectl get namespace spark

# Проверить, что политика создана в правильном namespace
kubectl get policy -n spark

# Проверить события
kubectl get events -n spark --sort-by='.lastTimestamp'
```

### Job не может удалить поды

```bash
# Проверить RBAC
kubectl auth can-i delete pods --as=system:serviceaccount:spark:spark-pod-cleaner -n spark

# Проверить, что ServiceAccount и Role созданы
kubectl get sa,role,rolebinding -n spark | grep spark-pod-cleaner
```

### Политика применилась не в том namespace

```bash
# Удалить из неправильного namespace
kubectl delete -f spark-app-banning-policy-namespaced.yaml -n wrong-namespace

# Применить в правильном namespace
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n correct-namespace
```

## Автоматизация

### Применить политику в нескольких namespaces

```bash
#!/bin/bash
NAMESPACES="spark-dev spark-staging spark-prod"

for ns in $NAMESPACES; do
    echo "Applying policy to namespace: $ns"
    ./apply-ban-policy-namespaced.sh "$ns"
    echo ""
done
```

### Применить политику во всех namespaces с определенной меткой

```bash
#!/bin/bash
# Найти все namespaces с меткой spark=enabled
NAMESPACES=$(kubectl get namespaces -l spark=enabled -o jsonpath='{.items[*].metadata.name}')

for ns in $NAMESPACES; do
    echo "Applying policy to namespace: $ns"
    ./apply-ban-policy-namespaced.sh "$ns"
    echo ""
done
```

## Сравнение команд

### Cluster-scoped версия
```bash
# Применить
kubectl apply -f spark-app-banning-policy.yaml

# Удалить
kubectl delete -f spark-app-banning-policy.yaml

# Проверить
kubectl get clusterpolicy
kubectl get clustercleanuppolicy
```

### Namespaced версия
```bash
# Применить
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n spark

# Удалить
kubectl delete -f spark-app-banning-policy-namespaced.yaml -n spark

# Проверить
kubectl get policy -n spark
kubectl get cleanuppolicy -n spark
```
