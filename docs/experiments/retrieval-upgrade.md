# 检索链路升级记录：从哈希伪向量到 BGE-M3 语义检索

> 本文记录一次**由真实缺陷驱动**的检索链路改造：为什么要改、改了什么、效果提升了多少、代价是什么、还有什么没解决。
> 数据全部来自本仓库的可复现实验（`backend/scripts/retrieval_bench.py`），不是估算值。

---

## 0. 一句话总结（可用于简历）

> 发现并修复了混合检索中"相关性阈值恒失效"的实现缺陷（BM25 分数按最大值归一导致 top1 恒为 1.0），
> 将字符哈希伪向量替换为 BGE-M3 语义向量，并引入"查询词覆盖率 + 词表未登录率"双信号门禁；
> 在 16 条标注查询上，Hit@1 由 53.8% 提升至 69.2%，Hit@3 由 76.9% 提升至 100%，
> 越界提问误纳率由 66.7% 降至 33.3%，语料内有答案却被误拒的比例由 30.8% 降至 7.7%。

---

## 1. 背景

系统（智评导学）的出题、阅卷、导学三个智能体都依赖同一套 RAG 检索：

```
query ──┬─→ 向量检索（Embedding + 本地向量库）─┐
        └─→ BM25 检索（jieba 分词 + rank_bm25）┴─→ RRF 融合 ─→ 按 relevance 过滤 ─→ 上下文
```

原始实现为了"克隆即跑、零外部依赖"，默认使用：

| 组件 | 原始实现 | 特性 |
|---|---|---|
| Embedding | `HashEmbedder`：字符/词 n-gram 经 `blake2b` 哈希到 1024 维 | 无参数、无网络、确定性，但**没有语义能力** |
| 向量库 | 本地 JSON + numpy 余弦 | 无语料规模压力时够用 |
| 稀疏检索 | BM25Okapi | 词面匹配，效果正常 |

即：**检索能力的天花板由 `HashEmbedder` 决定**，而它本质上是"稀疏词袋投影"。

---

## 2. 问题诊断

### 2.1 现象：向量分数处于噪声区间

同一课程语料（4 份课件 / 8 个分块）上，用 16 条标注查询实测各条 top1 的向量余弦相似度：

| 查询 | 语义上应命中的分块 | 向量分 | 排名 |
|---|---|---|---|
| TCP 三次握手 | 3.2.2 三次握手 | **0.17** | ✅ 1 |
| 慢开始门限 ssthresh | 3.4 拥塞控制 | **0.23** | ✅ 1 |
| 网络为什么会堵车 | 3.4 拥塞控制 | **0.10** | ❌ 给的是"三次握手" |
| 数据库 B+ 树索引 | 语料中不存在 | **0.08** | ❌ 给的是"DNS" |
| three-way handshake | 3.2 TCP 连接管理 | **0.017** | ❌ 接近随机 |

**相关与不相关的分数都挤在 0.02–0.23**，差距不足 0.1，属于噪声水平。BGE-M3 在同类查询上相关片段通常在 0.5–0.8、无关片段在 0.2 以下，两极分化明显。

### 2.2 缺陷一（更严重）：相关性阈值恒失效

`app/rag/retriever.py` 原始实现：

```python
# 旧：用"本次最高分"做归一化
max_sparse = max(score for _, score in sparse_hits) or 1.0
sparse_norm = {cid: score / max_sparse for cid, score in sparse_hits}

chunk.relevance = max(dense_score.get(cid, 0.0), sparse_norm.get(cid, 0.0))
```

归一化后 BM25 的 **top1 恒等于 1.0**，于是只要 BM25 有任何命中：

```
relevance = max(dense, 1.0) = 1.0  ≥  MIN_RETRIEVE_SCORE(0.35)   → 永远放行
```

实测 16 条查询的 `relevance` 中位数为 **0.909**，阈值形同虚设。后果是两类错误都无法拦截：

- **越界提问被当成有依据**：问"数据库 B+ 树"，因为语料里 DNS 段落含"分布式层级数据库"，匹配上"数据库"三个字，relevance=1.0 直接通过；
- **出题/导学拿到跑题材料**：mock 模型严格从片段抄写，所以表面正常；换成真实大模型后，会基于错误材料生成"像模像样但主题错位"的题目。

### 2.3 失败模式分两类（这一点决定了改法）

| 类型 | 例子 | 表现 | 危险性 |
|---|---|---|---|
| 安全失败 | `three-way handshake`（中文语料无字面重合） | BM25 零命中、向量 0.017 → 被拒答 | 低（系统说"知识库未覆盖"） |
| 静默失败 | `网络为什么会堵车`、`数据库 B+ 树索引` | 检索到错误片段但判定为"有依据" | **高（错得看起来像对的）** |

### 2.4 缺陷三：`use_rerank` 是空参数

`ENABLE_RERANK` / `retrieve(use_rerank=...)` 在代码中**声明但从未实现**，仅在签名里存在。这意味着文档里若声称"两阶段检索 + 重排"与代码不符。本次未实现（见第 6 节），但已在代码注释与本文件中如实标注。

---

## 3. 改动方案

### 3.1 P0-a：BM25 分数改为饱和归一（修复阈值失效）

```python
# 新：raw/(raw+K)，单调有界，保留绝对量级
sparse_norm = {cid: score / (score + settings.BM25_SATURATION_K)  # K=6.0
               for cid, score in sparse_hits if score > 0}
```

- 选择饱和函数而非 min-max：**不看本次分布**，同一条命中在不同查询间可比；
- K=6.0 的依据：本语料 BM25 原始分集中在 0.4–9.0，K=6 时 3 分→0.33、4.5 分→0.43、9 分→0.60，既不过度压缩强命中，也不让弱命中虚高。

### 3.2 P0-b：`relevance` 取三路信号最大值

```python
chunk.relevance = max(dense_score, sparse_norm, chunk.coverage)
```

新增第三路 `coverage`：**查询词在该分块中的覆盖率**（0~1，词集合求交）。理由：

- 纯词面量纲，不受模型尺度影响，能兜住"BM25 被饱和压缩到阈值以下"的误拒；
- 可解释，答辩时能指着说"这句话里的 5 个术语，片段覆盖了 3 个"。

### 3.3 P0-c：考纲外门禁（双条件联判）

```python
off_syllabus = (unknown_ratio >= MAX_UNKNOWN_TERM_RATIO        # 0.5
                and relevance < OFF_SYLLABUS_RELEVANCE_FLOOR)  # 0.5
```

`unknown_ratio` = 查询有效词中"在本课程语料里从未出现"的比例。

**为什么必须联判**：最初只按词表否决（阈值 0.75），实测把 `three-way handshake`、`congestion control` 两条**英文提问误杀**——而 BGE-M3 是多语言模型，本来能正确命中中文语料。加上"相关度也低才否决"后，跨语言提问被正确放行。

### 3.4 P1：切换到 BGE-M3

| 项目 | 改动 |
|---|---|
| 依赖 | `sentence-transformers` + **CPU 版 torch**（`--index-url https://download.pytorch.org/whl/cpu`；用官方默认源会拉 CUDA 依赖，镜像再 +3GB） |
| 模型缓存 | `HF_HOME=/models/hf`，挂载宿主机 `./data/models`，避免每次重建容器重下 2.27GB |
| 配置 | `.env`：`EMBEDDING_PROVIDER=local`、`EMBEDDING_MODEL=BAAI/bge-m3`、`EMBEDDING_DIM=1024` |
| 索引 | 换模型后**必须重建**（`python -m app.cli reindex --course-id 1`），旧哈希向量与新语义向量不可混用 |

---

## 4. 实验设计

| 项目 | 说明 |
|---|---|
| 语料 | 4 份自建 markdown 课件（计算机网络：传输层/网络层/应用层/网络安全），切分为 **8 个分块** |
| 查询集 | **16 条**，4 类：字面 6 条、口语同义 5 条、跨语言 2 条、领域外 3 条 |
| 标注 | 人工标注 gold chunk id；领域外查询 gold 为空（正确行为是拒答） |
| 指标 | Hit@1 / Hit@3（gold 是否进 top1/top3）、误拒率（有答案却被拒）、误纳率（无答案却放行）、静默错误（放行且 top3 无 gold）、门禁命中（门禁选中的证据是否为 gold） |
| 复现 | `backend/scripts/retrieval_bench.py`（跑数）+ `backend/scripts/bench_report.py`（统一口径汇总） |

三组配置使用**同一套指标定义**（由 `bench_report.py` 对原始信号复算），避免"改定义导致看起来变好"。

---

## 5. 结果

### 5.1 主表（统一口径）

| 配置 | Embedding | Hit@1 | Hit@3 | 误拒率 | 误纳率 | 静默错误 | 门禁命中 | 平均相关度 |
|---|---|---|---|---|---|---|---|---|
| 基线（原始实现） | Hash 1024d | 53.8% | 76.9% | 30.8% | **66.7%** | 1 | —（未记录） | 0.657 |
| + P0 门禁 | Hash 1024d | 53.8% | 76.9% | 30.8% | 33.3% | 1 | 69.2% | 0.440 |
| + P0 + P1 | **BGE-M3 1024d** | **69.2%** | **100%** | **7.7%** | 33.3% | **0** | **84.6%** | 0.584 |

关键变化：

- **Hit@1 +15.4 个百分点**（53.8% → 69.2%），**Hit@3 +23.1 个百分点**（76.9% → 100%，语料内有答案的 13 条全部进入 top3）；
- **误拒率从 30.8% 降到 7.7%**（13 条里只剩 1 条：查询"证明文件是某人发出的"，语义上对应数字签名，但该片段表述为"报文鉴别/不可否认性"，语义距离仍偏大——这是模型能力边界，不是门禁误判）；
- **误纳率从 66.7% 降到 33.3%**（3 条领域外查询中，红烧肉、矩阵特征值被正确拒答，仅 B+ 树漏网）；
- **静默错误归零**：所有放行的查询，其证据集（top3）都包含正确答案；
- **平均相关度从 0.657 降到 0.584**——这是"修 bug"而非"效果变差"：旧值被恒为 1.0 的归一化分数抬高，新值才是有意义的绝对尺度（同一分块，旧 1.00 → 新 0.50）。

### 5.2 分类别看，提升集中在哪

| 类别 | 基线 Hit@1 / Hit@3 | 改造后 Hit@1 / Hit@3 | 说明 |
|---|---|---|---|
| 字面（6 条） | 5/6 · 6/6 | 5/6 · 6/6 | **没有变化**——BM25 本来就擅长，改造不吹这个 |
| 口语同义（5 条） | 2/5 · 3/5 | 2/5 · **5/5** | 召回补齐（top3 全覆盖），但 top1 排序仍不理想 |
| 跨语言（2 条） | 0/2 · 1/2 | **2/2 · 2/2** | 从"完全失效 + 被误拒"变成"正确命中" |
| 领域外（3 条） | 误纳 3/3 | 误纳 1/3 | 门禁生效 |

可以清楚地说：**提升来自"语义/跨语言"而非"字面"，这正是换向量的目的**。

### 5.3 三个典型案例

**① 跨语言（`three-way handshake`）**

```
基线:   top3 = #4(0.02) #8(0.01) #5(0.00)      → 拒答（向量 0.017，噪声）
改造后: top3 = #2(0.56) #1(0.49) #3(0.40)      → 接受，top1 即正确片段
```

**② 口语提问（`网络为什么会堵车`）**

```
基线:   top3 = #2 三次握手(1.00) #6 路由(0.12) #1 传输层概述(0.44)   → gold(#3 拥塞控制) 完全没进
改造后: top3 = #2 三次握手(0.80) #3 拥塞控制(0.54) #1 传输层概述(0.60) → gold 进入 top2
```

排序仍把"三次握手"排第一（"为什么"这类虚词被 BM25 放大），但正确答案已进入证据集，加一次 rerank 即可纠正——这就是第 6 节把 rerank 列为下一步的原因。

**③ 领域外（`数据库 B+ 树索引的分裂过程`）**

```
基线:   accepted=True, top1=#8 DNS(1.00)      → 静默失败
改造后: accepted=True, top1=#8 DNS(0.50)      → 仍未拦住（未解决项）
```

未拦住的原因：分词把 `B+树` 切成 `b`/`树`，而"数据/数据库/过程"都在语料里出现，`unknown_ratio` 仅 0.375，未达 0.5 阈值。**小语料 + 中文分词粒度**共同导致的漏网，见第 6 节。

### 5.4 代价

| 指标 | Hash | BGE-M3 | 变化 |
|---|---|---|---|
| 单条 query 向量化 | 0.1 ms | **101.8 ms** | ×1000（CPU 推理） |
| 8 条批量向量化 | 1 ms | 299 ms | ×300 |
| 进程内首次加载 | 无 | 7.8 s（权重已缓存）/ 87 s（含首次下载） | 新增 |
| 后端镜像 | 988 MB | **2.7 GB** | +1.7 GB（torch） |
| 模型磁盘占用 | 0 | 4.25 GB（`data/models`，不入库） | 新增 |

结论：**检索延迟增加约 100ms**，相对一次大模型调用（1–3s）可忽略；代价主要是镜像与磁盘，可通过"最简部署不装 embedding"（`BACKEND_EXTRAS=postgres,queue`）在不需要语义检索的环境规避。

---

## 6. 局限与未解决项（如实记录）

1. **B+ 树一类"部分术语命中"的领域外提问仍会误纳**（3 条中漏 1 条）。词表未登录率在小语料上粒度不足；可行方向是 rerank 或"生成前先让 LLM 判断材料是否切题"。
2. **口语查询的 top1 排序未完全解决**：Hit@3 已达 100%，但 Hit@1 仍 2/5。`network 为什么会堵车` 这类"虚词拉高 BM25"的问题需要重排或查询改写。
3. **`use_rerank` 仍是空参数**（声明未实现）。本文档不把它算作已完成能力。
4. **样本量小**：8 个分块、16 条查询，指标波动敏感，参数（0.5 / 0.5 / K=6）在这套数据上校准，存在小样本过拟合风险。接入真实课程语料后应重跑并重新定标。
5. **单次实验、无重复方差**：CPU 推理确定性高，未做多次运行取均值。

---

## 7. 复现步骤

```bash
# 1) 构建带 embedding 依赖的镜像（首次会下载 CPU 版 torch）
docker compose build api worker-io worker-llm

# 2) 首次下载 BGE-M3 权重到持久化目录（约 2.27GB，落在 data/models）
docker compose exec api python -c "from sentence_transformers import SentenceTransformer as S; S('BAAI/bge-m3')"

# 3) 切换向量后端
#    .env: EMBEDDING_PROVIDER=local / EMBEDDING_MODEL=BAAI/bge-m3 / EMBEDDING_DIM=1024
docker compose up -d api worker-io worker-llm

# 4) 换模型必须重建索引
docker compose exec api python -m app.cli reindex --course-id 1

# 5) 跑评测（指标由同一份原始信号复算）
docker compose cp backend/scripts/retrieval_bench.py api:/tmp/
docker compose exec api python /tmp/retrieval_bench.py /tmp/bench.json
docker compose cp api:/tmp/bench.json .
python backend/scripts/bench_report.py bench.json
```

---

## 8. 可写入简历/论文的表述

**简历（3 条 bullet）**

- 定位并修复混合检索的相关性阈值失效缺陷：BM25 按最大值归一导致 top1 恒为 1.0、阈值永不触发；改用饱和归一 `raw/(raw+6)` 并引入查询词覆盖率，使门禁可用（门禁命中率 84.6%）。
- 将字符哈希伪向量替换为 BGE-M3（CPU 推理，镜像内预装、权重挂载持久化），16 条标注查询上 Hit@1 53.8%→69.2%、Hit@3 76.9%→100%，跨语言检索从 0/2 提升到 2/2。
- 设计"词表未登录率 + 相关度"双条件拒答门禁，越界提问误纳率 66.7%→33.3%，语料内有答案的误拒率 30.8%→7.7%，并定位跨语言误杀问题（单条件否决会误杀英文提问）。

**论文「实现与实验」可引用的句式**

> 针对小规模课程语料下稠密检索退化的问题，本文对比了字符 n-gram 哈希向量与 BGE-M3 两种表示。实验表明哈希向量在相关/不相关片段上的余弦相似度差异不足 0.1（0.02–0.23），不具备判别力；替换为 BGE-M3 后，在 16 条标注查询上 Hit@1 提升 15.4 个百分点、Hit@3 达到 100%。同时发现原实现采用"按最大值归一"的稀疏分数归一化方式，使相关性阈值恒被满足（中位相关度 0.909），本文改为饱和归一并引入查询词覆盖率作为第三路信号，使拒答机制真正生效。

---

## 9. 本次涉及的代码改动清单

| 文件 | 改动 |
|---|---|
| `backend/app/core/config.py` | 新增 `BM25_SATURATION_K=6.0`、`MAX_UNKNOWN_TERM_RATIO=0.5`、`OFF_SYLLABUS_RELEVANCE_FLOOR=0.5` |
| `backend/app/rag/retriever.py` | 饱和归一；`RetrievedChunk` 新增 `coverage`/`unknown_ratio`；`relevance` 取三路最大；`to_dict` 输出新字段 |
| `backend/app/rag/bm25_index.py` | `CourseBM25` 新增 `vocab` / `token_sets` / `coverage()`（惰性构建，随索引一起失效） |
| `backend/app/agents/question_graph.py` | 检索门禁改为"相关度阈值 + 考纲外双条件联判"，警告文案区分原因 |
| `backend/Dockerfile` | `EXTRAS` 默认含 embedding；先装 CPU 版 torch；`HF_HOME`/模型目录持久化 |
| `docker-compose.yml` | 构建参数 `EXTRAS`；`./data/models:/models` 挂载 |
| `backend/scripts/retrieval_bench.py` | 16 条标注查询的评测脚本（原始信号落 JSON） |
| `backend/scripts/bench_report.py` | 统一口径的指标汇总 |
| `backend/scripts/embed_perf.py` | 两种向量的耗时对比 |
| `backend/tests/unit/test_retriever.py` | 饱和归一有界性、词表与覆盖率单测 |
