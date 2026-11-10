"""pytest 全局配置：隔离测试数据库、离线 Mock LLM/Embedding。

注意：环境变量必须在导入 app 之前设置（settings 是模块级单例）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="course-agent-test-"))

os.environ.update(
    {
        "APP_ENV": "test",
        "DEBUG": "false",
        "SECRET_KEY": "test-secret-key-0123456789abcdef0123456789",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
        "DATABASE_URL_SYNC": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "USE_CELERY": "false",
        "JOB_WORKERS": "2",
        "VECTOR_BACKEND": "local",
        "VECTOR_DIR": str(_TMP / "vectors"),
        "EMBEDDING_PROVIDER": "hash",
        "LLM_PROVIDER": "mock",
        "AUTO_CREATE_TABLES": "true",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "MAX_UPLOAD_MB": "5",
        "MIN_RETRIEVE_SCORE": "0.05",
        "RATE_LIMIT_DISABLED": "true",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.ratelimit import reset_rate_limit  # noqa: E402
from app.db.base import AsyncSessionLocal, init_models  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        # 先占用「首个用户自动成为 admin」的名额，避免影响后续角色断言
        test_client.post(
            "/api/v1/auth/register",
            json={"username": "bootstrap_admin", "password": "123456"},
        )
        yield test_client


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_rate_limit()
    yield


@pytest.fixture
async def db():
    await init_models()
    async with AsyncSessionLocal() as session:
        yield session


def auth_headers(client: TestClient, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client: TestClient, username: str, role: str = "student") -> dict:
    payload = {"username": username, "password": "123456", "role": role}
    if role == "teacher":
        payload["invite_code"] = "TEACHER2026"
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {"token": data["access_token"], "user": data["user"]}


def make_course(client: TestClient, token: str, code: str, name: str = "测试课程") -> int:
    resp = client.post(
        "/api/v1/courses",
        json={"code": code, "name": name},
        headers=auth_headers(client, token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


DEMO_MD = """# 第一章 传输层

## 1.1 TCP 三次握手

三次握手过程中，客户端发送 SYN=1、序号 seq=x 的报文段，进入 SYN_SENT 状态，用于请求建立连接并同步初始序号。
服务器收到后回复 SYN=1、ACK=1、seq=y、ack=x+1 的报文段，进入 SYN_RCVD 状态。
客户端再发送 ACK=1、ack=y+1 的确认报文段，连接进入 ESTABLISHED 状态。
三次握手的根本目的是同步双方的初始序号并确认双方收发能力正常，缺少任何一次都无法完成这两个目标。

## 1.2 为什么不是两次握手

若只进行两次握手，网络中滞留的过期连接请求到达服务器后，服务器会误认为新连接并分配资源，造成资源浪费。
采用三次握手时，服务器在收到第三次确认之前不会认为连接已建立，从而避免历史连接占用资源。

## 1.3 拥塞控制

拥塞控制包括慢开始、拥塞避免、快重传与快恢复。慢开始阶段拥塞窗口从 1 个 MSS 开始按指数增长，
达到慢开始门限后进入拥塞避免阶段按线性增长。出现超时后门限减半并将拥塞窗口重置为 1。
收到三个重复确认时执行快重传，立即重传丢失的报文段并进入快恢复。
"""


def upload_demo_document(client: TestClient, token: str, course_id: int, filename: str = "demo.md") -> int:
    files = {"file": (filename, DEMO_MD.encode("utf-8"), "text/markdown")}
    resp = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files=files,
        headers=auth_headers(client, token),
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["document_id"])


def wait_job(client: TestClient, token: str, task_id: str, timeout: float = 60.0) -> dict:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v1/jobs/{task_id}", headers=auth_headers(client, token))
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        if data["status"] in ("success", "failed"):
            return data
        time.sleep(0.2)
    raise AssertionError(f"任务 {task_id} 超时未完成")


def create_kp(client: TestClient, token: str, course_id: int, name: str) -> int:
    resp = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points",
        json={"name": name, "importance": 5},
        headers=auth_headers(client, token),
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["id"])


__all__ = [
    "app",
    "auth_headers",
    "client",
    "create_kp",
    "db",
    "make_course",
    "register",
    "upload_demo_document",
    "wait_job",
]
