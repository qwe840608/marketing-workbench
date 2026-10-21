"""Internal client packages; stable bytes and one canonical release version."""

import hashlib
import io
import json
import re
import zipfile

from fastapi import HTTPException

from app.config import REPO_ROOT
from app.services import branding

PLUGIN_ROOT = REPO_ROOT / "plugin" / "mwb"
DESKTOP_ROOT = REPO_ROOT / "plugin" / "desktop"
MANIFEST = ".claude-plugin/plugin.json"


def manifest():
    return json.loads((PLUGIN_ROOT / MANIFEST).read_text(encoding="utf-8"))


PLUGIN_LATEST = manifest()["version"]
PLUGIN_MIN_COMPATIBLE = "0.3.0"
UPDATE_INSTRUCTIONS = (
    "請執行 /plugin marketplace update marketing-workbench，更新後重新開始對話；"
    "也可到 /plugin → Marketplaces 開啟 Enable auto-update，之後會自動更新。"
)


def version_key(value):
    # Strict SemVer prevents arbitrary header text from reaching tool responses.
    if not isinstance(value, str) or len(value) > 64:
        return None
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", value
    )
    if not match:
        return None
    prerelease = match[4]
    parts = []
    for part in prerelease.split(".") if prerelease else []:
        if part.isdigit():
            if len(part) > 1 and part.startswith("0"):
                return None
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(map(int, match.group(1, 2, 3))), not bool(prerelease), tuple(parts)


def client_info(version):
    key = version_key(version)
    incompatible = version is not None and (
        key is None or key < version_key(PLUGIN_MIN_COMPATIBLE)
    )
    update = version is not None and (key is None or key < version_key(PLUGIN_LATEST))
    return {
        "plugin_version": version if key is not None else None,
        "latest_version": PLUGIN_LATEST,
        "min_compatible_version": PLUGIN_MIN_COMPATIBLE,
        "update_available": update,
        "incompatible": incompatible,
        "instructions": UPDATE_INSTRUCTIONS if update or incompatible else None,
    }


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def source_files():
    # Package only regular repository payload files; no machine metadata or symlinks.
    return {path.relative_to(PLUGIN_ROOT).as_posix(): path.read_bytes()
            for path in sorted(PLUGIN_ROOT.rglob("*")) if path.is_file() and not path.is_symlink()}


def content_hash():
    files = source_files()
    value = json.loads(files[MANIFEST])
    value.pop("version", None)
    files[MANIFEST] = json_bytes(value)
    files.update({"desktop/" + name: content for name, content in desktop_files().items()})
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        # Length-delimited names and bytes make boundaries unambiguous.
        for chunk in (name.encode("utf-8"), content):
            digest.update(len(chunk).to_bytes(8, "big"))
            digest.update(chunk)
    return digest.hexdigest()


def desktop_files():
    return {path.relative_to(DESKTOP_ROOT).as_posix(): path.read_bytes()
            for path in sorted(DESKTOP_ROOT.rglob("*")) if path.is_file() and not path.is_symlink()}


def desktop_archive():
    files = desktop_files()
    value = json.loads(files["manifest.json"])
    value["version"] = PLUGIN_LATEST
    files["manifest.json"] = json_bytes(value)
    return zip_bytes(files)


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content, compresslevel=9)
    return buffer.getvalue()


def claude_archive(origin):
    files = source_files()
    config = json.loads(files[".mcp.json"])
    server = config["mcpServers"]["mwb"]
    server["url"] = origin + "/mcp"
    server.setdefault("headers", {})["X-MWB-Plugin-Version"] = PLUGIN_LATEST
    files[".mcp.json"] = json_bytes(config)
    return zip_bytes(files)


def marketplace(session, origin):
    archive = claude_archive(origin)
    return {
        "name": "marketing-workbench",
        "owner": {"name": branding.identity(session)["name"]},
        "plugins": [{"name": "mwb", "description": manifest()["description"], "source": {
            "source": "archive", "url": origin + f"/plugin/mwb-{PLUGIN_LATEST}.zip",
            "sha256": hashlib.sha256(archive).hexdigest(),
        }}],
    }


def install_info(session, settings):
    return {**branding.identity(session), "backoffice_origin": settings.backoffice_origin,
            "plugin_version": PLUGIN_LATEST}


def download(origin, version, *, codex=False, desktop=False):
    if version != PLUGIN_LATEST:
        raise HTTPException(404, "Not Found")
    if desktop:
        return desktop_archive(), f"mwb-{version}.mcpb"
    content = codex_archive(origin) if codex else claude_archive(origin)
    return content, f"mwb-{'codex-' if codex else ''}{version}.zip"


def codex_config(origin):
    from app.services.agent_tools import list_tools

    lines = ["[mcp_servers.mwb]", "url = " + json.dumps(origin + "/mcp"),
             'default_tools_approval_mode = "prompt"']
    for tool in sorted(list_tools(), key=lambda item: item.name):
        readonly = tool.annotations is not None and tool.annotations.readOnlyHint is True
        mode = "approve" if readonly and tool.name != "confirm_publish" else "prompt"
        lines.extend(["", f"[mcp_servers.mwb.tools.{tool.name}]", f'approval_mode = "{mode}"'])
    return "\n".join(lines) + "\n"


def codex_archive(origin):
    files = {name: content for name, content in source_files().items()
             if name.startswith("skills/") and name.endswith("/SKILL.md")}
    files["config.toml"] = codex_config(origin).encode("utf-8")
    files["README.md"] = (
        "# Codex 安裝\n\n"
        "解壓縮到 mwb-codex，將 skills 下五個資料夾放到 ~/.agents/skills/；"
        "若已有同名資料夾，先備份並確認再取代。\n\n"
        "將 config.toml 合併至自己的 ~/.codex/config.toml，不要覆蓋既有設定。"
        "唯讀免核准，寫入及 confirm_publish 每次核准；"
        "這是用戶端偏好，後端仍會檢查權限與兩段式發佈確認。\n\n"
        "首次執行 `codex mcp login mwb`，用自己的工作檯帳號登入並核准；"
        "之後開新對話使用。更新時重新下載並合併設定／skills。\n"
    ).encode()
    return zip_bytes(files)
