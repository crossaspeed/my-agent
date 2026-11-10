"""清洗规则链单元测试（对应计划书 8.3 的 9 条规则）。"""

from __future__ import annotations

from app.rag.cleaner import (
    clean_segments,
    dedupe_identical,
    detect_repeated_texts,
    drop_noise,
    drop_toc,
    merge_broken_lines,
    normalize_whitespace,
    remove_page_numbers,
    strip_control_chars,
)
from app.rag.parsers.base import Segment


def test_strip_control_chars():
    segs = [Segment(text="正常\x00文本\x07内容")]
    out = strip_control_chars(segs)
    assert out[0].text == "正常文本内容"


def test_remove_page_numbers():
    segs = [
        Segment(text="第 3 页"),
        Segment(text="Page 12 of 30"),
        Segment(text="- 15 -"),
        Segment(text="正文内容不应被删除"),
    ]
    out = remove_page_numbers(segs)
    assert [s.text for s in out] == ["正文内容不应被删除"]


def test_detect_repeated_texts_watermark():
    segs = []
    for page in range(1, 6):
        segs.append(Segment(text="内部资料 请勿外传", page_no=page))
        segs.append(Segment(text=f"第{page}页的正文内容", page_no=page))
    repeated = detect_repeated_texts(segs)
    assert "内部资料 请勿外传" in repeated
    assert len(repeated) == 1


def test_merge_broken_lines():
    segs = [
        Segment(text="TCP 通过序号、确认与超时重传实现可靠传输，" * 2, page_no=1),
        Segment(text="并通过滑动窗口实现流量控制。", page_no=1),
    ]
    out = merge_broken_lines(segs)
    assert len(out) == 1
    assert out[0].text.endswith("并通过滑动窗口实现流量控制。")


def test_merge_keeps_bullet_lines_separate():
    segs = [
        Segment(text="步骤如下所示，请按顺序执行操作，" * 2, page_no=1),
        Segment(text="- 第一步：建立连接", page_no=1),
    ]
    out = merge_broken_lines(segs)
    assert len(out) == 2


def test_normalize_whitespace():
    segs = [Segment(text="a\u3000 b\t\tc\n\n\n\nd")]
    out = normalize_whitespace(segs)
    assert out[0].text == "a b c\n\nd"


def test_dedupe_identical():
    segs = [
        Segment(text="重复出现的段落内容，长度足够", page_no=1),
        Segment(text="重复出现的段落内容，长度足够", page_no=1),
        Segment(text="另一段内容，长度也足够", page_no=1),
    ]
    out = dedupe_identical(segs)
    assert len(out) == 2


def test_drop_noise():
    segs = [
        Segment(text="短"),
        Segment(text="这是一段足够长的正文内容，不会被当作噪声丢弃"),
        Segment(text="表格", kind="table"),
    ]
    out = drop_noise(segs)
    assert [s.text for s in out] == ["这是一段足够长的正文内容，不会被当作噪声丢弃", "表格"]


def test_drop_toc():
    toc = [Segment(text=f"{i}. 章节标题 ........... {i * 3}") for i in range(1, 7)]
    body = [Segment(text="这是正文第一段，内容足够长不会被当成噪声")]
    out = drop_toc(toc + body)
    assert len(out) == 1


def test_clean_segments_pipeline_stats():
    raw = [
        Segment(text="计算机网络", page_no=1, kind="title",
                style={"is_title": True, "level": 1}),
        Segment(text="第 1 页", page_no=1),
        Segment(text="传输层为应用进程提供逻辑通信服务，并通过端口号实现复用与分用。" * 2, page_no=1),
        Segment(text="\x00坏字符", page_no=1),
    ]
    cleaned, stats = clean_segments(raw)
    assert cleaned
    assert 0 < stats.clean_ratio <= 1.0
    assert stats.removed_page_numbers == 1
    assert stats.raw_chars > stats.clean_chars
