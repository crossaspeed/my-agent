"""引用校验（防幻觉核心）单元测试。"""

from __future__ import annotations

from app.rag.citation import (
    best_matching_span,
    citation_coverage,
    lcs_ratio,
    normalize,
    verify_refs,
)
from app.rag.retriever import RetrievedChunk

CONTENT = (
    "三次握手过程中，客户端发送 SYN=1、序号 seq=x 的报文段，进入 SYN_SENT 状态。"
    "服务器回复 SYN=1、ACK=1、seq=y、ack=x+1，进入 SYN_RCVD 状态。"
    "客户端再发送 ACK=1、ack=y+1，双方进入 ESTABLISHED 状态。"
)


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=101,
        content=CONTENT,
        score=0.9,
        page_no=27,
        heading_path="第3章 传输层 > 3.2 TCP > 3.2.1 三次握手",
        document_id=3,
        document_name="第3章 传输层.pdf",
    )


def test_normalize_fullwidth_and_space():
    # 去空白 + 全角标点统一
    assert normalize("A  B，C") == "ab,c"
    assert normalize("三次握手 。") == "三次握手."


def test_verify_exact_quote_passes():
    refs = [{"chunk_id": 101, "quote": "服务器回复 SYN=1、ACK=1、seq=y、ack=x+1"}]
    outcome = verify_refs(refs, {101: _chunk()})
    assert outcome.ok
    assert outcome.fix_count == 0
    # 元数据必须由服务端（DB）覆盖
    assert outcome.refs[0]["page_no"] == 27
    assert outcome.refs[0]["document_name"] == "第3章 传输层.pdf"


def test_fabricated_chunk_id_rejected():
    refs = [{"chunk_id": 999, "quote": "随便编的一段话"}]
    outcome = verify_refs(refs, {101: _chunk()})
    assert not outcome.ok
    assert "不在本次检索结果" in (outcome.reason or "")


def test_quote_mismatch_rejected():
    refs = [{"chunk_id": 101, "quote": "TCP 使用 UDP 协议传输数据，不需要握手"}]
    outcome = verify_refs(refs, {101: _chunk()})
    assert not outcome.ok
    assert "引文与原文不符" in (outcome.reason or "")


def test_slight_rewrite_autofixed():
    # 模型在原文中插入连接词（轻微改写，非精确子串），应自动纠正为原文片段而不是整题丢弃
    quote = "服务器回复 SYN=1、ACK=1、seq=y、ack=x+1，随后进入 SYN_RCVD 状态"
    refs = [{"chunk_id": 101, "quote": quote}]
    outcome = verify_refs(refs, {101: _chunk()}, threshold=0.8)
    assert outcome.ok
    assert outcome.fix_count == 1
    assert outcome.refs[0]["quote"] in CONTENT


def test_empty_quote_rejected():
    outcome = verify_refs([{"chunk_id": 101, "quote": ""}], {101: _chunk()})
    assert not outcome.ok


def test_no_refs_rejected():
    outcome = verify_refs([], {})
    assert not outcome.ok


def test_lcs_ratio_and_span():
    ratio, matched = lcs_ratio("服务器回复 SYN=1", CONTENT)
    assert ratio > 0.8
    assert matched
    span = best_matching_span(CONTENT, "服务器回复 SYN=1、ACK=1", target_len=30)
    assert span
    assert span in CONTENT


def test_citation_coverage():
    assert citation_coverage([{"chunk_id": 1}, {"chunk_id": 1}, {"chunk_id": 2}]) == 2
