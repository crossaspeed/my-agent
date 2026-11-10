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
