"""Automated, low-rate collector for Suning public search result pages."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib import robotparser
from urllib.parse import quote, urlparse


USER_AGENT = "ecommerce-crawler-lab/0.2"
SEARCH_HOST = "search.suning.com"
ROBOTS_URL = "https://search.suning.com/robots.txt"
MAX_ITEMS = 30


class SuningCollectorError(RuntimeError):
    """Known and user-actionable Suning collection failure."""


@dataclass
class SuningProduct:
    rank: int
    product_id: str
    sku_id: str
    title: str
    price_cny: Optional[float]
    review_count_lower_bound: int
    review_count_display: str
    store_name: str
    selling_point: str
    is_sponsored: bool
    mentioned_materials: List[str]
    capacity_ml: Optional[int]
    product_url: str
    image_url: str
    source_url: str
    source: str
    collected_at: str


def clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()[:limit]


def absolute_url(value: str) -> str:
    value = clean_text(value, 2_000)
    if value.startswith("//"):
        return "https:" + value
    return value


def build_search_url(keyword: str) -> str:
    keyword = clean_text(keyword, 50)
    if not keyword or any(char in keyword for char in "/\\?#"):
        raise SuningCollectorError("关键词不能为空，也不能包含 URL 控制字符")
    return f"https://{SEARCH_HOST}/{quote(keyword, safe='')}/"


def require_search_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != SEARCH_HOST:
        raise SuningCollectorError("只允许苏宁公开搜索域名 https://search.suning.com/")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SuningCollectorError("搜索地址不能包含查询参数、片段或身份信息")
    return url


def check_robots(url: str) -> None:
    parser = robotparser.RobotFileParser()
    parser.set_url(ROBOTS_URL)
    try:
        parser.read()
    except OSError as error:
        raise SuningCollectorError(f"无法读取 robots.txt，已停止采集：{error}") from error
    if not parser.can_fetch(USER_AGENT, url):
        raise SuningCollectorError("robots.txt 不允许当前采集器访问该地址，已停止")


class ProductCardParser(HTMLParser):
    """Extract selected public fields without storing the whole document tree."""

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: List[Dict[str, Any]] = []
        self.card: Optional[Dict[str, Any]] = None
        self.stack: List[tuple[str, set[str]]] = []
        self.capture: Optional[str] = None
        self.capture_tag: Optional[str] = None
        self.capture_depth = -1
        self.capture_parts: List[str] = []

    @staticmethod
    def _attrs(attrs: List[tuple[str, Optional[str]]]) -> Dict[str, str]:
        return {name: value or "" for name, value in attrs}

    def _inside(self, class_name: str) -> bool:
        return any(class_name in classes for _, classes in self.stack)

    def _begin_capture(self, field: str, tag: str) -> None:
        if self.capture is None:
            self.capture = field
            self.capture_tag = tag
            self.capture_depth = len(self.stack)
            self.capture_parts = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        values = self._attrs(attrs)
        classes = set(values.get("class", "").split())
        if tag == "li" and "item-wrap" in classes and self.card is None:
            card_id = values.get("id", "")
            self.card = {
                "product_id": card_id,
                "title": "",
                "review_count_display": "",
                "store_name": "",
                "selling_point": "",
                "product_url": "",
                "image_url": "",
                "is_sponsored": card_id.endswith("-gg"),
            }

        if self.card is None:
            if tag not in self.VOID_TAGS:
                self.stack.append((tag, classes))
            return

        self.stack.append((tag, classes))
        href = values.get("href", "")
        if tag == "a" and self._inside("title-selling-point"):
            self.card["product_url"] = absolute_url(href)
            if "th.suning.com/calCpcClicks" in href:
                self.card["is_sponsored"] = True
            self._begin_capture("title", tag)
        elif tag == "a" and "store-name" in classes:
            self._begin_capture("store_name", tag)
        elif tag == "i" and self._inside("info-evaluate"):
            self._begin_capture("review_count_display", tag)
        elif tag == "a" and "sellPoint" in classes and not self.card["selling_point"]:
            self.card["selling_point"] = clean_text(values.get("title"), 200)
        elif tag == "img" and self._inside("res-img") and not self.card["image_url"]:
            self.card["image_url"] = absolute_url(values.get("src") or values.get("data-src") or "")
            if not self.card["title"]:
                self.card["image_alt"] = clean_text(values.get("alt"), 500)

        if tag in self.VOID_TAGS:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.card is not None and self.capture is not None:
            if not (self.capture == "title" and self.stack and self.stack[-1][0] == "em"):
                self.capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.card is not None and self.capture is not None:
            if tag == self.capture_tag and len(self.stack) == self.capture_depth:
                self.card[self.capture] = clean_text(" ".join(self.capture_parts), 500)
                self.capture = None
                self.capture_tag = None
                self.capture_depth = -1
                self.capture_parts = []

        matching_index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if matching_index is not None:
            root_item_ending = (
                self.card is not None
                and tag == "li"
                and "item-wrap" in self.stack[matching_index][1]
            )
            del self.stack[matching_index:]
            if root_item_ending:
                if not self.card["title"]:
                    self.card["title"] = self.card.pop("image_alt", "")
                else:
                    self.card.pop("image_alt", None)
                self.cards.append(self.card)
                self.card = None


def parse_cards(document: str) -> List[Dict[str, Any]]:
    parser = ProductCardParser()
    parser.feed(document)
    return parser.cards


PRICE_SCRIPT = """
elements => Object.fromEntries(elements.map(card => [
  card.id,
  (card.querySelector('.def-price')?.textContent || '').trim()
]))
"""


def fetch_browser_snapshot(url: str, timeout_ms: int) -> tuple[str, int, Dict[str, str]]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SuningCollectorError(
            "缺少 Playwright。请先运行 scripts/Install-Browser-Collector.ps1"
        ) from error

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                user_agent=USER_AGENT,
            )
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if response is None or response.status != 200:
                raise SuningCollectorError("Edge 未能加载苏宁公开搜索页")
            try:
                document = response.body().decode("utf-8")
            except UnicodeDecodeError as error:
                raise SuningCollectorError("苏宁页面编码不是预期的 UTF-8") from error
            if "id=\"product-list\"" not in document:
                raise SuningCollectorError("响应中没有公开商品列表，可能触发限制或页面已改版")
            page.locator("#product-list li.item-wrap").first.wait_for(state="attached", timeout=timeout_ms)
            page_height = page.evaluate("document.body.scrollHeight")
            for y in range(0, int(page_height), 800):
                page.evaluate("y => window.scrollTo(0, y)", y)
                page.wait_for_timeout(200)
            page.wait_for_timeout(3_000)
            prices = page.locator("#product-list li.item-wrap").evaluate_all(PRICE_SCRIPT)
            status = response.status
            context.close()
            browser.close()
            return document, status, prices
    except SuningCollectorError:
        raise
    except PlaywrightError as error:
        raise SuningCollectorError(f"价格渲染失败：{error}") from error


def parse_price(value: Any) -> Optional[float]:
    text = clean_text(value, 100).replace(",", "")
    match = re.search(r"(\d+(?:\.\d{1,2})?)", text)
    return float(match.group(1)) if match else None


def parse_review_lower_bound(value: Any) -> int:
    match = re.search(r"\d+", clean_text(value, 100).replace(",", ""))
    return int(match.group()) if match else 0


def extract_materials(text: str) -> List[str]:
    aliases = {
        "304不锈钢": ("304不锈钢", "304"),
        "316不锈钢": ("316L", "SUS316", "316不锈钢", "316"),
        "纯钛": ("纯钛", "TA1", "钛金属"),
        "陶瓷": ("陶瓷",),
        "玻璃": ("玻璃",),
    }
    return [name for name, terms in aliases.items() if any(term.lower() in text.lower() for term in terms)]


def extract_capacity(text: str) -> Optional[int]:
    match = re.search(r"(?<!\d)(\d{2,4})\s*(?:ml|毫升)(?!\w)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    return value if 30 <= value <= 10_000 else None


def normalize_product(
    raw: Mapping[str, Any],
    price_text: str,
    rank: int,
    source_url: str,
    collected_at: str,
) -> SuningProduct:
    product_id = clean_text(raw.get("product_id"), 200)
    title = clean_text(raw.get("title"), 500)
    product_url = clean_text(raw.get("product_url"), 2_000)
    parsed = urlparse(product_url)
    if not product_id or not title:
        raise SuningCollectorError("商品卡缺少 product_id 或 title")
    if parsed.scheme != "https" or parsed.hostname not in {"product.suning.com", "th.suning.com"}:
        raise SuningCollectorError("商品卡包含非苏宁商品地址")
    numeric_parts = re.findall(r"\d+", product_id)
    sku_id = numeric_parts[1] if len(numeric_parts) > 1 else (numeric_parts[0] if numeric_parts else product_id)
    return SuningProduct(
        rank=rank,
        product_id=product_id,
        sku_id=sku_id,
        title=title,
        price_cny=parse_price(price_text),
        review_count_lower_bound=parse_review_lower_bound(raw.get("review_count_display")),
        review_count_display=clean_text(raw.get("review_count_display"), 100),
        store_name=clean_text(raw.get("store_name"), 200),
        selling_point=clean_text(raw.get("selling_point"), 200),
        is_sponsored=bool(raw.get("is_sponsored")),
        mentioned_materials=extract_materials(title),
        capacity_ml=extract_capacity(title),
        product_url=product_url,
        image_url=clean_text(raw.get("image_url"), 2_000),
        source_url=source_url,
        source="suning_public_search",
        collected_at=collected_at,
    )


def collect(keyword: str, max_items: int, timeout: int) -> Dict[str, Any]:
    source_url = require_search_url(build_search_url(keyword))
    check_robots(source_url)
    document, status, prices = fetch_browser_snapshot(source_url, timeout * 1_000)
    raw_cards = parse_cards(document)
    if not raw_cards:
        raise SuningCollectorError("页面解析不到商品卡片，可能已改版")
    collected_at = datetime.now(timezone.utc).isoformat()
    items: List[SuningProduct] = []
    seen = set()
    errors = []
    for raw in raw_cards:
        if len(items) >= max_items:
            break
        try:
            item = normalize_product(
                raw,
                prices.get(clean_text(raw.get("product_id"), 200), ""),
                len(items) + 1,
                source_url,
                collected_at,
            )
        except SuningCollectorError as error:
            errors.append(str(error))
            continue
        if item.product_id in seen:
            continue
        seen.add(item.product_id)
        items.append(item)

    priced_items = sum(item.price_cny is not None for item in items)
    return {
        "schema_version": "1.0",
        "collection_mode": "public_search_low_rate",
        "source": "苏宁易购",
        "query": clean_text(keyword, 50),
        "source_url": source_url,
        "robots_url": ROBOTS_URL,
        "collected_at": collected_at,
        "http_status": status,
        "item_count": len(items),
        "priced_item_count": priced_items,
        "field_completeness": {
            "price": round(priced_items / len(items), 4) if items else 0,
            "store": round(sum(bool(item.store_name) for item in items) / len(items), 4) if items else 0,
            "reviews": round(sum(bool(item.review_count_display) for item in items) / len(items), 4) if items else 0,
        },
        "validation_errors": errors[:20],
        "items": [asdict(item) for item in items],
    }


def safe_csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    if not isinstance(value, str):
        return value
    value = re.sub(r"\s+", " ", value).strip()
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def write_outputs(output_directory: Path, payload: Dict[str, Any]) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    safe_query = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", payload["query"]).strip(" .-")[:50]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = output_directory / f"suning-{safe_query or 'products'}-{timestamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(SuningProduct.__dataclass_fields__)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in payload["items"]:
            writer.writerow({field: safe_csv_value(item.get(field, "")) for field in fields})
    return json_path, csv_path


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="苏宁公开搜索页低频商品采集器")
    parser.add_argument("keyword", help="搜索关键词，例如：保温杯")
    parser.add_argument("--max-items", type=int, default=30, choices=range(1, MAX_ITEMS + 1), metavar="1-30")
    parser.add_argument("--timeout", type=int, default=30, choices=range(10, 61), metavar="10-60")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        payload = collect(args.keyword, args.max_items, args.timeout)
        json_path, csv_path = write_outputs(args.output, payload)
    except SuningCollectorError as error:
        print(f"[suning-error] {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1
    print(
        f"采集完成：{payload['item_count']} 件商品，"
        f"其中 {payload['priced_item_count']} 件有页面展示价"
    )
    print(f"JSON：{json_path}")
    print(f"CSV ：{csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
