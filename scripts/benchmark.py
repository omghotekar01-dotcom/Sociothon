"""Reproducible local benchmark; results describe this machine/run only."""
import argparse
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.analytics.pipeline import bootstrap_dataset

parser = argparse.ArgumentParser()
parser.add_argument("--seed", type=int, default=360)
parser.add_argument("--days", type=int, default=56)
parser.add_argument("--output", default="artifacts/verification/benchmark.json")
args = parser.parse_args()
started = time.perf_counter()
data = bootstrap_dataset(seed=args.seed, days=args.days)
elapsed = time.perf_counter() - started
result = {"runtime": {"python": sys.version, "platform": platform.platform(), "processor": platform.processor()}, "dataset": data["metadata"], "analysis_seconds": round(elapsed, 4), "domains": {domain: {"findings": len(output.get("findings", [])), "coverage": output.get("quality", {}).get("coverage"), "evaluation": output.get("evaluation"), "forecast": output.get("forecast")} for domain, output in data["domains"].items()}, "limitation": "Single local run including independent-seed synthetic evaluation. No hardware-independent performance or real-world accuracy guarantee."}
target = ROOT / args.output
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
print(json.dumps({"rows": data["metadata"]["rows"], "seconds": result["analysis_seconds"], "output": str(target), "findings": {d: v["findings"] for d, v in result["domains"].items()}}))
