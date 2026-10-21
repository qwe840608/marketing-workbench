"""Package bytes, internal boundary and per-request compatibility with synthetic data."""

import hashlib
import io
import json
import runpy
import tomllib
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_agent_auth import OFFICE, ORIGIN
from test_agent_auth import agent_client as agent_client

from app.main import create_app
from app.models import Setting
from app.services import agent_packages as packages
from app.services import agent_tools, branding


def unzip(response):
    assert response.status_code == 200, response.text if response.status_code != 200 else ""
    return zipfile.ZipFile(io.BytesIO(response.content))


@pytest.mark.parametrize("origin", [ORIGIN, OFFICE])
def test_claude_catalog_and_deterministic_payload(agent_client, origin):
    with agent_client.app.state.session_factory.begin() as session:
        session.add(Setting(key=branding.NAME_KEY, value_json="隔離工作檯"))
    catalog = agent_client.get(origin + "/plugin/marketplace.json")
    assert catalog.status_code == 200
    value = catalog.json()
    assert value["name"] == "marketing-workbench"
    assert value["owner"] == {"name": "隔離工作檯"}
    assert len(value["plugins"]) == 1
    plugin = value["plugins"][0]
    assert plugin["name"] == "mwb" and "version" not in plugin
    assert plugin["description"] and plugin["source"]["source"] == "archive"
    url = origin + f"/plugin/mwb-{packages.PLUGIN_LATEST}.zip"
    assert plugin["source"]["url"] == url
    first, second = agent_client.get(url), agent_client.get(url)
    assert first.content == second.content
    assert hashlib.sha256(first.content).hexdigest() == plugin["source"]["sha256"]
    with unzip(first) as archive:
        source = packages.source_files()
        assert archive.namelist() == sorted(source)
        assert archive.read(packages.MANIFEST) == source[packages.MANIFEST]
        for name, content in source.items():
            if name != ".mcp.json":
                assert archive.read(name) == content
        mcp = json.loads(archive.read(".mcp.json"))["mcpServers"]["mwb"]
        assert mcp["url"] == origin + "/mcp"
        assert mcp["headers"]["X-MWB-Plugin-Version"] == packages.PLUGIN_LATEST
        assert all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in archive.infolist())
    assert len(first.content) < 256 * 1024 * 1024
    assert len(catalog.content) < 5 * 1024 * 1024


@pytest.mark.parametrize("path", ["/plugin/marketplace.json",
                                  f"/plugin/mwb-{packages.PLUGIN_LATEST}.zip",
                                  f"/plugin/codex/mwb-codex-{packages.PLUGIN_LATEST}.zip",
                                  f"/plugin/desktop/mwb-{packages.PLUGIN_LATEST}.mcpb"])
def test_package_boundary(agent_client, path):
    assert agent_client.get(path, headers={"X-MWB-Public": "1"}).status_code == 404
    assert agent_client.get(path, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 404
    assert agent_client.get("https://other.example.test" + path).status_code == 404
    assert agent_client.get(path, headers={"Host": "unallowed.example.test"}).status_code == 404
    # Downloads don't require a member session, but external source addresses are hidden.
    agent_client.cookies.clear()
    assert agent_client.get(path).status_code == 200
    with TestClient(create_app(agent_client.app.state.settings), base_url=ORIGIN,
                    client=("203.0.113.9", 30000)) as external:
        assert external.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/plugin/mwb-0.2.0.zip", "/plugin/mwb-999.0.0.zip",
                                  "/plugin/codex/mwb-codex-0.2.0.zip",
                                  "/plugin/desktop/mwb-0.3.0.mcpb",
                                  "/plugin/desktop/mwb-999.0.0.mcpb"])
def test_unknown_versions(agent_client, path):
    assert agent_client.get(path).status_code == 404


def test_recorded_release_hash():
    record = json.loads((packages.PLUGIN_ROOT.parent / "content-hash.json").read_text())
    assert record == {"version": packages.PLUGIN_LATEST, "sha256": packages.content_hash()}, (
        "請提高 plugin 版本，並執行 scripts/update_plugin_hash.py 更新雜湊記錄"
    )
    assert packages.version_key(packages.PLUGIN_LATEST) is not None
    assert packages.manifest()["name"] == "mwb"
    config = json.loads((packages.PLUGIN_ROOT / ".mcp.json").read_text())
    assert config["mcpServers"]["mwb"]["headers"]["X-MWB-Plugin-Version"] == packages.PLUGIN_LATEST


def test_hash_ignores_only_manifest_version(monkeypatch):
    source = packages.source_files()
    original = packages.content_hash()
    value = json.loads(source[packages.MANIFEST])
    value["version"] = "999.0.0"
    source[packages.MANIFEST] = packages.json_bytes(value)
    monkeypatch.setattr(packages, "source_files", lambda: source)
    assert packages.content_hash() == original
    source["skills/report/SKILL.md"] += b"\nchanged\n"
    assert packages.content_hash() != original


@pytest.mark.parametrize("origin", [ORIGIN, OFFICE])
def test_desktop_deterministic_manifest_and_entrypoint(agent_client, origin):
    url = origin + f"/plugin/desktop/mwb-{packages.PLUGIN_LATEST}.mcpb"
    first, second = agent_client.get(url), agent_client.get(url)
    assert first.content == second.content == packages.desktop_archive()
    assert first.headers["content-disposition"] == (
        f'attachment; filename="mwb-{packages.PLUGIN_LATEST}.mcpb"')
    with unzip(first) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == packages.manifest()["version"] == "0.4.4"
        assert manifest["name"] == "mwb" and manifest["display_name"] == "行銷工作檯"
        assert manifest["manifest_version"] == "0.3"
        server = manifest["server"]
        assert server["type"] == "node"
        assert server["entry_point"] in archive.namelist()
        assert server["mcp_config"] == {"command": "node",
            "args": ["${__dirname}/server/index.js"], "env": {
                "MWB_WORKBENCH_URL": "${user_config.workbench_url}",
                "MWB_TOKEN": "${user_config.token}"}}
        assert manifest["user_config"]["token"]["sensitive"] is True
        assert all(manifest["user_config"][key]["required"] for key in ("token", "workbench_url"))
        assert "win32" in manifest["compatibility"]["platforms"]
        assert manifest["tools_generated"] is True
        assert "upload_local_file" in {tool["name"] for tool in manifest["tools"]}
        assert archive.read(server["entry_point"]) == (
            packages.desktop_files()[server["entry_point"]])
        assert all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in archive.infolist())


@pytest.mark.parametrize("name", ["manifest.json", "server/index.js"])
def test_desktop_content_changes_require_release_hash(monkeypatch, name):
    files = packages.desktop_files()
    original = packages.content_hash()
    files[name] += b"\nchanged\n"
    monkeypatch.setattr(packages, "desktop_files", lambda: files)
    assert packages.content_hash() != original
    record = json.loads((packages.PLUGIN_ROOT.parent / "content-hash.json").read_text())
    assert record["version"] == packages.PLUGIN_LATEST
    assert record["sha256"] != packages.content_hash()
    updater = runpy.run_path(str(packages.PLUGIN_ROOT.parent.parent /
                                "scripts/update_plugin_hash.py"))
    with pytest.raises(SystemExit, match="請提高 plugin 版本"):
        updater["main"]()


@pytest.mark.parametrize("origin", [ORIGIN, OFFICE])
def test_codex_skills_and_approval_policy(agent_client, origin):
    url = origin + f"/plugin/codex/mwb-codex-{packages.PLUGIN_LATEST}.zip"
    first, second = agent_client.get(url), agent_client.get(url)
    assert first.content == second.content
    with unzip(first) as archive:
        skills = [name for name in archive.namelist() if name.endswith("/SKILL.md")]
        assert skills == [f"skills/{name}/SKILL.md" for name in
                          ("ideas", "post", "publish", "report", "script")]
        for name in skills:
            content = archive.read(name)
            assert content == (packages.PLUGIN_ROOT / name).read_bytes()
            assert b"get_guide" in content and b"get_server_info" in content
        config = tomllib.loads(archive.read("config.toml").decode())["mcp_servers"]["mwb"]
        assert config["url"] == origin + "/mcp"
        assert config["default_tools_approval_mode"] == "prompt"
        assert "http_headers" not in config  # Codex connections have no plugin version header.
        tools = agent_tools.list_tools()
        assert set(config["tools"]) == {tool.name for tool in tools}
        for tool in tools:
            readonly = tool.annotations.readOnlyHint is True
            assert config["tools"][tool.name]["approval_mode"] == (
                "approve" if readonly and tool.name != "confirm_publish" else "prompt")
        assert config["tools"]["confirm_publish"]["approval_mode"] == "prompt"
        assert b"codex mcp login mwb" in archive.read("README.md")


def call(client, token, name, arguments=None, version=None):
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/json, text/event-stream"}
    if version is not None:
        headers["X-MWB-Plugin-Version"] = version
    response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1,
        "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}})
    assert response.status_code == 200
    return response.json()["result"]


@pytest.mark.parametrize("version", [
    None, "0.3.0", "1.0.0", "0.2.9", "0.3.0-beta.1", "invalid", "",
])
def test_version_gate_and_server_info(agent_client, version):
    token = agent_client.post("/api/agent/connections", json={"name": "隔離套件"}).json()["token"]
    info = call(agent_client, token, "get_server_info", version=version)
    assert not info["isError"]
    client = info["structuredContent"]["client"]
    incompatible = version in {"0.2.9", "0.3.0-beta.1", "invalid", ""}
    assert client["incompatible"] is incompatible
    assert client["update_available"] is (incompatible or version == "0.3.0")
    assert client["plugin_version"] == (None if version in {"invalid", ""} else version)
    guide = call(agent_client, token, "get_guide", {"workflow": "report"}, version)
    assert not guide["isError"]
    # Enumerate the live contract: every other tool is blocked before argument validation.
    if incompatible:
        for tool in agent_tools.list_tools():
            if tool.name in {"get_server_info", "get_guide"}:
                continue
            result = call(agent_client, token, tool.name, version=version)
            assert result["isError"] and result["structuredContent"]["message"] == (
                "plugin 版本過舊；下一步：更新 plugin 後重新開始對話")
    else:
        assert not call(agent_client, token, "get_brand_guide",
                        {"brand_id": agent_client.brand_id}, version)["isError"]


def test_older_compatible_release_prompts_update(agent_client, monkeypatch):
    monkeypatch.setattr(packages, "PLUGIN_LATEST", "0.4.0")
    token = agent_client.post("/api/agent/connections", json={"name": "隔離相容"}).json()["token"]
    info = call(agent_client, token, "get_server_info", version="0.3.0")["structuredContent"]
    assert info["client"]["update_available"] and not info["client"]["incompatible"]
    assert "/plugin marketplace update marketing-workbench" in info["client"]["instructions"]
    assert "Enable auto-update" in info["client"]["instructions"]
    assert not call(agent_client, token, "get_brand_guide",
                    {"brand_id": agent_client.brand_id}, "0.3.0")["isError"]
    info = call(agent_client, token, "get_server_info")["structuredContent"]
    assert info["client"]["plugin_version"] is None
