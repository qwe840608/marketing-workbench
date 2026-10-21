"""Evaluate an explicitly selected dataset using an official API, with no platform effects."""

from runtime_tmp import output_dir, runtime_check

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings
from app.services import credentials, jev
from app.services.redact import scrub


@runtime_check
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset", type=Path, help="使用者指定 JSON 題庫；會呼叫付費 jev API"
    )
    parser.add_argument(
        "--output", type=Path, default=output_dir() / "report.json"
    )
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    settings = Settings()
    if not credentials.resolve("JEV_API_KEY", settings):
        parser.error("缺少 JEV_API_KEY")
    results = []
    for case in dataset["cases"]:
        result = jev.ask(scrub(case["state"]), case["questions"], settings)
        answers = result.response["answers"] if result.response else {}
        results.append(
            {
                "id": case["id"],
                "passed": all(
                    answers.get(k, {}).get("choice") == v
                    for k, v in case["expected"].items()
                ),
                "error": result.error,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps({"cases": len(results), "passed": sum(r["passed"] for r in results)})
    )


if __name__ == "__main__":
    main()
