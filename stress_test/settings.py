from datetime import timedelta
from typing import Dict, Optional, Union

from pydantic import Field
from pydantic_settings import BaseSettings


class KubeSparkMasterSettings(BaseSettings):
    master_url: str = Field(
        default="k8s://https://192.168.112.2:8443",
        description="URL Kubernetes API server в формате k8s://https://<IP>:<PORT>",
    )
    executor_image: str = Field(
        default="felixneko/spark:spark-3.5.8-python-3.8",
        description="Docker-образ для executor-подов (должен содержать ту же версию Spark)",
    )
    namespace: str = Field(default="spark", description="Kubernetes namespace для создания executor-подов")
    driver_host: str = Field(
        default="driver-proxy.spark.svc.cluster.local", description="По какому хосту драйвер доступен для экзекуторов"
    )
    driver_port: int = Field(
        default=7077, description="По какому порту драйвер доступен для экзекуторов (со стороны экзекуторов)"
    )
    block_manager_port: int = Field(
        default=7078, description="Порт для BlockManager (передача данных driver <-> executor)"
    )
    app_name: str = Field(default="spark-stress-test", description="Имя Spark-приложения (видно в Spark UI)")
    service_account: str = Field(
        default="spark-client", description="Kubernetes ServiceAccount для создания executor-подов"
    )
    ca_cert_file: Optional[str] = Field(
        default="/home/felix/.minikube/ca.crt", description="Путь к CA-сертификату кластера"
    )
    client_key_file: Optional[str] = Field(
        default="/home/felix/.minikube/profiles/minikube/client.key", description="Путь к приватному ключу клиента"
    )
    client_cert_file: Optional[str] = Field(
        default="/home/felix/.minikube/profiles/minikube/client.crt", description="Путь к клиентскому сертификату"
    )
    executor_pyspark_python: str = Field(
        default="/usr/bin/python3.8",
        description="Путь к Python-интерпретатору внутри executor-образа (должен совпадать с версией driver-а)",
    )
    startup_timeout: int = Field(
        default=120, description="Таймаут на запуск Spark-сессии и поднятие executor-ов (секунды)"
    )
    extra_spark_configs: Dict[str, str] = Field(
        default_factory=dict, description="Дополнительные Spark-конфиги (key -> value)"
    )


class KubeStressTestSettings(BaseSettings):
    duration: Union[float, timedelta] = Field(
        default=60.0, description="Продолжительность нагрузочного теста (секунды или timedelta)"
    )
    num_executors: int = Field(default=2, description="Количество executor-подов в Kubernetes")
    cores_target_utilization: float = Field(
        default=2.0, description="Сколько всего CPU-ядер занять на кластере (целевой показатель)"
    )
    memory_target_utilization: float = Field(
        default=2 * 1024**3, description="Сколько всего памяти занять на кластере (в байтах, целевой показатель)"
    )
