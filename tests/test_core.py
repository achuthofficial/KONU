"""Offline unit tests: python -m unittest discover -s tests"""
import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from konu import crawl, legacy, pincode
from konu.parsing import age_group, money, num
from konu.scheduler import next_run
from konu.schema import COLUMNS
from konu.sources import magicbricks, nobroker, squareyards
from konu.sources.common import crawl_listing_pages


class Parsing(unittest.TestCase):
    def test_money_units(self):
        self.assertEqual(money("45 Lacs"), 4_500_000)
        self.assertEqual(money("₹ 1.2 Cr"), 12_000_000)
        self.assertEqual(money("₹ 5,000"), 5000)
        self.assertIsNone(money("Price on Request"))

    def test_age_group(self):
        self.assertEqual(age_group(0), "New")
        self.assertEqual(age_group(12), "10+ Years")
        self.assertEqual(num("12 years"), 12)


class SourceParsers(unittest.TestCase):
    def test_magicbricks_project_without_price_is_kept(self):
        ld = {"@type": ["Product", "Residence"], "name": "Elite Plaza",
              "address": {"addressLocality": "Somajiguda", "postalCode": "500082", "streetAddress": "Somajiguda"},
              "geo": {"latitude": 17.42, "longitude": 78.45}}
        html = f'<script type="application/ld+json">{json.dumps(ld)}</script><body>Total Units 8</body>'
        row = magicbricks.parse("https://www.magicbricks.com/x-pdpid-1", html)
        self.assertEqual((row["Society"], row["Pincode"], row["Total_Units"]), ("Elite Plaza", "500082", 8.0))
        self.assertEqual(row["Price_INR"], "")

    def test_non_listing_pages_return_none(self):
        self.assertIsNone(nobroker.parse("https://www.nobroker.in/property/buy/a/b/detail", "<html>nothing</html>"))
        self.assertIsNone(squareyards.parse("https://www.squareyards.com/resale-x/1", "<html>nothing</html>"))

    def test_squareyards_extracts_listing_links(self):
        html = 'href="https://www.squareyards.com/resale-2-bhk-100-sq-ft-apartment-in-x/123" href="/other"'
        self.assertEqual(squareyards._extract(html),
                         ["https://www.squareyards.com/resale-2-bhk-100-sq-ft-apartment-in-x/123"])


class ListingPages(unittest.TestCase):
    def test_page_marked_done_only_after_all_links_yielded(self):
        class F:
            def get(self, url):
                return "a b"
        done = set()
        gen = crawl_listing_pages(F(), done, ["p1"], lambda html: html.split())
        self.assertEqual(next(gen), "a")
        self.assertNotIn("p1", done)  # interrupted mid-page: must be revisited next run
        list(gen)
        self.assertIn("p1", done)


class Pipeline(unittest.TestCase):
    def test_legacy_load_keeps_urlless_rows_and_repairs_bad_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.csv"
            pd.DataFrame({"URL": ["https://+A2:AB145www.nobroker.in/x", None],
                          "Pincode": [500001, None], "Price_INR": [1, 2]}).to_csv(path, index=False)
            df = legacy.load(path)
        self.assertEqual(list(df.columns), COLUMNS)
        self.assertEqual(df["URL"].iloc[0], "https://www.nobroker.in/x")
        self.assertEqual(list(df["Source"]), ["nobroker.in", legacy.UNKNOWN_SOURCE])

    def test_pincode_enrich_fills_missing_and_ranks_neighbours(self):
        square = lambda x0, x1: {"type": "Polygon", "coordinates": [[[x0, 0], [x1, 0], [x1, 1], [x1 - 0.0, 1], [x0, 1], [x0, 0]]]}
        gj = {"features": [{"properties": {"pincode": "111111"}, "geometry": square(0, 1)},
                           {"properties": {"pincode": "222222"}, "geometry": square(1, 2)}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "z.geojson"
            path.write_text(json.dumps(gj))
            df = pd.DataFrame({"Latitude": [0.5, 0.5, None], "Longitude": [0.99, 1.5, None],
                               "Pincode": pd.array([None, "999999", None], dtype="string")})
            out = pincode.enrich(df, [path])
        self.assertEqual(out["Pincode"].tolist()[:2], ["111111", "999999"])  # existing pincode is kept
        self.assertEqual(out["Possible_Pincodes"].iloc[0], "111111, 222222")  # nearest first
        self.assertTrue(pd.isna(out["Pincode"].iloc[2]))

    def test_crawl_migrates_old_interim_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            path.write_text("URL,Price_INR\nhttp://a,5\n")
            crawl._migrate_header(path)
            rows = list(csv.DictReader(open(path)))
        self.assertEqual(list(rows[0].keys()), COLUMNS)
        self.assertEqual((rows[0]["URL"], rows[0]["Price_INR"]), ("http://a", "5"))


class Scheduler(unittest.TestCase):
    def test_next_run(self):
        now = datetime(2026, 1, 1, 10, 0)
        self.assertEqual(next_run(SimpleNamespace(at="02:30", every=24), now), datetime(2026, 1, 2, 2, 30))
        self.assertEqual(next_run(SimpleNamespace(at="23:00", every=24), now), datetime(2026, 1, 1, 23, 0))
        self.assertEqual(next_run(SimpleNamespace(at=None, every=6), now), datetime(2026, 1, 1, 16, 0))


if __name__ == "__main__":
    unittest.main()
