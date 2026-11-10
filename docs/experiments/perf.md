# 性能压测报告（M6-3）

> 状态：**脚本与方案就绪，尚未在目标机器执行**。下表为待填模板，跑完后把 CSV 数据替换进来即可直接用于论文第 13 章。
> 之所以如实标注「未执行」，而不是编造数字：压测结论强依赖机器规格与部署形态，虚假数据在答辩追问下站不住脚。

## 1. 压测方案

| 项 | 取值 |
|---|---|
| 工具 | Locust 2.32+（`backend/tests/perf/locustfile.py`） |
| 被测形态 | 形态 A：`uvicorn` + SQLite + 本地向量（演示态）<br/>形态 B：`docker compose`（PG16 + Redis + Celery + Qdrant） |
| 流量模型 | 教师:学生 = 2:3；教师侧重课程列表/检索/题库/概览，学生侧重报告/试卷/会话 |
| 负载 | 50 并发用户，spawn rate 5/s，持续 3 分钟；再补 100 并发一轮观察拐点 |
| 指标 | RPS、P50/P95/P99、错误率、CPU/内存 |
| 观察重点 | `/search`（混合检索）、`/attempts/{id}/report`（聚合查询）、`/questions`（分页） |

```bash
# 形态 A
python -m app.cli seed --demo
uvicorn app.main:app --port 8000 --workers 1
locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000 \
       --headless -u 50 -r 5 -t 3m --csv docs/experiments/locust

# 形态 B（推荐，接近生产）
make dev && make migrate && make seed
locust -f backend/tests/perf/locustfile.py --host http://localhost:8000 \
       --headless -u 50 -r 5 -t 3m --csv docs/experiments/locust_pg
```

## 2. 结果（待填）

### 2.1 形态 A：SQLite + 本地向量 + mock LLM

| 接口 | RPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误率 |
|---|---|---|---|---|---|
| `POST /auth/login` | — | — | — | — | — |
| `GET /courses` | — | — | — | — | — |
| `GET /courses/{id}/documents` | — | — | — | — | — |
| `POST /search (hybrid)` | — | — | — | — | — |
| `GET /questions` | — | — | — | — | — |
| `GET /attempts/{id}/report` | — | — | — | — | — |
| **合计** | — | — | — | — | — |

### 2.2 形态 B：PG + Redis + Celery + Qdrant

| 接口 | RPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误率 |
|---|---|---|---|---|---|
| （同上表结构） | — | — | — | — | — |

### 2.3 拐点观察（100 并发）

| 指标 | 值 |
|---|---|
| 出现首个 P95 > 1s 的并发数 | — |
| 首个错误（429/超时）出现时间 | — |
| 瓶颈定位（CPU/DB/锁/限流） | — |

## 3. 已做的优化（无论压测是否执行，代码里都成立）

1. **检索缓存**：`retrieve(use_cache=True)` 命中进程内/Redis JSON 缓存，重复查询 < 50ms
2. **BM25 课程级 LRU + dirty 失效**：避免每次查询重建索引（`bm25_built` 日志可见构建次数）
3. **图编译单例**：三张 Agent 图在进程内只 `compile()` 一次
4. **审计日志独立连接池**：`llm_calls` 写入用 `AuditSessionLocal`（`busy_timeout=300`），不阻塞主流程
5. **SQLite WAL + `busy_timeout=8000`**：解决并发写 `database is locked`
6. **阅卷题目级并发**：`Semaphore(4)` 控制 LLM 并发，避免触发上游限流
7. **任务进度批量提交**：阅卷进度按题累加仅更新一次 job 行，减少写放大
8. **列表接口分页上限**：`size ≤ 100`，防止一次拉全表

## 4. 注意事项

- 演示语料只有 6 个分块，检索耗时几乎为常数，**该形态的 RPS 不能代表真实规模**；真实课件应至少 200+ 分块后重测
- `questions:generate` 受 `MAX_GENERATE_PER_HOUR` 限流，压测时应剔除或把权重降到最小
- SSE 接口是长连接，用 Locust 压会得到失真的连接数指标，建议另写 asyncio 客户端做首字延迟（TTFT）统计
