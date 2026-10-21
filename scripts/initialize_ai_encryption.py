"""Initialize the Fernet master key in .env without emitting or copying its value."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def initialize(path):
    from cryptography.fernet import Fernet
    from dotenv import dotenv_values

    value = dotenv_values(path).get("ACCOUNT_ENCRYPTION_KEY")
    if value:
        Fernet(value.encode())
        return False
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    value = Fernet.generate_key().decode()
    line = "ACCOUNT_ENCRYPTION_KEY=" + value
    pattern = r"(?m)^\s*(?:export\s+)?ACCOUNT_ENCRYPTION_KEY\s*=.*$"
    if re.search(pattern, text):
        text = re.sub(pattern, lambda _: line, text)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    with path.open("w", encoding="utf-8", newline="") as output:
        output.write(text)
    return True


if __name__ == "__main__":
    try:
        initialize(REPO / ".env")
    except (OSError, ValueError):
        raise SystemExit("主金鑰初始化失敗，請檢查 .env 權限與格式") from None
