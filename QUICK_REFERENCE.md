# Быстрая справка

## Выбор версии политики

### 🎯 Рекомендуется: Namespaced версия
```bash
# Применить в namespace 'spark'
./apply-ban-policy-namespaced.sh spark

# Применить в другом namespace
./apply-ban-policy-namespaced.sh production
```

**Когда использовать:** Executor'ы в одном namespace (90% случаев)

### Cluster-scoped версия
```bash
./apply-ban-policy.sh
```

**Когда использовать:** Executor'ы в разных namespaces

📖 **Подробнее:** См. `WHICH_VERSION.md`

---

## Применение политики бана

### ✅ Namespaced (рекомендуется)
```bash
# С помощью скрипта
./apply-ban-policy-namespaced.sh spark

# Вручную
kubectl apply -f spark-app-banning-policy-namespaced.yaml -n spark
```

### ✅ Cluster-scoped
```bash
# С помощью скрипта
./apply-ban-policy.sh

# Вручную
kubectl apply -f spark-app-banning-policy.yaml
```

### ❌ Неправильно (cluster-scoped с флагом -n)
```bash
kubectl apply -f spark-app-banning-policy.yaml -n kyverno  # Job не создастся!
```

## Почему не нужен флаг `-n`?

Файл `spark-app-banning-policy.yaml` содержит ресурсы в **разных namespace**:

| Ресурс | Namespace | Scope |
|--------|-----------|-------|
| `ClusterPolicy` | - | cluster-scoped |
| `ClusterCleanupPolicy` | - | cluster-scoped |
| `Job` (immediate cleanup) | `spark` | namespaced |
| `ServiceAccount` | `spark` | namespaced |
| `Role` | `spark` | namespaced |
| `RoleBinding` | `spark` | namespaced |
| `Job` (policy cleanup) | `kyverno` | namespaced |
| `ServiceAccount` (kyverno) | `kyverno` | namespaced |
| `ClusterRole` | - | cluster-scoped |
| `ClusterRoleBinding` | - | cluster-scoped |

При использовании `-n kyverno`:
- ❌ Job в namespace `spark` не создастся
- ❌ RBAC ресурсы в namespace `spark` не создадутся
- ❌ Поды не будут удалены немедленно
- ✅ Только ClusterPolicy и cleanup Job в `kyverno` применятся

## Таймлайн удаления подов

### С правильным применением
```
0s   - kubectl apply -f spark-app-banning-policy.yaml
1s   - ClusterPolicy активна (блокирует новые поды)
2s   - Job запущен
3s   - Job находит поды
4s   - Поды удаляются
5s   - Готово! ✓
```

### С неправильным применением (-n kyverno)
```
0s   - kubectl apply -f spark-app-banning-policy.yaml -n kyverno
1s   - ClusterPolicy активна (блокирует новые поды)
...  - Job не создан в namespace spark
30s  - CleanupPolicy первый запуск (по расписанию)
35s  - Поды удаляются
```

## Проверка статуса

```bash
# Проверить, что Job создан
kubectl get job -n spark cleanup-banned-pods-immediate

# Посмотреть логи Job
kubectl logs -n spark job/cleanup-banned-pods-immediate

# Проверить, что поды удалены
kubectl get pods -n spark -l spark-app-name=pyspark-k8s-client

# Проверить статус политик
kubectl get clusterpolicy deny-spark-app-pyspark-k8s-client
kubectl get clustercleanuppolicy cleanup-banned-spark-app
```

## Удаление политики вручную

```bash
# Удалить все политики
kubectl delete -f spark-app-banning-policy.yaml

# Или по отдельности
kubectl delete clusterpolicy deny-spark-app-pyspark-k8s-client
kubectl delete clustercleanuppolicy cleanup-banned-spark-app
kubectl delete job -n spark cleanup-banned-pods-immediate
```

## Изменение таргета политики

Чтобы забанить другое приложение, измените в файле:

```yaml
# Было
spark-app-name: pyspark-k8s-client

# Стало (например)
spark-app-name: my-other-app
```

И не забудьте изменить в нескольких местах:
1. ClusterPolicy → validate → pattern → labels
2. ClusterCleanupPolicy → match → selector → matchLabels
3. Job → command → kubectl get/delete -l

## Настройка скорости удаления

### CleanupPolicy (периодическая проверка)
```yaml
spec:
  schedule: "*/5 * * * * *"  # Каждые 5 секунд (по умолчанию)
  # schedule: "*/10 * * * * *"  # Каждые 10 секунд
  # schedule: "*/30 * * * * *"  # Каждые 30 секунд
```

### Job (задержка перед удалением)
```bash
# В скрипте Job
sleep 2  # Задержка 2 секунды (по умолчанию)
# sleep 0  # Без задержки
# sleep 5  # Задержка 5 секунд
```

## Отладка

### Job не запускается
```bash
# Проверить события
kubectl describe job -n spark cleanup-banned-pods-immediate

# Проверить RBAC
kubectl auth can-i delete pods --as=system:serviceaccount:spark:spark-pod-cleaner -n spark

# Пересоздать
kubectl delete job -n spark cleanup-banned-pods-immediate
kubectl apply -f spark-app-banning-policy.yaml
```

### Поды не удаляются
```bash
# Проверить статус подов
kubectl get pods -n spark -l spark-app-name=pyspark-k8s-client -o wide

# Удалить вручную
kubectl delete pods -n spark -l spark-app-name=pyspark-k8s-client --force --grace-period=0

# Удалить finalizers
kubectl patch pod <pod-name> -n spark -p '{"metadata":{"finalizers":null}}'
```

### CleanupPolicy не работает
```bash
# Проверить версию Kyverno (нужна 1.10+)
kubectl get deployment -n kyverno kyverno -o jsonpath='{.spec.template.spec.containers[0].image}'

# Проверить логи Kyverno
kubectl logs -n kyverno deployment/kyverno -f

# Если версия старая, используйте только Job (удалите ClusterCleanupPolicy)
```
