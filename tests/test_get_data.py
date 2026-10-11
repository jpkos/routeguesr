import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

import get_data


class RouteDataRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            dir=get_data.PROJECT_ROOT
        )
        self.gtfs_directory = Path(self.temporary_directory.name) / "gtfs"
        self.gtfs_directory.mkdir()

        pd.DataFrame(
            [
                {
                    "shape_id": "10_weekday",
                    "shape_pt_lat": 60.20,
                    "shape_pt_lon": 24.90,
                    "shape_pt_sequence": 2,
                },
                {
                    "shape_id": "10_weekday",
                    "shape_pt_lat": 60.10,
                    "shape_pt_lon": 24.80,
                    "shape_pt_sequence": 1,
                },
            ]
        ).to_csv(self.gtfs_directory / "shapes.txt", index=False)
        pd.DataFrame(
            [{"trip_id": "trip-10", "route_id": "route-10", "shape_id": "10_weekday"}]
        ).to_csv(self.gtfs_directory / "trips.txt", index=False)
        pd.DataFrame(
            [
                {
                    "route_id": "route-10",
                    "agency_id": "HSL",
                    "route_short_name": "10",
                    "route_long_name": "Test route",
                    "route_type": 0,
                }
            ]
        ).to_csv(self.gtfs_directory / "routes.txt", index=False)
        pd.DataFrame(
            [
                {"trip_id": "trip-10", "stop_id": "stop-a", "stop_sequence": 1},
                {"trip_id": "trip-10", "stop_id": "stop-b", "stop_sequence": 2},
            ]
        ).to_csv(self.gtfs_directory / "stop_times.txt", index=False)
        pd.DataFrame(
            [
                {"stop_id": "stop-a", "zone_id": "A"},
                {"stop_id": "stop-b", "zone_id": "B"},
            ]
        ).to_csv(self.gtfs_directory / "stops.txt", index=False)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_refresh_orders_points_and_writes_verified_pickle(self):
        output = Path(self.temporary_directory.name) / "processed" / "lines.pkl"

        lines = get_data.refresh_lines(self.gtfs_directory, output)

        self.assertTrue(output.is_file())
        self.assertEqual(lines.loc[0, "route_short_name"], "10")
        self.assertEqual(lines.loc[0, "line"], "10")
        self.assertEqual(lines.loc[0, "zones"], ("A", "B"))
        self.assertEqual(
            list(lines.loc[0, "geometry"].coords),
            [(24.8, 60.1), (24.9, 60.2)],
        )
        saved = pd.read_pickle(output)
        self.assertEqual(
            saved.attrs["geometry_coordinate_order"], "longitude_latitude"
        )

    def test_missing_required_table_returns_cli_error(self):
        (self.gtfs_directory / "routes.txt").unlink()
        output = Path(self.temporary_directory.name) / "lines.pkl"

        exit_code = get_data.main(
            ["--input", str(self.gtfs_directory), "--output", str(output)]
        )

        self.assertEqual(exit_code, 1)
        self.assertFalse(output.exists())

    def test_refresh_accepts_gtfs_zip_input(self):
        archive_path = Path(self.temporary_directory.name) / "hsl.zip"
        with ZipFile(archive_path, "w") as archive:
            for table_name in (
                "shapes.txt",
                "trips.txt",
                "routes.txt",
                "stop_times.txt",
                "stops.txt",
            ):
                archive.write(self.gtfs_directory / table_name, table_name)
        output = Path(self.temporary_directory.name) / "from-zip.pkl"

        exit_code = get_data.main(
            ["--input", str(archive_path), "--output", str(output)]
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
