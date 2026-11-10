"""黄金路径集成测试：上传 → 出题 → 审核 → 组卷 → 作答 → 阅卷 → 报告 → 导学。"""

from __future__ import annotations

import uuid

from tests.conftest import (
    auth_headers,
    create_kp,
    make_course,
    register,
    upload_demo_document,
    wait_job,
)


def _setup_course(client):
    teacher = register(client, f"tea_{uuid.uuid4().hex[:6]}", role="teacher")
    student = register(client, f"stu_{uuid.uuid4().hex[:6]}")
    course_id = make_course(client, teacher["token"], f"CS{uuid.uuid4().hex[:4]}", "计算机网络")
    th = auth_headers(client, teacher["token"])
    client.post(
        f"/api/v1/courses/{course_id}/members",
        json={"usernames": [student["user"]["username"]]},
        headers=th,
    )
    # 文档
    upload_demo_document(client, teacher["token"], course_id)
    jobs = client.get(f"/api/v1/courses/{course_id}/jobs", headers=th).json()["data"]
    wait_job(client, teacher["token"], jobs[0]["task_id"])
    kp_id = create_kp(client, teacher["token"], course_id, "TCP 三次握手")
    return teacher, student, course_id, kp_id, th


def test_full_flow(client):
    teacher, student, course_id, kp_id, th = _setup_course(client)
    sh = auth_headers(client, student["token"])

    # 1) 出题
    resp = client.post(
        f"/api/v1/courses/{course_id}/questions:generate",
        json={
            "course_id": course_id,
            "kp_ids": [kp_id],
            "types": {"single": 2, "judge": 1, "short": 1},
            "difficulty": {"easy": 0.2, "medium": 0.6, "hard": 0.2},
            "requirements": "侧重三次握手的目的",
        },
        headers=th,
    )
    assert resp.status_code == 200, resp.text
    job = wait_job(client, teacher["token"], resp.json()["data"]["job_id"])
    assert job["status"] == "success", job

    listed = client.get(f"/api/v1/courses/{course_id}/questions", headers=th).json()["data"]
    assert listed["total"] >= 3
    question_ids = [q["id"] for q in listed["items"]]

    # 每道题必须有可点开的溯源（chunk_id + 逐字引文）
    for question in listed["items"]:
        assert question["source_refs"], question
        ref = question["source_refs"][0]
        assert ref["chunk_id"] > 0
        assert ref["quote"]
        assert ref["document_name"]

    # 2) 审核通过
    review = client.post(
        "/api/v1/questions:batch-review",
        json={"ids": question_ids, "action": "approve"},
        headers=th,
    )
    assert review.status_code == 200
    assert review.json()["data"]["updated"] == len(question_ids)

    # 3) 组卷 + 发布
    paper_resp = client.post(
        "/api/v1/papers",
        json={
            "course_id": course_id,
            "title": "三次握手专项测评",
            "mode": "manual",
            "question_ids": question_ids,
            "duration_min": 30,
            "total_score": 100,
        },
        headers=th,
    )
    assert paper_resp.status_code == 200, paper_resp.text
    paper = paper_resp.json()["data"]
    paper_id = paper["id"]
    assert abs(sum(q["score"] for q in paper["questions"]) - 100) < 0.6

    published = client.post(f"/api/v1/papers/{paper_id}:publish", headers=th)
    assert published.status_code == 200

    # 4) 学生端无答案泄漏
    for_student = client.get(f"/api/v1/papers/{paper_id}/for-student", headers=sh).json()["data"]
    for question in for_student["questions"]:
        assert "answer" not in question
        assert "rubric" not in question
        assert "explanation" not in question

    # 5) 作答（单选答对、判断答错、简答留空）
    attempt = client.post(f"/api/v1/papers/{paper_id}/attempts", headers=sh).json()["data"]
    attempt_id = attempt["id"]
    paper_detail = client.get(f"/api/v1/papers/{paper_id}", headers=th).json()["data"]
    by_id = {q["question_id"]: q for q in paper_detail["questions"]}
    for item in attempt["answers"]:
        source = by_id[item["question_id"]]["question"]
        if source["type"] == "single":
            value = source["answer"]
        elif source["type"] == "judge":
            value = not source["answer"]
        elif source["type"] == "multiple":
            value = source["answer"]
        else:
            value = ""
        client.put(
            f"/api/v1/attempts/{attempt_id}/answers/{item['question_id']}",
            json={"value": value, "flagged": False},
            headers=sh,
        )

    # 草稿可恢复
    draft = client.get(f"/api/v1/attempts/{attempt_id}", headers=sh).json()["data"]
    assert draft["status"] == "in_progress"
    assert any(a["value"] not in (None, "") for a in draft["answers"])

    submit = client.post(f"/api/v1/attempts/{attempt_id}:submit", headers=sh)
    assert submit.status_code == 200
    grade_job = wait_job(client, teacher["token"], submit.json()["data"]["job_id"], timeout=120)
    assert grade_job["status"] == "success", grade_job

    # 6) 报告
    report = client.get(f"/api/v1/attempts/{attempt_id}/report", headers=sh).json()["data"]
    assert report["status"] == "graded"
    assert report["max_score"] == 100
    assert 0 <= report["total_score"] <= 100
    assert report["items"]
    assert report["kp_mastery"]

    blank_items = [
        i for i in report["items"] if i["type"] in ("short", "essay") and not i["student_answer"]
    ]
    assert blank_items
    assert blank_items[0]["score"] == 0
    assert "未作答" in blank_items[0]["error_tags"]

    # 7) 错题导学（SSE）
    wrong = report["wrong_items"][0]
    session = client.post(
        "/api/v1/tutor/sessions",
        json={"course_id": course_id, "question_id": wrong["question_id"]},
        headers=sh,
    )
    assert session.status_code == 200, session.text
    session_data = session.json()["data"]
    assert session_data["message"]["content"]
    assert session_data["refs"]

    events: list[str] = []
    with client.stream(
        "POST",
        f"/api/v1/tutor/sessions/{session_data['session_id']}/messages",
        json={"content": "那为什么不用两次握手？"},
        headers=sh,
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
    assert events[0] == "meta"
    assert "token" in events
    assert events[-1] == "done"

    history = client.get(
        f"/api/v1/tutor/sessions/{session_data['session_id']}", headers=sh
    ).json()["data"]
    assert len(history["messages"]) >= 3

    # 8) 教师端统计
    overview = client.get(f"/api/v1/courses/{course_id}/stats/overview", headers=th).json()["data"]
    assert overview["documents"] >= 1
    assert overview["questions"] >= 3
    assert overview["attempts"] >= 1

    stats = client.get("/api/v1/admin/llm-calls", headers=th)
    assert stats.status_code == 200


def test_submit_is_idempotent(client):
    teacher, student, course_id, kp_id, th = _setup_course(client)
    sh = auth_headers(client, student["token"])
    question_id = create_question(client, th, course_id, kp_id)
    paper = client.post(
        "/api/v1/papers",
        json={
            "course_id": course_id,
            "title": "幂等测试卷",
            "mode": "manual",
            "question_ids": [question_id],
            "total_score": 10,
        },
        headers=th,
    ).json()["data"]
    client.post(f"/api/v1/papers/{paper['id']}:publish", headers=th)

    attempt = client.post(f"/api/v1/papers/{paper['id']}/attempts", headers=sh).json()["data"]
    first = client.post(f"/api/v1/attempts/{attempt['id']}:submit", headers=sh).json()["data"]
    second = client.post(f"/api/v1/attempts/{attempt['id']}:submit", headers=sh).json()["data"]
    assert first["status"] == "submitted"
    assert second["status"] in ("submitted", "grading", "graded")


def create_question(client, headers, course_id: int, kp_id: int) -> int:
    resp = client.post(
        f"/api/v1/courses/{course_id}/questions:generate",
        json={
            "course_id": course_id,
            "kp_ids": [kp_id],
            "types": {"single": 1},
            "auto_publish": True,
        },
        headers=headers,
    )
    job = wait_job(client, headers["Authorization"].split(" ", 1)[1], resp.json()["data"]["job_id"])
    assert job["status"] == "success", job
    listed = client.get(f"/api/v1/courses/{course_id}/questions?status=published", headers=headers)
    return int(listed.json()["data"]["items"][0]["id"])
