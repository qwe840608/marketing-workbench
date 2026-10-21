"""backup.ps1 的 Python 入口；不輸出第三方例外或密碼。"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.config import Settings
    from app.services import backup
    from app.services.export_data import atomic_write

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "restore"])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.action == "run":
            result = backup.run(settings)
        else:
            if not args.archive or not args.destination:
                raise backup.BackupError("還原需要 --archive 與 --destination")
            manifest = backup.restore(settings, args.archive, args.destination)
            result = {
                "ok": True,
                "restored_verified": True,
                "tables": manifest["database"]["tables"],
                "export_files": len(manifest["exports"]),
            }
    except backup.BackupError as error:
        result = {"ok": False, "error": str(error)}
    except Exception as error:
        result = {
            "ok": False,
            "error": "備份未完成，請檢查磁碟、設定與檔案權限",
            "error_type": type(error).__name__,
        }
    if args.action == "run":
        atomic_write(
            ROOT / ".runtime",
            "backup-last.json",
            json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
