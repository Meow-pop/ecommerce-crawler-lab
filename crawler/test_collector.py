import csv
import json
import tempfile
import unittest
from pathlib import Path

from collector import (
    CollectorError,
    canonical_message,
    normalize_product,
    require_local_base_url,
    safe_csv_value,
    sign_request,
    write_outputs,
)


class CollectorTests(unittest.TestCase):
    def test_signature_is_deterministic(self):
        message = canonical_message("100", "abcdefgh", "保温杯", 1, 12)
        self.assertEqual(
            sign_request("token", message),
            "eb659404d7ab2b734be829b8d08270e5e3d4d7243594ce269070b180765ae078",
        )

    def test_only_owned_local_targets_are_allowed(self):
        self.assertEqual(require_local_base_url("http://127.0.0.1:8081"), "http://127.0.0.1:8081")
        self.assertEqual(require_local_base_url("http://target:8080/"), "http://target:8080")
        with self.assertRaises(CollectorError):
            require_local_base_url("https://example.com")

    def test_product_validation_and_normalization(self):
        product = normalize_product({
            "product_id": "LAB-1",
            "title": "测试保温杯",
            "brand": "星桥",
            "price": "79.90",
            "monthly_sales": 100,
            "rating": 4.8,
            "review_count": 30,
            "capacity_ml": 500,
            "material": "304不锈钢",
            "stock": 20,
            "product_url": "/products/LAB-1",
        }, 1, "http://127.0.0.1:8081", "http://127.0.0.1:8081/api/products", "now")
        self.assertEqual(product.price, 79.9)
        self.assertEqual(product.product_url, "http://127.0.0.1:8081/products/LAB-1")

    def test_negative_price_is_rejected(self):
        with self.assertRaises(CollectorError):
            normalize_product({
                "product_id": "LAB-1", "title": "测试", "price": -1,
                "monthly_sales": 0, "rating": 0, "review_count": 0,
                "capacity_ml": 0, "stock": 0,
            }, 1, "http://127.0.0.1:8081", "source", "now")

    def test_csv_formula_prefix_is_neutralized(self):
        self.assertEqual(safe_csv_value("=1+1"), "'=1+1")

    def test_json_and_csv_outputs(self):
        product = normalize_product({
            "product_id": "LAB-1", "title": "=测试", "price": 10,
            "monthly_sales": 1, "rating": 5, "review_count": 1,
            "capacity_ml": 500, "material": "304", "stock": 1,
        }, 1, "http://127.0.0.1:8081", "source", "now")
        payload = {"items": [product.__dict__]}
        with tempfile.TemporaryDirectory() as directory:
            json_path, csv_path = write_outputs(Path(directory), "保温杯", payload)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["items"][0]["product_id"], "LAB-1")
            with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["title"], "'=测试")


if __name__ == "__main__":
    unittest.main()
