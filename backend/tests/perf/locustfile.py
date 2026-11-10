"""Locust 压测脚本（计划书 13.3）。

用法：
    # 1) 先准备好演示数据
    python -m app.cli seed --demo
    # 2) 起服务（建议 PG + Celery，压测结果更接近生产）
    uvicorn app.main:app --port 8000
    # 3) 压测（Web UI：http://localhost:8089）
    locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000
    # 或直接跑无头模式出 CSV
    locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 50 -r 5 -t 3m --csv docs/experiments/locust

说明：
- 只读接口与读多写少链路（列表/检索/报告）是主要压测目标；
- 出题/阅卷是异步任务，`questions:generate` 受限流保护，压测时把权重设低，避免把「限流 429」误读为系统瓶颈；
- 导学 SSE 不建议用 Locust 压（长连接 + 流式），如需评估请单独写 asyncio 脚本。
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

HOST = os.getenv("LOCUST_HOST", "http://127.0.0.1:8000")
TEACHER = (os.getenv("SEED_TEACHER", "teacher"), os.getenv("SEED_PASSWORD", "123456"))
STUDENT = (os.getenv("SEED_STUDENT", "student"), os.getenv("SEED_PASSWORD", "123456"))
COURSE_ID = int(os.getenv("SEED_COURSE_ID", "1"))

QUERIES = [
    "三次握手为什么不能是两次",
    "TIME_WAIT 的作用",
    "拥塞控制慢开始和拥塞避免的区别",
    "滑动窗口如何实现流量控制",
    "UDP 首部有哪些字段",
]


class BaseUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.token: str | None = None

    def login(self, credentials: tuple[str, str]) -> None:
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": credentials[0], "password": credentials[1]},
            name="POST /auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"登录失败：{resp.status_code} {resp.text[:120]}")
                return
            body = resp.json()
            self.token = (body.get("data") or {}).get("access_token")
            self.client.headers.update({"Authorization": f"Bearer {self.token}"})

    def on_start(self) -> None:
        self.login(self.credentials)  # type: ignore[attr-defined]


class TeacherUser(BaseUser):
    """教师：课程工作台为主（列表 + 检索 + 题库 + 学情）。"""

    weight = 2
    credentials = TEACHER

    @task(3)
    def list_courses(self) -> None:
        self.client.get("/api/v1/courses", name="GET /courses")

    @task(2)
    def course_detail(self) -> None:
        self.client.get(f"/api/v1/courses/{COURSE_ID}", name="GET /courses/{id}")

    @task(2)
    def documents(self) -> None:
        self.client.get(f"/api/v1/courses/{COURSE_ID}/documents", name="GET /documents")

    @task(1)
    def chunks(self) -> None:
        self.client.get(
            "/api/v1/documents/1/chunks",
            params={"page": 1, "size": 20},
            name="GET /documents/{id}/chunks",
        )

    @task(3)
    def hybrid_search(self) -> None:
        self.client.post(
            f"/api/v1/courses/{COURSE_ID}/search",
            json={"query": random.choice(QUERIES), "top_k": 6},
            name="POST /search (hybrid)",
        )

    @task(2)
    def questions(self) -> None:
        self.client.get(
            f"/api/v1/courses/{COURSE_ID}/questions",
            params={"page": 1, "size": 20},
            name="GET /questions",
        )

    @task(1)
    def overview(self) -> None:
        self.client.get(
            f"/api/v1/courses/{COURSE_ID}/stats/overview",
            name="GET /stats/overview",
        )


class StudentUser(BaseUser):
    """学生：报告与测评记录为主。"""

    weight = 3
    credentials = STUDENT

    @task(4)
    def my_attempts(self) -> None:
        self.client.get("/api/v1/me/attempts", name="GET /me/attempts")

    @task(3)
    def papers(self) -> None:
        self.client.get(
            "/api/v1/papers", params={"course_id": COURSE_ID}, name="GET /papers"
        )

    @task(2)
    def report(self) -> None:
        # 演示数据里 student 已有一次已批阅的作答
        self.client.get("/api/v1/attempts/1/report", name="GET /attempts/{id}/report")

    @task(2)
    def grading_status(self) -> None:
        self.client.get("/api/v1/attempts/1/grading-status", name="GET /grading-status")

    @task(1)
    def tutor_sessions(self) -> None:
        self.client.get("/api/v1/tutor/sessions", name="GET /tutor/sessions")
