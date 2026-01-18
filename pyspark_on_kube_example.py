"""
pyspark_on_kube_example.py

Пример запуска PySpark в client mode с executor'ами в Kubernetes.

Архитектура:
- Driver: Запускается локально на вашей машине (вне Kubernetes)
- Executors: Запускаются как поды внутри Kubernetes кластера
- Коммуникация: Через driver-proxy Service, который проксирует трафик
  из кластера на локальную машину

Требования:
1. Kubernetes кластер (minikube, kind, или реальный кластер)
2. kubectl настроен и имеет доступ к кластеру
3. Применены RBAC правила (spark-rbac.yaml)
4. Создан driver-proxy Service (driver-proxy.yaml)
5. Установлен PySpark (pip install pyspark)
"""

from pyspark.sql import SparkSession
import time
import sys
import signal

# ============================================================================
# КОНФИГУРАЦИЯ KUBERNETES
# ============================================================================

# URL Kubernetes API server
# Формат: k8s://https://<API_SERVER_IP>:<PORT>
# Получить можно командой: kubectl cluster-info
K8S_MASTER = "k8s://https://192.168.85.2:8443"

# Docker образ для executor'ов
# Должен содержать Spark той же версии, что и локальный PySpark
# Официальные образы: https://hub.docker.com/r/apache/spark
# EXECUTOR_IMAGE = "apache/spark:3.3.3-python3"  # Важно: здесь используется Python 3.8, у нас тоже должен быть Python 3.8
EXECUTOR_IMAGE = "felixneko/spark:spark-3.5.8-python-3.8"

# Namespace в Kubernetes, где будут создаваться executor поды
NAMESPACE = "spark"

# ============================================================================
# КОНФИГУРАЦИЯ DRIVER (для client mode)
# ============================================================================

# Hostname driver'а, который будет виден из Kubernetes
# Это DNS имя driver-proxy Service внутри кластера
# Формат: <service-name>.<namespace>.svc.cluster.local
DRIVER_HOST = "driver-proxy.spark.svc.cluster.local"

# Порт для RPC коммуникации между driver и executor'ами
DRIVER_PORT = "7077"

# Порт для BlockManager (передача данных между driver и executor'ами)
BLOCKMANAGER_PORT = "7078"

# ============================================================================
# ТАЙМАУТ ДЛЯ ВСЕГО ПРИЛОЖЕНИЯ
# ============================================================================

# Обработчик таймаута - должен быть определен ДО создания SparkSession
def timeout_handler(signum, frame):
    print(f"\n{'='*60}")
    print("⏱️  TIMEOUT: Приложение не смогло запуститься за 120 секунд")
    print("   Вероятно, executor'ы не могут быть созданы в Kubernetes.")
    print("   Проверьте:")
    print("   1. Нет ли Kyverno политик, блокирующих создание подов")
    print("   2. Достаточно ли ресурсов в кластере")
    print("   3. Правильно ли настроены RBAC права")
    print(f"{'='*60}\n")
    sys.exit(1)

# Устанавливаем глобальный таймаут для всего приложения
APP_TIMEOUT = 120  # 2 минуты
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(APP_TIMEOUT)

print(f"⏱️  Установлен таймаут: {APP_TIMEOUT} секунд для запуска приложения\n")

# ============================================================================
# СОЗДАНИЕ SPARK SESSION
# ============================================================================

spark = (
    SparkSession.builder
    .appName("pyspark-k8s-client")  # Имя приложения (видно в Spark UI)
    .master(K8S_MASTER)  # Kubernetes API server URL
    
    # ========================================================================
    # РЕЖИМ РАЗВЕРТЫВАНИЯ
    # ========================================================================
    # client mode - driver локально, executor'ы в Kubernetes
    # cluster mode - и driver, и executor'ы в Kubernetes
    .config("spark.submit.deployMode", "client")
    
    # ========================================================================
    # KUBERNETES КОНФИГУРАЦИЯ
    # ========================================================================
    # Namespace для создания executor подов
    .config("spark.kubernetes.namespace", NAMESPACE)
    
    # Docker образ для executor'ов
    .config("spark.kubernetes.container.image", EXECUTOR_IMAGE)
    
    # ========================================================================
    # DRIVER NETWORKING (критично для client mode!)
    # ========================================================================
    # Hostname, который executor'ы будут использовать для подключения к driver
    # Указываем на driver-proxy Service внутри кластера
    .config("spark.driver.host", DRIVER_HOST)
    
    # Bind на всех интерфейсах локальной машины
    .config("spark.driver.bindAddress", "0.0.0.0")
    
    # Порты для коммуникации
    .config("spark.driver.port", DRIVER_PORT)
    .config("spark.driver.blockManager.port", BLOCKMANAGER_PORT)
    
    # ========================================================================
    # KUBERNETES AUTHENTICATION
    # ========================================================================
    # ServiceAccount, от имени которого driver будет создавать executor'ы
    .config("spark.kubernetes.authenticate.driver.serviceAccountName", "spark-client")
    
    # Аутентификация через kubeconfig (для запуска вне кластера)
    # Эти сертификаты используются для подключения к Kubernetes API
    .config("spark.kubernetes.authenticate.submission.caCertFile", 
            "/home/felix/.minikube/ca.crt")  # CA сертификат кластера
    .config("spark.kubernetes.authenticate.submission.clientKeyFile", 
            "/home/felix/.minikube/profiles/minikube/client.key")  # Приватный ключ
    .config("spark.kubernetes.authenticate.submission.clientCertFile", 
            "/home/felix/.minikube/profiles/minikube/client.crt")  # Клиентский сертификат
    
    # ========================================================================
    # EXECUTOR КОНФИГУРАЦИЯ
    # ========================================================================
    # Количество executor'ов
    .config("spark.executor.instances", "2")
    
    # Память на executor (можно увеличить для больших данных)
    .config("spark.executor.memory", "1g")
    
    # CPU cores на executor
    .config("spark.executor.cores", "1")
    
    # ========================================================================
    # ТАЙМАУТЫ И СЕТЬ
    # ========================================================================
    # Общий таймаут для сетевых операций
    .config("spark.network.timeout", "600s")
    
    # Интервал heartbeat от executor к driver
    .config("spark.executor.heartbeatInterval", "60s")
    
    # Максимальный размер RPC сообщений (в MB)
    .config("spark.rpc.message.maxSize", "256")
    
    # ========================================================================
    # KUBERNETES SCHEDULER - ЗАЩИТА ОТ БЕСКОНЕЧНЫХ RETRY
    # ========================================================================
    # Максимальное количество попыток создания executor pod'а
    # По умолчанию Spark будет пытаться бесконечно
    .config("spark.kubernetes.allocation.batch.size", "2")  # Создавать по 2 пода за раз
    .config("spark.kubernetes.allocation.batch.delay", "5s")  # Задержка между батчами
    
    # КРИТИЧНО: Таймаут ожидания запуска executor'а
    # Если за это время executor не запустится, Spark прекратит попытки
    .config("spark.kubernetes.executor.request.timeout", "30s")
    
    # Интервал между попытками создания pod'ов
    .config("spark.kubernetes.allocation.executor.timeout", "30s")
    
    # Максимальное время ожидания создания pod'а (Spark 3.4+)
    .config("spark.kubernetes.executor.podNamePrefix", "pyspark-k8s-client")
    
    # Отключаем динамическое выделение, чтобы Spark не пытался бесконечно
    .config("spark.dynamicAllocation.enabled", "false")
    
    # Scheduler mode - fail fast при недоступности executor'ов
    .config("spark.scheduler.mode", "FAIR")
    .config("spark.scheduler.maxRegisteredResourcesWaitingTime", "30s")
    .config("spark.scheduler.minRegisteredResourcesRatio", "0.8")
    
    # ========================================================================
    # ЛОГИРОВАНИЕ
    # ========================================================================
    # Отключаем Event Log (можно включить для production)
    .config("spark.eventLog.enabled", "false")
    
    # Создаем или получаем существующую сессию
    .getOrCreate()
)

# ============================================================================
# ПРОВЕРКА КОНФИГУРАЦИИ
# ============================================================================

# Выводим информацию о Spark сессии
print("=" * 60)
print(f"Spark version: {spark.version}")
print(f"Spark master: {spark.sparkContext.master}")
print(f"App name: {spark.sparkContext.appName}")
print("=" * 60)

# ============================================================================
# ТЕСТОВЫЙ JOB
# ============================================================================

# Простой тест: создаем DataFrame с числами от 0 до 999 и считаем их
print("\nStarting test job...")
start_time = time.time()

try:
    # spark.range() создает DataFrame с одной колонкой "id"
    # Эта операция будет выполнена на executor'ах в Kubernetes
    df = spark.range(0, 1000)
    
    # count() - action, которая запускает вычисления на executor'ах
    # Если executor'ы не могут быть созданы, эта операция зависнет
    print(f"Count result: {df.count()}")
    
    elapsed = time.time() - start_time
    print(f"Test job completed successfully in {elapsed:.2f} seconds!\n")
    print("^__^")
    
except Exception as e:
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"ERROR: Job failed after {elapsed:.2f} seconds")
    print(f"Error type: {type(e).__name__}")
    print(f"Error message: {str(e)}")
    print(f"{'='*60}\n")
    
    # Проверяем, связана ли ошибка с Kubernetes admission webhook
    if "admission webhook" in str(e).lower() or "denied the request" in str(e).lower():
        print("⚠️  Приложение заблокировано Kyverno policy.")
        print("   Возможные решения:")
        print("   1. Измените appName в коде")
        print("   2. Удалите policy: kubectl delete clusterpolicy deny-spark-app-pyspark-k8s-client")
        print("   3. Подождите 15 минут (policy автоматически удалится)\n")
    
    # Останавливаем Spark и выходим с ошибкой
    spark.stop()
    sys.exit(1)

# ============================================================================
# ЗАВЕРШЕНИЕ
# ============================================================================

# Отключаем таймаут, так как приложение успешно завершилось
signal.alarm(0)

# Останавливаем Spark сессию и освобождаем ресурсы
# Это удалит все executor поды из Kubernetes
spark.stop()
print("Spark session stopped.")
