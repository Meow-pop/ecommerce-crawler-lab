import csv
import json
import tempfile
import unittest
from pathlib import Path

from smzdm_insights import (
    PublicSourceError,
    extract_capacities,
    extract_materials,
    extract_platforms,
    extract_prices,
    normalize_card,
    require_public_category_url,
    write_outputs,
)


SAMPLE_CARD = {
    "title": "京东50元入手316L保温杯",
    "excerpt": "天猫同款约79.9元，容量500ml，纯钛款更贵。",
    "likes": "131",
    "favorites": "232",
    "comments": "129",
    "published_date": "24-11-19",
    "article_url": "https://post.smzdm.com/talk/p/a60l2nwn/",
    "image_url": "https://example.invalid/cup.jpg",
}


class SmzdmInsightTests(unittest.TestCase):
    def test_only_public_category_urls_are_allowed(self):
        url = "https://www.smzdm.com/fenlei/baowenbaolengbei/"
        self.assertEqual(require_public_category_url(url), url)
        for invalid in (
            "https://search.smzdm.com/?s=保温杯",
            "https://www.smzdm.com/p/123/",
            "https://www.smzdm.com/fenlei/test/?page=2",
            "https://example.com/fenlei/test/",
        ):
            with self.assertRaises(PublicSourceError):
                require_public_category_url(invalid)

    def test_market_signal_extractors(self):
        text = SAMPLE_CARD["title"] + " " + SAMPLE_CARD["excerpt"]
        self.assertEqual(extract_platforms(text), ["京东", "天猫"])
        self.assertEqual(extract_prices(text), [50.0, 79.9])
        self.assertEqual(extract_materials(text), ["316不锈钢", "纯钛"])
        self.assertEqual(extract_capacities(text), [500])

    def test_card_is_normalized_with_evidence(self):
        item = normalize_card(SAMPLE_CARD, 1, "保温杯", "now")
        self.assertEqual(item.insight_id, "a60l2nwn")
        self.assertEqual(item.comments, 129)
        self.assertEqual(item.mentioned_platforms, ["京东", "天猫"])
        self.assertEqual(item.mentioned_prices_cny, [50.0, 79.9])

    def test_invalid_article_host_is_rejected(self):
        card = dict(SAMPLE_CARD, article_url="https://example.com/p/a60l2nwn/")
        with self.assertRaises(PublicSourceError):
            normalize_card(card, 1, "保温杯", "now")

    def test_json_and_csv_outputs(self):
        item = normalize_card(SAMPLE_CARD, 1, "保温杯", "now")
        payload = {"category": "保温杯", "items": [item.__dict__]}
        with tempfile.TemporaryDirectory() as directory:
            json_path, csv_path = write_outputs(Path(directory), payload)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["items"][0]["likes"], 131)
            with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(json.loads(row["mentioned_platforms"]), ["京东", "天猫"])


if __name__ == "__main__":
    unittest.main()
