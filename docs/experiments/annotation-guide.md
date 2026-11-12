# 检索评测标注手册

本文件说明 `cases-course8.csv`（60 条人工标注查询）是怎么标出来的、为什么这样标，
以及换语料后如何沿用同一套方法。**它是评测数据的"使用说明"，不含任何课件正文。**

---

## 一、评测对象

| 项 | 值 |
|---|---|
| 课程 | 计算机网络2（`course_id=8`，教师自建） |
| 语料 | 4 份 PPTX：数据链路层 / 网络层 / 运输层 / 应用层 |
| 分块 | 随切块策略变化：600/900 档 134 块，**当前 900/1200 档 88 块** |
| 查询 | **60 条**：语料内 40 + 领域外 20 |
| 指标 | Hit@1 / Hit@3 / 误拒率 / 误纳率 / 静默错误 / 门禁命中 |

> 分块 id 是**全库自增**且每次重新解析都会变（曾出现 308–441、1487 起等多套）。
> 因此 `gold` **只在"当前这套分块"上有效**，换分块必须重新映射（见第六节）。

---

## 二、三条铁律

**1. `gold` 只能填 `document_chunks.id`。**
不要填 `chunk_index`（每份文档从 0 开始的本地序号）。填错会让所有查询被判为未命中，
而指标会呈现"系统完全不可用"的假象。

**2. 先写 query，再找 gold。**
顺序反了就是循环论证——系统答什么你就标什么，指标必然接近 100%。
更隐蔽的错误是：**读过全文再写 query**，会不自觉地复用原文措辞，使字面重合虚高。

**3. `gold` 按「最少依据」标：离了它就答不出这个问题。**
自检问法：把这块拿掉，还能不能回答？不能 → 保留；能 → 删掉，它只是背景。

> 反面案例（真实发生过）：「网络为什么会堵车」最初标 `400/401/402`，但那三块讲的是
> **"怎么控制拥塞"**（慢开始、拥塞避免），而不是**"为什么会堵"**。
> 按最少依据改为给出"需求超过资源 → 产生拥塞"定义的两块，并把"举例说明"那块补进来。
> 这正是"主题相关 ≠ 能回答问题"——**标 gold 要按答案类型判，不能按关键词圈。**

---

## 三、8 列含义

| 列 | 填写要求 |
|---|---|
| `category` | 五选一：`字面` / `口语` / `跨语言` / `例题` / `领域外` |
| `query` | 一句像人说的话；不要写"请根据课件回答"；不要把答案写进问题 |
| `gold` | 分块 id；多值写 `"1487,1488"`（**带英文引号**）；领域外**必须留空** |
| `doc` | 主要依据所在文档：`ch3` / `ch4` / `ch5` / `ch6` |
| `source` | 真实提问 / 自己写 / 标题构造 / 原文改写 / 翻译 / 模型起草 |
| `transform` | 相对原文改了什么，如 `拥塞→堵车`；未改写留空 |
| `evidence` | **该块中能支撑答案的原话**（手工摘录，20~60 字），复核时只看这一列 |
| `note` | 附加说明：歧义、标题不可靠、是否需重写 |

CSV 编码为 **UTF-8 with BOM**：Excel/WPS 直接打开不乱码，程序读取需 `encoding="utf-8-sig"`。
多值 `gold` 必须加英文双引号，否则会被拆成多列（全角逗号 `，` 不算分隔符）。

---

## 四、配额与分布

| category | 条数 | 作用 |
|---|---|---|
| 字面 | 15 | 用课件原术语提问，基线，不该出错 |
| 口语 | 15 | 学生口吻（"堵车""处理不过来""先对暗号"），**最能暴露问题** |
| 跨语言 | 10 | 中英混写或纯英文（`three-way handshake`） |
| 领域外 | 20 | **必须最多**，用于测误纳率；含邻近学科（B+ 树、进程调度）与完全无关（红烧肉） |
| 例题 | 0 | 需要时再加 10 条，针对课件中的例题块 |

**为什么领域外必须最多**：误纳率的分母就是它。3 条领域外时，一条错就是 33.3 个百分点，
统计上毫无意义；20 条时一条错约 5 个百分点，才谈得上比较。

---

## 五、如何避免"自己证明自己"

这是全套数据最容易被质疑的地方，四条纪律：

1. **口语类必须由人独立撰写**。模型起草的口语题仍带教材腔，等于把字面类换了层皮；
2. **冻结评测集**：`cases-course8.csv` 一旦用于出数，就不再改。发现 gold 标错要记一次修订并说明改了哪几条；
3. **保留一个无偏子集**：即使部分 query 由模型起草，也至少留 15~20 条完全人工独立写的，单独算一遍指标。两个子集差距大，说明起草带偏置——**这个对比本身可以写进论文**；
4. **不要边看检索结果边改 gold**。若某条 gold 是通过"看系统返回才发现漏了"而补上的，必须标注为污染样本，不能静默修改。

---

## 六、分块变了，gold 怎么办

改 `CHUNK_BOUNDARY` / `CHUNK_TARGET_CHARS` 并重新解析后，分块 id 全变、旧标注失效。
`backend/scripts/remap_cases.py` 用 chunker 记录的 `char_start/char_end` 做区间交叠，自动迁移：

```bash
# 1) 改造前导出区间快照（只需一次，已归档在 docs/experiments/ranges/）
python scripts/remap_cases.py --course-id 8 --dump-out /tmp/ranges-old.json

# 2) 重新解析后迁移 gold
python scripts/remap_cases.py --course-id 8 \
  --old docs/experiments/ranges/ranges-A-size600.json \
  --cases docs/experiments/cases-course8.csv --out /tmp/cases-new.csv
```

实测 60 条中 **40 条 gold 变化、0 条失败**，无需重标。

> 迁移会改变"命中难度"：切细后一条旧 gold 会拆成 2~3 块，`top1 ∈ gold` 变容易。
> 所以**跨切法比较不能只看各自 gold 上的命中率**，要用字符覆盖率口径（见 `chunking.md`）。

---

## 七、已知弱点（如实记录）

1. **query 由模型起草**：字面 / 跨语言 / 领域外三类是模型按标题与正文起草的，
   虽已做同义替换（`transform` 列有记录），仍存在语料—查询同源偏置；口语类已标注需人工重写；
2. **gold 曾受系统输出影响**：两处 gold（动态地址转换、交换机查表转发）是在看检索结果时
   发现"可能漏了"的，**未擅自修改**，记录待人工按原文确认；
3. **样本量**：60 条、单门课，每个百分点约 0.4 条 query，**1~2 条的差异不构成结论**；
4. **只测检索**：不反映出的题质量、讲解正确性、阅卷一致性，那些需要另设评估。

---

## 八、跑评测

```bash
docker compose cp docs/experiments/cases-course8.csv api:/tmp/cases.csv
docker compose cp backend/scripts/retrieval_bench.py api:/tmp/retrieval_bench.py

# 基线（不开重排）
MSYS_NO_PATHCONV=1 docker compose exec -T api python /tmp/retrieval_bench.py \
  --cases /tmp/cases.csv --course-id 8 --out /tmp/bench.json

# 开重排 / 开改写
MSYS_NO_PATHCONV=1 docker compose exec -T api python /tmp/retrieval_bench.py \
  --cases /tmp/cases.csv --course-id 8 --rerank --rewrite --out /tmp/bench-rr.json

# 取回并按统一口径汇总
docker compose cp api:/tmp/bench.json docs/experiments/bench-local.json
python backend/scripts/bench_report.py docs/experiments/bench-local.json
```

输出含 `by_category` 分类别指标，能看出"口语差还是字面差"，不只是一个总分。
