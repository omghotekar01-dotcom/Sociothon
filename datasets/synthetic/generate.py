"""Export reproducible inputs and separate truth: python -m datasets.synthetic.generate."""
import json
from pathlib import Path

from services.analytics.pipeline import SEED, generate_consumption, generate_domain_inputs


def main() -> None:
    target = Path(__file__).parent / "generated"
    target.mkdir(exist_ok=True)
    manifest = {"source": "Synthetic", "seed": SEED, "days": 56, "interval": "UTC interval start; hourly quantities", "domains": {}}
    for domain in ("water", "electricity"):
        readings, labels = generate_consumption(domain)
        (target / f"{domain}-readings.json").write_text(json.dumps(readings), encoding="utf-8")
        (target / f"{domain}-ground-truth.json").write_text(json.dumps(labels), encoding="utf-8")
        manifest["domains"][domain] = {"rows": len(readings), "truth_separate": True}
    (target / "domain-observations.json").write_text(json.dumps(generate_domain_inputs(), indent=2), encoding="utf-8")
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
