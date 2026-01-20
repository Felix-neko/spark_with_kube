#!/usr/bin/env python3
"""
Скрипт для запуска Spark-приложения в cluster-режиме на Kubernetes с real-time логами драйвера.
Использует MinIO для хранения app.py вместо HTTP-сервера или hostPath.

Подход:
1. Загружаем app.py в MinIO bucket
2. Spark скачивает файл из MinIO по HTTP URL
3. После завершения файл удаляется из MinIO
4. Не требуется HTTP-сервер или minikube mount
"""

import os
import re
import subprocess
import sys
import tarfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


BASEDIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BASEDIR.parent
VENV_PATH = PROJECT_ROOT / ".venv"

K8S_MASTER = "k8s://https://192.168.85.2:8443"
EXECUTOR_IMAGE = "felixneko/spark:spark-3.5.8-python-3.8"
NAMESPACE = "spark"

CA_CERT = Path.home() / ".minikube" / "ca.crt"
CLIENT_KEY = Path.home() / ".minikube" / "profiles" / "minikube" / "client.key"
CLIENT_CERT = Path.home() / ".minikube" / "profiles" / "minikube" / "client.crt"

LOG_PORT = 9999

# MinIO настройки
MINIO_ENDPOINT = "minio.spark.svc.cluster.local:9000"  # Внутренний endpoint для Spark
MINIO_EXTERNAL_ENDPOINT = None  # Будет определён динамически (minikube ip:30900)
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin123"
MINIO_BUCKET = "spark-apps"
MINIO_USE_SSL = False


def get_host_ip() -> str:
    """Получает IP хост-машины, видимый из кластера."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def get_minikube_ip() -> str:
    """Получает IP minikube."""
    result = subprocess.run(
        ["minikube", "ip"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return "192.168.85.2"  # Fallback


def timestamp() -> str:
    """Возвращает текущее время в формате HH:MM:SS."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


def log_info(msg: str):
    """Выводит информационное сообщение."""
    print(f"[{timestamp()}] [INFO] {msg}", flush=True)


def log_error(msg: str):
    """Выводит сообщение об ошибке."""
    print(f"[{timestamp()}] [ERROR] {msg}", file=sys.stderr, flush=True)


def create_archive(source_dir: Path, archive_path: Path) -> None:
    """Создаёт tar.gz архив из директории."""
    log_info(f"Создание архива {archive_path.name} из {source_dir.name}...")
    
    with tarfile.open(archive_path, "w:gz") as tar:
        # Добавляем директорию в архив с сохранением структуры
        tar.add(source_dir, arcname=source_dir.name)
    
    log_info(f"✓ Архив создан: {archive_path} ({archive_path.stat().st_size} байт)")


@dataclass
class AppStatus:
    """Состояние Spark-приложения."""
    app_id: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None
    finished: bool = False
    success: bool = False


class SparkSubmitThread(threading.Thread):
    """Поток для запуска spark-submit и мониторинга статуса приложения."""
    
    def __init__(self, app_name: str, log_host: str, log_port: int, app_url: str, archive_url: Optional[str] = None):
        super().__init__(daemon=True)
        self.app_name = app_name
        self.log_host = log_host
        self.log_port = log_port
        self.app_url = app_url
        self.archive_url = archive_url
        
        self.status = AppStatus()
        self.status_lock = threading.Lock()
        self.finished_event = threading.Event()
        self._stop_event = threading.Event()
    
    def get_status(self) -> AppStatus:
        with self.status_lock:
            return AppStatus(
                app_id=self.status.app_id,
                state=self.status.state,
                error=self.status.error,
                finished=self.status.finished,
                success=self.status.success,
            )
    
    def stop(self):
        self._stop_event.set()
    
    def run(self):
        try:
            self._run_spark_submit()
        except Exception as e:
            with self.status_lock:
                self.status.error = str(e)
                self.status.finished = True
            self.finished_event.set()
    
    def _run_spark_submit(self):
        cmd = [
            "spark-submit",
            "--master", K8S_MASTER,
            "--deploy-mode", "cluster",
            "--conf", f"spark.kubernetes.namespace={NAMESPACE}",
            "--conf", f"spark.kubernetes.container.image={EXECUTOR_IMAGE}",
            "--conf", f"spark.kubernetes.driver.pod.name=spark-driver-cluster-demo",
            "--conf", f"spark.kubernetes.authenticate.driver.serviceAccountName=spark-client",
            "--conf", f"spark.kubernetes.authenticate.submission.caCertFile={CA_CERT}",
            "--conf", f"spark.kubernetes.authenticate.submission.clientKeyFile={CLIENT_KEY}",
            "--conf", f"spark.kubernetes.authenticate.submission.clientCertFile={CLIENT_CERT}",
            
            "--conf", f"spark.kubernetes.driverEnv.LOG_HOST={self.log_host}",
            "--conf", f"spark.kubernetes.driverEnv.LOG_PORT={self.log_port}",
            "--conf", "spark.kubernetes.driverEnv.PYSPARK_PYTHON=python3.8",
            "--conf", "spark.kubernetes.driverEnv.PYSPARK_DRIVER_PYTHON=python3.8",
            "--conf", "spark.executorEnv.PYSPARK_PYTHON=python3.8",
            "--conf", "spark.pyspark.python=python3.8",
            "--conf", "spark.pyspark.driver.python=python3.8",
            "--conf", "spark.executor.instances=2",
            "--conf", "spark.executor.memory=1g",
            "--conf", "spark.executor.cores=1",
            "--conf", "spark.driver.memory=1g",
            "--conf", "spark.driver.cores=1",
            "--conf", "spark.network.timeout=600s",
            "--conf", "spark.executor.heartbeatInterval=60s",
            "--conf", "spark.kubernetes.submission.waitAppCompletion=true",
            "--conf", "spark.kubernetes.driver.limit.cores=1",
            "--conf", "spark.kubernetes.executor.limit.cores=1",
        ]
        
        # Добавляем архив с дополнительными пакетами, если указан
        if self.archive_url:
            # Формат: URL#директория_распаковки
            # Spark распакует архив в рабочую директорию и создаст симлинк с указанным именем
            cmd.extend(["--archives", f"{self.archive_url}#extra_libs"])
        
        # URL файла из MinIO
        cmd.append(self.app_url)
        
        log_info(f"Запуск spark-submit: {self.app_name}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        app_id_pattern = re.compile(r"spark-[a-f0-9]+")
        
        for line in process.stdout:
            line = line.rstrip()
            print(f"[spark-submit] {line}", flush=True)
            
            if not self.status.app_id:
                match = app_id_pattern.search(line)
                if match:
                    with self.status_lock:
                        self.status.app_id = match.group()
                    log_info(f"Application ID: {self.status.app_id}")
            
            if "phase: Failed" in line or "exit code: 1" in line or "exit code: 2" in line:
                with self.status_lock:
                    self.status.error = "Application failed"
                    self.status.finished = True
                    self.status.success = False
                self.finished_event.set()
            
            if "phase: Succeeded" in line or "exit code: 0" in line:
                with self.status_lock:
                    self.status.success = True
            
            if self._stop_event.is_set():
                process.terminate()
                break
        
        process.wait()
        
        with self.status_lock:
            self.status.finished = True
            if self.status.success is None:
                self.status.success = (process.returncode == 0)
        
        self.finished_event.set()


class LogListenerThread(threading.Thread):
    """Поток для запуска log_listener.py."""
    
    def __init__(self, port: int, timeout: int = 120):
        super().__init__(daemon=True)
        self.port = port
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self.exit_code: Optional[int] = None
        self.connected = threading.Event()
    
    def stop(self, delay: float = 0):
        """Останавливает listener с опциональной задержкой."""
        if delay > 0:
            time.sleep(delay)
        self._stop_event.set()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
    
    def run(self):
        cmd = [
            sys.executable,
            str(BASEDIR / "log_listener.py"),
            "--port", str(self.port),
            "--timeout", str(self.timeout),
            "--exit-on-disconnect",
        ]
        
        log_info(f"Запуск log_listener на порту {self.port}")
        
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        for line in self.process.stdout:
            line = line.rstrip()
            print(line, flush=True)
            
            if "Connected to" in line or "SOCKET" in line:
                self.connected.set()
            
            if self._stop_event.is_set():
                break
        
        self.exit_code = self.process.wait()


def upload_to_minio(file_path: Path, object_name: str) -> str:
    """Загружает файл в MinIO через библиотеку minio."""
    from minio import Minio
    from minio.error import S3Error
    import json
    
    global MINIO_EXTERNAL_ENDPOINT
    minikube_ip = get_minikube_ip()
    MINIO_EXTERNAL_ENDPOINT = f"{minikube_ip}:30900"
    
    log_info(f"Подключение к MinIO: {MINIO_EXTERNAL_ENDPOINT}")
    
    # Создаём MinIO-клиент
    client = Minio(
        MINIO_EXTERNAL_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL
    )
    
    # Создаём bucket, если не существует
    try:
        if not client.bucket_exists(MINIO_BUCKET):
            log_info(f"Создание bucket '{MINIO_BUCKET}'...")
            client.make_bucket(MINIO_BUCKET)
            log_info(f"✓ Bucket '{MINIO_BUCKET}' создан")
        else:
            log_info(f"Bucket '{MINIO_BUCKET}' уже существует")
    except S3Error as e:
        log_error(f"Ошибка при проверке/создании bucket: {e}")
        raise
    
    # Устанавливаем публичную политику для bucket (разрешаем чтение всем)
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{MINIO_BUCKET}/*"]
            }
        ]
    }
    
    try:
        client.set_bucket_policy(MINIO_BUCKET, json.dumps(bucket_policy))
        log_info(f"✓ Публичная политика установлена для bucket '{MINIO_BUCKET}'")
    except S3Error as e:
        log_error(f"Не удалось установить политику bucket: {e}")
    
    # Загружаем файл
    log_info(f"Загрузка {file_path.name} в MinIO...")
    try:
        client.fput_object(
            MINIO_BUCKET,
            object_name,
            str(file_path)
        )
        log_info(f"✓ Файл загружен: {MINIO_BUCKET}/{object_name}")
    except S3Error as e:
        log_error(f"Ошибка при загрузке файла: {e}")
        raise
    
    # Возвращаем HTTP URL (используем внутренний endpoint для Spark)
    # Spark будет скачивать файл изнутри кластера
    url = f"http://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_name}"
    return url


def delete_from_minio(object_name: str):
    """Удаляет файл из MinIO через библиотеку minio."""
    if not MINIO_EXTERNAL_ENDPOINT:
        return
    
    from minio import Minio
    from minio.error import S3Error
    
    log_info(f"Удаление {object_name} из MinIO...")
    
    # Создаём MinIO-клиент
    client = Minio(
        MINIO_EXTERNAL_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL
    )
    
    try:
        client.remove_object(MINIO_BUCKET, object_name)
        log_info(f"✓ Файл удалён из MinIO: {MINIO_BUCKET}/{object_name}")
    except S3Error as e:
        log_error(f"Не удалось удалить файл из MinIO: {e}")


def main():
    activate_script = VENV_PATH / "bin" / "activate_this.py"
    if activate_script.exists():
        exec(open(activate_script).read(), {"__file__": str(activate_script)})
    
    log_host = get_host_ip()
    app_name = f"cluster-mode-demo-{int(time.time())}"
    app_file = BASEDIR / "app.py"
    timestamp_str = str(int(time.time()))
    object_name = f"app-{timestamp_str}.py"
    
    # Пути для архива с дополнительными пакетами
    extra_package_dir = BASEDIR / "extra_package"
    archive_name = f"extra_package-{timestamp_str}.tar.gz"
    archive_path = BASEDIR / archive_name
    archive_object_name = archive_name
    
    print("=" * 60)
    print("=== Запуск Spark-приложения в cluster-режиме ===")
    print("=== (через MinIO S3-хранилище с архивами) ===")
    print("=" * 60)
    log_info(f"Application Name: {app_name}")
    log_info(f"Log Host: {log_host}:{LOG_PORT}")
    log_info(f"App File: {app_file}")
    log_info(f"MinIO Object: {MINIO_BUCKET}/{object_name}")
    log_info(f"Extra Package: {extra_package_dir}")
    log_info(f"Archive: {archive_name}")
    print()
    
    # Удаляем старый под драйвера
    subprocess.run(
        ["kubectl", "delete", "pod", "spark-driver-cluster-demo", "-n", NAMESPACE, "--ignore-not-found=true"],
        capture_output=True
    )
    
    # Создаём архив с дополнительными пакетами
    archive_url = None
    try:
        if extra_package_dir.exists():
            create_archive(extra_package_dir, archive_path)
            
            # Загружаем архив в MinIO
            archive_url = upload_to_minio(archive_path, archive_object_name)
            log_info(f"URL архива: {archive_url}")
            print()
        else:
            log_info(f"Директория {extra_package_dir} не найдена, пропускаем создание архива")
    except Exception as e:
        log_error(f"Не удалось создать/загрузить архив: {e}")
        return 1
    
    # Загружаем app.py в MinIO
    try:
        app_url = upload_to_minio(app_file, object_name)
        log_info(f"URL приложения: {app_url}")
        print()
    except Exception as e:
        log_error(f"Не удалось загрузить файл в MinIO: {e}")
        return 1
    
    try:
        # Запускаем log_listener
        listener_thread = LogListenerThread(port=LOG_PORT, timeout=180)
        listener_thread.start()
        time.sleep(1)
        
        if not listener_thread.is_alive():
            log_error("Не удалось запустить log_listener")
            return 1
        
        log_info("log_listener запущен")
        print()
        
        # Запускаем spark-submit с URL из MinIO
        spark_thread = SparkSubmitThread(
            app_name=app_name,
            log_host=log_host,
            log_port=LOG_PORT,
            app_url=app_url,
            archive_url=archive_url
        )
        spark_thread.start()
        
        # Ожидаем завершения
        while True:
            spark_thread.finished_event.wait(timeout=1)
            
            status = spark_thread.get_status()
            
            if status.finished:
                break
            
            if not listener_thread.is_alive() and not listener_thread.connected.is_set():
                log_error("log_listener завершился без подключения драйвера")
                time.sleep(5)
        
        status = spark_thread.get_status()
        
        print()
        print("=" * 60)
        print("РЕЗУЛЬТАТ:")
        print(f"  Application ID: {status.app_id}")
        print(f"  State: {status.state}")
        print(f"  Listener Exit Code: {listener_thread.exit_code}")
        print("=" * 60)
        
        # При ошибке получаем логи из Kubernetes
        if status.error:
            print()
            log_info(">>> Получение логов драйвера из Kubernetes...")
            
            if listener_thread.is_alive():
                threading.Thread(target=listener_thread.stop, args=(5,), daemon=True).start()
            
            if status.app_id:
                result = subprocess.run(
                    ["kubectl", "logs", "-n", NAMESPACE, "spark-driver-cluster-demo"],
                    capture_output=True,
                    text=True
                )
                print()
                print("=" * 60)
                print(f"ЛОГИ ДРАЙВЕРА (spark-driver-cluster-demo)")
                print("=" * 60)
                print(result.stdout)
                print("=" * 60)
        
        if listener_thread.is_alive():
            listener_thread.stop(delay=0)
        
        spark_thread.join(timeout=5)
        listener_thread.join(timeout=5)
        
        if status.success:
            print()
            log_info("✓ Приложение успешно завершено!")
            return 0
        else:
            print()
            log_error("✗ Приложение завершилось с ошибкой")
            return 1
    
    finally:
        # Всегда удаляем файлы из MinIO
        delete_from_minio(object_name)
        if archive_url:
            delete_from_minio(archive_object_name)
        
        # Удаляем локальный архив
        if archive_path.exists():
            archive_path.unlink()
            log_info(f"✓ Локальный архив удалён: {archive_path}")


if __name__ == "__main__":
    sys.exit(main())
