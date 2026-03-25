import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from stress_test.worker import run_stress_test_worker


def main():
    parser = argparse.ArgumentParser(description="Запуск Spark stress test worker")
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--num-executors", type=int, required=True)
    parser.add_argument("--cores-target", type=float, required=True)
    parser.add_argument("--memory-target", type=float, required=True)
    parser.add_argument("--extra-configs", type=str, required=True)
    
    args = parser.parse_args()
    
    extra_spark_configs = json.loads(args.extra_configs)
    
    run_stress_test_worker(
        duration=args.duration,
        num_executors=args.num_executors,
        cores_target_utilization=args.cores_target,
        memory_target_utilization=args.memory_target,
        extra_spark_configs=extra_spark_configs,
    )


if __name__ == "__main__":
    main()
