"""
PySpark-приложение для запуска в кластерном режиме на Kubernetes.

В cluster mode:
- Driver запускается внутри Kubernetes как под
- Executors также запускаются как поды в Kubernetes
- Приложение полностью автономно и не требует локального driver'а

Поддерживает отправку логов на удалённый сокет для real-time мониторинга.

Переменные окружения:
    LOG_HOST - IP-адрес хоста для отправки логов (опционально)
    LOG_PORT - порт для отправки логов (опционально, по умолчанию 9999)
"""

import os
import sys
import socket
from contextlib import contextmanager
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, upper


class SocketWriter:
    """Писатель, который отправляет данные на сокет и дублирует в оригинальный поток."""
    
    def __init__(self, sock: socket.socket, original_stream):
        self.sock = sock
        self.original = original_stream
        self._encoding = "utf-8"
    
    @property
    def encoding(self):
        return self._encoding
    
    def write(self, s: str) -> int:
        if s:
            if self.original:
                self.original.write(s)
                self.original.flush()
            
            try:
                self.sock.sendall(s.encode(self._encoding))
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        return len(s) if s else 0
    
    def flush(self):
        if self.original:
            self.original.flush()
    
    def fileno(self):
        if self.original:
            return self.original.fileno()
        raise OSError("No file descriptor")
    
    def isatty(self):
        return False


@contextmanager
def socket_logging(host: str, port: int):
    """Контекстный менеджер для перенаправления stdout/stderr на сокет."""
    sock = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        
        sys.stdout = SocketWriter(sock, original_stdout)
        sys.stderr = SocketWriter(sock, original_stderr)
        
        print(f"[SOCKET] Connected to {host}:{port}")
        yield sock
        
    except (ConnectionRefusedError, OSError) as e:
        print(f"[SOCKET] Failed to connect to {host}:{port}: {e}", file=original_stderr)
        yield None
        
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def get_executor_python_info(iterator):
    """Получает информацию о Python на executor-нодах."""
    import sys
    import os
    import platform
    executor_info = {
        'python_version': sys.version,
        'python_executable': sys.executable,
        'python_prefix': sys.prefix,
        'python_exec_prefix': sys.exec_prefix,
        'hostname': os.environ.get('HOSTNAME', 'UNKNOWN'),
        'cwd': os.getcwd(),
        'platform': platform.platform(),
        'python_implementation': platform.python_implementation()
    }
    yield executor_info


def run_spark_job():
    """Основная логика Spark-приложения."""
    print("=" * 80)
    print("CLUSTER MODE DEMO STARTED")
    print("=" * 80)
    
    print("\n" + "=" * 80)
    print("ИНФОРМАЦИЯ О PYTHON НА ДРАЙВЕРЕ")
    print("=" * 80)
    print(f"Current working dir: {os.getcwd()}")
    print(f"Python version: {sys.version}")
    print(f"Python executable: {sys.executable}")
    print(f"Python prefix: {sys.prefix}")
    print(f"Python exec_prefix: {sys.exec_prefix}")
    
    import platform
    print(f"Platform: {platform.platform()}")
    print(f"Python implementation: {platform.python_implementation()}")
    
    # Проверяем наличие virtualenv
    print("\n--- Проверка наличия virtualenv ---")
    pyspark_venv_path = os.path.join(os.getcwd(), "pyspark_venv")
    if os.path.exists(pyspark_venv_path):
        print(f"✓ Найден pyspark_venv: {pyspark_venv_path}")
        print(f"  Содержимое: {os.listdir(pyspark_venv_path)}")
        
        # Проверяем структуру внутри
        for item in os.listdir(pyspark_venv_path):
            item_path = os.path.join(pyspark_venv_path, item)
            if os.path.isdir(item_path):
                print(f"  Директория {item}: {os.listdir(item_path)[:10]}")  # Первые 10 элементов
        
        # Тестируем Python из virtualenv
        venv_python = os.path.join(pyspark_venv_path, "conda_venv_temp", "bin", "python")
        if os.path.exists(venv_python):
            print(f"\n✓ Найден Python из virtualenv: {venv_python}")
            
            # Запускаем Python из virtualenv и получаем информацию
            import subprocess
            result = subprocess.run(
                [venv_python, "-c", "import sys; print(f'Python: {sys.executable}'); print(f'Version: {sys.version}'); import pyspark; print(f'PySpark: {pyspark.__version__}')"],
                capture_output=True,
                text=True
            )
            print("  Вывод Python из virtualenv:")
            for line in result.stdout.strip().split('\n'):
                print(f"    {line}")
            if result.stderr:
                print(f"  Ошибки: {result.stderr}")
        else:
            print(f"✗ Python не найден в virtualenv: {venv_python}")
    else:
        print(f"✗ pyspark_venv не найден в {os.getcwd()}")
    
    print("=" * 80)
    
    # Проверяем наличие архива с дополнительными пакетами
    extra_libs_path = os.path.join(os.getcwd(), "extra_libs")
    if os.path.exists(extra_libs_path):
        print(f"\n✓ Найден архив extra_libs: {extra_libs_path}")
        print(f"  Содержимое: {os.listdir(extra_libs_path)}")
        
        # Добавляем путь к extra_package в sys.path
        sys.path.insert(0, extra_libs_path)
        
        # Импортируем и тестируем extra_module
        try:
            from extra_package import extra_module
            result = extra_module.extra_function()
            print(f"  ✓ extra_function() вызвана успешно!")
            print(f"  ✓ Результат: {result}")
            
            # Проверяем корректность результата
            expected = "extra_function called!"
            if result == expected:
                print(f"  ✓ Результат корректен: '{result}' == '{expected}'")
            else:
                print(f"  ✗ ОШИБКА: ожидалось '{expected}', получено '{result}'")
                raise ValueError(f"Некорректный результат от extra_function: {result}")
        except Exception as e:
            print(f"  ✗ Ошибка при импорте/вызове extra_module: {e}")
            raise
    else:
        print(f"\n⚠ Архив extra_libs не найден в {os.getcwd()}")
    
    print("\n" + "=" * 80)
    print("CREATING SPARK SESSION")
    print("=" * 80)
    
    spark = SparkSession.builder \
        .appName("Cluster Mode Custom Image Demo") \
        .getOrCreate()
    
    print(f"Spark version: {spark.version}")
    print(f"Spark master: {spark.sparkContext.master}")
    print(f"App ID: {spark.sparkContext.applicationId}")
    
    print("\n" + "=" * 80)
    print("ПРОВЕРКА 1: Информация о Python на executor'ах")
    print("=" * 80)
    
    test_rdd = spark.sparkContext.parallelize(range(2), 2)
    executor_info = test_rdd.mapPartitions(get_executor_python_info).collect()
    
    for i, info in enumerate(executor_info):
        print(f"\n[EXECUTOR {i+1}]")
        print(f"  Hostname: {info['hostname']}")
        print(f"  Current working dir: {info['cwd']}")
        print(f"  Python version: {info['python_version']}")
        print(f"  Python executable: {info['python_executable']}")
        print(f"  Python prefix: {info['python_prefix']}")
        print(f"  Python exec_prefix: {info['python_exec_prefix']}")
        print(f"  Platform: {info['platform']}")
        print(f"  Python implementation: {info['python_implementation']}")
    
    print("\n" + "=" * 80)
    print("ПРОВЕРКА 2: Базовые операции с DataFrame")
    print("=" * 80)
    
    data = [
        (1, "Alice", 25, "Engineering"),
        (2, "Bob", 30, "Sales"),
        (3, "Charlie", 35, "Engineering"),
        (4, "Diana", 28, "HR"),
        (5, "Eve", 32, "Sales")
    ]
    columns = ["id", "name", "age", "department"]
    
    df = spark.createDataFrame(data, columns)
    print("\nИсходный DataFrame:")
    df.show()
    
    print("\nФильтрация (age > 28):")
    filtered_df = df.filter(col("age") > 28)
    filtered_df.show()
    
    print("\nДобавление столбца с именем в верхнем регистре:")
    transformed_df = df.withColumn("name_upper", upper(col("name")))
    transformed_df.show()
    
    print("\nГруппировка по department:")
    agg_df = df.groupBy("department").count()
    agg_df.show()
    
    print("\nСортировка по возрасту (убывание):")
    sorted_df = df.orderBy(col("age").desc())
    sorted_df.show()
    
    total_count = df.count()
    filtered_count = filtered_df.count()
    
    print(f"\nВсего записей: {total_count}")
    print(f"После фильтрации: {filtered_count}")
    
    assert total_count == 5, f"Ожидалось 5 записей, получено {total_count}"
    assert filtered_count == 3, f"После фильтрации ожидалось 3 записи, получено {filtered_count}"
    
    print("\n✓ Все проверки DataFrame пройдены успешно!")
    
    print("\n" + "=" * 80)
    print("ПРОВЕРКА 3: Тестирование библиотек из кастомного образа")
    print("=" * 80)
    
    try:
        import dill
        import pandas
        import pyarrow
        
        print(f"✓ dill версия: {dill.__version__}")
        print(f"✓ pandas версия: {pandas.__version__}")
        print(f"✓ pyarrow версия: {pyarrow.__version__}")
        
        print("\nТестирование pandas на executor'ах:")
        def test_pandas(iterator):
            import pandas as pd
            df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
            yield f"Pandas DataFrame shape: {df.shape}"
        
        pandas_test = spark.sparkContext.parallelize(range(1), 1).mapPartitions(test_pandas).collect()
        print(f"  {pandas_test[0]}")
        
    except ImportError as e:
        print(f"✗ Ошибка импорта библиотек: {e}")
    
    print("\n" + "=" * 80)
    print("ИНФОРМАЦИЯ О SPARK-КОНФИГУРАЦИИ")
    print("=" * 80)
    print(f"Spark Version: {spark.version}")
    print(f"Master: {spark.sparkContext.master}")
    print(f"App Name: {spark.sparkContext.appName}")
    print(f"App ID: {spark.sparkContext.applicationId}")
    
    print("\n" + "=" * 80)
    print("CLUSTER MODE DEMO FINISHED SUCCESSFULLY")
    print("=" * 80)
    
    spark.stop()


if __name__ == "__main__":
    log_host = os.environ.get("LOG_HOST")
    log_port = int(os.environ.get("LOG_PORT", "9999"))
    
    if log_host:
        with socket_logging(log_host, log_port):
            run_spark_job()
    else:
        run_spark_job()
