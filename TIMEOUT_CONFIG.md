# Конфигурация таймаутов для Spark on Kubernetes

## Проблема

По умолчанию Spark бесконечно пытается создать executor'ы в Kubernetes, даже если они блокируются admission webhook (например, Kyverno policy). Это приводит к спаму запросов в Kubernetes API.

## Критическое замечание

⚠️ **Таймаут должен быть установлен ДО создания SparkSession!**

Spark начинает пытаться создать executor'ы при первой **action** (например, `df.count()`), но может начать резервировать ресурсы уже при создании сессии. Поэтому таймаут нужно установить в самом начале программы.

## Решение

Добавлены два уровня защиты:

### 1. Spark Kubernetes конфигурация

```python
# Таймаут ожидания запуска executor'а (2 минуты)
.config("spark.kubernetes.executor.request.timeout", "120s")

# Интервал между попытками создания pod'ов
.config("spark.kubernetes.allocation.executor.timeout", "30s")

# Создавать executor'ы батчами с задержкой
.config("spark.kubernetes.allocation.batch.size", "2")
.config("spark.kubernetes.allocation.batch.delay", "5s")
```

**Ограничения:** Эти параметры не всегда надежно останавливают приложение при ошибках создания pod'ов.

### 2. Signal-based таймаут (надежный метод)

```python
import signal
import sys

# КРИТИЧНО: Определяем обработчик ДО создания SparkSession
def timeout_handler(signum, frame):
    print("TIMEOUT: Приложение не смогло запуститься за 120 секунд")
    sys.exit(1)

# Устанавливаем глобальный таймаут ДО создания SparkSession
APP_TIMEOUT = 120  # 2 минуты
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(APP_TIMEOUT)

# Теперь создаем SparkSession
spark = SparkSession.builder.appName("my-app").getOrCreate()

try:
    # Выполняем job
    result = df.count()
    
    # Отключаем таймаут при успехе
    signal.alarm(0)
except Exception as e:
    # Обработка ошибок
    spark.stop()
    sys.exit(1)
```

**Порядок важен:**
1. ✅ Определить `timeout_handler`
2. ✅ Установить `signal.alarm(120)`
3. ✅ Создать `SparkSession`
4. ✅ Выполнить job
5. ✅ Отключить `signal.alarm(0)` при успехе

## Поведение

- **Если executor'ы создаются успешно:** Job выполняется нормально
- **Если executor'ы заблокированы:** Через 2 минуты приложение завершится с кодом 1
- **Количество попыток:** Spark будет пытаться создать pod'ы в течение 2 минут с интервалами ~5 секунд (примерно 24 попытки вместо бесконечных)

## Альтернативные значения таймаута

```python
JOB_TIMEOUT = 60   # 1 минута (быстрый fail)
JOB_TIMEOUT = 120  # 2 минуты (рекомендуется)
JOB_TIMEOUT = 180  # 3 минуты (для медленных кластеров)
```

## Проверка работы

1. Примените Kyverno policy для блокировки:
   ```bash
   kubectl apply -f spark-app-banning-policy.yaml
   ```

2. Запустите приложение:
   ```bash
   python pyspark_on_kube_example.py
   ```

3. Приложение должно завершиться через ~2 минуты с сообщением о таймауте

## Отключение таймаута

Закомментируйте строки с `signal.alarm()` если нужно вернуть поведение по умолчанию.

## Troubleshooting

### Приложение не падает через 2 минуты

**Причина:** Таймаут был установлен ПОСЛЕ создания SparkSession.

**Решение:** Переместите код с `signal.alarm()` ПЕРЕД строкой `SparkSession.builder...getOrCreate()`.

**Неправильно:**
```python
spark = SparkSession.builder.getOrCreate()  # ❌ Таймаут еще не установлен
signal.alarm(120)  # ❌ Слишком поздно
```

**Правильно:**
```python
signal.alarm(120)  # ✅ Таймаут установлен
spark = SparkSession.builder.getOrCreate()  # ✅ Теперь защищено
```

### Spark продолжает пытаться создать executor'ы

**Причина:** Параметры Spark Kubernetes scheduler не всегда работают надежно.

**Решение:** Используйте `signal.alarm()` - это единственный гарантированный способ остановить приложение.

### Приложение зависает при создании SparkSession

**Причина:** Spark пытается подключиться к Kubernetes API и создать executor'ы.

**Решение:** Это нормально. `signal.alarm()` прервет процесс через указанное время.
