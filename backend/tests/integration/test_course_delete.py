"""删除课程：权限、级联清理与幂等性。"""

from __future__ import annotations

import uuid

from tests.conftest import auth_headers, make_course, register


def _name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def _setup(client) -> tuple[dict, int]:
    teacher = register(client, _name("t_del"), role="teacher")
    course_id = make_course(client, teacher["token"], _name("C"))
    return teacher, course_id


def test_only_owner_can_delete(client):
    teacher, course_id = _setup(client)
    other = register(client, _name("t_other"), role="teacher")
    student = register(client, _name("s_del"))

    # 非成员：连课程都看不到
    resp = client.delete(
        f"/api/v1/courses/{course_id}", headers=auth_headers(client, student["token"])
    )
    assert resp.status_code == 403

    # 其他教师：既不是成员也不是创建者，同样禁止
    resp = client.delete(
        f"/api/v1/courses/{course_id}", headers=auth_headers(client, other["token"])
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 1003

    # 创建者可以删
    resp = client.delete(
        f"/api/v1/courses/{course_id}", headers=auth_headers(client, teacher["token"])
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_delete_removes_course_and_members(client):
    teacher, course_id = _setup(client)
    student = register(client, _name("s_member"))
    headers = auth_headers(client, teacher["token"])

    added = client.post(
        f"/api/v1/courses/{course_id}/members",
        json={"usernames": [student["user"]["username"]]},
        headers=headers,
    )
    assert added.status_code == 200
    assert client.get(f"/api/v1/courses/{course_id}", headers=headers).status_code == 200

    assert client.delete(f"/api/v1/courses/{course_id}", headers=headers).status_code == 200

    # 课程与成员关系都应消失
    assert client.get(f"/api/v1/courses/{course_id}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/courses/{course_id}/members", headers=headers).status_code == 404
    student_courses = client.get(
        "/api/v1/courses", headers=auth_headers(client, student["token"])
    ).json()["data"]
    assert all(item["id"] != course_id for item in student_courses)


def test_delete_is_not_idempotent_but_reports_missing(client):
    teacher, course_id = _setup(client)
    headers = auth_headers(client, teacher["token"])
    assert client.delete(f"/api/v1/courses/{course_id}", headers=headers).status_code == 200
    # 再删一次：明确告知不存在，而不是静默成功
    again = client.delete(f"/api/v1/courses/{course_id}", headers=headers)
    assert again.status_code == 404


def test_delete_does_not_touch_other_courses(client):
    teacher = register(client, _name("t_keep"), role="teacher")
    headers = auth_headers(client, teacher["token"])
    keep_id = make_course(client, teacher["token"], _name("KEEP"))
    drop_id = make_course(client, teacher["token"], _name("DROP"))

    assert client.delete(f"/api/v1/courses/{drop_id}", headers=headers).status_code == 200
    remaining = client.get("/api/v1/courses", headers=headers).json()["data"]
    ids = {item["id"] for item in remaining}
    assert keep_id in ids
    assert drop_id not in ids
