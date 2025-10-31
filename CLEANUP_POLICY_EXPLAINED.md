# Политика удаления существующих подов

## Проблема

Стандартная Kyverno `ClusterPolicy` с `validate` правилами блокирует только **создание новых** подов. Если поды уже запущены, они продолжат работать.

## Решение

Добавлены **три механизма** для удаления существующих подов:

### 1. Background Mode (базовый)

```yaml
spec:
  background: true  # Применять политику к существующим ресурсам
```

**Ограничение:** `validate` правила с `background: true` только проверяют существующие ресурсы, но **не удаляют** их.

### 2. ClusterCleanupPolicy (автоматический)

```yaml
apiVersion: kyverno.io/v2beta1
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-banned-spark-app
spec:
  schedule: "*/30 * * * * *"  # Каждые 30 секунд
  match:
    any:
    - resources:
        kinds:
          - Pod
        namespaces:
          - spark
        selector:
          matchLabels:
            spark-app-name: pyspark-k8s-client
```

**Как работает:**
- Каждые 30 секунд сканирует namespace `spark`
- Находит поды с меткой `spark-app-name=pyspark-k8s-client`
- Автоматически удаляет их

**Требования:** Kyverno 1.10+ (поддержка `v2beta1` CleanupPolicy)

### 3. Immediate Cleanup Job (мгновенный)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: cleanup-banned-pods-immediate
spec:
  template:
    spec:
      containers:
      - name: kubectl
        command:
        - kubectl delete -n spark -l spark-app-name=pyspark-k8s-client pods
```

**Как работает:**
- Запускается сразу при применении политики
- Немедленно удаляет все существующие поды с запрещенной меткой
- Завершается после выполнения

## Полный workflow

1. **Применяем политику:**
   ```bash
   kubectl apply -f spark-app-banning-policy.yaml
   ```

2. **Что происходит:**
   - ✅ `ClusterPolicy` блокирует создание новых подов
   - ✅ `Job` немедленно удаляет существующие поды (0-5 секунд)
   - ✅ `ClusterCleanupPolicy` продолжает мониторить каждые 30 секунд
   - ✅ Через 15 минут все политики автоматически удаляются

## Проверка работы

### Быстрый способ (рекомендуется)

```bash
# Используйте готовый скрипт
./apply-ban-policy.sh
```

Скрипт автоматически:
- Применит все политики
- Дождется запуска Job
- Покажет логи удаления
- Проверит, что поды удалены

### Ручной способ

#### Шаг 1: Запустить Spark приложение
```bash
python pyspark_on_kube_example.py
```

#### Шаг 2: Проверить, что поды запущены
```bash
kubectl get pods -n spark -l spark-app-name=pyspark-k8s-client
```

#### Шаг 3: Применить политику бана (БЕЗ флага -n!)
```bash
# ❌ НЕПРАВИЛЬНО: kubectl apply -f spark-app-banning-policy.yaml -n kyverno
# ✅ ПРАВИЛЬНО:
kubectl apply -f spark-app-banning-policy.yaml
```

**Важно:** Не указывайте `-n kyverno`! Файл содержит ресурсы для разных namespace:
- `ClusterPolicy` - cluster-scoped (без namespace)
- `ClusterCleanupPolicy` - cluster-scoped (без namespace)
- `Job` - в namespace `spark`
- `ServiceAccount`, `Role`, `RoleBinding` - в namespace `spark`
- Cleanup Job для политик - в namespace `kyverno`

#### Шаг 4: Дождаться удаления подов (2-5 секунд)
```bash
# Поды должны быть удалены почти сразу
watch kubectl get pods -n spark -l spark-app-name=pyspark-k8s-client
```

#### Шаг 5: Проверить логи Job
```bash
kubectl logs -n spark job/cleanup-banned-pods-immediate
```

Ожидаемый вывод:
```
[Fri Oct 31 13:30:15 UTC 2025] Starting immediate cleanup of banned pods...
Target: pods with label spark-app-name=pyspark-k8s-client in namespace spark

Searching for pods...
✗ Found pods to delete:
  - pod/pyspark-k8s-client-xxx-exec-1
  - pod/pyspark-k8s-client-xxx-exec-2

Deleting pods...
  pod "pyspark-k8s-client-xxx-exec-1" force deleted
  pod "pyspark-k8s-client-xxx-exec-2" force deleted

✓ Cleanup completed successfully.
[Fri Oct 31 13:30:18 UTC 2025] Job finished.
```

## Версии Kyverno

### Kyverno 1.10+
Используйте `ClusterCleanupPolicy` (рекомендуется):
```yaml
apiVersion: kyverno.io/v2beta1
kind: ClusterCleanupPolicy
```

### Kyverno < 1.10
Удалите `ClusterCleanupPolicy` из файла, оставьте только:
- `ClusterPolicy` (блокирует новые)
- `Job` (удаляет существующие один раз)

## Безопасность

### RBAC для удаления подов

```yaml
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: spark-pod-cleaner
  namespace: spark

# Role - права только на поды в namespace spark
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: spark-pod-cleaner-role
  namespace: spark
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "delete"]
```

**Принцип наименьших привилегий:** Job имеет права только на удаление подов в namespace `spark`, не может влиять на другие ресурсы.

## Альтернативы

### Вариант 1: Использовать только Job (без CleanupPolicy)
Если не нужен постоянный мониторинг, удалите `ClusterCleanupPolicy` из файла.

### Вариант 2: Использовать kubectl напрямую
```bash
kubectl delete pods -n spark -l spark-app-name=pyspark-k8s-client --force --grace-period=0
```

### Вариант 3: Использовать Kyverno Generate Policy
Можно создать политику, которая генерирует ConfigMap с триггером для удаления, но это более сложно.

## Troubleshooting

### Поды удаляются слишком долго (более 10 секунд)

**Причина:** Вы применили политику с флагом `-n kyverno`, и Job не был создан в namespace `spark`.

**Решение:**
```bash
# Удалите политику
kubectl delete -f spark-app-banning-policy.yaml

# Примените БЕЗ флага -n
kubectl apply -f spark-app-banning-policy.yaml

# Или используйте скрипт
./apply-ban-policy.sh
```

### CleanupPolicy не работает
```bash
# Проверить версию Kyverno
kubectl get deployment -n kyverno kyverno -o jsonpath='{.spec.template.spec.containers[0].image}'

# Если версия < 1.10, удалите ClusterCleanupPolicy
kubectl delete clustercleanuppolicy cleanup-banned-spark-app
```

### Job не удаляет поды
```bash
# Проверить, создан ли Job
kubectl get job -n spark cleanup-banned-pods-immediate

# Проверить логи Job
kubectl logs -n spark job/cleanup-banned-pods-immediate

# Проверить RBAC
kubectl auth can-i delete pods --as=system:serviceaccount:spark:spark-pod-cleaner -n spark

# Если RBAC не настроен, применить заново
kubectl apply -f spark-app-banning-policy.yaml
```

### Job завершился с ошибкой
```bash
# Посмотреть детали
kubectl describe job -n spark cleanup-banned-pods-immediate

# Пересоздать Job
kubectl delete job -n spark cleanup-banned-pods-immediate
kubectl apply -f spark-app-banning-policy.yaml
```

### Поды не удаляются принудительно
```bash
# Удалить finalizers вручную
kubectl patch pod <pod-name> -n spark -p '{"metadata":{"finalizers":null}}'

# Или удалить напрямую
kubectl delete pod <pod-name> -n spark --force --grace-period=0
```
