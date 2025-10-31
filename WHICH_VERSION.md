# Какую версию политики использовать?

## Быстрый выбор

```
У вас Spark executor'ы в одном namespace?
│
├─ ДА → Используйте NAMESPACED версию ✅
│        ./apply-ban-policy-namespaced.sh spark
│
└─ НЕТ → Используйте CLUSTER-SCOPED версию
         ./apply-ban-policy.sh
```

## Сравнение версий

| Критерий | Cluster-scoped | Namespaced |
|----------|----------------|------------|
| **Файл** | `spark-app-banning-policy.yaml` | `spark-app-banning-policy-namespaced.yaml` |
| **Скрипт** | `apply-ban-policy.sh` | `apply-ban-policy-namespaced.sh` |
| **Тип политики** | `ClusterPolicy` | `Policy` |
| **Scope** | Весь кластер | Один namespace |
| **Применение** | `kubectl apply -f file.yaml` | `kubectl apply -f file.yaml -n <ns>` |
| **Namespace** | Жестко задан в YAML | Параметр скрипта |
| **RBAC** | `ClusterRole` | `Role` |
| **Гибкость** | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Безопасность** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Простота** | ⭐⭐⭐ | ⭐⭐⭐⭐ |

## Используйте NAMESPACED версию если:

✅ **Executor'ы в одном namespace**
```bash
# Все executor'ы в namespace 'spark'
./apply-ban-policy-namespaced.sh spark
```

✅ **Разные окружения (dev/staging/prod)**
```bash
./apply-ban-policy-namespaced.sh dev
./apply-ban-policy-namespaced.sh staging
./apply-ban-policy-namespaced.sh prod
```

✅ **Хотите задавать namespace в скрипте**
```bash
NAMESPACE="my-spark-namespace"
./apply-ban-policy-namespaced.sh "$NAMESPACE"
```

✅ **Нужна изоляция между проектами**
```bash
./apply-ban-policy-namespaced.sh project-a
./apply-ban-policy-namespaced.sh project-b
```

✅ **Минимальные RBAC права**
- `Role` вместо `ClusterRole`
- Права только в одном namespace

## Используйте CLUSTER-SCOPED версию если:

✅ **Executor'ы в разных namespaces**
```bash
# Заблокировать во всех namespaces сразу
./apply-ban-policy.sh
```

✅ **Централизованное управление**
```bash
# Одна политика для всего кластера
./apply-ban-policy.sh
```

✅ **Нужно заблокировать везде**
```bash
# Блокирует в spark, spark-dev, spark-prod, etc.
./apply-ban-policy.sh
```

## Примеры использования

### Пример 1: Один Spark кластер

**Ситуация:** Все executor'ы в namespace `spark`

**Решение:** Namespaced версия
```bash
./apply-ban-policy-namespaced.sh spark
```

**Почему:** Проще, безопаснее, все ресурсы в одном месте

---

### Пример 2: Dev и Prod окружения

**Ситуация:** 
- Dev executor'ы в `spark-dev`
- Prod executor'ы в `spark-prod`

**Решение:** Namespaced версия для каждого
```bash
# Забанить в dev
./apply-ban-policy-namespaced.sh spark-dev

# Забанить в prod
./apply-ban-policy-namespaced.sh spark-prod
```

**Почему:** Изоляция между окружениями

---

### Пример 3: Множество проектов

**Ситуация:** 
- Проект A: executor'ы в `project-a-spark`
- Проект B: executor'ы в `project-b-spark`
- Проект C: executor'ы в `project-c-spark`

**Решение:** Namespaced версия
```bash
./apply-ban-policy-namespaced.sh project-a-spark
./apply-ban-policy-namespaced.sh project-b-spark
./apply-ban-policy-namespaced.sh project-c-spark
```

**Почему:** Каждый проект изолирован

---

### Пример 4: Общий Spark кластер

**Ситуация:** Executor'ы могут быть в любом namespace

**Решение:** Cluster-scoped версия
```bash
./apply-ban-policy.sh
```

**Почему:** Нужно заблокировать везде

---

### Пример 5: Динамические namespaces

**Ситуация:** Namespaces создаются динамически (CI/CD)

**Решение:** Namespaced версия в скрипте
```bash
#!/bin/bash
NAMESPACE="spark-${CI_PIPELINE_ID}"
kubectl create namespace "$NAMESPACE"
./apply-ban-policy-namespaced.sh "$NAMESPACE"
```

**Почему:** Гибкость в выборе namespace

## Миграция между версиями

### С cluster-scoped на namespaced

```bash
# 1. Удалить cluster-scoped
kubectl delete -f spark-app-banning-policy.yaml

# 2. Применить namespaced
./apply-ban-policy-namespaced.sh spark
```

### С namespaced на cluster-scoped

```bash
# 1. Удалить namespaced из всех namespaces
kubectl delete -f spark-app-banning-policy-namespaced.yaml -n spark
kubectl delete -f spark-app-banning-policy-namespaced.yaml -n spark-dev
# ... для каждого namespace

# 2. Применить cluster-scoped
./apply-ban-policy.sh
```

## Рекомендации

### 🎯 Рекомендуется: Namespaced версия

**Причины:**
- ✅ Более гибкая (namespace как параметр)
- ✅ Более безопасная (меньше прав)
- ✅ Проще отлаживать (все в одном namespace)
- ✅ Лучше изоляция

**Когда:** В 90% случаев

### ⚠️ Используйте cluster-scoped только если:
- Executor'ы действительно в разных namespaces
- Нужна централизованная политика для всего кластера

## Быстрая команда

### Namespaced (рекомендуется)
```bash
./apply-ban-policy-namespaced.sh spark
```

### Cluster-scoped
```bash
./apply-ban-policy.sh
```

## Проверка версии

### Какая версия установлена?

```bash
# Cluster-scoped
kubectl get clusterpolicy deny-spark-app-pyspark-k8s-client

# Namespaced
kubectl get policy deny-spark-app-pyspark-k8s-client -n spark
```

### В каких namespaces установлена namespaced версия?

```bash
kubectl get policy --all-namespaces | grep deny-spark-app
```

## Итоговая рекомендация

**Используйте namespaced версию по умолчанию:**
```bash
./apply-ban-policy-namespaced.sh spark
```

**Переходите на cluster-scoped только если:**
- У вас executor'ы в разных namespaces
- Вам действительно нужна политика для всего кластера
