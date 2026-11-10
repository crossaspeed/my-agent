"""Celery 任务声明：薄封装，真正的实现在 app.workers.registry 中。"""

from __future__ import annotations

from typing import Any

from app.workers.celery_app import celery_app
from app.workers.runner import run_job_sync


@celery_app.task(bind=True, name="tasks.parse_document", max_retries=2)
def parse_document(self, payload: dict[str, Any]) -> None:  # type: ignore[misc]
    run_job_sync("parse_document", payload)


@celery_app.task(bind=True, name="tasks.generate_questions", max_retries=1)
def generate_questions(self, payload: dict[str, Any]) -> None:  # type: ignore[misc]
    run_job_sync("generate_questions", payload)


@celery_app.task(bind=True, name="tasks.grade_attempt", max_retries=1)
def grade_attempt(self, payload: dict[str, Any]) -> None:  # type: ignore[misc]
    run_job_sync("grade_attempt", payload)


@celery_app.task(bind=True, name="tasks.reindex_course", max_retries=0)
def reindex_course(self, payload: dict[str, Any]) -> None:  # type: ignore[misc]
    run_job_sync("reindex_course", payload)
