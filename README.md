# small_road_network_pipeline

A **minimum working** data pipeline that downloads 国土数値情報 道路データ
**N13-2024**, converts each mesh to **GeoParquet**, and stream-merges the parts
into a single nationwide-style GeoParquet.

This is a learning / portfolio project. Scope is deliberately small: the target
mesh URLs are hard-coded (no scraping), and the pipeline runs on 3 tiny meshes
by default.

## Data source / 出典

> 「国土数値情報（道路データ N13-2024）」（国土交通省）
> https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N13-2024.html
>
> This product uses the 国土数値情報 (National Land Numerical Information) and is
> processed by the author. Redistribution of the data is subject to the
> 国土数値情報 terms of use.

**What the raw data looks like** (verified against real downloads, 2026-07):

| Property | Value |
| --- | --- |
| Distribution unit | one zip per 1-次メッシュ (4-digit primary mesh) |
| Contents of each zip | one `*.geojson` (UTF-8) + a `KS-META-*.xml` |
| Geometry | `LineString` (road centerlines) |
| CRS | **JGD2011 geographic, EPSG:6668** (lon/lat) |
| Attributes | `N13_001` … `N13_008` (see mapping below) |

Attribute mapping applied in `convert.py` (per the N13 product spec):

| Source | Normalized name | Meaning |
| --- | --- | --- |
| `N13_001` | `registration_date` | データ登録日 |
| `N13_002` | `road_type` | 種別 |
| `N13_003` | `road_classification` | 道路分類 |
| `N13_004` | `road_status` | 道路状態 |
| `N13_005` | `layer_order` | 階層順（地表からの上下関係） |
| `N13_006` | `width_category` | 幅員区分 |
| `N13_007` | `toll_category` | 有料区分 |
| `N13_008` | `secondary_mesh_code` | 二次メッシュ番号 |

`convert.py` also adds a `source_mesh` column (the 4-digit mesh code taken from
the zip filename) so every feature is traceable to its origin file.

### Default meshes

The three smallest meshes nationwide are used by default (5–66 KB each), so the
demo is fast and polite to the source server:

| Mesh | URL | zip size | features |
| --- | --- | --- | --- |
| 3631 | `.../N13-24/N13-24_3631_GEOJSON.zip` | ~5 KB | 19 |
| 3724 | `.../N13-24/N13-24_3724_GEOJSON.zip` | ~22 KB | 620 |
| 3622 | `.../N13-24/N13-24_3622_GEOJSON.zip` | ~66 KB | 800 |

Override the list via the `ROADNET_MESH_ZIP_URLS` env var or a `.env` file.

## Install

Requires **Python 3.12+** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

```bash
uv run roadnet all         # download -> convert -> merge
# or step by step:
uv run roadnet download    # -> data/raw/*.zip     (idempotent; skips existing)
uv run roadnet convert     # -> data/parts/*.parquet
uv run roadnet merge       # -> data/output/roads_all.parquet + roads_all.fgb
```

`merge` produces **two** outputs from the same parts:

| File | Format | Why |
| --- | --- | --- |
| `data/output/roads_all.parquet` | GeoParquet | columnar analytics (DuckDB, pandas, cloud) |
| `data/output/roads_all.fgb` | FlatGeobuf | built-in spatial index — QGIS streaming display, bbox-filtered reads |

Read the results:

```python
import geopandas as gpd

gdf = gpd.read_parquet("data/output/roads_all.parquet")
print(len(gdf), gdf.crs)   # 1439  EPSG:6668

fgb = gpd.read_file("data/output/roads_all.fgb")
print(len(fgb))            # 1439

# FGB spatial index in action: read only features inside a bbox
subset = gpd.read_file("data/output/roads_all.fgb", bbox=(122.9, 24.4, 123.0, 24.5))
```

### Configuration

All settings live in `src/roadnet/config.py` (pydantic-settings). Override with
env vars prefixed `ROADNET_`, e.g.:

```bash
ROADNET_SLEEP_SECONDS=5 ROADNET_DATA_DIR=/tmp/roads uv run roadnet all
```

Network behavior: a descriptive `User-Agent` is sent and requests are spaced by
`sleep_seconds` (default 2 s) between *actual* downloads.

## Architecture

I/O and pure transforms are separated at the function level so the transform
logic is unit-testable with no network or files:

```
src/roadnet/
  config.py    pydantic-settings: URLs, paths, sleep, timeout, User-Agent
  download.py  I/O:        idempotent httpx download (skip existing)
  convert.py   transform:  normalize_roads / count_invalid_geometries / crs_epsg
               I/O:        read_mesh_zip (/vsizip) -> per-mesh GeoParquet
  merge.py     transform:  find_cross_mesh_duplicates (pure helper)
               I/O:        merge_parts (streaming ParquetWriter)
                           merge_parts_to_flatgeobuf (streaming pyogrio append)
  cli.py       argparse: download / convert / merge / all
```

### Streaming merge

`merge.py` does **not** load all parts into memory — at most one part is held
at a time, for both formats:

- **GeoParquet**: a single `pyarrow.parquet.ParquetWriter` using the **first
  part's** Arrow schema (including its GeoParquet `geo` metadata) writes parts
  one by one.
- **FlatGeobuf**: parts are appended one by one via
  `pyogrio.write_dataframe(..., append=True)`. Verified against pyogrio 0.13 /
  GDAL 3.12: append works and the packed spatial index is present after
  appends (`fast_spatial_filter` capability; bbox queries return correct
  subsets).

This matters for the real "millions of features" case.

### Invalid geometries

`count_invalid_geometries` only **reports** missing / empty / invalid geometries
(logged as a warning per mesh). It never repairs them, so source data is not
silently altered. (The 3 default meshes report 0 invalid.)

## Known limitations

- **GeoParquet `bbox` metadata is from the first part only.** Because the
  streaming writer reuses the first part's `geo` metadata, the merged file's
  advertised bounding box covers just that first mesh — not the full extent.
  The geometry data is correct (`gdf.total_bounds` is accurate); only the
  metadata hint is narrow. Fixing this would require rewriting the `geo`
  metadata after computing the union bbox, which is out of MVP scope.
- **FlatGeobuf append cost can grow super-linearly.** GDAL's FGB append may
  rebuild the file internally (spatial-index re-sort) on each append, so total
  write cost can exceed O(total rows) when merging many parts. Fine at MVP
  scale (a few parts); revisit before merging thousands of parts / tens of
  millions of rows (e.g. write once from a single pass, or post-process with
  `ogr2ogr`).
- **No scraping.** Mesh URLs are hard-coded. A real pipeline would enumerate
  meshes from the download page or the KSJ API.
- **Cross-mesh de-duplication is detect-only.** `find_cross_mesh_duplicates`
  flags identical geometries shared across meshes but the pipeline does not drop
  them (N13 has no stable global feature id to dedupe on safely).

## Docker

`pyogrio` wheels bundle GDAL, so no OSGeo/GDAL base image is needed. The
Dockerfile follows uv's current official pattern (copy the `uv` binary from
`ghcr.io/astral-sh/uv`, cache-mounted `uv sync --locked`).

```bash
docker build -t roadnet .

# Run the full pipeline, persisting data to a host directory:
docker run --rm -v "$(pwd)/data:/app/data" roadnet all

# Just one step:
docker run --rm -v "$(pwd)/data:/app/data" roadnet download
```

> Note: the Docker build was **not** verified in the authoring environment
> (Docker daemon unavailable). The Dockerfile follows the documented uv pattern
> but has not been built/run here.

## Development

```bash
uv run pytest        # 12 tests, network-free (synthetic GeoDataFrames)
uv run ruff check .
uv run mypy src tests
```
