"""试卷与作答路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.schemas.attempt import SaveAnswerRequest
from app.schemas.common import ok
from app.schemas.paper import PaperCreate
from app.services import attempt_service, paper_service, stats_service

router = APIRouter(tags=["试卷与作答"])


@router.post("/papers", summary="组卷（手动 / 按知识点自动）")
async def create_paper(req: PaperCreate, user: CurrentUser, session: SessionDep):
    return ok(await paper_service.create_paper(session, user, req))


@router.get("/papers", summary="试卷列表")
async def list_papers(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await paper_service.list_papers(session, course_id, user))


@router.get("/papers/{paper_id}", summary="试卷详情（含答案，教师用）")
async def get_paper(paper_id: int, user: CurrentUser, session: SessionDep):
    return ok(await paper_service.get_paper(session, paper_id, user))


@router.get("/papers/{paper_id}/for-student", summary="学生端试卷（服务层剥离答案）")
async def get_paper_for_student(paper_id: int, user: CurrentUser, session: SessionDep):
    return ok(await paper_service.get_paper_for_student(session, paper_id, user))


@router.post("/papers/{paper_id}:publish", summary="发布试卷")
async def publish(paper_id: int, user: CurrentUser, session: SessionDep):
    return ok(await paper_service.publish_paper(session, paper_id, user))


@router.get("/papers/{paper_id}/stats", summary="班级成绩（教师端）")
async def paper_stats(paper_id: int, user: CurrentUser, session: SessionDep):
    return ok(await paper_service.paper_stats(session, paper_id, user))


@router.post("/papers/{paper_id}/attempts", summary="开始作答（幂等）")
async def start_attempt(paper_id: int, user: CurrentUser, session: SessionDep):
    return ok(await attempt_service.start_attempt(session, paper_id, user))


@router.get("/attempts/{attempt_id}", summary="作答详情（草稿恢复）")
async def get_attempt(attempt_id: int, user: CurrentUser, session: SessionDep):
    return ok(await attempt_service.get_attempt(session, attempt_id, user))


@router.put("/attempts/{attempt_id}/answers/{question_id}", summary="保存单题草稿")
async def save_answer(
    attempt_id: int,
    question_id: int,
    req: SaveAnswerRequest,
    user: CurrentUser,
    session: SessionDep,
):
    await attempt_service.save_answer(
        session, attempt_id, question_id, user, req.value, req.flagged
    )
    return ok(None, message="已保存")


@router.post("/attempts/{attempt_id}:submit", summary="提交并触发异步阅卷")
async def submit(attempt_id: int, user: CurrentUser, session: SessionDep):
    return ok(await attempt_service.submit_attempt(session, attempt_id, user))


@router.get("/attempts/{attempt_id}/report", summary="成绩报告")
async def report(attempt_id: int, user: CurrentUser, session: SessionDep):
    return ok(await attempt_service.build_report(session, attempt_id, user))


@router.get("/attempts/{attempt_id}/grading-status", summary="阅卷进度")
async def grading_status(attempt_id: int, user: CurrentUser, session: SessionDep):
    return ok(await attempt_service.grading_status(session, attempt_id, user))


@router.get("/attempts/{attempt_id}/stats/kp-mastery", summary="知识点掌握度（雷达数据）")
async def kp_mastery(attempt_id: int, user: CurrentUser, session: SessionDep):
    return ok(await stats_service.kp_mastery(session, attempt_id, user))


@router.get("/me/attempts", summary="我的测评记录")
async def my_attempts(user: CurrentUser, session: SessionDep):
    return ok(await attempt_service.list_my_attempts(session, user))


@router.get("/courses/{course_id}/stats/overview", summary="课程概览")
async def overview(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await stats_service.overview(session, course_id, user))


@router.get("/courses/{course_id}/stats/error-heatmap", summary="班级错题分布")
async def error_heatmap(course_id: int, user: CurrentUser, session: SessionDep):
    return ok(await stats_service.error_heatmap(session, course_id, user))


@router.get("/courses/{course_id}/jobs", summary="课程任务列表")
async def course_jobs(
    course_id: int,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    job_type: str | None = None,
):
    from app.services import job_service

    jobs = await job_service.list_by_course(session, course_id, limit=limit, job_type=job_type)
    return ok(
        [
            {
                "task_id": j.task_id,
                "job_type": j.job_type,
                "target_id": j.target_id,
                "status": j.status,
                "progress": j.progress,
                "stage": j.stage,
                "result": j.result,
                "error_msg": j.error_msg,
                "created_at": j.created_at,
                "finished_at": j.finished_at,
            }
            for j in jobs
        ]
    )
