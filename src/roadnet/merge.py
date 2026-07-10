"""Merge layer: stream per-mesh GeoParquet parts into merged outputs.

Two output formats are produced from the same ``parts/*.parquet``:

- **GeoParquet** (``merge_parts``): a single ``pyarrow.parquet.ParquetWriter``
  writes parts one at a time — we never concatenate every part into memory.
  The writer adopts the *first* part's schema, including its GeoParquet ``geo``
  metadata, so the output is readable by ``geopandas.read_parquet``.
- **FlatGeobuf** (``merge_parts_to_flatgeobuf``): parts are read one at a time
  and appended via ``pyogrio.write_dataframe(append=True)``. Verified against
  pyogrio 0.13 / GDAL 3.12: append works and the packed spatial index is
  present after appends (``fast_spatial_filter`` capability, bbox queries).

Streaming rule (important for the real "millions of features" case): at most
one part is held in memory at a time, for either format.

Known limitations:

- GeoParquet: the ``geo`` metadata (notably ``bbox``) is copied verbatim from
  the first part, so the merged file's advertised bbox covers only that mesh,
  not the full extent. See README.
- FlatGeobuf: GDAL's append may internally rebuild the file (index re-sort),
  so with many parts the total write cost can grow super-linearly. Fine at MVP
  scale; revisit before merging thousands of parts / tens of millions of rows.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import pyogrio

from .convert import SOURCE_MESH_COLUMN

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure helper (no I/O — unit-testable)                                         #
# --------------------------------------------------------------------------- #
def find_cross_mesh_duplicates(
    gdf: gpd.GeoDataFrame, mesh_col: str = SOURCE_MESH_COLUMN
) -> gpd.GeoDataFrame:
    """Return rows whose geometry appears under more than one distinct mesh.

    N13 features have no stable global id, so we key on geometry (WKB) to detect
    the same road line delivered by two adjacent mesh files. Returns the subset
    of ``gdf`` (possibly empty) involved in such cross-mesh duplication.
    """
    if len(gdf) == 0:
        return gdf.iloc[0:0]
    wkb = gdf.geometry.apply(lambda g: None if g is None else g.wkb)
    # Count distinct meshes per geometry key; keep rows sharing a geom across >1 mesh.
    distinct = gdf.assign(_wkb=wkb).groupby("_wkb")[mesh_col].transform("nunique")
    mask = distinct > 1
    return gdf[mask.to_numpy()]


# --------------------------------------------------------------------------- #
# Streaming merge (I/O)                                                        #
# --------------------------------------------------------------------------- #
def merge_parts(part_paths: list[Path], output_path: Path) -> int:
    """Stream-merge parquet parts into one file. Returns total rows written.

    The first part's Arrow schema (with GeoParquet ``geo`` metadata) is used for
    the whole output; later parts are cast to it before writing.
    """
    if not part_paths:
        raise ValueError("No parts to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer: pq.ParquetWriter | None = None
    total_rows = 0
    try:
        for path in part_paths:
            table = pq.read_table(path)
            if writer is None:
                writer = pq.ParquetWriter(output_path, table.schema)
            else:
                # Align column types to the first part; also drops per-part
                # schema metadata so we keep the first part's `geo` block.
                table = table.cast(writer.schema)
            writer.write_table(table)
            total_rows += table.num_rows
            logger.info("merged %s (%d rows)", path.name, table.num_rows)
    finally:
        if writer is not None:
            writer.close()

    logger.info("wrote %d total rows -> %s", total_rows, output_path)
    return total_rows


def merge_parts_to_flatgeobuf(part_paths: list[Path], output_path: Path) -> int:
    """Stream-merge parquet parts into one FlatGeobuf. Returns total rows written.

    Parts are read one at a time (bounded memory) and appended with pyogrio's
    FlatGeobuf driver. The first part creates the file; any pre-existing output
    is removed first so re-runs stay deterministic instead of appending to the
    previous result.

    The resulting .fgb carries FlatGeobuf's built-in packed spatial index, so
    QGIS and bbox-filtered reads work as expected.

    Note: GDAL's FGB append may rebuild the file internally on each append, so
    write cost can grow super-linearly with the number of parts. Acceptable at
    MVP scale (a few parts); see module docstring.
    """
    if not part_paths:
        raise ValueError("No parts to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)

    total_rows = 0
    for i, path in enumerate(part_paths):
        gdf = gpd.read_parquet(path)
        pyogrio.write_dataframe(gdf, output_path, driver="FlatGeobuf", append=i > 0)
        total_rows += len(gdf)
        logger.info("merged %s (%d rows) -> fgb", path.name, len(gdf))

    logger.info("wrote %d total rows -> %s", total_rows, output_path)
    return total_rows
