# 系统架构与流程（论文配图源文件）

> 全部图表使用 Mermaid，可在 Typora / VS Code / GitHub 直接渲染；导出 PNG 后即可贴入论文。

## 1. 分层架构

```mermaid
flowchart TB
    subgraph Client["客户端"]
        B["浏览器 SPA<br/>React 18 + AntD 5"]
    end

    subgraph Access["接入层"]
        NG["Nginx<br/>静态资源 + /api 反代<br/>SSE proxy_buffering off"]
    end

    subgraph App["应用层 FastAPI"]
        direction TB
        RT["api/v1/* 路由<br/>参数校验 · 权限装配 · 信封包装"]
        SV["services/*<br/>业务编排 · 事务边界"]
        AG["agents/*<br/>出题官 / 阅卷官 / 导学师<br/>StateGraph 运行时"]
        RG["rag/*<br/>解析 · 清洗 · 分块 · 混合检索 · 引用校验"]
        WK["workers/*<br/>任务注册表 · Celery / 线程池"]
    end

    subgraph Data["数据与依赖层"]
        DB[("PostgreSQL / SQLite<br/>17 张表")]
        VS[("Qdrant / Chroma / 本地 JSON 向量库")]
        RD[("Redis / 进程内缓存")]
        LLM["LLM 服务<br/>deepseek · qwen · glm · mock"]
        FS[("课件文件存储")]
    end

    B -->|HTTPS / SSE| NG
    NG --> RT
    RT --> SV
    SV --> AG
    SV --> RG
    SV --> WK
    SV --> DB
    RT --> DB
    RG --> VS
    RG --> DB
    AG --> LLM
    WK --> RD
    WK --> DB
    SV --> FS
```

设计约束：

- 路由层零业务逻辑；层间只传 Pydantic 模型（禁止裸 dict）
- 每个外部依赖都有降级实现（见 README「降级矩阵」）
- 长耗时操作（解析/出题/阅卷）一律异步任务化，接口只返回 `job_id`

## 2. 部署拓扑

```mermaid
flowchart LR
    U["用户浏览器"] -->|8080| WEB["web 容器<br/>Nginx + 静态包"]
    WEB -->|/api| API["api 容器<br/>uvicorn ×1"]
    API --> PG[("postgres:16")]
    API --> RE[("redis:7")]
    API --> QD[("qdrant:1.12<br/>profile: qdrant")]
    API -->|USE_CELERY=true| RE
    W1["worker-io 容器<br/>解析/向量化 (Q=io)"] --> RE
    W2["worker-llm 容器<br/>出题/阅卷/导学 (Q=llm)"] --> RE
    W1 --> PG
    W2 --> PG
    W1 -->|读写| VOL[("./data/uploads · /data/vectors")]
    API --> VOL
    FL["flower<br/>profile: ops"] --> RE
```

单机演示可直接 `uvicorn` + `vite dev`（SQLite + 本地向量 + mock LLM），不需要上面任何容器。

## 3. 数据模型（ER）

```mermaid
erDiagram
    users ||--o{ courses : owns
    users ||--o{ course_members : joins
    courses ||--o{ course_members : has
    courses ||--o{ knowledge_points : defines
    knowledge_points ||--o{ knowledge_points : parent_of
    courses ||--o{ documents : contains
    documents ||--o{ document_chunks : splits_into
    document_chunks ||--o{ chunk_knowledge_points : tagged
    knowledge_points ||--o{ chunk_knowledge_points : tags
    courses ||--o{ questions : has
    questions ||--o{ question_knowledge_points : covers
    knowledge_points ||--o{ question_knowledge_points : covered_by
    courses ||--o{ papers : has
    papers ||--o{ paper_questions : composed_of
    questions ||--o{ paper_questions : used_in
    papers ||--o{ attempts : attempted
    users ||--o{ attempts : takes
    attempts ||--o{ answers : records
    questions ||--o{ answers : answered
    answers ||--o{ tutor_sessions : triggers
    users ||--o{ tutor_sessions : asks
    tutor_sessions ||--o{ tutor_messages : contains
    users ||--o{ jobs : creates
    users ||--o{ llm_calls : produces
```

关键字段（与 `app/db/models/` 一致）：

| 表 | 关键字段 | 说明 |
|---|---|---|
| `documents` | `status(pending/parsing/ready/failed)`、`sha256`、`chunk_count`、`meta` | sha256 去重；`meta.ocr_pages` 标记扫描页 |
| `document_chunks` | `content`、`page_no`、`heading_path`、`token_count`、`meta` | 向量库只存 id，原文永远以 DB 为准 |
| `questions` | `type`、`answer`、`rubric`、`source_refs(JSON)`、`quality(JSON)`、`status` | `source_refs` 是防幻觉核心证据 |
| `answers` | `student_answer(JSON)`、`score`、`rubric_detail`、`error_tags`、`needs_human`、`confidence` | 主观题要点式给分明细 |
| `jobs` | `task_id`、`progress`、`stage`、`attempts`、`heartbeat_at`、`payload` | 前端轮询；超时可重试 |
| `llm_calls` | `scene`、`model`、`prompt_ver`、`latency_ms`、`tokens`、`success` | 论文性能章节数据源 |

## 4. 出题官时序

```mermaid
sequenceDiagram
    autonumber
    participant T as 教师
    participant API as API
    participant W as worker-llm
    participant G as 出题图
    participant R as 检索器
    participant L as LLM
    participant DB as DB
    participant V as 引用校验

    T->>API: POST /courses/{id}/questions:generate
    API->>DB: 校验课程/权限/知识点覆盖度/限流
    API->>DB: create job(pending) → 返回 job_id
    API-->>T: 202 {job_id}
    W->>G: 执行 question_generate
    G->>R: plan 后按知识点检索原文（混合 RRF）
    R-->>G: [chunk_id, content, 页码, 标题路径]
    G->>L: 提示词 + 原文片段（[CHUNK id] 编号）
    L-->>G: 题目草稿 JSON（含 source_refs）
    G->>G: validate_drafts（按题型严格校验）
    G->>V: verify_refs(草稿, 本次检索集合)
    alt 引文轻微改写
        V-->>G: 用原文片段自动纠正（记 fix_count）
    else chunk_id 不在集合 / 匹配度过低
        V-->>G: 拒绝 → 触发 repair 重生成（有上限）
    end
    G->>L: score_quality（答案是否被证据支撑）
    G->>DB: 入库 draft/pending + 回填 DB 元数据
    W->>DB: job progress 5→…→100，result={created,rejected}
    T->>API: GET /jobs/{task_id}
    API-->>T: {status, progress, stage, result}
```

## 5. 阅卷官时序

```mermaid
sequenceDiagram
    autonumber
    participant S as 学生
    participant API as API
    participant W as worker-llm
    participant G as 阅卷图
    participant L as LLM
    participant DB as DB

    S->>API: POST /attempts/{id}:submit（幂等）
    API->>DB: attempt.status=submitted（已提交则直接返回）
    API->>W: 提交 grade_attempt 任务
    API-->>S: {status, job_id}
    W->>G: 逐题并发（Semaphore=4）
    alt 客观题 single/multiple/judge
        G->>G: grade_objective（空答/少选/多选边界）
    else 主观题 short/essay
        G->>L: 抽取学生答案要点
        G->>DB: 检索该题评分细则/原文
        G->>L: 要点逐项给分 + 反馈 + 错因标签
        G->>L: temperature=0 复评（一致性）
        G->>G: 差值>15% 取均值；极差>30% 或校验失败 → needs_human
    end
    G->>DB: 写 answers(score/rubric_detail/error_tags/confidence)
    W->>DB: 汇总 attempt.total_score、status=graded、job 完成
    S->>API: GET /attempts/{id}/grading-status（1.5s 轮询）
    API-->>S: {graded, total, progress}
    S->>API: GET /attempts/{id}/report
    API-->>S: 总分/得分率/逐题/知识点掌握度/错因统计
```

## 6. 导学师时序（SSE）

```mermaid
sequenceDiagram
    autonumber
    participant S as 学生
    participant API as API
    participant G as 导学图
    participant R as 检索器
    participant L as LLM
    participant DB as DB

    S->>API: POST /tutor/sessions {course_id, question_id}
    API->>DB: 建会话并先 commit（避免长事务锁库）
    API->>G: 首轮讲解
    G->>DB: 加载题目/学生作答/阅卷错因
    G->>G: diagnose（判定错在哪一步）
    G->>R: 检索对应知识点原文
    G->>L: 讲解提示词 + 原文（流式）
    API-->>S: 返回开场讲解 + refs + practice
    S->>API: POST /tutor/sessions/{id}/messages（SSE）
    API-->>S: event: meta {session_id, message_id}
    loop 逐 token
        G-->>API: delta
        API-->>S: event: token {delta}
    end
    API-->>S: event: refs {refs, practice, diagnosis}
    API->>DB: 落库 assistant 消息 + refs
    API-->>S: event: done {message_id, content, refs}
    Note over API,S: 异常时 event: error（含 partial，前端可保留已收内容并重试）
```

## 7. 混合检索流程

```mermaid
flowchart LR
    Q["query"] --> A["向量检索<br/>top_k × 2"]
    Q --> B["BM25 检索<br/>jieba 分词"]
    A --> F["RRF 融合<br/>score = Σ 1/(k+rank)"]
    B --> F
    F --> T{"最高分 ≥<br/>MIN_RETRIEVE_SCORE?"}
    T -- 否 --> NC["返回空 → 上层提示<br/>「知识库未覆盖」"]
    T -- 是 --> E["相邻块扩展<br/>（可选）"]
    E --> OUT["RetrievedChunk[]<br/>含页码/标题路径/相关度"]
```
