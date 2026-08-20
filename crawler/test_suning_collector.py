import csv
import json
import tempfile
import unittest
from pathlib import Path

from suning_collector import (
    SuningCollectorError,
    build_search_url,
    normalize_product,
    parse_cards,
    parse_price,
    require_search_url,
    write_outputs,
)


SAMPLE_HTML = """
<div id="product-list"><ul>
<li class="item-wrap 007-123 basic" id="007-123">
  <div class="product-box">
    <div class="res-img"><a class="sellPoint" title="保温性能好" href="//product.suning.com/007/123.html">
      <img alt="哈尔斯 316L保温杯 500ML" src="//img.example/123.jpg">
    </a></div>
    <div class="res-info">
      <div class="title-selling-point"><a href="//product.suning.com/007/123.html">
        哈尔斯 316L保温杯 500ML <em style="display:none">隐藏卖点</em>
      </a></div>
      <div class="info-evaluate"><a><i>90+</i>评价</a></div>
      <a class="store-name">哈尔斯旗舰店</a>
    </div>
  </div>
</li>
</ul></div>
"""


class SuningCollectorTests(unittest.TestCase):
    def test_keyword_builds_path_without_query_string(self):
        self.assertEqual(
            build_search_url("保温杯"),
            "https://search.suning.com/%E4%BF%9D%E6%B8%A9%E6%9D%AF/",
        )
        with self.assertRaises(SuningCollectorError):
            build_search_url("test?page=2")

    def test_only_public_search_host_is_allowed(self):
        url = build_search_url("保温杯")
        self.assertEqual(require_search_url(url), url)
        with self.assertRaises(SuningCollectorError):
            require_search_url("https://example.com/保温杯/")

    def test_public_product_card_is_parsed(self):
        cards = parse_cards(SAMPLE_HTML)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["product_id"], "007-123")
        self.assertEqual(cards[0]["title"], "哈尔斯 316L保温杯 500ML")
        self.assertEqual(cards[0]["review_count_display"], "90+")
        self.assertEqual(cards[0]["store_name"], "哈尔斯旗舰店")
        self.assertEqual(cards[0]["selling_point"], "保温性能好")

    def test_product_normalization_and_price(self):
        card = parse_cards(SAMPLE_HTML)[0]
        product = normalize_product(card, "¥89.00", 1, "source", "now")
        self.assertEqual(product.price_cny, 89.0)
        self.assertEqual(product.review_count_lower_bound, 90)
        self.assertEqual(product.capacity_ml, 500)
        self.assertEqual(product.mentioned_materials, ["316不锈钢"])
        self.assertFalse(product.is_sponsored)

    def test_missing_price_is_explicit(self):
        self.assertIsNone(parse_price(""))

    def test_json_and_csv_outputs(self):
        product = normalize_product(parse_cards(SAMPLE_HTML)[0], "¥89", 1, "source", "now")
        payload = {"query": "保温杯", "items": [product.__dict__]}
        with tempfile.TemporaryDirectory() as directory:
            json_path, csv_path = write_outputs(Path(directory), payload)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["items"][0]["sku_id"], "123")
            with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(json.loads(row["mentioned_materials"]), ["316不锈钢"])


if __name__ == "__main__":
    unittest.main()
