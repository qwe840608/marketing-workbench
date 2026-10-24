"""Custom roles: per-feature permissions, assignment and admin-only management."""

import test_members
from test_members import sign_in

from app.models import Staff
from app.services import agent_tools
from app.services.roles import BUILTIN, PERMISSIONS

member_password = test_members.member_password
member_digest = test_members.member_digest
people = test_members.people


def create_role(client, name, permissions):
    return client.post("/api/roles", json={"name": name, "permissions": permissions})


def assign(client, people, username, role):
    response = client.put(
        f"/api/members/{people[username]}",
        json={"display_name": username, "role": role, "brand_ids": [people["brands"][0]]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_lists_builtin_roles_and_permissions(client, people):
    catalog = client.get("/api/roles").json()
    assert catalog["permissions"] == list(PERMISSIONS)
    builtin = {role["key"]: role for role in catalog["roles"] if role["builtin"]}
    assert {key: role["permissions"] for key, role in builtin.items()} == {
        key: list(value) for key, value in BUILTIN.items()
    }
    assert builtin["marketing"]["member_count"] == 1


def test_create_edit_validate_and_delete_role(client, people):
    created = create_role(client, " 文案助理 ", ["publish.submit", "posts.sync"])
    assert created.status_code == 201, created.text
    role = created.json()
    # 送出發佈一定附帶編輯草稿；權限依固定順序回傳。
    assert role["name"] == "文案助理" and role["permissions"] == [
        "posts.sync", "publish.edit", "publish.submit"
    ]
    assert role["key"] == f"custom_{role['id']}" and role["builtin"] is False
    assert create_role(client, "文案助理", []).status_code == 409
    assert create_role(client, "壞角色", ["members.manage"]).status_code == 422
    assert create_role(client, " ", []).status_code == 422
    edited = client.put(f"/api/roles/{role['id']}", json={"name": "文案", "permissions": []})
    assert edited.status_code == 200 and edited.json()["permissions"] == []
    assert client.put("/api/roles/99999", json={"name": "x", "permissions": []}).status_code == 404

    assign(client, people, "assistant", role["key"])
    assert client.delete(f"/api/roles/{role['id']}").status_code == 409
    assign(client, people, "assistant", "marketing")
    assert client.delete(f"/api/roles/{role['id']}").status_code == 204
    assert all(r["key"] != role["key"] for r in client.get("/api/roles").json()["roles"])
    bad = client.put(
        f"/api/members/{people['assistant']}",
        json={"display_name": "a", "role": role["key"], "brand_ids": []},
    )
    assert bad.status_code == 422


def test_custom_role_permissions_are_enforced(client, people, member_password):
    role = create_role(client, "設定管理", ["settings.manage"]).json()
    member = assign(client, people, "assistant", role["key"])
    assert member["role_name"] == "設定管理" and member["permissions"] == ["settings.manage"]
    # 管理員才能管理成員與角色，即使有其他設定權限。
    assert sign_in(client, "assistant", member_password).status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["role"] == role["key"] and me["permissions"] == ["settings.manage"]
    assert client.get("/api/settings/export").status_code == 200
    assert client.get("/api/scheduler/jobs").status_code == 200
    assert client.get("/api/members").status_code == 403
    assert client.get("/api/roles").status_code == 403
    assert client.post("/api/roles", json={"name": "x", "permissions": []}).status_code == 403
    assert client.get("/api/credentials").status_code == 403
    assert client.get("/api/ai/keys").status_code == 403
    assert client.post("/api/scheduler/metrics-sync").status_code == 403
    assert client.post("/api/publish/posts", json={}).status_code == 403
    # 自訂角色只看得到被指派的品牌。
    assert [b["id"] for b in client.get("/api/brands").json()] == people["brands"][:1]


def test_role_without_permissions_is_read_only(client, people, member_password):
    role = create_role(client, "只看", []).json()
    assign(client, people, "assistant", role["key"])
    assert sign_in(client, "assistant", member_password).status_code == 200
    assert client.get("/api/dashboard").status_code == 200
    assert client.put("/api/auth/language", json={"language": "en"}).status_code == 200
    assert client.post("/api/scheduler/metrics-sync").status_code == 403


def test_missing_role_grants_nothing(client, people, member_password):
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, people["assistant"]).role = "custom_404"
    assert sign_in(client, "assistant", member_password).status_code == 200
    assert client.get("/api/auth/me").json()["permissions"] == []
    assert client.post("/api/scheduler/metrics-sync").status_code == 403


def test_every_agent_write_tool_maps_to_a_permission():
    writes = {name for name, (_, write, _) in agent_tools.SPECS.items() if write}
    assert writes <= set(agent_tools.TOOL_PERMISSIONS)
    assert {agent_tools.TOOL_PERMISSIONS[name] for name in writes} <= set(PERMISSIONS)
    for name in ("confirm_publish", "retry_failed_platforms", "cancel_schedule"):
        assert agent_tools.TOOL_PERMISSIONS[name] == "publish.submit"
