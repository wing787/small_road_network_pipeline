"""http_stats.py の純粋ヘルパーのテスト — DuckDB / ネットワーク不要。

サンプルの message は DuckDB 1.5.5 が実際に ``duckdb_logs`` へ出力した形（struct の
文字列化）を再現したもの。列1本だけ読むと footer + 該当列チャンクだけ Range GET され、
全体のごく一部しか転送しない、という挙動を最小構成で固定する。
"""

from __future__ import annotations

from roadnet.http_stats import parse_http_message, summarize_transfer

# HEAD: 全体サイズ 47,673,370 バイトを返すだけ（本文転送なし）。
_HEAD = (
    "{'request': {'type': HEAD, 'url': 'https://example/f.parquet', "
    "'headers': {User-Agent='duckdb/v1.5.5'}, 'request_body_length': NULL}, "
    "'response': {'status': OK_200, 'reason': OK, "
    "'headers': {Date='Thu, 06 Aug 2026 14:07:03 GMT', Content-Length='47673370'}}}"
)
# GET 206: footer（末尾 64KB）。
_GET_FOOTER = (
    "{'request': {'type': GET, 'url': 'https://example/f.parquet', "
    "'headers': {User-Agent='duckdb/v1.5.5', Range='bytes=47607834-47673369'}}, "
    "'response': {'status': PartialContent_206, "
    "'headers': {Content-Length='65536', "
    "Content-Range='bytes 47607834-47673369/47673370'}}}"
)
# GET 206: 1 列分のチャンク。
_GET_COLUMN = (
    "{'request': {'type': GET, 'url': 'https://example/f.parquet', "
    "'headers': {User-Agent='duckdb/v1.5.5', Range='bytes=23501754-24103593'}}, "
    "'response': {'status': PartialContent_206, "
    "'headers': {Content-Length='601840', "
    "Content-Range='bytes 23501754-24103593/47673370'}}}"
)


def test_parse_head_has_full_size_and_no_range() -> None:
    req = parse_http_message(_HEAD)
    assert req.method == "HEAD"
    assert req.status == "OK_200"
    assert req.range_header is None
    assert req.content_length == 47673370


def test_parse_get_extracts_range_and_bytes() -> None:
    req = parse_http_message(_GET_COLUMN)
    assert req.method == "GET"
    assert req.status == "PartialContent_206"
    assert req.range_header == "23501754-24103593"
    assert req.content_length == 601840
    assert req.total_size == 47673370


def test_summarize_sums_only_get_bytes() -> None:
    summ = summarize_transfer([_HEAD, _GET_FOOTER, _GET_COLUMN])
    assert summ.n_requests == 3
    assert summ.n_get == 2
    assert summ.get_bytes == 65536 + 601840  # HEAD は数えない
    assert summ.full_size == 47673370
    assert summ.fraction is not None
    assert summ.fraction < 0.02  # 全体の 2% 未満しか転送していない


def test_summarize_falls_back_to_content_range_when_no_head() -> None:
    summ = summarize_transfer([_GET_FOOTER, _GET_COLUMN])
    assert summ.full_size == 47673370  # HEAD 無しでも Content-Range の分母で補完


def test_fraction_is_none_without_size() -> None:
    empty = summarize_transfer([])
    assert empty.full_size is None
    assert empty.fraction is None
