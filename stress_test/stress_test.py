# Generated with Claude Sonnet 4.5

import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from stress_test.settings import KubeSparkMasterSettings, KubeStressTestSettings


def _bytes_to_spark_memory_str(memory_bytes: float) -> str:
    """Конвертирует байты в строку Spark-формата (например '4g', '512m')."""
    gib = memory_bytes / (1024**3)
    if gib >= 1.0:
        return f"{max(1, int(gib))}g"
    mib = memory_bytes / (1024**2)
    return f"{max(512, int(mib))}m"


def process_stress_test(kube_master_settings: KubeSparkMasterSettings, stress_test_settings: KubeStressTestSettings):
    """
    Создаёт Spark-сессию в client mode, подключается к K8s-кластеру
    и нагружает его CPU и памятью в течение заданного времени.

    CPU-нагрузка: параллельные вычисления (sin/cos/sqrt) на каждом ядре.
    Память: резервируется через spark.executor.memory (K8s блокирует ресурсы на нодах).
    """
    from pyspark.sql import SparkSession

    # --- Вычисляем параметры ---
    if isinstance(stress_test_settings.duration, timedelta):
        duration_sec = stress_test_settings.duration.total_seconds()
    else:
        duration_sec = float(stress_test_settings.duration)

    n_exec = stress_test_settings.num_executors
    target_total_cores = stress_test_settings.cores_target_utilization
    target_total_memory = stress_test_settings.memory_target_utilization

    memory_per_executor_bytes = target_total_memory / n_exec
    memory_per_executor_str = _bytes_to_spark_memory_str(memory_per_executor_bytes)
    # Количество partition-ов ≈ количество целевых ядер (каждая partition грузит одно ядро)
    num_partitions = int(target_total_cores)

    print("=" * 60)
    print("  НАГРУЗОЧНЫЙ ТЕСТ KUBERNETES-КЛАСТЕРА")
    print("=" * 60)
    print(f"  Executor-ов:            {n_exec}")
    print(f"  Целевое потребление ядер на кластере: {target_total_cores}")
    print(f"  Целевое потребление памяти:           {target_total_memory / (1024**3):.1f} GiB")
    print(f"  Partition-ов (задач):   {num_partitions}")
    print(f"  Продолжительность:      {duration_sec} сек")
    print("=" * 60)
    print()

    # --- Таймаут на запуск Spark ---
    ms = kube_master_settings

    def _timeout_handler(signum, frame):
        print(f"\n⏱️  TIMEOUT: Spark не смог запуститься за {ms.startup_timeout} сек")
        sys.exit(1)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(ms.startup_timeout)

    # --- Устанавливаем PYSPARK_PYTHON в окружение процесса (критично для K8s client mode) ---
    os.environ["PYSPARK_PYTHON"] = ms.executor_pyspark_python

    # --- Создаём Spark-сессию в client mode ---
    print("Создаём Spark-сессию...")
    builder = (
        SparkSession.builder.appName(ms.app_name)
        .master(ms.master_url)
        # --- Kubernetes ---
        .config("spark.kubernetes.namespace", ms.namespace)
        .config("spark.kubernetes.container.image", ms.executor_image)
        # --- Driver networking (client mode) ---
        .config("spark.driver.host", ms.driver_host)
        .config("spark.driver.bindAddress", "0.0.0.0")
        .config("spark.driver.port", str(ms.driver_port))
        .config("spark.driver.blockManager.port", str(ms.block_manager_port))
        # --- Kubernetes auth ---
        .config("spark.kubernetes.authenticate.driver.serviceAccountName", ms.service_account)
        # --- Executor-ресурсы ---
        .config("spark.executor.instances", str(n_exec))
        # --- Таймауты и сеть ---
        .config("spark.network.timeout", "600s")
        .config("spark.executor.heartbeatInterval", "60s")
        .config("spark.rpc.message.maxSize", "256")
        # --- K8s scheduler ---
        .config("spark.kubernetes.allocation.batch.size", str(n_exec))
        .config("spark.kubernetes.allocation.batch.delay", "5s")
        .config("spark.kubernetes.executor.request.timeout", "60s")
        .config("spark.kubernetes.allocation.executor.timeout", "60s")
        .config("spark.dynamicAllocation.enabled", "false")
        .config("spark.scheduler.maxRegisteredResourcesWaitingTime", "60s")
        .config("spark.scheduler.minRegisteredResourcesRatio", "0.8")
        # --- Python-версия на executor-ах (должна совпадать с driver) ---
        .config("spark.pyspark.python", ms.executor_pyspark_python)
        .config("spark.pyspark.driver.python", sys.executable)
        .config("spark.executorEnv.PYSPARK_PYTHON", ms.executor_pyspark_python)
        # --- Логирование ---
        .config("spark.eventLog.enabled", "false")
    )

    # Сертификаты (опционально, для запуска вне кластера)
    if ms.ca_cert_file:
        builder = builder.config("spark.kubernetes.authenticate.submission.caCertFile", ms.ca_cert_file)
    if ms.client_key_file:
        builder = builder.config("spark.kubernetes.authenticate.submission.clientKeyFile", ms.client_key_file)
    if ms.client_cert_file:
        builder = builder.config("spark.kubernetes.authenticate.submission.clientCertFile", ms.client_cert_file)

    # Пользовательские конфиги
    for key, value in ms.extra_spark_configs.items():
        builder = builder.config(key, value)

    spark = builder.getOrCreate()

    # Отключаем таймаут — сессия создана
    signal.alarm(0)

    print(f"✓ Spark-сессия создана (version={spark.version}, master={spark.sparkContext.master})")

    # Выводим примененные конфиги
    if ms.extra_spark_configs:
        print(f"  Примененные конфиги:")
        for key, value in ms.extra_spark_configs.items():
            print(f"    {key} = {value}")
    print()

    # --- Создаём DataFrame для занятия памяти ---
    bytes_per_row = 80
    memory_efficiency = 0.7
    num_rows = int((target_total_memory * memory_efficiency) / bytes_per_row)

    print(f"Создаём DataFrame для занятия памяти...")
    print(f"  Строк:         {num_rows:,}")
    print(f"  Partition-ов:  {n_exec}")
    print(f"  Целевой размер: {target_total_memory / (1024**3):.1f} GiB")

    from pyspark.sql.functions import rand

    memory_df = (
        spark.range(0, num_rows, numPartitions=n_exec)
        .select(
            "id",
            rand().alias("col1"),
            rand().alias("col2"),
            rand().alias("col3"),
            rand().alias("col4"),
            rand().alias("col5"),
            rand().alias("col6"),
            rand().alias("col7"),
            rand().alias("col8"),
            rand().alias("col9"),
        )
        .cache()
    )

    row_count = memory_df.count()
    print(f"✓ DataFrame создан и закэширован ({row_count:,} строк)")
    print()

    # --- Запуск CPU-нагрузки параллельно с удержанием DataFrame в cache ---
    duration_bc = spark.sparkContext.broadcast(duration_sec)
    df_cached_bc = spark.sparkContext.broadcast(memory_df.count())

    def cpu_stress_worker(partition_index):
        """CPU-intensive вычисления на executor-е."""
        import math as _math
        import time as _time

        end_time = _time.time() + duration_bc.value
        iterations = 0
        x = 1.0

        while _time.time() < end_time:
            for _ in range(10_000):
                x = _math.sin(x) * _math.cos(x) + _math.sqrt(abs(x) + 1.0)
                iterations += 1

        return [(partition_index, iterations)]

    print(f"Запуск CPU-нагрузки на {num_partitions} partition-ах ({duration_sec} сек)...")
    print(f"  DataFrame ({row_count:,} строк) остаётся в cache во время теста...")
    t0 = time.time()

    try:
        rdd = spark.sparkContext.parallelize(range(num_partitions), num_partitions)
        results = rdd.flatMap(cpu_stress_worker).collect()

        elapsed = time.time() - t0
        total_iters = sum(it for _, it in results)

        print()
        print("=" * 60)
        print("  РЕЗУЛЬТАТЫ")
        print("=" * 60)
        print(f"  Реальное время:   {elapsed:.1f} сек")
        print(f"  Всего итераций:   {total_iters:,}")
        print(f"  DataFrame в cache: {row_count:,} строк")
        for idx, iters in sorted(results):
            print(f"    Partition {idx:>3}: {iters:>15,} итераций")
        print("=" * 60)

    except Exception as e:
        elapsed = time.time() - t0
        print(f"\nОШИБКА: задача упала через {elapsed:.1f} сек")
        print(f"  Тип:      {type(e).__name__}")
        print(f"  Сообщение: {e}")
        raise
    finally:
        print()
        spark.stop()
        print("✓ Spark-сессия остановлена.")


def run_with_monitoring(kube_master_settings: KubeSparkMasterSettings, stress_test_settings: KubeStressTestSettings):
    master_settings = kube_master_settings
    test_settings = stress_test_settings

    print("=" * 70)
    print("  МОНИТОРИНГ РЕСУРСОВ (ЛОКАЛЬНАЯ МАШИНА + KUBERNETES)")
    print("=" * 70)
    print()

    baseline_samples = []
    for _ in range(5):
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem_info = psutil.virtual_memory()
        baseline_samples.append({"cpu": cpu_percent, "memory_gb": mem_info.used / (1024**3)})

    baseline_cpu = sum(s["cpu"] for s in baseline_samples) / len(baseline_samples)
    baseline_memory_gb = sum(s["memory_gb"] for s in baseline_samples) / len(baseline_samples)

    print(f"📊 Baseline (до запуска):")
    print(f"   CPU:    {baseline_cpu:6.2f}%")
    print(f"   Memory: {baseline_memory_gb:6.2f} GiB")
    print()

    monitoring_data = {"samples": [], "k8s_samples": [], "running": True}

    def get_k8s_pods_memory():
        try:
            result = subprocess.run(
                ["kubectl", "top", "pods", "-n", master_settings.namespace, "--no-headers"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return 0.0

            total_memory_mi = 0.0
            for line in result.stdout.strip().split("\n"):
                if not line or "spark" not in line.lower():
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    mem_str = parts[2]
                    if mem_str.endswith("Mi"):
                        total_memory_mi += float(mem_str[:-2])
                    elif mem_str.endswith("Gi"):
                        total_memory_mi += float(mem_str[:-2]) * 1024

            return total_memory_mi / 1024
        except Exception:
            return 0.0

    def monitor_resources():
        while monitoring_data["running"]:
            cpu_percent = psutil.cpu_percent(interval=None)
            mem_info = psutil.virtual_memory()
            k8s_memory_gb = get_k8s_pods_memory()

            monitoring_data["samples"].append(
                {"cpu": cpu_percent, "memory_gb": mem_info.used / (1024**3), "timestamp": time.time()}
            )
            monitoring_data["k8s_samples"].append({"memory_gb": k8s_memory_gb, "timestamp": time.time()})
            time.sleep(1)

    monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
    monitor_thread.start()

    print("🚀 Запуск stress test в отдельном процессе...")
    print()

    worker_script = str(Path(__file__).parent / "worker_main.py")
    extra_configs_json = json.dumps(master_settings.extra_spark_configs)

    cmd = [
        sys.executable,
        worker_script,
        "--duration",
        str(test_settings.duration),
        "--num-executors",
        str(test_settings.num_executors),
        "--cores-target",
        str(test_settings.cores_target_utilization),
        "--memory-target",
        str(test_settings.memory_target_utilization),
        "--extra-configs",
        extra_configs_json,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    for line in proc.stdout:
        print(line, end="")

    proc.wait()

    monitoring_data["running"] = False
    monitor_thread.join(timeout=2)

    if not monitoring_data["samples"]:
        print("\n⚠️  Нет данных мониторинга")
        return

    max_cpu_sample = max(monitoring_data["samples"], key=lambda s: s["cpu"])
    max_memory_sample = max(monitoring_data["samples"], key=lambda s: s["memory_gb"])

    max_cpu = max_cpu_sample["cpu"]
    max_memory_gb = max_memory_sample["memory_gb"]

    cpu_delta = max_cpu - baseline_cpu
    memory_delta_gb = max_memory_gb - baseline_memory_gb

    k8s_memory_samples = [s["memory_gb"] for s in monitoring_data["k8s_samples"] if s["memory_gb"] > 0]
    max_k8s_memory_gb = max(k8s_memory_samples) if k8s_memory_samples else 0.0

    print()
    print("=" * 70)
    print("  СТАТИСТИКА РЕСУРСОВ")
    print("=" * 70)
    print()
    print(f"📊 CPU (локальная машина):")
    print(f"   Baseline:    {baseline_cpu:6.2f}%")
    print(f"   Максимум:    {max_cpu:6.2f}%")
    print(f"   Δ (разница): {cpu_delta:+6.2f}%")
    print()
    print(f"💾 Memory (локальная машина):")
    print(f"   Baseline:    {baseline_memory_gb:6.2f} GiB")
    print(f"   Максимум:    {max_memory_gb:6.2f} GiB")
    print(f"   Δ (разница): {memory_delta_gb:+6.2f} GiB")
    print()
    print(f"☸️  Memory (Kubernetes-поды):")
    print(f"   Максимум:    {max_k8s_memory_gb:6.2f} GiB")
    print(f"   📝 Примечание: executor-ы работают в K8s, память занимается там")
    print()
    print(f"🎯 Целевые значения:")
    print(f"   CPU cores: {test_settings.cores_target_utilization} ядер")
    print(f"   Memory:    {test_settings.memory_target_utilization / (1024**3):.1f} GiB")
    print("=" * 70)


if __name__ == "__main__":
    # Параметры теста
    target_cpu_cores = 8.0
    target_memory_utilization_gib = 20.0
    reserved_memory_gib = 22.0
    n_executors = 3

    # Вычисляем ресурсы на executor
    # spark.executor.memory * n_executors + spark.driver.memory = reserved_memory_gib
    # Целевая утилизация для теста = target_memory_utilization_gib
    driver_memory_gib = 2.0
    executor_memory_gib = (reserved_memory_gib - driver_memory_gib) / n_executors
    executor_cores = int(math.ceil(target_cpu_cores / n_executors))

    master_settings = KubeSparkMasterSettings(
        extra_spark_configs={
            "spark.driver.memory": f"{int(driver_memory_gib)}g",
            "spark.executor.memory": f"{int(executor_memory_gib)}g",
            "spark.executor.cores": str(executor_cores),
        }
    )

    test_settings = KubeStressTestSettings(
        duration=180.0,
        num_executors=n_executors,
        cores_target_utilization=target_cpu_cores,
        memory_target_utilization=int(target_memory_utilization_gib * 1024**3),
    )

    process_stress_test(master_settings, test_settings)
    # run_with_monitoring(master_settings, test_settings)
