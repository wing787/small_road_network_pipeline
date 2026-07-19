"""roadnet: 国土数値情報 道路データ N13-2024 の MVP パイプライン。

メッシュ zip をダウンロード → 各 zip を GeoParquet に変換 → 1つの GeoParquet に結合。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
