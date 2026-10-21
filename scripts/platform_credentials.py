"""Local provisioning bridge: resolve through the backend, encrypt all IPC output."""

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def envelope(settings, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from app.services import credentials

    values = {name: credentials.raw(credentials.resolve(name, settings))
              for name in credentials.NAMES}
    nonce = os.urandom(12)
    encrypted = AESGCM(key).encrypt(nonce, json.dumps(values).encode(), b"platform-config")
    return base64.b64encode(nonce + encrypted).decode()


def main():
    from app.config import Settings

    try:
        key = base64.b64decode(sys.stdin.buffer.read(128), validate=True)
        if len(key) != 32:
            raise ValueError("invalid_ipc_key")
        result = envelope(Settings(), key)
    except Exception:
        print("Platform configuration unavailable", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
