"""对比 hash 与 bge-m3 的向量化开销（论文"代价"一栏的数据来源）。"""

import asyncio
import time

from app.core.config import settings
from app.rag.embedder import HashEmbedder, get_embedder

TEXTS = [
    "TCP 三次握手的 SYN 和 ACK 标志位分别起什么作用",
    "慢开始门限 ssthresh 是怎么变化的",
    "滑动窗口 rwnd 如何实现流量控制",
    "RIP 与 OSPF 的区别是什么",
    "NAT 与 NAPT 的作用",
    "DES 和 AES 属于对称加密算法吗",
    "两台主机开始对话之前为什么要先对暗号",
    "网络为什么会堵车",
]
CHUNK = (
    "拥塞控制由慢开始、拥塞避免、快重传和快恢复四个算法组成。慢开始阶段拥塞窗口 cwnd 从 1 个 MSS 开始，"
    "每经过一个传输轮次就翻倍增长，呈指数上升；当 cwnd 达到慢开始门限 ssthresh 后进入拥塞避免阶段。"
)


async def bench(embedder, label: str) -> None:
    await embedder.embed_documents([CHUNK])  # 预热（首次含模型加载）
    t0 = time.perf_counter()
    for text in TEXTS:
        await embedder.embed_query(text)
    query_ms = (time.perf_counter() - t0) / len(TEXTS) * 1000

    t0 = time.perf_counter()
    await embedder.embed_documents(TEXTS)
    batch_ms = (time.perf_counter() - t0) * 1000
    print(
        f"{label}: query_avg={query_ms:.1f}ms/条  batch={batch_ms:.0f}ms/{len(TEXTS)}条"
        f"  dim={embedder.dim}"
    )


async def main() -> None:
    print("provider=", settings.EMBEDDING_PROVIDER)
    await bench(HashEmbedder(), "hash    ")
    if settings.EMBEDDING_PROVIDER != "hash":
        t0 = time.perf_counter()
        real = get_embedder()
        load_s = time.perf_counter() - t0
        print(f"bge-m3 进程内首次加载: {load_s:.1f}s")
        await bench(real, "bge-m3  ")


asyncio.run(main())
