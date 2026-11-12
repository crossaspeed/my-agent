# 实验记录索引

本目录按"**问题 → 文档 → 原始数据**"组织。所有数字都来自实测，可由脚本离线复算；
数据文件只含 `chunk_id` / 区间 / 标题 / 分数，**不含课件正文**。

---

## 一、想快速了解结论，读这三份

| 顺序 | 文档 | 内容 |
|---|---|---|
| 1 | [`metrics-current.md`](metrics-current.md) | **当前生效配置的一页速查**：总体与分类别指标、残余错例、演进路径、场景化检索策略 |
| 2 | [`retrieval-upgrade.md`](retrieval-upgrade.md) | 第一轮：哈希伪向量 → BGE-M3 → 两阶段重排；含阈值重标定（第 11 节） |
| 3 | [`chunking.md`](chunking.md) | 第二轮：分块五档对比（按页 / 按标题 / 600 / 900 / 1200），峰值落在 700~750 字 |

配套两份方法学文档：

| 文档 | 用途 |
|---|---|
| [`annotation-guide.md`](annotation-guide.md) | **60 条标注怎么标的**：三条铁律、最少依据、防循环论证、分块变化后的 gold 迁移 |
| [`query-rewrite.md`](query-rewrite.md) | 查询改写实验：收益（Hit@3→1.00）与代价（误纳 15%→30%） |

---

## 二、演进时间线

```
① 原始实现（hash 向量）
      ↓  发现 relevance 恒为 1.0、拒答阈值形同虚设
② + P0 门禁（词表未登录率 + 相关度双条件）
      ↓  向量分数无判别力（0.02–0.23）
③ + BGE-M3 语义向量
      ↓  Hit@3 到 100%，但 Hit@1 仍低
④ + LLM listwise 重排
      ↓  换真实课件（4 份 PPT / 88 块 / 60 条标注）后重跑，暴露阈值过期
⑤ + 阈值重标定 0.35→0.55
      ↓  切块策略成为瓶颈（邻块命中占失败的三分之一）
⑥ + 分块 600/900 → 900/1200
      ↓  口语类仍是短板
⑦ + 查询改写（仅导学追问启用）
```

早期 ①②③ 是在**8 个分块的演示课程**上做的；④ 之后换到**用户真实的 4 份 PPT**，
两者样本不可直接横向比较，`retrieval-upgrade.md` 与 `metrics-current.md` 分别标注了各自口径。

---

## 三、文档清单

| 文件 | 阶段 | 说明 |
|---|---|---|
| `evaluation.md` | 早期 | 三份评测报告（M6-6）。**明确声明**：演示语料仅 6 块 + hash + mock，数字只证明链路正确 |
| `perf.md` | 早期 | 压测方案与模板。**如实标注"尚未执行"**，未编造数据 |
| `retrieval-upgrade.md` | 第 1 轮 | 阈值失效缺陷、饱和归一、双条件门禁、BGE-M3、重排四坑复盘、阈值扫描 |
| `chunking.md` | 第 2 轮 | 五档切块对比 + 开重排的 2×2 补测 |
| `query-rewrite.md` | 第 3 轮 | 改写收益与误纳代价、改写+阈值组合矩阵 |
| `metrics-current.md` | 汇总 | 当前指标速查 + 场景化检索策略（重排/改写按检索点取舍） |
| `annotation-guide.md` | 方法 | 标注规范与偏差控制 |
| `retrieval.csv` | 早期 | 10 条 query 的 top3 对比（演示语料） |

---

## 四、数据文件：60 条标注的实测结果

同一批 60 条 query（语料内 40 + 领域外 20）、同一门课。`rk` = 重排后端。

### 4.1 分块策略对比（均不开重排）

| 文件 | 分块 | 块数 | Hit@1 | Hit@3 | 误拒 | 误纳 | 静默 |
|---|---|---|---|---|---|---|---|
| `bench-course8-slide600.json` | 按页断开 | 421 | 0.100 | 0.400 | 0.000 | 0.700 | 24 |
| `bench-course8-heading600.json` | 按标题断开 | 233 | 0.425 | 0.650 | 0.025 | 0.550 | 14 |
| `bench-course8-size600.json` | 600 / 900 | 134 | 0.475 | 0.775 | 0.025 | 0.500 | 9 |
| `bench-course8-size900.json` | **900 / 1200** | **88** | **0.625** | **0.850** | 0.025 | 0.500 | **6** |
| `bench-course8-size1200.json` | 1200 / 1500 | 70 | 0.600 | 0.825 | 0.025 | 0.500 | 7 |

### 4.2 重排与阈值

| 文件 | 配置 | Hit@1 | Hit@3 | 误拒 | 误纳 | 静默 |
|---|---|---|---|---|---|---|
| `bench-course8-size900-rerank.json` | 900/1200 + LLM 重排，阈值 0.35 | 0.750 | 0.950 | 0.025 | 0.500 | 2 |
| **`bench-course8-final-llm-t055.json`** | **900/1200 + 重排 + 阈值 0.55（当前生效）** | **0.750** | **0.950** | **0.050** | **0.150** | **2** |
| `bench-course8-rewrite.json` | 上一行 + 查询改写 | 0.800 | 1.000 | 0.000 | 0.300 | 0 |

> `bench-course8-final-llm-t055.json` 是**唯一与当前 `.env` 配置一致的**结果文件。
> 其余文件用于"改前 vs 改后"的配对比较，不要当成当前水平。

### 4.3 标注集

| 文件 | 内容 |
|---|---|
| `cases-course8.csv` | **当前生效标注**（60 条，8 列含 `evidence`），gold 对齐 900/1200 档 |
| `cases-course8-size600.csv` | 600/900 档的旧标注（旧 id），留档用于演示 gold 迁移 |

### 4.4 分块区间快照 `ranges/`

字符区间快照（`id / document_id / chunk_index / char_start / char_end / slide_no / heading / filename`），
是 **gold 迁移与跨切法覆盖率比较的唯一依据**——因为 chunk id 每次重新解析都会变。

| 文件 | 对应档位 |
|---|---|
| `ranges/ranges-A-size600.json` | 600/900（改造前，**迁移源**） |
| `ranges/ranges-B-heading600.json` | 按标题断开 |
| `ranges/ranges-C-slide600.json` | 按页断开 |
| `ranges/ranges-D-size900.json` | 900/1200 |
| `ranges/ranges-E-size1200.json` | 1200/1500 |
| `ranges/ranges-current.json` | **当前生效配置** |

---

## 五、如何复算

```bash
# 1) 汇总表（任意份 bench JSON，统一口径）
python backend/scripts/bench_report.py docs/experiments/bench-course8-*.json

# 2) 阈值扫描（离线，不改配置、不重启）
python backend/scripts/threshold_sweep.py \
  docs/experiments/bench-course8-final-llm-t055.json --start 0.45 --end 0.65 --step 0.01

# 3) 重跑评测（需服务在跑）
docker compose cp docs/experiments/cases-course8.csv api:/tmp/cases.csv
docker compose cp backend/scripts/retrieval_bench.py api:/tmp/retrieval_bench.py
MSYS_NO_PATHCONV=1 docker compose exec -T api python /tmp/retrieval_bench.py \
  --cases /tmp/cases.csv --course-id 8 --rerank --out /tmp/bench.json
```

**三条口径约定**（避免"改口径让数字变好"）：

1. `silent_error` = 门禁放行但 top3 内无正确答案（两个脚本已统一为此定义）；
2. 跨切法比较用**字符覆盖口径**（返回块覆盖答案区间的 ≥50% 记为命中），不用各自 gold 上的命中率；
3. 门禁相关度取**候选集最大值**，与重排后的位置无关。

---

## 六、样本量提醒

60 条中，语料内 40 条 → 一条 = 2.5 个百分点；领域外 20 条 → 一条 = 5 个百分点。
**1~2 条的差异不构成结论**，只用于同口径下的方向性对照。换语料后必须重扫阈值、重标 query。
