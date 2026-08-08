"""DuckDB httpfs の HTTP アクセスログ（``duckdb_logs``）を集計する純粋ヘルパー。

用途: GeoParquet を S3 から読むとき、DuckDB が Range GET で「ファイルのどれだけ」を
実際に転送したかを測る（M3 タスク1）。DuckDB は ``CALL enable_logging('HTTP')`` で
リクエストごとの行を ``duckdb_logs`` に残すが、``message`` 列は正規 JSON ではなく
struct を文字列化したもの（キーが無引用、``OK_200`` のような非 JSON 値を含む）。
ここではその文字列から必要な数値だけを正規表現で取り出し、転送量に畳み込む。

この層は I/O を持たない（DuckDB 接続もネットワークも触らない）。呼び出し側が集めた
``message`` 文字列のリストを渡す形にすることで、ログ解析ロジックを DB 無しで単体テスト
できる（I/O と純粋変換の分離）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# message 例（改行なしの1行、抜粋）:
#   {'request': {'type': GET, ..., 'headers': {User-Agent='duckdb/v1.5.5',
#     Range='bytes=23501754-24103593'}, ...},
#    'response': {'status': PartialContent_206, ...,
#     'headers': {Content-Length='601840',
#       Content-Range='bytes 23501754-24103593/47673370', ...}}}
_TYPE_RE = re.compile(r"'type':\s*(\w+)")
_STATUS_RE = re.compile(r"'status':\s*(\w+)")
# 要求側の Range ヘッダ（bytes の直後が '='）。応答の Content-Range（bytes の直後が空白）
# には一致しないので取り違えない。
_RANGE_RE = re.compile(r"Range='?bytes=([0-9\-]+)")
_CONTENT_LENGTH_RE = re.compile(r"Content-Length='?(\d+)")
# Content-Range の分母（= ファイル全体サイズ）。HEAD が取れないときの保険。
_CONTENT_RANGE_TOTAL_RE = re.compile(r"Content-Range='?bytes [0-9\-]+/(\d+)")


@dataclass(frozen=True)
class HttpRequest:
    """1回の HTTP リクエスト/レスポンスから抜き出した要点。"""

    method: str  # "HEAD" / "GET" など
    status: str  # "OK_200" / "PartialContent_206" など
    range_header: str | None  # 例 "47607834-47673369"（Range 無しなら None）
    content_length: int | None  # 応答本文のバイト数（= このリクエストの転送量）
    total_size: int | None  # Content-Range の分母（全体サイズ、分かれば）


def parse_http_message(message: str) -> HttpRequest:
    """``duckdb_logs.message`` の1行を ``HttpRequest`` に変換する。"""
    t = _TYPE_RE.search(message)
    s = _STATUS_RE.search(message)
    r = _RANGE_RE.search(message)
    cl = _CONTENT_LENGTH_RE.search(message)
    cr = _CONTENT_RANGE_TOTAL_RE.search(message)
    return HttpRequest(
        method=t.group(1) if t else "?",
        status=s.group(1) if s else "?",
        range_header=r.group(1) if r else None,
        content_length=int(cl.group(1)) if cl else None,
        total_size=int(cr.group(1)) if cr else None,
    )


@dataclass(frozen=True)
class TransferSummary:
    """1つの問いに対する転送量サマリ。"""

    n_requests: int  # HTTP リクエスト総数（HEAD 含む）
    n_get: int  # GET の数
    get_bytes: int  # GET 応答の Content-Length 合計（= 実転送量）
    full_size: int | None  # ファイル全体サイズ（HEAD 優先、無ければ Content-Range から）

    @property
    def fraction(self) -> float | None:
        """全体に対して実際に転送した割合（full_size 不明なら None）。"""
        if not self.full_size:
            return None
        return self.get_bytes / self.full_size


def summarize_transfer(messages: Iterable[str]) -> TransferSummary:
    """HTTP ログ message 群を、転送量サマリに畳み込む。"""
    reqs = [parse_http_message(m) for m in messages]
    n_get = sum(1 for q in reqs if q.method == "GET")
    get_bytes = sum(q.content_length or 0 for q in reqs if q.method == "GET")

    # 全体サイズ: HEAD 応答の Content-Length を最優先。無ければ Content-Range の分母。
    full_size: int | None = None
    for q in reqs:
        if q.method == "HEAD" and q.content_length:
            full_size = q.content_length
            break
    if full_size is None:
        totals = [q.total_size for q in reqs if q.total_size]
        full_size = max(totals) if totals else None

    return TransferSummary(
        n_requests=len(reqs),
        n_get=n_get,
        get_bytes=get_bytes,
        full_size=full_size,
    )
