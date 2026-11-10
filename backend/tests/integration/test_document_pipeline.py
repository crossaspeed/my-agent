"""文档上传 → 异步解析 → 分块 → 混合检索 集成测试。"""

from __future__ import annotations

import uuid

from tests.conftest import (
    DEMO_MD,
    auth_headers,
    make_course,
    register,
    upload_demo_document,
    wait_job,
)


def _teacher_with_course(client):
    teacher = register(client, f"tea_{uuid.uuid4().hex[:6]}", role="teacher")
    course_id = make_course(client, teacher["token"], f"CS{uuid.uuid4().hex[:4]}")
    return teacher, course_id


def test_upload_parse_and_chunks(client):
    teacher, course_id = _teacher_with_course(client)
    headers = auth_headers(client, teacher["token"])
    doc_id = upload_demo_document(client, teacher["token"], course_id)

    jobs = client.get(f"/api/v1/courses/{course_id}/jobs", headers=headers).json()["data"]
    job = wait_job(client, teacher["token"], jobs[0]["task_id"])
    assert job["status"] == "success", job
    assert job["result"]["chunk_count"] > 0

    docs = client.get(f"/api/v1/courses/{course_id}/documents", headers=headers).json()["data"]
    doc = next(d for d in docs if d["id"] == doc_id)
    assert doc["status"] == "ready"
    assert doc["chunk_count"] > 0

    chunks = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=headers).json()["data"]
    assert chunks["total"] > 0
    assert chunks["items"][0]["heading_path"]
    assert chunks["items"][0]["document_name"]


def test_duplicate_upload_reuses_document(client):
    teacher, course_id = _teacher_with_course(client)
    first = upload_demo_document(client, teacher["token"], course_id, "a.md")
    files = {"file": ("b.md", DEMO_MD.encode("utf-8"), "text/markdown")}
    resp = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files=files,
        headers=auth_headers(client, teacher["token"]),
    )
    data = resp.json()["data"]
    assert data["document_id"] == first
    assert data["duplicated"] is True


def test_reject_unsupported_extension(client):
    teacher, course_id = _teacher_with_course(client)
    files = {"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")}
    resp = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files=files,
        headers=auth_headers(client, teacher["token"]),
    )
    assert resp.status_code == 400


def test_reject_empty_file(client):
    teacher, course_id = _teacher_with_course(client)
    files = {"file": ("empty.md", b"", "text/markdown")}
    resp = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files=files,
        headers=auth_headers(client, teacher["token"]),
    )
    assert resp.status_code == 400


def test_reject_fake_pdf(client):
    teacher, course_id = _teacher_with_course(client)
    files = {"file": ("fake.pdf", b"not a real pdf", "application/pdf")}
    resp = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files=files,
        headers=auth_headers(client, teacher["token"]),
    )
    assert resp.status_code == 400


def test_hybrid_search_returns_tcp_chunk(client):
    teacher, course_id = _teacher_with_course(client)
    headers = auth_headers(client, teacher["token"])
    upload_demo_document(client, teacher["token"], course_id)
    jobs = client.get(f"/api/v1/courses/{course_id}/jobs", headers=headers).json()["data"]
    wait_job(client, teacher["token"], jobs[0]["task_id"])

    resp = client.post(
        f"/api/v1/courses/{course_id}/search",
        json={"query": "三次握手 同步 初始序号", "top_k": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items
    assert any("握手" in item["content"] for item in items)
    assert all(0 <= item["score"] <= 1.0 for item in items)


def test_student_cannot_upload(client):
    teacher, course_id = _teacher_with_course(client)
    student = register(client, f"stu_{uuid.uuid4().hex[:6]}")
    client.post(
        f"/api/v1/courses/{course_id}/members",
        json={"usernames": [student["user"]["username"]]},
        headers=auth_headers(client, teacher["token"]),
    )
    files = {"file": ("x.md", DEMO_MD.encode("utf-8"), "text/markdown")}
    resp = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files=files,
        headers=auth_headers(client, student["token"]),
    )
    assert resp.status_code == 403


def test_delete_document_clears_chunks(client):
    teacher, course_id = _teacher_with_course(client)
    headers = auth_headers(client, teacher["token"])
    doc_id = upload_demo_document(client, teacher["token"], course_id)
    jobs = client.get(f"/api/v1/courses/{course_id}/jobs", headers=headers).json()["data"]
    wait_job(client, teacher["token"], jobs[0]["task_id"])

    assert client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 200
    docs = client.get(f"/api/v1/courses/{course_id}/documents", headers=headers).json()["data"]
    assert all(d["id"] != doc_id for d in docs)
    assert client.get(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 404
