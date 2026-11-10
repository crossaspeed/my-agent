"""认证、课程与权限集成测试。"""

from __future__ import annotations

import uuid

from tests.conftest import auth_headers, make_course, register


def _name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def test_register_login_me(client):
    username = _name("stu")
    data = register(client, username)
    headers = auth_headers(client, data["token"])
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["username"] == username
    assert me.json()["data"]["role"] == "student"


def test_duplicate_username_conflict(client):
    username = _name("dup")
    register(client, username)
    resp = client.post(
        "/api/v1/auth/register", json={"username": username, "password": "123456"}
    )
    assert resp.status_code == 409


def test_wrong_password_401(client):
    username = _name("wrong")
    register(client, username)
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "bad-password"}
    )
    assert resp.status_code == 401


def test_missing_token_401(client):
    assert client.get("/api/v1/courses").status_code == 401


def test_change_password(client):
    username = _name("pwd")
    data = register(client, username)
    headers = auth_headers(client, data["token"])
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "123456", "new_password": "abcdef"},
        headers=headers,
    )
    assert resp.status_code == 200
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "abcdef"})
    assert login.status_code == 200


def test_teacher_requires_invite_code(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": _name("t"), "password": "123456", "role": "teacher"},
    )
    assert resp.status_code == 400


def test_student_cannot_create_course(client):
    data = register(client, _name("stu2"))
    resp = client.post(
        "/api/v1/courses",
        json={"code": _name("C"), "name": "越权课程"},
        headers=auth_headers(client, data["token"]),
    )
    assert resp.status_code == 403


def test_course_isolation(client):
    teacher = register(client, _name("tea"), role="teacher")
    other = register(client, _name("tea2"), role="teacher")
    course_id = make_course(client, teacher["token"], _name("CS"))

    # 其他教师看不到、也访问不了
    listed = client.get("/api/v1/courses", headers=auth_headers(client, other["token"]))
    assert all(c["id"] != course_id for c in listed.json()["data"])
    assert (
        client.get(f"/api/v1/courses/{course_id}", headers=auth_headers(client, other["token"]))
        .status_code
        == 403
    )


def test_add_members_and_student_view(client):
    teacher = register(client, _name("tea"), role="teacher")
    student = register(client, _name("stu"), role="student")
    course_id = make_course(client, teacher["token"], _name("CS"))

    resp = client.post(
        f"/api/v1/courses/{course_id}/members",
        json={"usernames": [student["user"]["username"], "not-exist-user"]},
        headers=auth_headers(client, teacher["token"]),
    )
    assert resp.status_code == 200
    assert student["user"]["username"] in resp.json()["data"]["added"]
    assert "not-exist-user" in resp.json()["data"]["skipped"]

    listed = client.get("/api/v1/courses", headers=auth_headers(client, student["token"]))
    assert any(c["id"] == course_id for c in listed.json()["data"])


def test_knowledge_point_tree(client):
    teacher = register(client, _name("tea"), role="teacher")
    course_id = make_course(client, teacher["token"], _name("CS"))
    headers = auth_headers(client, teacher["token"])

    parent = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points",
        json={"name": "传输层", "importance": 5},
        headers=headers,
    ).json()["data"]
    child = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points",
        json={"name": "TCP 三次握手", "parent_id": parent["id"]},
        headers=headers,
    ).json()["data"]
    tree = client.get(f"/api/v1/courses/{course_id}/knowledge-points", headers=headers)
    assert tree.status_code == 200
    root = tree.json()["data"][0]
    assert root["name"] == "传输层"
    assert root["children"][0]["id"] == child["id"]

    patched = client.patch(
        f"/api/v1/knowledge-points/{child['id']}",
        json={"importance": 4},
        headers=headers,
    )
    assert patched.json()["data"]["importance"] == 4
