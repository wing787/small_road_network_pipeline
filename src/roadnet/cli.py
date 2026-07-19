"""コマンドラインエントリポイント: download / convert / merge / load / all。

各層モジュールの薄いオーケストレーション。各サブコマンドは冪等で、単独でも
実行できる。``load`` は到達可能な PostGIS（compose.yaml 参照）を必要とする
ため、``all`` には含めていない。
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import Settings, get_settings
from .convert import convert_all
from .download import download_all
from .merge import merge_parts, merge_parts_to_flatgeobuf


def _sorted_paths(directory: Path, pattern: str) -> list[Path]:
    return sorted(directory.glob(pattern))


def cmd_download(settings: Settings) -> None:
    settings.ensure_dirs()
    paths = download_all(
        settings.mesh_zip_urls,
        settings.raw_dir,
        user_agent=settings.user_agent,
        timeout_seconds=settings.timeout_seconds,
        sleep_seconds=settings.sleep_seconds,
    )
    logging.info("download: %d mesh zip(s) available in %s", len(paths), settings.raw_dir)


def cmd_convert(settings: Settings) -> None:
    settings.ensure_dirs()
    zips = _sorted_paths(settings.raw_dir, "*.zip")
    if not zips:
        logging.error("convert: no zips in %s — run `download` first", settings.raw_dir)
        raise SystemExit(1)
    parts = convert_all(zips, settings.parts_dir)
    logging.info("convert: wrote %d part(s) to %s", len(parts), settings.parts_dir)


def cmd_merge(settings: Settings) -> None:
    settings.ensure_dirs()
    parts = _sorted_paths(settings.parts_dir, "*.parquet")
    if not parts:
        logging.error("merge: no parts in %s — run `convert` first", settings.parts_dir)
        raise SystemExit(1)
    total_pq = merge_parts(parts, settings.output_parquet_path)
    logging.info("merge: %d feature(s) -> %s", total_pq, settings.output_parquet_path)
    total_fgb = merge_parts_to_flatgeobuf(parts, settings.output_fgb_path)
    logging.info("merge: %d feature(s) -> %s", total_fgb, settings.output_fgb_path)
    if total_pq != total_fgb:
        logging.error(
            "merge: row count mismatch between outputs (parquet=%d, fgb=%d)",
            total_pq, total_fgb,
        )
        raise SystemExit(1)


def cmd_all(settings: Settings) -> None:
    cmd_download(settings)
    cmd_convert(settings)
    cmd_merge(settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roadnet",
        description=(
            "国土数値情報 N13-2024 道路データをダウンロード・変換し GeoParquet に結合する。"
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="DEBUG レベルのログを有効にする。"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download", help="メッシュ zip をダウンロードする（冪等）。")
    sub.add_parser("convert", help="各メッシュ zip を GeoParquet パートに変換する。")
    sub.add_parser("merge", help="パートを GeoParquet + FlatGeobuf にストリーム結合する。")
    sub.add_parser("load", help="パートを PostGIS にストリーム投入する（DB の起動が必要）。")
    sub.add_parser("all", help="download -> convert -> merge を実行する。")
    return parser


_COMMANDS = {
    "download": cmd_download,
    "convert": cmd_convert,
    "merge": cmd_merge,
    "all": cmd_all,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    _COMMANDS[args.command](settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
