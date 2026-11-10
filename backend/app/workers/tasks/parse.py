"""解析任务入口（实现位于 document_service，此处仅做注册侧的显式导出）。"""

from app.services.document_service import parse_document_task

__all__ = ["parse_document_task"]
