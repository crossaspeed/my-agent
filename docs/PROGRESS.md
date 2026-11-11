# 开发进度与偏离记录（PROGRESS）

> 依据《开发计划-多智能体自主测评与导学系统》第 15 章任务卡推进。
> 状态：✅ 已完成 ｜ 🟡 已完成但实现方式有偏离（见「偏离记录」）｜ ⬜ 未做（见「已知技术债」）

最近更新：本轮交付（后端全链路 + 前端全站 + 部署产物 + 文档）。测试结果：**89 passed, 1 skipped**（`pytest -q`），`ruff check` 零告警，`npm run build` 通过。

---

## M0 工程骨架

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M0-1 | monorepo、pyproject、ruff 配置 | ✅ | `backend/pyproject.toml`，`ruff check app tests` → All checks passed |
| M0-2 | `core/config.py` + `.env.example` 全量字段 | ✅ | `Settings` 校验 `SECRET_KEY` ≥32、生产环境额外校验；`.env.example` 逐项注释 |
| M0-3 | 模型 + 首个 Alembic 迁移 | ✅ | `alembic upgrade head` 建出 17 张表（逐字段对齐第 6 章，另加 `jobs.payload`、`answers.needs_human/confidence`、`document_chunks.meta`） |
| M0-4 | `main.py`：CORS / 异常 handler / trace / health | ✅ | 统一 `{code,message,data}` 信封；`X-Trace-Id`；`/health` 返回依赖健康 |
| M0-5 | docker-compose + 后端多阶段 Dockerfile | ✅ | 已在 Docker Desktop（29.9.3 / Compose v5.7.0）实机跑通：6 个服务全部 `(healthy)`，一次性 `migrate` 服务自动执行 alembic，`seed --demo` 在容器内生成演示数据 |
| M0-6 | 前端脚手架 + 布局壳 + axios 客户端 | ✅ | Vite+TS+AntD+Router+Query+Zustand；`npm run build` 通过 |
| M0-7 | `cli.py seed` | ✅ | `python -m app.cli seed --demo` 一条命令产出课程/课件/题库/试卷/作答/报告 |

## M1 认证与课程

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M1-1 | 注册/登录/me/改密 | ✅ | bcrypt(12) + JWT(HS256)；`tests/unit/test_security.py`、`tests/integration/test_auth_course.py` |
| M1-2 | `deps.py` 角色守卫 | ✅ | `require_role` / `TeacherUser`；越权 403 有集成测试（含建课越权、跨教师课程隔离） |
| M1-3 | 课程 CRUD + 成员管理 | ✅ | 学生仅见已加入课程；`add_members` 批量用户名 |
| M1-4 | 知识点树 CRUD | ✅ | 递归 `KnowledgePointOut.children`；另加 `knowledge-points:auto` 从课件标题结构抽取 |
| M1-5 | 登录页 / 课程列表 / 工作台四 Tab | ✅ | `pages/Login.tsx`、`pages/Courses.tsx`、`pages/course/CourseWorkbench.tsx` |

## M2 知识库与检索

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M2-1 | 上传（白名单/大小/sha256 去重/落盘） | ✅ | 重复上传返回 `duplicated=true` + 同 doc_id；文本文件整段解码避免多字节截断 |
| M2-2 | `Segment`/`ParseResult`/`BaseParser` | ✅ | `app/rag/parsers/base.py` |
| M2-3 | PDF 解析器 | 🟡 | 页眉页脚 y-band 去重、`find_tables`→markdown、扫描页记 `ocr_pages`；**未接 OCR** |
| M2-4 | PPTX 解析器 | ✅ | 一页一段 + 备注 + 表格 |
| M2-5 | DOCX + MD/TXT 解析器 | ✅ | `test_parsers.py` 覆盖四类 |
| M2-6 | 清洗规则链 | 🟡 | 实现 9 条规则（计划书写 8 条）；`clean_ratio` 指标可用于论文统计 |
| M2-7 | 结构感知分块 | ✅ | 标题栈 `heading_path`、表格整块保护、句级重叠；块的章节归属以正文为准（本轮修正） |
| M2-8 | 分块落库 + 文档状态机 | ✅ | `pending→parsing→ready/failed`，启动时 `reconcile_stuck_documents` 兜底 |
| M2-9 | Embedder 抽象 + 双实现 | ✅ | `hash`（默认，无网络）/`api`（OpenAI 兼容）/`local`（BGE-M3，**已实机**：CPU torch + 权重挂载持久化 + 2.27GB 下载实测）|
| M2-10 | VectorStore 抽象 + Chroma/Qdrant | 🟡 | 三实现齐全，**默认走 `local`（JSON+numpy）**；Chroma/Qdrant 未实机验证（本机无 Docker、未装可选依赖） |
| M2-11 | 任务队列 + `parse_document` 分阶段进度 | 🟡 | 分阶段 5/40/60/75/95 已实现；默认 **进程内线程池**，Celery 代码路径已写但未实机跑通 |
| M2-12 | BM25（课程级 LRU + dirty） | ✅ | jieba + rank_bm25；删除/重解析时 `invalidate` |
| M2-13 | 混合检索 RRF + `/search` 调试接口 | ✅ | `rrf_fuse(k=60)`；本轮修复「相关性阈值恒失效」并加考纲外门禁，指标见 `docs/experiments/retrieval-upgrade.md`（Hit@1 53.8%→69.2%、Hit@3 76.9%→100%）|
| M2-14 | 上传区/文档列表/进度条/原文抽屉 | ✅ | `DocumentsTab.tsx` + `TaskProgress` + 分块预览抽屉（含关键词检索、分页） |

## M3 出题官

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M3-1 | `LLMClient`（超时/重试/JSON/埋点/熔断） | ✅ | tenacity + 信号量 + 熔断器 + json-repair；审计写 `llm_calls`（独立连接池） |
| M3-2 | 提示词注册表 + 模板 + 校验测试 | ✅ | 7 个 `v1.md` 模板；`test_prompts.py` 校验占位符 |
| M3-3 | 状态定义 + 严格校验 | ✅ | `validators.py` 按题型校验（单选必须 4 选项且答案在选项内等），rubric 分数归一 |
| M3-4 | 引用三关校验 | ✅ | 伪造 chunk_id 100% 拒；轻微改写自动纠正（本轮升级为「最长公共子串 + 锚点窗口块级对齐」） |
| M3-5 | 出题闭环 plan→retrieve→draft→validate→verify→repair | ✅ | `question_graph.py`，修复轮次上限后仍失败则丢弃 |
| M3-6 | 出题任务 + `questions:generate` | ✅ | 任务进度与结果 `{created,rejected}` 可查 |
| M3-7 | 溯源元数据 DB 回填 | ✅ | 页码/文档名/标题路径一律取自 DB，不信任模型输出 |
| M3-8 | 重复题检测 | ✅ | embedding 相似度 >0.92 标记重复 |
| M3-9 | 题库 + 审核 API | ✅ | 单条/批量审核；`review-queue` |
| M3-10 | 出题抽屉 + 审核页（quality 徽标 + CitationCard） | ✅ | `QuestionsTab.tsx`（含批量审核、溯源按钮） |
| M3-11 | 题库表格 + `QuestionEditor` | ✅ | 选项/答案/要点/解析可视化编辑 |

## M4 阅卷官与测评

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M4-1 | 组卷（manual/auto，kp 覆盖 + 难度配比 + 总分） | ✅ | 分值 0.5 粒度归一；自动组卷按知识点覆盖 + 题型配额贪心 |
| M4-2 | 发布 + 学生端剥离答案 | ✅ | 剥离发生在 **service 层**（`get_paper_for_student`），非前端隐藏 |
| M4-3 | 开始/草稿/提交（幂等） | ✅ | `start_attempt` 幂等；重复提交返回既有状态（集成测试断言） |
| M4-4 | 客观题规则判分 | ✅ | 空答、多选少选/多选、判断题边界有单测 |
| M4-5 | 主观题三步评分 + 一致性复核 | ✅ | 要点抽取→逐点评分→temperature=0 复评；极差 >30% 或差值 >15% 转人工 |
| M4-6 | 整卷并发阅卷（Semaphore=4） | ✅ | 单题异常隔离，写 `needs_human` |
| M4-7 | 报告 API（总分/逐题/掌握度/错题本） | ✅ | 另加 `course_id`（本轮补充，供前端一键唤起导学） |
| M4-8 | 作答页（导航/自动保存/倒计时/标记） | ✅ | `Exam.tsx` + `ExamTimer`，600ms 防抖存草稿 |
| M4-9 | 报告页（雷达/逐题反馈/错题卡片） | ✅ | `Report.tsx` + `ScoreRadar`（纯 SVG，无图表库） |
| M4-10 | 班级成绩 + 人工改分 | 🟡 | 班级成绩抽屉已做（提交人数/均分/极值/明细）；**人工改分接口未实现** |

## M5 导学师

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M5-1 | 导学图 load_context→diagnose→retrieve→explain→cite_check→practice | ✅ | `tutor_graph.py`，含追问分支 |
| M5-2 | SSE 四类事件 | ✅ | `event: meta/token/refs/done/error`；实测首字 ~0.3s（mock），Nginx 关闭缓冲 |
| M5-3 | 多轮追问（历史窗口） | ✅ | `HISTORY_WINDOW=10`；摘要压缩未做（见技术债） |
| M5-4 | 会话与消息持久化 | ✅ | 创建会话先 commit 再调模型，避免长事务锁库 |
| M5-5 | 推荐练习（同 kp 未做 2 道） | ✅ | `practice` 字段随 `refs` 事件下发 |
| M5-6 | 对话页（流式/Markdown/溯源/练习） | ✅ | `Tutor.tsx` + `useSSE`（fetch 流式解析，因后端为 POST+Header 鉴权） |
| M5-7 | 错题一键进入导学 | ✅ | 报告页按钮 → `POST /tutor/sessions`（question_id + course_id） |

## M6 加固与交付

| 卡号 | 任务 | 状态 | 证据 |
|---|---|---|---|
| M6-1 | 检索缓存 + 图编译单例 + 幂等 | ✅ | 检索结果 JSON 缓存（Redis/内存）；图 `compile()` 单例 |
| M6-2 | 连接池/索引调优 | 🟡 | SQLite WAL + `busy_timeout`、审计写走独立连接池（解决 `database is locked`）；PG 的 EXPLAIN 与分析未做（本机无 PG） |
| M6-3 | Locust 压测 + 报告 | 🟡 | 脚本就绪（`backend/tests/perf/locustfile.py`），**未在目标机器执行**，`docs/experiments/perf.md` 留了待填表 |
| M6-4 | 单测 + 集成主链路 | ✅ | 89 passed / 1 skipped；8 组单元 + 3 组集成（含 SSE 断言） |
| M6-5 | Playwright E2E | ⬜ | 未做，前端以手动黄金路径 + 集成测试覆盖后端链路 |
| M6-6 | 三份评测报告 | 🟡 | 检索评测已产出真实 CSV；出题/评分一致性报告给出方法与模板（受限于 mock 模型，数值不可作为结论） |
| M6-7 | 架构图/时序图/ER 图 | ✅ | `docs/architecture/README.md`（mermaid，可直接渲染或贴图） |
| M6-8 | README + 演示数据 | ✅ | README 覆盖安装/启动/架构/降级矩阵；`seed --demo` 即演示快照（**录屏未做**） |
| M6-9 | PROGRESS + 已知问题 | ✅ | 本文件 |

---

## 偏离记录（重要，论文「实现说明」可直接引用）

1. **Python 3.13 而非 3.11**
   环境仅有 3.13.14。已确认依赖全部兼容；`pyproject` 仍声明 `>=3.11`，Docker 镜像固定 `python:3.12-slim`（3.13 的预编译轮子生态尚不完整）。

2. **自研图运行时替代 LangGraph**
   `app/agents/graph_runtime.py` 实现 `StateGraph` / reducer / 条件边 / `compile()`，API 形态与 LangGraph 对齐（`langgraph` 保留在可选依赖 `[agents]`）。原因：目标机器无法稳定安装重型依赖，而三张图必须可单测、可画流程图；后续替换成本接近零。

3. **任务队列默认走进程内线程池**
   `USE_CELERY=false` 时 `workers/runner.py` 用 `ThreadPoolExecutor`，任务注册表、进度、失败重试语义与 Celery 路径一致。Celery 侧（`celery_app.py` + `celery_tasks.py`，队列 `io`/`llm`、`acks_late`、`max_tasks_per_child`）已按计划书写好，仅未实机验证。

4. **向量库默认本地实现**
   `local_store`（JSON 元数据 + numpy 余弦 + 进程内缓存）在无语料规模压力时足够，且让「零依赖启动」成立；Chroma/Qdrant 实现保留，`VECTOR_BACKEND` 一行切换。

5. **Embedding 默认哈希向量**
   字符 n-gram 哈希 → 固定维度向量，确定性、无网络、可离线跑通全链路测试；它只有词面召回能力，因此论文中检索指标需在切换 `api`/`local` 后重测（README 已注明）。

6. **Mock LLM 参与真实链路**
   `app/adapters/mock/mock_llm.py` 解析提示词里的 `[CHUNK id | header]` 块，用真实片段拼装题干与引文，因此**引用校验、去重、阅卷、SSE 全部是真实代码路径**，只有「文本质量」是模拟的。这让无网络环境下也能完整演示与回归测试。

7. **分块章节归属规则修正**
   原实现把标题段落装进块内、`heading_path` 取块首标题（父级路径），导致「正文属于 3.2 节但元数据只有第 3 章」。现改为：标题文本仍保留在块内容中（利于召回），但块归属升级为**首段正文所在章节**，元数据更精确，也更利于按知识点过滤。

8. **引文匹配度算法增强**
   仅用「最长公共子串 / len(quote)」会低估「插入连接词」这类轻微改写（实测 0.67 被误杀）。现改为取「最长公共子串比」与「锚点窗口块级对齐匹配比」的较大值，阈值策略不变；被接受后引文仍会被替换成原文片段，不放松防幻觉要求。

9. **SQLite 并发写锁**
   审计日志（`llm_calls`）与主流程共用连接时高并发会 `database is locked`。已拆分独立 `AuditSessionLocal`（`busy_timeout=300`、失败仅 debug 日志），主库开启 WAL + `busy_timeout=8000`。

10. **教师角色守卫前移到路由层**
    `POST /courses` 原仅依赖 `CurrentUser`（由 service 内部判断），越权用例暴露了漏洞。现改为 `TeacherUser` 依赖，403 由框架统一返回，与 M1-2 的验收口径一致。

11. **容器启动补了 `migrate` 一次性服务**
    原编排把 `AUTO_CREATE_TABLES` 设为 false，却没人执行 `alembic upgrade head`，容器起来就是"表不存在"。现加 `migrate` 服务（带 30 次重试），api / worker 通过 `service_completed_successfully` 等它成功；迁移失败会直接阻断启动，而不是留一个报错的半成品。

12. **Celery 任务注册缺失（实机才暴露）**
    `registry.load_all()` 只装载任务实现，`tasks/celery_tasks.py` 里带 `@celery_app.task` 的薄封装从未被导入，worker 启动日志的 `[tasks]` 段是空的，投递后一律 `Received unregistered task`。已在 `celery_app.py` 末尾显式导入该模块（放在 `load_all()` 之后避免循环导入）。这类问题单靠单测（线程池路径）无法发现。

13. **卡住任务的确定性回收**
    消息丢失时 `jobs` 永远 pending、文档永远停在 pending/parsing，前端无限转圈。`reconcile_stuck_documents` 重写为按「任务缺失 / pending 超时 / running 心跳超时」重新入队（同文档最多 3 次），超过则标记失败并给出可读原因；另加 `reconcile_stale_jobs` 处理出题/阅卷/重建索引这类不可安全重投的任务，直接判失败提示重试。

14. **前端 lock 文件指向私有源**
    `package-lock.json` 里 214 个依赖的 `resolved` 全是你本机的 `packages.aliyun.com` 私有源，容器内无凭据 → `npm ci` 401。已改为 `registry.npmjs.org`（路径与完整性哈希不变），使镜像可复现构建。

15. **相关性阈值恒失效（实机评测才暴露）**
    `sparse_norm = score / max_score` 使 BM25 的 top1 恒为 1.0，`relevance` 随之为 1.0，`MIN_RETRIEVE_SCORE` 永不触发（实测 16 条查询的 relevance 中位数 0.909）。改为饱和归一 `raw/(raw+K)`（K=6）并把"查询词覆盖率"纳入 `relevance` 取最大，阈值才具备绝对尺度。

16. **Embedding 从哈希升级为 BGE-M3**
    哈希向量在相关/不相关片段上的余弦差异不足 0.1（0.02–0.23），无语义判别力。镜像改为预装 CPU 版 torch（官方默认源会拉 CUDA，+3GB），权重缓存到挂载卷 `./data/models`；切换后强制 `reindex`。代价：镜像 988MB→2.7GB、单条 query 向量化 0.1ms→101.8ms。

17. **两阶段重排落地（含四个被数据打回的直觉）**
    补齐了此前只有声明、没有实现的 `use_rerank`，改为 `RERANK_BACKEND=off|cross|llm`，调用点声明场景取舍。
    过程中先后踩到：① `chat_json` 返回 `(dict, LLMResult)` 元组，当成 dict 用会静默空结果；② 把重排分合进
    `relevance` 使越界提问误纳率 33%→100%（sigmoid 对无关样本≈0.5）；③ 交叉编码器无信息量时仍排序，使
    Hit@3 100%→92.3%，加"最高分<0.55 则回退"后恢复；④ 重排后又按 `relevance` 二次排序把结果覆盖掉。
    最终结论：cross 后端在本语料零增益，llm 后端把 Hit@1 提到 100%（1.17s/2208 tokens per 次）。

18. **考纲外门禁必须与相关度联判**
    最初只用"查询词未登录率 ≥0.75"否决，实测把 `three-way handshake`、`congestion control` 两条英文提问误杀（BGE-M3 本来已正确命中中文语料）。改为「未登录率 ≥0.5 **且** 相关度 <0.5」双条件后，跨语言提问正确放行，越界提问误纳率 66.7%→33.3%。

19. **后台任务跨事件循环复用数据库连接（解析 PPTX 失败的真实原因）**
    现象：一次上传 4 个 PPTX，前两个解析成功（21 / 29 分块），后两个失败，job 记录
    `Task <Task pending ... run_job() ...> got Future ... attached to a different loop`。
    根因：Celery（prefork）与线程池的执行方式都是「一个任务一次 `asyncio.run`」，每次新建事件循环；
    而任务入口用的是全局 `AsyncSessionLocal`，asyncpg 连接在创建时已绑定旧循环，复用即报错——
    所以同一子进程的**第一个任务成功、之后全挂**。同类隐患还有两处：全局 LLM 客户端内的
    `asyncio.Semaphore` 绑定首次使用的循环；`llm_calls` 审计用全局引擎，失败后被 except 吞掉，
    导致审计静默丢数据。
    修复：新增 `db/base.py: task_session()`（每任务新建引擎 + NullPool + 用完 dispose），
    解析/出题/阅卷/重建索引（含并发的 `_grade_one`）统一改用；`get_llm_client()` 改为按事件循环
    缓存（WeakKeyDictionary）；审计改用 `task_session(busy_timeout=300)`。
    说明：该缺陷**只在 Celery + PostgreSQL 下出现**，本地 sqlite + 线程池的单测无法复现——
    这也是"必须有真机集成验证"的又一个例证。

20. **本地向量库并发写覆盖 + 索引跨进程不刷新**
    一次上传 4 个 PPTX（Celery 并发 2）后，doc5 的 29 个分块向量凭空消失：两个 worker 各持
    整份字典的内存副本、`_flush` 整体写回，后写者覆盖先写者。同时"刚上传的课件搜不到"——
    向量库 `_matrix()` 命中缓存后不再看文件、BM25 缓存 TTL 10 分钟且 `invalidate` 只作用于
    当前进程。修法：写入路径统一「跨进程文件锁 + 强制重载 + 原子写回」；`_matrix` 先按
    mtime+size 探一次文件；BM25 缓存命中时校验 `(分块数, 最大 id)` 签名。
    另修 nginx 只在启动时解析上游域名导致「api 健康但 502」：改用 Docker 内置 DNS
    （`resolver 127.0.0.11`）按请求解析。这三处都只在"多进程 + 容器"环境暴露，
    单进程 sqlite 测试无法复现。

---

## 已知技术债

优先级从高到低：

1. **仍未实机验证**：Chroma/Qdrant 运行态、Playwright E2E、Locust 压测、PG 连接池与 EXPLAIN。
   （Docker 全栈、Celery 双队列、PG + Alembic 迁移、Nginx 反代下的 SSE、本地 BGE-M3 向量均已实机验证通过。）
2. **LLM 重排的成本与稳定性**：两阶段重排已实现（`RERANK_BACKEND=off|cross|llm`），但唯一有效的是 `llm`
   后端，每次约 1.17s / 2208 tokens；出题 19 个知识点会多花约 20s，导学因首字延迟显式关闭。
   后续可考虑"先用 cross 粗排、仅在低置信时升级到 llm"的分级策略以降本。
3. **考纲外门禁仍漏"部分术语命中"**：`数据库 B+ 树索引`这类查询因分词命中"数据库/过程"而 unk 仅 0.375，未被拦截；需 rerank 或生成前 LLM 切题判定。
2. **人工改分（M4-10 P1）**：目前只能整卷重跑阅卷，教师无法对单题改分并重算总分。
3. **多轮对话摘要压缩**：当前只截取最近 10 条，长会话会丢早期信息。
4. **OCR**：扫描版 PDF 只记录 `ocr_pages` 提示，不提取文字。
5. **演示语料规模**：2 份 markdown、6 个分块，检索指标不足以支撑规模结论；接真实课件后需重跑 `make eval`。
6. **前端体验细节**：无 SSR、无骨架屏细粒度优化、无移动端专项适配；图表为手写 SVG（好处是无额外依赖，代价是交互能力弱于 ECharts）。
7. **可观测性**：只有结构化日志 + `llm_calls` 统计，未接 Prometheus/OpenTelemetry。
