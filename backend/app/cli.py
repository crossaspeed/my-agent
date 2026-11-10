"""命令行工具：建库、造演示数据、重建索引、检索评测。

用法：
    python -m app.cli seed --demo      # 建演示数据（教师/学生/课程/课件/题库/试卷/一次作答）
    python -m app.cli create-user <username> <password> --role teacher
    python -m app.cli reindex --course-id 1
    python -m app.cli eval-retrieval --course-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.agents.orchestrator import build_kp_specs
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.security import hash_password
from app.db.base import AsyncSessionLocal, init_models
from app.db.models import (
    Attempt,
    Course,
    CourseMember,
    Document,
    KnowledgePoint,
    Question,
    User,
)
from app.schemas.paper import AutoPaperConfig, PaperCreate
from app.services import (
    attempt_service,
    document_service,
    job_service,
    paper_service,
    question_service,
)

logger = get_logger(__name__)

DEMO_DOCS: list[tuple[str, str]] = [
    (
        "第3章-传输层.md",
        """# 第3章 传输层

## 3.1 传输层概述

传输层为运行在不同主机上的应用进程之间提供逻辑通信。它把网络层的尽力而为交付服务转换为面向应用的可靠服务，
并通过端口号实现进程到进程的复用与分用。传输层协议主要有 TCP 与 UDP 两类：TCP 提供面向连接的可靠字节流服务，
UDP 提供无连接的尽力而为数据报服务。复用指发送方多个应用进程共用同一个传输层协议发送数据，
分用指接收方根据端口号把数据交付给正确的应用进程。

## 3.2 TCP 连接管理

### 3.2.1 三次握手

三次握手过程中，客户端发送 SYN=1、序号 seq=x 的报文段，进入 SYN_SENT 状态，表示请求建立连接并同步初始序号。
服务器收到后回复 SYN=1、ACK=1、seq=y、ack=x+1 的报文段，进入 SYN_RCVD 状态，同时确认客户端序号并通告自己的初始序号。
客户端再发送 ACK=1、ack=y+1 的确认报文段，双方进入 ESTABLISHED 状态，连接建立完成。
三次握手的根本目的是同步双方的初始序号并确认双方的收发能力都正常，缺少任何一次交互都无法同时完成这两个目标。

### 3.2.2 为什么是三次而不是两次

若只进行两次握手，网络中滞留的过期连接请求到达服务器后，服务器会误认为新的连接请求并分配资源，
造成服务器资源浪费，同时客户端不会响应该连接，形成半开连接。
采用三次握手时，服务器在收到第三次确认前不会认为连接已建立，从而避免历史连接请求造成的资源浪费。
这也是为什么不能把三次握手简化为两次的直接原因。

### 3.2.3 四次挥手与 TIME_WAIT

连接释放需要四次挥手：主动关闭方发送 FIN，进入 FIN_WAIT_1；被动关闭方回复 ACK，进入 CLOSE_WAIT；
被动关闭方数据发送完毕后发送 FIN，进入 LAST_ACK；主动关闭方回复 ACK 后进入 TIME_WAIT 状态，
等待 2MSL 时间后进入 CLOSED。TIME_WAIT 的作用有两个：保证最后一个 ACK 能够到达对端，
以及让本次连接中滞留的报文段在网络中消亡，避免影响后续使用相同四元组的新连接。

## 3.3 TCP 可靠传输与流量控制

TCP 通过序号、确认、超时重传与快速重传来实现可靠传输。接收方使用累积确认，ACK 号表示期望接收的下一个字节序号。
流量控制通过滑动窗口实现：接收方在报文段的首部通告接收窗口 rwnd，发送方保证未确认的数据量不超过该窗口，
从而避免发送速度超过接收方的处理能力。窗口为 0 时发送方启动持续计时器，定期发送零窗口探测报文。

## 3.4 TCP 拥塞控制

拥塞控制由慢开始、拥塞避免、快重传和快恢复四个算法组成。慢开始阶段拥塞窗口 cwnd 从 1 个 MSS 开始，
每经过一个传输轮次就翻倍增长，呈指数上升；当 cwnd 达到慢开始门限 ssthresh 后进入拥塞避免阶段，
每个轮次只增加 1 个 MSS，呈线性增长。发送方判断出现超时后，将 ssthresh 设为当前 cwnd 的一半，
并把 cwnd 重置为 1，重新执行慢开始。若收到三个重复确认，则执行快重传立即重传丢失的报文段，
并进入快恢复：ssthresh 与 cwnd 都设为当前 cwnd 的一半，随后执行拥塞避免，而不是回到慢开始。

## 3.5 UDP 与适用场景

UDP 只在 IP 数据报服务之上增加了复用分用和差错检测功能，首部仅 8 字节，包含源端口、目的端口、长度和校验和。
UDP 不保证可靠交付、不保证顺序、不进行拥塞控制，因此传输时延小、开销低，适合实时音视频、
DNS 查询和广播多播等对实时性要求高而能容忍少量丢包的场景。
""",
    ),
    (
        "第4章-网络层.md",
        """# 第4章 网络层

## 4.1 网络层功能

网络层负责把分组从源主机经若干路由器转发到目的主机，核心功能包括转发与路由选择。
转发是路由器把到达的分组从合适端口送出的本地动作，路由选择则是全网范围内计算路径的过程。
网络层向上提供无连接的数据报服务，不保证可靠交付，可靠性由传输层负责。

## 4.2 IP 地址与子网划分

IPv4 地址长 32 位，采用点分十进制表示。传统分类地址分为 A、B、C、D、E 五类，
无分类编址 CIDR 使用网络前缀代替分类地址，形式为 a.b.c.d/n，n 表示网络前缀长度。
子网掩码用于从 IP 地址中提取网络前缀：把 IP 地址与子网掩码按位与运算即可得到网络地址。
划分子网时从主机号借位作为子网号，借位越多可划分的子网越多，但每个子网可分配的主机数越少。

## 4.3 ARP 与 MAC 地址

地址解析协议 ARP 用于把同一局域网内的 IP 地址解析为 MAC 地址。主机发送数据前先查询 ARP 高速缓存，
若不存在目的 IP 对应的表项，则广播 ARP 请求，目标主机以单播方式回复自己的 MAC 地址。
ARP 只在同一局域网内工作，跨网段通信时解析的是默认网关的 MAC 地址。

## 4.4 路由选择协议

内部网关协议包括 RIP 与 OSPF。RIP 基于距离向量算法，以跳数为度量，最大跳数为 15，16 表示不可达，
收敛慢且存在坏消息传播慢的问题。OSPF 基于链路状态算法，使用 Dijkstra 最短路径算法计算路由，
支持区域划分与等价多路径，收敛速度快，适合大型网络。外部网关协议 BGP 用于自治系统之间的路由交换，
基于路径向量算法，重视策略而非最短路径。

## 4.5 NAT 与 IPv6

网络地址转换 NAT 使私有地址网络中的主机能够访问互联网，路由器在转发时把私有源地址替换为公网地址并记录映射表。
NAPT 进一步利用端口号区分不同内网主机，使多个主机共用一个公网地址。
IPv6 地址长 128 位，采用冒号十六进制表示，取消了首部校验和，简化了首部格式，并原生支持地址自动配置。
""",
    ),
]


# ---------------- 种子数据 ----------------
async def _ensure_user(session, username: str, password: str, role: str, real_name: str) -> User:
    row = await session.execute(select(User).where(User.username == username))
    user = row.scalar_one_or_none()
    if user:
        return user
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        real_name=real_name,
        email=f"{username}@example.com",
    )
    session.add(user)
    await session.flush()
    return user


async def _ensure_course(session, owner: User) -> Course:
    row = await session.execute(select(Course).where(Course.code == "CS-NET-01"))
    course = row.scalar_one_or_none()
    if course:
        return course
    course = Course(
        code="CS-NET-01",
        name="计算机网络",
        description="面向计算机类专业核心课，覆盖体系结构、应用层、传输层、网络层与链路层。",
        owner_id=owner.id,
        settings={"score_per_question": 5, "strictness": "medium"},
    )
    session.add(course)
    await session.flush()
    return course


KP_TREE = {
    "计算机网络体系结构": ["分层模型", "OSI 七层模型", "TCP/IP 四层模型"],
    "应用层": ["HTTP 协议", "DNS 域名解析", "电子邮件协议"],
    "传输层": ["TCP 三次握手", "TCP 四次挥手", "TCP 滑动窗口与流量控制", "TCP 拥塞控制", "UDP 协议"],
    "网络层": ["IP 地址与子网划分", "ARP 协议", "路由选择协议", "NAT 与 IPv6"],
    "链路层": ["以太网与 CSMA/CD", "交换机与 VLAN"],
}


async def _ensure_kps(session, course: Course) -> list[KnowledgePoint]:
    existing = (
        await session.execute(select(KnowledgePoint).where(KnowledgePoint.course_id == course.id))
    ).scalars().all()
    if existing:
        return list(existing)
    created: list[KnowledgePoint] = []
    order = 0
    for parent_name, children in KP_TREE.items():
        order += 1
        parent = KnowledgePoint(
            course_id=course.id, name=parent_name, importance=5, sort_order=order
        )
        session.add(parent)
        await session.flush()
        created.append(parent)
        for child in children:
            order += 1
            child_kp = KnowledgePoint(
                course_id=course.id,
                parent_id=parent.id,
                name=child,
                importance=4,
                sort_order=order,
            )
            session.add(child_kp)
            await session.flush()
            created.append(child_kp)
    return created


async def _seed_documents(session, course: Course, teacher: User) -> None:
    demo_dir = settings.resolve_path("./data/demo")
    demo_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in DEMO_DOCS:
        path = demo_dir / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
        existing = await session.execute(
            select(Document).where(
                Document.course_id == course.id, Document.filename == filename
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        result = await document_service.upload_document(
            session, course.id, teacher, filename, content.encode("utf-8"), enqueue=False
        )
        if result.duplicated and result.job_id is None:
            continue
        await document_service.process_document_now(session, result.document_id)
    print(f"  ✓ 文档已解析并入库（{len(DEMO_DOCS)} 份）")


async def _seed_questions(session, course: Course, teacher: User) -> list[Question]:
    existing = (
        await session.execute(
            select(Question).where(Question.course_id == course.id, Question.status == "published")
        )
    ).scalars().all()
    if existing:
        return list(existing)

    kps = (
        await session.execute(select(KnowledgePoint).where(KnowledgePoint.course_id == course.id))
    ).scalars().all()
    target_names = ["TCP 三次握手", "TCP 拥塞控制", "TCP 滑动窗口与流量控制", "TCP 四次挥手"]
    chosen = [kp for kp in kps if kp.name in target_names] or list(kps)[:2]
    specs = build_kp_specs(
        kp_ids=[kp.id for kp in chosen],
        kp_names={kp.id: kp.name for kp in chosen},
        types={"single": 2, "multiple": 1, "judge": 1, "short": 1},
        difficulty={"easy": 0.2, "medium": 0.6, "hard": 0.2},
        score_per_question=5,
    )
    payload = {
        "course_id": course.id,
        "course_name": course.name,
        "kp_specs": specs,
        "requirements": "侧重 TCP 连接管理与拥塞控制，避免纯记忆性题目",
        "doc_ids": None,
        "auto_publish": True,
        "score_per_question": 5,
        "trace_id": "seed",
    }
    job = await job_service.create(
        session, "generate_questions", course_id=course.id, created_by=teacher.id, payload=payload
    )
    await session.commit()
    await question_service.generate_questions_task({**payload, "task_id": job.task_id})

    rows = await session.execute(
        select(Question).where(Question.course_id == course.id, Question.status == "published")
    )
    questions = list(rows.scalars().all())
    print(f"  ✓ 已生成并审核通过 {len(questions)} 道题目")
    return questions


async def _seed_paper(session, course: Course, teacher: User, student: User) -> None:
    existing = await session.execute(select(Question).limit(1))
    if existing.scalar_one_or_none() is None:
        return
    papers = await paper_service.list_papers(session, course.id, teacher)
    if papers:
        return
    cfg = AutoPaperConfig(
        kp_ids=[kp.id for kp in (
            await session.execute(select(KnowledgePoint).where(KnowledgePoint.course_id == course.id))
        ).scalars().all() if kp.name.startswith("TCP")],
        types={"single": 2, "multiple": 1, "judge": 1, "short": 1},
        difficulty={"easy": 0.3, "medium": 0.5, "hard": 0.2},
    )
    paper = await paper_service.create_paper(
        session,
        teacher,
        PaperCreate(
            course_id=course.id,
            title="《计算机网络》传输层阶段测评",
            description="覆盖 TCP 连接管理、可靠传输与拥塞控制",
            mode="auto",
            config=cfg,
            duration_min=45,
            total_score=100,
        ),
    )
    await paper_service.publish_paper(session, paper.id, teacher)
    print(f"  ✓ 已创建并发布试卷：{paper.title}")

    attempt = await attempt_service.start_attempt(session, paper.id, student)
    attempt_row = await session.get(Attempt, attempt.id)
    pairs = await attempt_service._pairs(session, paper.id)
    for _pq, question in pairs:
        answer = None
        if question.type == "single":
            answer = question.answer  # 单选答对
        elif question.type == "multiple":
            answer = (question.answer or [])[:1]  # 多选少选（判错）
        elif question.type == "judge":
            answer = not question.answer  # 判断答错
        else:
            answer = "三次握手用于同步双方的初始序号，并确认双方的收发能力；只握手两次会让过期的连接请求占用服务器资源。"
        await attempt_service.save_answer(
            session, attempt.id, question.id, student, answer, False
        )
    await session.commit()
    from datetime import UTC, datetime

    from app.services import grading_service

    attempt_row.status = "submitted"
    attempt_row.submitted_at = datetime.now(UTC)
    session.add(attempt_row)
    await session.commit()
    await grading_service.grade_attempt(session, attempt.id)
    print(f"  ✓ 已为 {student.username} 创建一次作答并完成阅卷（attempt_id={attempt.id}）")


async def seed_demo() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        await _ensure_user(session, "admin", "123456", "admin", "系统管理员")
        teacher = await _ensure_user(session, "teacher", "123456", "teacher", "张老师")
        student = await _ensure_user(session, "student", "123456", "student", "李同学")
        for i in range(1, 4):
            await _ensure_user(session, f"student{i}", "123456", "student", f"学生{i}")
        course = await _ensure_course(session, teacher)
        for user in (student,):
            exists = await session.execute(
                select(CourseMember).where(
                    CourseMember.course_id == course.id, CourseMember.user_id == user.id
                )
            )
            if exists.scalar_one_or_none() is None:
                session.add(CourseMember(course_id=course.id, user_id=user.id, role="student"))
        for i in range(1, 4):
            row = await session.execute(select(User).where(User.username == f"student{i}"))
            extra = row.scalar_one_or_none()
            if extra:
                exists = await session.execute(
                    select(CourseMember).where(
                        CourseMember.course_id == course.id, CourseMember.user_id == extra.id
                    )
                )
                if exists.scalar_one_or_none() is None:
                    session.add(
                        CourseMember(course_id=course.id, user_id=extra.id, role="student")
                    )
        await session.commit()
        print(f"  ✓ 用户与课程就绪（admin/teacher/student，密码均 {settings.DEFAULT_PASSWORD}）")

        await _ensure_kps(session, course)
        await session.commit()
        await _seed_documents(session, course, teacher)
        await _seed_questions(session, course, teacher)
        await _seed_paper(session, course, teacher, student)

        print("\n演示数据准备完成：")
        print(f"  课程 ID：{course.id}  教师：teacher/123456  学生：student/123456")
        print("  启动后端：uvicorn app.main:app --reload")
        print("  启动前端：cd frontend && npm run dev")


# ---------------- 其它命令 ----------------
async def create_user(username: str, password: str, role: str, real_name: str) -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        user = await _ensure_user(session, username, password, role, real_name)
        await session.commit()
        print(f"用户已就绪：{user.username}（{user.role}）")


async def reindex(course_id: int | None) -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        job = await job_service.create(
            session, "reindex_course", course_id=course_id, payload={"course_id": course_id}
        )
        await session.commit()
        from app.workers.runner import run_job

        await run_job("reindex_course", {"course_id": course_id, "task_id": job.task_id})
        print(f"重建完成（course_id={course_id or '全部'}）")


async def eval_retrieval(course_id: int) -> None:
    """检索评测：对比纯向量 / 纯 BM25 / 混合 RRF，输出 docs/experiments/retrieval.csv。"""
    import csv

    from app.rag import bm25_index
    from app.rag.embedder import get_embedder
    from app.rag.retriever import retrieve
    from app.rag.vector_store import get_vector_store

    queries = [
        "三次握手为什么不能是两次",
        "TIME_WAIT 的作用",
        "拥塞控制慢开始和拥塞避免的区别",
        "滑动窗口如何实现流量控制",
        "快重传和快恢复的过程",
        "UDP 首部有哪些字段",
        "ARP 如何解析 MAC 地址",
        "子网掩码如何计算网络地址",
        "OSPF 与 RIP 的区别",
        "NAT 的作用是什么",
    ]
    out_dir = Path("../docs/experiments")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    async with AsyncSessionLocal() as session:
        embedder = get_embedder()
        store = get_vector_store()
        index = await bm25_index.get_index(session, course_id)
        for query in queries:
            vector = await embedder.embed_query(query)
            dense = await store.search(course_id, vector, top_k=6)
            sparse = index.search(query, top_k=6)
            hybrid = await retrieve(session, course_id, query, top_k=6, use_cache=False)
            rows.append(
                {
                    "query": query,
                    "dense_top3": [h.chunk_id for h in dense[:3]],
                    "sparse_top3": [cid for cid, _ in sparse[:3]],
                    "hybrid_top3": [c.chunk_id for c in hybrid[:3]],
                    "dense_best_score": round(dense[0].score, 4) if dense else 0,
                    "hybrid_best_relevance": hybrid[0].relevance if hybrid else 0,
                }
            )

    csv_path = out_dir / "retrieval.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["query"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"queries": len(rows), "output": str(csv_path)}, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(prog="course-agent", description="智评导学 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="初始化数据")
    seed.add_argument("--demo", action="store_true", help="写入演示课程与课件")

    user = sub.add_parser("create-user", help="创建用户")
    user.add_argument("username")
    user.add_argument("password")
    user.add_argument("--role", default="student", choices=["student", "teacher", "admin"])
    user.add_argument("--real-name", default="")

    reindex_cmd = sub.add_parser("reindex", help="重建向量索引")
    reindex_cmd.add_argument("--course-id", type=int, default=None)

    ev = sub.add_parser("eval-retrieval", help="检索效果评测")
    ev.add_argument("--course-id", type=int, default=1)

    args = parser.parse_args(argv)
    if args.command == "seed":
        asyncio.run(seed_demo())
    elif args.command == "create-user":
        asyncio.run(create_user(args.username, args.password, args.role, args.real_name))
    elif args.command == "reindex":
        asyncio.run(reindex(args.course_id))
    elif args.command == "eval-retrieval":
        asyncio.run(eval_retrieval(args.course_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
