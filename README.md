# spark_with_kube

Базовый пример для запуска PySpark в **client mode** с executor'ами в Kubernetes.

## 📋 Описание проекта

Этот проект демонстрирует, как запустить Apache Spark приложение на Python, где:
- **Driver** работает локально на вашей машине (вне Kubernetes)
- **Executor'ы** запускаются как поды внутри Kubernetes кластера
- Коммуникация между driver и executor'ами происходит через специальный proxy Service

## 🗂️ Структура проекта

### Основные файлы

#### `pyspark_on_kube_example.py`
**Назначение:** Главный Python скрипт с примером Spark приложения.

**Что делает:**
- Создает SparkSession с конфигурацией для Kubernetes
- Настраивает аутентификацию через minikube сертификаты
- Запускает тестовый job (подсчет чисел от 0 до 999)
- Демонстрирует работу Spark в client mode

**Ключевые настройки:**
- `spark.submit.deployMode=client` - driver локально, executor'ы в K8s
- `spark.driver.host=driver-proxy.spark.svc.cluster.local` - адрес для executor'ов
- `spark.kubernetes.authenticate.driver.serviceAccountName=spark-client` - RBAC

---

#### `spark-rbac.yaml`
**Назначение:** Настройка RBAC (Role-Based Access Control) для Spark.

**Что создает:**
1. **Namespace `spark`** - изолированное пространство для Spark ресурсов
2. **ServiceAccount `spark-client`** - идентификатор для Spark driver'а
3. **Role `spark-role`** - набор разрешений (создание pods, services, configmaps, secrets)
4. **RoleBinding `spark-rolebinding`** - связывает ServiceAccount с Role

**Зачем нужно:**
Spark driver должен иметь права в Kubernetes для создания и управления executor подами.
Без этих прав Spark не сможет запустить executor'ы.

---

#### `driver-proxy.yaml`
**Назначение:** Service и Endpoints для проксирования трафика из K8s на локальную машину.

**Проблема, которую решает:**
В client mode driver работает вне кластера, но executor'ы внутри кластера должны
подключаться к driver'у. Executor'ы не могут напрямую достучаться до вашей машины.

**Решение:**
- Создается Service `driver-proxy` без selector'а
- Вручную создаются Endpoints, указывающие на IP вашей локальной машины
- Executor'ы подключаются к `driver-proxy.spark.svc.cluster.local`
- Трафик перенаправляется на вашу машину через Endpoints

**Порты:**
- `7077` - RPC коммуникация driver-executor
- `7078` - BlockManager (передача данных)
- `4040` - Spark Web UI

**⚠️ ВАЖНО:** В файле нужно указать актуальный IP вашей машины!

---

#### `spark-app-banning-policy.yaml`
**Назначение:** Kyverno ClusterPolicy для временного запрета запуска конкретного Spark приложения.

**Что делает:**
- Блокирует создание подов с меткой `spark-app-selector=pyspark-k8s-client`
- Применяется только к ServiceAccount `spark-client` в namespace `spark`
- Автоматически удаляется через 15 минут с помощью Kubernetes Job

**Компоненты:**
1. **ClusterPolicy** - правило валидации Kyverno
2. **Job** - удаляет политику через 15 минут (sleep 900)
3. **ServiceAccount** - для Job с правами на удаление ClusterPolicy
4. **ClusterRole + ClusterRoleBinding** - RBAC для удаления политик

**Применение:**
```bash
kubectl apply -f spark-app-banning-policy.yaml
```

---

#### `setup_minikube.sh`
**Назначение:** Скрипт для первоначальной настройки minikube кластера.

**Что делает:**
- Удаляет старый minikube кластер
- Настраивает системные параметры (inotify limits)
- Запускает minikube с Docker driver
- Включает необходимые addons (metrics-server, storage, ingress)

**Параметры запуска:**
- 8 CPU cores
- 32 GB RAM
- 100 GB disk

---

#### `install.sh`
**Назначение:** Скрипт для установки всех необходимых компонентов в Kubernetes.

**Что устанавливает:**
1. Создает namespace `spark`
2. Применяет driver-proxy Service и Endpoints
3. Применяет RBAC правила
4. Устанавливает Kyverno (policy engine)
5. Устанавливает Kyverno Policies
6. Устанавливает Policy Reporter (UI для просмотра политик)
7. Запускает port-forward для Policy Reporter UI на порт 8082

**Использование:**
```bash
./install.sh
```

---

#### `pyproject.toml`
**Назначение:** Конфигурация Python проекта и зависимостей.

**Зависимости:**
- `pyspark` - Apache Spark для Python

**Управление зависимостями:**
Проект использует `uv` (современный менеджер пакетов Python).

---

#### `.gitignore`
**Назначение:** Список файлов и директорий, игнорируемых Git.

**Игнорируемые файлы:**
- `.venv/` - виртуальное окружение Python
- `__pycache__/` - скомпилированные Python файлы
- `.idea/` - настройки PyCharm/IntelliJ
- и другие временные файлы

---

## 🚀 Быстрый старт

### 1. Подготовка окружения

```bash
# Запустить minikube (если еще не запущен)
./setup_minikube.sh

# Установить все компоненты в Kubernetes
./install.sh

# Создать Python виртуальное окружение и установить зависимости
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 2. Проверка IP адреса

Проверьте, что IP в `driver-proxy.yaml` соответствует IP вашей машины:

```bash
ip addr show | grep "inet "
```

Если IP отличается, обновите файл `driver-proxy.yaml` и примените изменения:

```bash
kubectl apply -f driver-proxy.yaml
```

### 3. Запуск Spark приложения

```bash
python pyspark_on_kube_example.py
```

### 4. Мониторинг

Во время выполнения можно наблюдать за подами:

```bash
# Смотреть поды в namespace spark
kubectl get pods -n spark -w

# Логи executor'а
kubectl logs -n spark <executor-pod-name>

# Spark UI (если порт 4040 открыт)
# http://localhost:4040
```

---

## 🔍 Как это работает

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  Локальная машина (вне Kubernetes)                          │
│                                                               │
│  ┌──────────────────────────────────────┐                   │
│  │  PySpark Driver                      │                   │
│  │  - Запускает SparkSession            │                   │
│  │  - Управляет executor'ами            │                   │
│  │  - Слушает на портах 7077, 7078      │                   │
│  └──────────────────────────────────────┘                   │
│           │                                                   │
│           │ Kubernetes API                                   │
│           ▼                                                   │
└───────────┼───────────────────────────────────────────────────┘
            │
┌───────────┼───────────────────────────────────────────────────┐
│ Kubernetes Cluster                                            │
│           │                                                   │
│           ▼                                                   │
│  ┌─────────────────────┐         ┌─────────────────────┐    │
│  │ driver-proxy        │         │ Executor Pod 1      │    │
│  │ Service + Endpoints │◄────────┤ - Выполняет задачи  │    │
│  │ (192.168.1.66)      │         │ - Отправляет данные │    │
│  └─────────────────────┘         └─────────────────────┘    │
│           ▲                                                   │
│           │                       ┌─────────────────────┐    │
│           └───────────────────────┤ Executor Pod 2      │    │
│                                   │ - Выполняет задачи  │    │
│                                   │ - Отправляет данные │    │
│                                   └─────────────────────┘    │
│                                                               │
│  namespace: spark                                            │
└───────────────────────────────────────────────────────────────┘
```

### Поток выполнения

1. **Инициализация:**
   - Python скрипт создает SparkSession
   - Driver аутентифицируется в K8s через minikube сертификаты
   - Driver использует ServiceAccount `spark-client` для создания ресурсов

2. **Создание executor'ов:**
   - Driver создает ConfigMap с конфигурацией
   - Driver создает Pod'ы для executor'ов в namespace `spark`
   - Executor'ы запускаются с образом `apache/spark:3.4.4-python3`

3. **Коммуникация:**
   - Executor'ы подключаются к `driver-proxy.spark.svc.cluster.local:7077`
   - Service перенаправляет трафик на `192.168.1.66:7077` (ваша машина)
   - Driver и executor'ы обмениваются задачами и данными

4. **Выполнение job:**
   - Driver отправляет задачи executor'ам
   - Executor'ы выполняют вычисления
   - Результаты возвращаются driver'у

5. **Завершение:**
   - `spark.stop()` удаляет все executor поды
   - Очищаются ConfigMap'ы и другие ресурсы

---

## 🛡️ Kyverno Policy Management

### Применение политики запрета

Чтобы временно заблокировать запуск приложения `pyspark-k8s-client`:

```bash
kubectl apply -f spark-app-banning-policy.yaml
```

Политика автоматически удалится через 15 минут.

### Просмотр политик

```bash
# Список всех ClusterPolicy
kubectl get clusterpolicy

# Детали политики
kubectl describe clusterpolicy deny-spark-app-pyspark-k8s-client

# Policy Reporter UI (если установлен)
# http://localhost:8082
```

### Ручное удаление политики

```bash
kubectl delete clusterpolicy deny-spark-app-pyspark-k8s-client
kubectl delete job delete-spark-policy-after-15min -n kyverno
```

---

## 🐛 Troubleshooting

### Проблема: SSL timeout при создании executor'ов

**Причина:** Неправильная аутентификация в Kubernetes API.

**Решение:** Проверьте пути к сертификатам в `pyspark_on_kube_example.py`:
```bash
ls -la ~/.minikube/ca.crt
ls -la ~/.minikube/profiles/minikube/client.key
ls -la ~/.minikube/profiles/minikube/client.crt
```

### Проблема: Executor'ы не могут подключиться к driver

**Причина:** Неправильный IP в `driver-proxy.yaml`.

**Решение:**
1. Узнайте IP вашей машины: `ip addr show`
2. Обновите IP в `driver-proxy.yaml`
3. Примените изменения: `kubectl apply -f driver-proxy.yaml`

### Проблема: Permission denied при создании подов

**Причина:** RBAC не настроен.

**Решение:**
```bash
kubectl apply -f spark-rbac.yaml
```

---

## 📚 Дополнительные ресурсы

- [Apache Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html)
- [Kyverno Documentation](https://kyverno.io/docs/)
- [Minikube Documentation](https://minikube.sigs.k8s.io/docs/)

---

## 📝 Лицензия

Этот проект предназначен для образовательных целей.
