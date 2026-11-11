"""Celery 应用配置（USE_CELERY=true 时启用；io / llm 双队列分离）。"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.workers.registry import load_all

celery_app = Celery(
    "course_agent",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    worker_max_tasks_per_child=50,
    task_routes={
        "tasks.parse_document": {"queue": "io"},
        "tasks.reindex_course": {"queue": "io"},
        "tasks.generate_questions": {"queue": "llm"},
        "tasks.grade_attempt": {"queue": "llm"},
    },
)

load_all()

# 注册 Celery 任务声明：registry 只装载任务实现（与 broker 无关），
# 真正带 @celery_app.task 的薄封装在 tasks/celery_tasks.py 里，必须显式导入才会注册。
# 放在 load_all() 之后以避免与 celery_app 的循环导入。
from app.workers.tasks import celery_tasks  # noqa: E402,F401
