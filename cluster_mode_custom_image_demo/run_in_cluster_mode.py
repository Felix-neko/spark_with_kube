#!/usr/bin/env python3
"""
Скрипт для запуска Spark-приложения в cluster-режиме на Kubernetes с real-time логами драйвера.

Используется Socket-подход:
1. Запускается log_listener для приёма логов
2. spark-submit отправляет приложение с переменными LOG_HOST/LOG_PORT
3. Драйвер подключается к listener и стримит логи в реальном времени
"""

import os
import re
import subprocess
import sys
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


def get_host_ip() -> str:
    """Получает IP хост-машины, видимый из кластера."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


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
    
    def __init__(self, app_name: str, log_host: str, log_port: int, app_url: str):
        super().__init__(daemon=True)
        self.app_name = app_name
        self.log_host = log_host
        self.log_port = log_port
        self.app_url = app_url
        
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
            "--name", self.app_name,
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
            self.app_url,
        ]
        
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


def main():
    activate_script = VENV_PATH / "bin" / "activate_this.py"
    if activate_script.exists():
        exec(open(activate_script).read(), {"__file__": str(activate_script)})
    
    log_host = get_host_ip()
    app_name = f"cluster-mode-demo-{int(time.time())}"
    app_file = BASEDIR / "app.py"
    http_port = 8765
    app_url = f"http://{log_host}:{http_port}/app.py"
    
    print("=" * 60)
    print("=== Запуск Spark-приложения в cluster-режиме ===")
    print("=" * 60)
    log_info(f"Application Name: {app_name}")
    log_info(f"Log Host: {log_host}:{LOG_PORT}")
    log_info(f"App URL: {app_url}")
    print()
    
    subprocess.run(
        ["kubectl", "delete", "pod", "spark-driver-cluster-demo", "-n", NAMESPACE, "--ignore-not-found=true"],
        capture_output=True
    )
    
    log_info(f"Запуск HTTP-сервера на порту {http_port}...")
    http_server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(http_port), "--bind", "0.0.0.0"],
        cwd=str(BASEDIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    log_info("HTTP-сервер запущен")
    
    listener_thread = LogListenerThread(port=LOG_PORT, timeout=180)
    listener_thread.start()
    time.sleep(1)
    
    if not listener_thread.is_alive():
        log_error("Не удалось запустить log_listener")
        http_server.terminate()
        return 1
    
    log_info("log_listener запущен")
    print()
    
    spark_thread = SparkSubmitThread(
        app_name=app_name,
        log_host=log_host,
        log_port=LOG_PORT,
        app_url=app_url
    )
    spark_thread.start()
    
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
    
    log_info("Остановка HTTP-сервера...")
    http_server.terminate()
    try:
        http_server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        http_server.kill()
    
    if status.success:
        print()
        log_info("✓ Приложение успешно завершено!")
        return 0
    else:
        print()
        log_error("✗ Приложение завершилось с ошибкой")
        return 1


if __name__ == "__main__":
    sys.exit(main())
