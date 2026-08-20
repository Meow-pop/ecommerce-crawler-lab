import unittest

from market_report import ReportError, build_report, price_band


PAYLOAD = {
    "schema_version": "1.0",
    "source": "苏宁易购",
    "query": "保温杯",
    "source_url": "https://search.suning.com/example/",
    "collected_at": "2026-08-20T00:00:00+00:00",
    "field_completeness": {"price": 1, "store": 1, "reviews": 1},
    "items": [
        {
            "rank": 1,
            "title": "A 316保温杯 500ML",
            "price_cny": 49,
            "review_count_lower_bound": 100,
            "review_count_display": "100+",
            "store_name": "A店",
            "is_sponsored": False,
            "mentioned_materials": ["316不锈钢"],
            "capacity_ml": 500,
            "product_url": "https://product.suning.com/a",
        },
        {
            "rank": 2,
            "title": "B保温杯",
            "price_cny": 149,
            "review_count_lower_bound": 20,
            "review_count_display": "20+",
            "store_name": "B店",
            "is_sponsored": True,
            "mentioned_materials": [],
            "capacity_ml": None,
            "product_url": "https://product.suning.com/b",
        },
    ],
}


class MarketReportTests(unittest.TestCase):
    def test_price_bands(self):
        self.assertEqual(price_band(49.99), "50元以下")
        self.assertEqual(price_band(50), "50–99元")
        self.assertEqual(price_band(100), "100–199元")
        self.assertEqual(price_band(200), "200元及以上")

    def test_report_contains_metrics_and_evidence(self):
        report = build_report(PAYLOAD)
        self.assertIn("¥99.00", report)
        self.assertIn("50.0%", report)
        self.assertIn("[商品页](https://product.suning.com/a)", report)
        self.assertIn("316不锈钢", report)

    def test_empty_payload_is_rejected(self):
        with self.assertRaises(ReportError):
            build_report({"schema_version": "1.0", "items": []})


if __name__ == "__main__":
    unittest.main()
