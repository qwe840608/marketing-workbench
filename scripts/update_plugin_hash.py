"""Record a bumped plugin release; never touches a database or client config."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.services.agent_packages import PLUGIN_LATEST, content_hash

    path = ROOT / "plugin" / "content-hash.json"
    record = {"version": PLUGIN_LATEST, "sha256": content_hash()}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["version"] == record["version"] and previous != record:
            raise SystemExit("請提高 plugin 版本，再更新雜湊記錄")
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded plugin {PLUGIN_LATEST}")


if __name__ == "__main__":
    main()
