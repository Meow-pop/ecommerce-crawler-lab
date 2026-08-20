"""Crawler for the repository-owned local e-commerce target."""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import http.cookiejar
import json
import re
import secrets
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


ALLOWED_HOSTS = {"127.0.0.1", "localhost", "target"}


class CollectorError(RuntimeError):
    """Known and user-actionable collection failure."""


@dataclass
class Product:
    rank: int
    product_id: str
    title: str
    brand: str
    price: float
    monthly_sales: int
    rating: float
    review_count: int
    capacity_ml: int
    material: str
    stock: int
    product_url: str
    source_url: str
    collected_at: str


def canonical_message(timestamp: str, nonce: str, query: str, page: int, page_size: int) -> str:
    return f"{timestamp}\n{nonce}\n{query}\n{page}\n{page_size}"


def sign_request(token: str, message: str) -> str:
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def require_local_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise CollectorError(
            "M1 采集器只允许仓库自带的本地目标：http://127.0.0.1、http://localhost 或 Docker 服务 target"
        )
    if parsed.username or parsed.password:
        raise CollectorError("目标地址不能包含用户名或密码")
    return value.rstrip("/")


def nonnegative_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise CollectorError(f"字段 {field} 不是整数") from error
    if result < 0:
        raise CollectorError(f"字段 {field} 不能小于 0")
    return result


def nonnegative_float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CollectorError(f"字段 {field} 不是数字") from error
    if result < 0:
        raise CollectorError(f"字段 {field} 不能小于 0")
    return result


def clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_product(
    raw: Mapping[str, Any],
    rank: int,
    base_url: str,
    source_url: str,
    collected_at: str,
) -> Product:
    product_id = clean_text(raw.get("product_id"), 100)
    title = clean_text(raw.get("title"), 500)
    if not product_id or not title:
        raise CollectorError("商品缺少 product_id 或 title")
    product_path = clean_text(raw.get("product_url"), 1000)
    product_url = urljoin(base_url + "/", product_path.lstrip("/")) if product_path else ""
    return Product(
        rank=rank,
        product_id=product_id,
        title=title,
        brand=clean_text(raw.get("brand"), 200),
        price=nonnegative_float(raw.get("price"), "price"),
        monthly_sales=nonnegative_int(raw.get("monthly_sales"), "monthly_sales"),
        rating=nonnegative_float(raw.get("rating"), "rating"),
        review_count=nonnegative_int(raw.get("review_count"), "review_count"),
        capacity_ml=nonnegative_int(raw.get("capacity_ml"), "capacity_ml"),
        material=clean_text(raw.get("material"), 200),
        stock=nonnegative_int(raw.get("stock"), "stock"),
        product_url=product_url,
        source_url=source_url,
        collected_at=collected_at,
    )


def safe_csv_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = re.sub(r"\s+", " ", value).strip()
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


class LabClient:
    def __init__(self, base_url: str, timeout: int = 15, max_retries: int = 3) -> None:
        self.base_url = require_local_base_url(base_url)
        self.timeout = timeout
        self.max_retries = max_retries
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.client_token = ""

    def _decode_response(self, response: Any) -> Dict[str, Any]:
        try:
            document = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CollectorError("目标站返回了无法解析的响应") from error
        if not isinstance(document, dict):
            raise CollectorError("目标站返回结构不是 JSON 对象")
        return document

    def bootstrap(self) -> None:
        request = Request(
            self.base_url + "/api/bootstrap",
            data=b"",
            headers={"Accept": "application/json", "User-Agent": "ecommerce-crawler-lab/0.1"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                document = self._decode_response(response)
        except (HTTPError, URLError) as error:
            raise CollectorError(f"无法建立本地实验会话：{error}") from error
        token = document.get("client_token")
        if not isinstance(token, str) or len(token) < 16:
            raise CollectorError("bootstrap 响应缺少有效 client_token")
        self.client_token = token

    def fetch_page(self, query: str, page: int, page_size: int) -> tuple[Dict[str, Any], str, int]:
        if not self.client_token:
            self.bootstrap()
        params = urlencode({"q": query, "page": page, "page_size": page_size})
        source_url = f"{self.base_url}/api/products?{params}"

        for attempt in range(self.max_retries + 1):
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(16)
            message = canonical_message(timestamp, nonce, query, page, page_size)
            request = Request(
                source_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ecommerce-crawler-lab/0.1",
                    "X-Lab-Timestamp": timestamp,
                    "X-Lab-Nonce": nonce,
                    "X-Lab-Signature": sign_request(self.client_token, message),
                },
            )
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return self._decode_response(response), source_url, attempt
            except HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self.bootstrap()
                    continue
                if error.code == 429 and attempt < self.max_retries:
                    retry_after = error.headers.get("Retry-After", "1")
                    try:
                        wait_seconds = max(1, min(10, int(retry_after)))
                    except ValueError:
                        wait_seconds = 1
                    time.sleep(wait_seconds)
                    continue
                raise CollectorError(f"目标站返回 HTTP {error.code}") from error
            except URLError as error:
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise CollectorError(f"无法连接本地实验站：{error.reason}") from error
        raise CollectorError("超过最大重试次数")


def collect(client: LabClient, query: str, pages: int, page_size: int, delay: float) -> Dict[str, Any]:
    collected_at = datetime.now(timezone.utc).isoformat()
    products: List[Product] = []
    seen = set()
    diagnostics = []
    reported_total: Optional[int] = None

    for page in range(1, pages + 1):
        document, source_url, retry_count = client.fetch_page(query, page, page_size)
        if document.get("schema_version") != "1.0":
            raise CollectorError(f"不支持的 schema_version：{document.get('schema_version')}")
        items = document.get("items")
        if not isinstance(items, list):
            raise CollectorError("items 字段不是列表")
        if reported_total is None:
            reported_total = nonnegative_int(document.get("total"), "total")

        accepted = 0
        errors = []
        for raw in items:
            if not isinstance(raw, dict):
                errors.append("商品不是 JSON 对象")
                continue
            try:
                product = normalize_product(raw, len(products) + 1, client.base_url, source_url, collected_at)
            except CollectorError as error:
                errors.append(str(error))
                continue
            if product.product_id in seen:
                continue
            seen.add(product.product_id)
            products.append(product)
            accepted += 1

        diagnostics.append({
            "page": page,
            "returned": len(items),
            "accepted": accepted,
            "retries": retry_count,
            "validation_errors": errors[:20],
        })
        if not document.get("has_next"):
            break
        if page < pages:
            time.sleep(delay)

    return {
        "query": query,
        "collection_mode": "owned_local_ecommerce_lab",
        "collected_at": collected_at,
        "reported_total": reported_total,
        "item_count": len(products),
        "diagnostics": diagnostics,
        "items": [asdict(product) for product in products],
    }


def write_outputs(output_directory: Path, query: str, payload: Dict[str, Any]) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    safe_query = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", query).strip(" .-")[:50] or "products"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = output_directory / f"lab-{safe_query}-{timestamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = list(Product.__dataclass_fields__)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in payload["items"]:
            writer.writerow({field: safe_csv_value(item.get(field, "")) for field in fields})
    return json_path, csv_path


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自有本地电商实验站采集器")
    parser.add_argument("keyword", help="搜索关键词，例如：保温杯")
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--pages", type=int, default=3, choices=range(1, 11), metavar="1-10")
    parser.add_argument("--page-size", type=int, default=12, choices=range(1, 25), metavar="1-24")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--max-retries", type=int, default=3, choices=range(0, 6), metavar="0-5")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args(argv)
    if not 0 <= args.delay <= 30:
        parser.error("--delay 必须在 0 到 30 秒之间")
    return args


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        client = LabClient(args.base_url, max_retries=args.max_retries)
        payload = collect(client, args.keyword, args.pages, args.page_size, args.delay)
        json_path, csv_path = write_outputs(args.output, args.keyword, payload)
    except CollectorError as error:
        print(f"[collector-error] {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"采集完成：{payload['item_count']} 件商品")
    print(f"JSON：{json_path}")
    print(f"CSV ：{csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
