"""Download HSL GTFS data and rebuild the route geometry dataset.

Run this module from the repository root to refresh the application's data:

    python get_data.py

The generated pickle is replaced only after the complete GTFS package has been
validated and processed successfully.
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Sequence
from zipfile import BadZipFile, ZipFile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_GTFS_URL = "https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "lines.pkl"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
REQUIRED_COLUMNS = {
    "shapes.txt": {"shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"},
    "trips.txt": {"trip_id", "route_id", "shape_id"},
    "routes.txt": {"route_id", "route_short_name", "route_type"},
    "stop_times.txt": {"trip_id", "stop_id"},
    "stops.txt": {"stop_id", "zone_id"},
}
READ_COLUMNS = {
    "shapes.txt": REQUIRED_COLUMNS["shapes.txt"],
    "trips.txt": REQUIRED_COLUMNS["trips.txt"],
    "stop_times.txt": REQUIRED_COLUMNS["stop_times.txt"],
    "stops.txt": REQUIRED_COLUMNS["stops.txt"],
}
HSL_FARE_ZONES = frozenset({"A", "B", "C", "D", "E"})

LOGGER = logging.getLogger(__name__)


class DataRefreshError(RuntimeError):
    """Raised when the GTFS package cannot produce a valid route dataset."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the latest HSL GTFS package and rebuild lines.pkl."
    )
    parser.add_argument(
        "--input",
        type=Path,
        metavar="PATH",
        help="Use an existing GTFS ZIP or extracted GTFS directory instead of downloading.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_GTFS_URL,
        help=f"GTFS ZIP URL (default: {DEFAULT_GTFS_URL}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output pickle path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Download read timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed logging.",
    )
    return parser.parse_args(argv)


def download_gtfs(url: str, destination: Path, timeout: float) -> None:
    """Stream a GTFS ZIP to ``destination`` without loading it into memory."""
    if timeout <= 0:
        raise DataRefreshError("Download timeout must be greater than zero.")

    LOGGER.info("Downloading HSL GTFS data from %s", url)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(15, timeout),
            headers={"User-Agent": "hsl-route-guesser-data-refresh/1.0"},
        ) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        output.write(chunk)
    except requests.RequestException as error:
        destination.unlink(missing_ok=True)
        raise DataRefreshError(f"GTFS download failed: {error}") from error
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise DataRefreshError(f"Could not save the GTFS download: {error}") from error

    if not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise DataRefreshError("The downloaded GTFS archive is empty.")

    LOGGER.info("Downloaded %.1f MiB", destination.stat().st_size / 1024**2)


def _validate_columns(frame: pd.DataFrame, table_name: str) -> None:
    missing = REQUIRED_COLUMNS[table_name].difference(frame.columns)
    if missing:
        columns = ", ".join(sorted(missing))
        raise DataRefreshError(f"{table_name} is missing required columns: {columns}")


def _read_csv(path_or_buffer: object, table_name: str) -> pd.DataFrame:
    dtype = {
        "shape_id": "string",
        "route_id": "string",
        "route_short_name": "string",
        "trip_id": "string",
        "stop_id": "string",
        "zone_id": "string",
    }
    try:
        frame = pd.read_csv(
            path_or_buffer,
            dtype=dtype,
            usecols=READ_COLUMNS.get(table_name),
            low_memory=False,
        )
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        raise DataRefreshError(f"Could not read {table_name}: {error}") from error
    _validate_columns(frame, table_name)
    return frame


def _find_archive_member(archive: ZipFile, table_name: str) -> str:
    matches = [
        name
        for name in archive.namelist()
        if not name.endswith("/") and PurePosixPath(name).name == table_name
    ]
    if not matches:
        raise DataRefreshError(f"GTFS archive does not contain {table_name}.")
    if len(matches) > 1:
        raise DataRefreshError(f"GTFS archive contains more than one {table_name} file.")
    return matches[0]


def read_gtfs_tables(source: Path) -> tuple[pd.DataFrame, ...]:
    """Read the GTFS tables needed for route geometries and fare zones."""
    source = source.expanduser().resolve()
    table_names = tuple(REQUIRED_COLUMNS)

    if source.is_dir():
        tables = []
        for table_name in table_names:
            table_path = source / table_name
            if not table_path.is_file():
                raise DataRefreshError(f"GTFS directory does not contain {table_name}.")
            tables.append(_read_csv(table_path, table_name))
        return tuple(tables)  # type: ignore[return-value]

    if not source.is_file():
        raise DataRefreshError(f"GTFS input does not exist: {source}")

    try:
        with ZipFile(source) as archive:
            tables = []
            for table_name in table_names:
                member = _find_archive_member(archive, table_name)
                with archive.open(member) as table_file:
                    tables.append(_read_csv(table_file, table_name))
            return tuple(tables)  # type: ignore[return-value]
    except BadZipFile as error:
        raise DataRefreshError(f"GTFS input is not a valid ZIP archive: {source}") from error


def _coerce_numeric_column(
    frame: pd.DataFrame, column: str, table_name: str
) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    invalid_count = int(values.isna().sum())
    if invalid_count:
        raise DataRefreshError(
            f"{table_name} contains {invalid_count} invalid value(s) in {column}."
        )
    return values


def build_line_data(
    shapes: pd.DataFrame,
    trips: pd.DataFrame,
    routes: pd.DataFrame,
    stop_times: pd.DataFrame,
    stops: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Create one ordered LineString for every route/shape combination."""
    shapes = shapes.copy()
    trips = trips.copy()
    routes = routes.copy()
    stop_times = stop_times.copy()
    stops = stops.copy()

    for frame, columns, table_name in (
        (shapes, ("shape_id",), "shapes.txt"),
        (trips, ("trip_id", "shape_id", "route_id"), "trips.txt"),
        (routes, ("route_id", "route_short_name"), "routes.txt"),
        (stop_times, ("trip_id", "stop_id"), "stop_times.txt"),
        (stops, ("stop_id",), "stops.txt"),
    ):
        missing_rows = int(frame[list(columns)].isna().any(axis=1).sum())
        if missing_rows:
            raise DataRefreshError(
                f"{table_name} contains {missing_rows} row(s) without required identifiers."
            )

    shapes["shape_pt_lat"] = _coerce_numeric_column(
        shapes, "shape_pt_lat", "shapes.txt"
    )
    shapes["shape_pt_lon"] = _coerce_numeric_column(
        shapes, "shape_pt_lon", "shapes.txt"
    )
    shapes["shape_pt_sequence"] = _coerce_numeric_column(
        shapes, "shape_pt_sequence", "shapes.txt"
    )
    routes["route_type"] = _coerce_numeric_column(routes, "route_type", "routes.txt")

    invalid_coordinates = ~(
        shapes["shape_pt_lat"].between(-90, 90)
        & shapes["shape_pt_lon"].between(-180, 180)
    )
    if invalid_coordinates.any():
        raise DataRefreshError(
            f"shapes.txt contains {int(invalid_coordinates.sum())} invalid coordinate(s)."
        )

    if routes["route_id"].duplicated().any():
        raise DataRefreshError("routes.txt contains duplicate route_id values.")
    if stops["stop_id"].duplicated().any():
        raise DataRefreshError("stops.txt contains duplicate stop_id values.")

    trip_routes = trips[["trip_id", "route_id"]].drop_duplicates()
    if trip_routes["trip_id"].duplicated().any():
        raise DataRefreshError("trips.txt maps a trip_id to more than one route_id.")

    stop_zones = stops[["stop_id", "zone_id"]]
    stop_zones = stop_zones[stop_zones["zone_id"].isin(HSL_FARE_ZONES)]
    route_zones = (
        stop_times[["trip_id", "stop_id"]]
        .merge(stop_zones, on="stop_id", how="inner", validate="many_to_one")
        .merge(trip_routes, on="trip_id", how="inner", validate="many_to_one")
        .groupby("route_id")["zone_id"]
        .agg(lambda values: tuple(sorted(set(values))))
        .rename("zones")
    )

    shapes = shapes.sort_values(
        ["shape_id", "shape_pt_sequence"], kind="stable"
    )
    geometry_rows: list[dict[str, object]] = []
    skipped_shapes = 0
    for shape_id, points in shapes.groupby("shape_id", sort=False):
        # GeoJSON/GeoPandas use longitude-latitude coordinate order.
        coordinates = list(
            points[["shape_pt_lon", "shape_pt_lat"]].itertuples(
                index=False, name=None
            )
        )
        if len(coordinates) < 2:
            skipped_shapes += 1
            continue
        geometry_rows.append(
            {"shape_id": shape_id, "geometry": LineString(coordinates)}
        )

    if not geometry_rows:
        raise DataRefreshError("No shapes with at least two points were found.")
    if skipped_shapes:
        LOGGER.warning("Skipped %d shape(s) with fewer than two points", skipped_shapes)

    shape_lines = gpd.GeoDataFrame(
        geometry_rows, geometry="geometry", crs="EPSG:4326"
    )
    trip_routes = trips[["shape_id", "route_id"]].drop_duplicates()
    joined = shape_lines.merge(
        trip_routes,
        on="shape_id",
        how="inner",
        validate="one_to_many",
    )
    joined = joined.merge(
        routes,
        on="route_id",
        how="inner",
        validate="many_to_one",
    )
    if joined.empty:
        raise DataRefreshError("No GTFS shapes could be linked to named routes.")

    joined = joined.merge(route_zones, on="route_id", how="left", validate="many_to_one")
    joined["zones"] = joined["zones"].apply(
        lambda value: value if isinstance(value, tuple) else ()
    )

    joined["line"] = joined["shape_id"].str.split("_", n=1).str[0]
    joined["route_type"] = joined["route_type"].astype("int64")
    route_columns = [column for column in routes.columns if column != "route_id"]
    output_columns = ["shape_id", "geometry", "line", "route_id", *route_columns, "zones"]
    result = gpd.GeoDataFrame(
        joined[output_columns], geometry="geometry", crs="EPSG:4326"
    ).reset_index(drop=True)
    result.attrs["geometry_coordinate_order"] = "longitude_latitude"
    result.attrs["source"] = "HSL GTFS"
    return result


def write_pickle_atomically(lines: gpd.GeoDataFrame, output_path: Path) -> None:
    """Write the pickle beside its destination, then atomically replace it."""
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    try:
        lines.to_pickle(temporary_path)
        saved = pd.read_pickle(temporary_path)
        if len(saved) != len(lines) or "geometry" not in saved.columns:
            raise DataRefreshError("The generated pickle failed verification.")
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def refresh_lines(source: Path, output_path: Path) -> gpd.GeoDataFrame:
    """Build and save route geometries from a local GTFS source."""
    LOGGER.info("Reading GTFS data from %s", source)
    shapes, trips, routes, stop_times, stops = read_gtfs_tables(source)
    lines = build_line_data(shapes, trips, routes, stop_times, stops)
    write_pickle_atomically(lines, output_path)
    LOGGER.info(
        "Wrote %d route geometries covering %d route names to %s",
        len(lines),
        lines["route_short_name"].nunique(),
        output_path.resolve(),
    )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        if args.input:
            refresh_lines(args.input, args.output)
        else:
            with tempfile.TemporaryDirectory(prefix="hsl-gtfs-") as directory:
                archive_path = Path(directory) / "hsl.zip"
                download_gtfs(args.url, archive_path, args.timeout)
                refresh_lines(archive_path, args.output)
    except (DataRefreshError, OSError, ValueError) as error:
        LOGGER.error("Route data refresh failed: %s", error)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
