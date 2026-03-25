from typing import Dict

from stress_test.settings import KubeSparkMasterSettings, KubeStressTestSettings
from stress_test.stress_test import process_stress_test


def run_stress_test_worker(
    duration: float,
    num_executors: int,
    cores_target_utilization: float,
    memory_target_utilization: float,
    extra_spark_configs: Dict[str, str],
):
    """Запускает stress test в отдельном процессе с заданными параметрами."""
    master_settings = KubeSparkMasterSettings(
        extra_spark_configs=extra_spark_configs
    )
    test_settings = KubeStressTestSettings(
        duration=duration,
        num_executors=num_executors,
        cores_target_utilization=cores_target_utilization,
        memory_target_utilization=memory_target_utilization,
    )
    process_stress_test(master_settings, test_settings)
