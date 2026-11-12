"""结构感知分块单元测试。"""

from __future__ import annotations

from app.rag.chunker import ChunkConfig, chunk_segments, chunk_stats
from app.rag.parsers.base import Segment


def _cfg(**kwargs) -> ChunkConfig:
    base = {"target_chars": 120, "max_chars": 200, "min_chars": 40, "overlap_chars": 20}
    base.update(kwargs)
    return ChunkConfig(**base)


def test_heading_path_stack():
    segs = [
        Segment(text="第3章 传输层", kind="title", style={"level": 1}, page_no=1),
        Segment(text="3.2 TCP", kind="title", style={"level": 2}, page_no=1),
        Segment(text="三次握手用于同步初始序号并确认收发能力。" * 5, page_no=1),
        Segment(text="3.3 拥塞控制", kind="title", style={"level": 2}, page_no=2),
        Segment(text="慢开始阶段拥塞窗口按指数增长直到达到门限。" * 5, page_no=2),
    ]
    chunks = chunk_segments(segs, _cfg())
    assert chunks
    # 标题文本保留在块内容里（利于检索），但块的章节归属以正文为准
    assert chunks[0].content.startswith("第3章 传输层")
    assert chunks[0].heading_path == "第3章 传输层 > 3.2 TCP"
    handshake = [c for c in chunks if "三次握手" in c.content]
    assert handshake and handshake[0].heading_path == "第3章 传输层 > 3.2 TCP"
    assert any(c.heading_path == "第3章 传输层 > 3.3 拥塞控制" for c in chunks)


def test_overlap_between_chunks():
    long_text = "这是一句用于测试重叠逻辑的正文内容。"
    segs = [Segment(text=long_text * 40, page_no=1)]
    chunks = chunk_segments(segs, _cfg(target_chars=150, overlap_chars=30))
    assert len(chunks) >= 2
    assert all(len(c.content) <= 260 for c in chunks)


def test_table_kept_whole():
    table = "| 字段 | 含义 |\n| --- | --- |\n" + "\n".join(
        f"| 字段{i} | 描述{i} |" for i in range(5)
    )
    segs = [
        Segment(text="表格前后的正文内容需要保持完整。" * 3, page_no=1),
        Segment(text=table, kind="table", page_no=1),
    ]
    chunks = chunk_segments(segs, _cfg())
    assert any(c.meta.get("is_table") and "| 字段0 |" in c.content for c in chunks)


def test_short_chunks_merged():
    segs = [
        Segment(text="短句一。", page_no=1),
        Segment(text="短句二。", page_no=1),
        Segment(text="短句三。", page_no=1),
    ]
    chunks = chunk_segments(segs, _cfg(min_chars=200))
    assert len(chunks) == 1


def test_chunk_stats_warning():
    segs = [Segment(text="短" * 10, page_no=1), Segment(text="长" * 400, page_no=1)]
    chunks = chunk_segments(
        segs, _cfg(target_chars=1000, max_chars=2000, min_chars=1, overlap_chars=0)
    )
    stats = chunk_stats(chunks)
    assert stats["count"] == len(chunks)
    assert stats["heading_ratio"] == 0


def _two_slides() -> list[Segment]:
    return [
        Segment(text="第一页讲的是分块边界的意义。" * 6, slide_no=1, page_no=1),
        Segment(text="第二页讲的是另一个独立知识点。" * 6, slide_no=2, page_no=2),
    ]


def test_size_boundary_still_merges_across_slides():
    """默认 size 模式必须保持旧行为：长度够就跨页合并。"""
    cfg = _cfg(target_chars=300, max_chars=400, min_chars=10)
    chunks = chunk_segments(_two_slides(), cfg)
    assert len(chunks) == 1


def test_slide_boundary_splits_pages():
    cfg = _cfg(target_chars=300, max_chars=400, min_chars=10, boundary="slide")
    chunks = chunk_segments(_two_slides(), cfg)
    assert len(chunks) == 2
    assert chunks[0].slide_no == 1 and chunks[1].slide_no == 2
    # 结构边界不沿用上一块的尾部重叠，否则相邻块内容近似、检索难以区分
    assert not chunks[1].meta.get("overlap_prefix")


def test_heading_boundary_splits_sections():
    segs = [
        Segment(text="3.1 封装成帧", kind="title", style={"level": 1}, page_no=1),
        Segment(text="帧首部和帧尾部用于帧定界。" * 6, page_no=1),
        Segment(text="3.2 差错检测", kind="title", style={"level": 1}, page_no=1),
        Segment(text="循环冗余检验只能做到无差错接受。" * 6, page_no=1),
    ]
    chunks = chunk_segments(segs, _cfg(boundary="heading"))
    assert len(chunks) == 2
    assert chunks[0].heading_path == "3.1 封装成帧"
    assert chunks[1].heading_path == "3.2 差错检测"


def test_boundary_merge_does_not_cross_section():
    """过短块的向后合并也不能跨节，否则边界等于没切。"""
    segs = [
        Segment(text="3.1 小节标题", kind="title", style={"level": 1}, page_no=1),
        Segment(text="很短的一句。", page_no=1),
        Segment(text="3.2 另一个标题", kind="title", style={"level": 1}, page_no=1),
        Segment(text="另一句也很短。", page_no=1),
    ]
    chunks = chunk_segments(segs, _cfg(boundary="heading", min_chars=200))
    assert len(chunks) == 2

