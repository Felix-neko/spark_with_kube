# Исправления ошибок

## Критические изменения в namespaced версии

### ❌ Удалена CleanupPolicy
**Причина:** Требует дополнительных RBAC прав на удаление подов  
**Решение:** Используется только immediate Job для одноразового удаления

### ❌ Удален автоматический cleanup Job
**Причина:** Блокируется самой политикой из-за Kyverno autogen правил  
**Решение:** Скрипт предлагает запустить таймер в фоне

### ✅ Изменена логика exclude
**Причина:** Namespaced Policy не может фильтровать по namespaces  
**Решение:** Используется exclude по именам подов и меткам

### ✅ Изменена логика validate
**Причина:** Блокировались поды без метки spark-app-name  
**Решение:** Проверка только если метка существует (anyPattern)

---

## Проблема 1: CleanupPolicy schedule формат

### Ошибка
```
Error: schedule spec in the cleanupPolicy is not in proper cron format
```

### Причина
Использовался формат с 6 полями (включая секунды):
```yaml
schedule: "*/5 * * * * *"  # ❌ Неправильно
```

### Решение
Стандартный cron формат использует 5 полей:
```yaml
schedule: "*/5 * * * *"  # ✅ Правильно
# Формат: минута час день месяц день_недели
```

**Примеры:**
```yaml
schedule: "*/5 * * * *"   # Каждые 5 минут
schedule: "*/10 * * * *"  # Каждые 10 минут
schedule: "0 * * * *"     # Каждый час
schedule: "0 0 * * *"     # Каждый день в полночь
```

**Важно:** Kyverno CleanupPolicy не поддерживает секунды в cron расписании.

---

## Проблема 2: Policy блокирует собственные Job'ы

### Ошибка
```
resource Job/spark/delete-spark-policy-after-15min was blocked due to the following policies 
deny-spark-app-pyspark-k8s-client:
  autogen-deny-pyspark-k8s-client-pods: validation error
```

### Причина
Kyverno автоматически создает правила для Job'ов (autogen), и политика блокирует поды cleanup Job'ов, потому что Kubernetes автоматически добавляет метку `job-name` к подам Job'а.

### Решение
Добавлен блок `exclude` для исключения cleanup Job'ов:

```yaml
rules:
  - name: deny-pyspark-k8s-client-pods
    match:
      any:
      - resources:
          kinds:
            - Pod
    
    # Исключаем cleanup Job'ы
    exclude:
      any:
      - resources:
          kinds:
            - Pod
          selector:
            matchLabels:
              job-name: delete-spark-policy-after-15min
      - resources:
          kinds:
            - Pod
          selector:
            matchLabels:
              job-name: cleanup-banned-pods-immediate
    
    validate:
      # ...
```

**Как работает:**
1. Kubernetes создает под для Job
2. Автоматически добавляет метку `job-name: <job-name>`
3. Kyverno проверяет метку
4. Если `job-name` совпадает с cleanup Job'ами - пропускает проверку
5. Иначе - применяет валидацию

---

## Проблема 3: Warnings при применении

### Warning 1: Deprecated validation actions
```
Warning: Validation failure actions enforce/audit are deprecated, use Enforce/Audit instead.
```

**Причина:** Kyverno изменил регистр для `validationFailureAction`

**Решение:** Использовать с заглавной буквы:
```yaml
# ❌ Старый формат
validationFailureAction: enforce

# ✅ Новый формат
validationFailureAction: Enforce
```

### Warning 2: Deprecated CleanupPolicy version
```
Warning: kyverno.io/v2beta1 CleanupPolicy is deprecated; use kyverno.io/v2 CleanupPolicy
```

**Причина:** API версия устарела

**Решение:** Использовать `v2`:
```yaml
# ❌ Старая версия
apiVersion: kyverno.io/v2beta1

# ✅ Новая версия
apiVersion: kyverno.io/v2
```

---

## Применение исправлений

### Обновить существующие политики

```bash
# Удалить старые
kubectl delete -f spark-app-banning-policy.yaml
kubectl delete -f spark-app-banning-policy-namespaced.yaml -n spark

# Применить исправленные
./apply-ban-policy.sh
# или
./apply-ban-policy-namespaced.sh spark
```

### Проверить, что все работает

```bash
# Проверить политику
kubectl get policy -n spark

# Проверить CleanupPolicy
kubectl get cleanuppolicy -n spark

# Проверить Job'ы
kubectl get job -n spark

# Проверить логи
kubectl logs -n spark job/cleanup-banned-pods-immediate
```

---

## Дополнительные исключения

Если нужно исключить другие поды от проверки:

### По namespace
```yaml
exclude:
  any:
  - resources:
      namespaces:
        - kube-system
        - kyverno
        - monitoring
```

### По метке
```yaml
exclude:
  any:
  - resources:
      kinds:
        - Pod
      selector:
        matchLabels:
          exclude-from-policy: "true"
```

### По имени
```yaml
exclude:
  any:
  - resources:
      kinds:
        - Pod
      names:
        - "special-pod-*"
```

### Комбинированное
```yaml
exclude:
  any:
  # Системные namespaces
  - resources:
      namespaces:
        - kube-system
        - kyverno
  # Cleanup Job'ы
  - resources:
      kinds:
        - Pod
      selector:
        matchLabels:
          job-name: cleanup-banned-pods-immediate
  # Поды с особой меткой
  - resources:
      kinds:
        - Pod
      selector:
        matchLabels:
          skip-validation: "true"
```

---

## Troubleshooting

### CleanupPolicy не работает после исправления

```bash
# Проверить версию API
kubectl get cleanuppolicy -n spark -o yaml | grep apiVersion

# Если v2beta1, пересоздать
kubectl delete cleanuppolicy cleanup-banned-spark-app -n spark
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n spark
```

### Job все еще блокируется

```bash
# Проверить, что exclude правило применилось
kubectl get policy deny-spark-app-pyspark-k8s-client -n spark -o yaml | grep -A 10 exclude

# Проверить метки пода Job'а
kubectl get pods -n spark -l job-name=cleanup-banned-pods-immediate -o yaml | grep -A 5 labels
```

### Политика не применяется к новым подам

```bash
# Проверить статус политики
kubectl get policy deny-spark-app-pyspark-k8s-client -n spark -o jsonpath='{.status}'

# Проверить логи Kyverno
kubectl logs -n kyverno deployment/kyverno -f
```
