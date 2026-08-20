"""Low-rate browser collector for public SMZDM category insight pages.

This adapter intentionally avoids the search subdomain, login-only pages,
CAPTCHA solving, private APIs, and pagination. It collects one public category
snapshot and stops if a verification page is detected.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib import robotparser
from urllib.parse import urlparse


USER_AGENT = "ecommerce-crawler-lab/0.2"
ALLOWED_HOST = "www.smzdm.com"
ALLOWED_PATH_PREFIX = "/fenlei/"
ROBOTS_URL = "https://www.smzdm.com/robots.txt"
DEFAULT_CATEGORY_URL = "https://www.smzdm.com/fenlei/baowenbaolengbei/"


class PublicSourceError(RuntimeError):
    """Known and user-actionable public-source collection failure."""


@dataclass
class Insight:
    rank: int
    insight_id: str
    title: str
    excerpt: str
    likes: int
    favorites: int
    comments: int
    published_date: str
    mentioned_platforms: List[str]
    mentioned_prices_cny: List[float]
    mentioned_materials: List[str]
    mentioned_capacities_ml: List[int]
    article_url: str
    image_url: str
    source: str
    category: str
    collected_at: str


def clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def nonnegative_int(value: Any, field: str) -> int:
    text = clean_text(value, 30).replace(",", "")
    if not text:
        return 0
    try:
        result = int(text)
    except ValueError as error:
        raise PublicSourceError(f"字段 {field} 不是整数：{text}") from error
    if result < 0:
        raise PublicSourceError(f"字段 {field} 不能小于 0")
    return result


def require_public_category_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != ALLOWED_HOST:
        raise PublicSourceError("只允许 https://www.smzdm.com/fenlei/ 下的公开分类页")
    if not parsed.path.startswith(ALLOWED_PATH_PREFIX):
        raise PublicSourceError("目标必须是什么值得买公开分类页 /fenlei/...")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise PublicSourceError("分类地址不能包含查询参数、片段或身份信息")
    return value.rstrip("/") + "/"


def check_robots(url: str) -> None:
    parser = robotparser.RobotFileParser()
    parser.set_url(ROBOTS_URL)
    try:
        parser.read()
    except OSError as error:
        raise PublicSourceError(f"无法读取 robots.txt，已停止采集：{error}") from error
    if not parser.can_fetch(USER_AGENT, url):
        raise PublicSourceError("robots.txt 不允许当前采集器访问该分类页，已停止")


def extract_platforms(text: str) -> List[str]:
    aliases = {
        "京东": ("京东", "JD"),
        "淘宝": ("淘宝",),
        "天猫": ("天猫",),
        "拼多多": ("拼多多", "拼夕夕", "PDD", "pdd"),
        "苏宁": ("苏宁",),
        "闲鱼": ("闲鱼", "海鲜市场"),
        "小米有品": ("小米有品",),
    }
    return [name for name, terms in aliases.items() if any(term in text for term in terms)]


def extract_prices(text: str) -> List[float]:
    patterns = (
        r"(?:¥|￥)\s*(\d+(?:\.\d{1,2})?)",
        r"(?<!\d)(\d+(?:\.\d{1,2})?)\s*(?:元|块钱|块)(?!\d)",
    )
    values: List[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = float(match.group(1))
            if 0 < value <= 1_000_000 and value not in values:
                values.append(value)
    return values[:20]


def extract_materials(text: str) -> List[str]:
    aliases = {
        "304不锈钢": ("304不锈钢", "304"),
        "316不锈钢": ("316L", "SUS316", "316不锈钢", "316"),
        "纯钛": ("纯钛", "TA1", "钛金属"),
        "陶瓷涂层": ("陶瓷涂层",),
        "玻璃": ("玻璃",),
    }
    return [name for name, terms in aliases.items() if any(term.lower() in text.lower() for term in terms)]


def extract_capacities(text: str) -> List[int]:
    values: List[int] = []
    for match in re.finditer(r"(?<!\d)(\d{2,4})\s*(?:ml|毫升)(?!\w)", text, flags=re.IGNORECASE):
        value = int(match.group(1))
        if 30 <= value <= 10_000 and value not in values:
            values.append(value)
    return values[:20]


def article_id(url: str) -> str:
    match = re.search(r"/p/([^/?#]+)/?", url)
    if not match:
        raise PublicSourceError("文章地址缺少稳定 ID")
    return match.group(1)


def normalize_card(raw: Mapping[str, Any], rank: int, category: str, collected_at: str) -> Insight:
    title = clean_text(raw.get("title"), 300)
    excerpt = clean_text(raw.get("excerpt"), 2_000)
    article_url = clean_text(raw.get("article_url"), 1_000)
    parsed = urlparse(article_url)
    if not title or parsed.scheme != "https" or parsed.hostname != "post.smzdm.com":
        raise PublicSourceError("内容卡片缺少标题或有效的公开文章地址")
    combined = f"{title} {excerpt}"
    return Insight(
        rank=rank,
        insight_id=article_id(article_url),
        title=title,
        excerpt=excerpt,
        likes=nonnegative_int(raw.get("likes"), "likes"),
        favorites=nonnegative_int(raw.get("favorites"), "favorites"),
        comments=nonnegative_int(raw.get("comments"), "comments"),
        published_date=clean_text(raw.get("published_date"), 30),
        mentioned_platforms=extract_platforms(combined),
        mentioned_prices_cny=extract_prices(combined),
        mentioned_materials=extract_materials(combined),
        mentioned_capacities_ml=extract_capacities(combined),
        article_url=article_url,
        image_url=clean_text(raw.get("image_url"), 1_000),
        source="smzdm_public_category",
        category=clean_text(category, 100),
        collected_at=collected_at,
    )


CARD_SCRIPT = """
elements => elements.map(card => {
  const text = selector => (card.querySelector(selector)?.textContent || '').trim();
  const titleLink = card.querySelector('a.title-normal-box');
  const firstImage = card.querySelector('.shaiwu-card-container img, .zhuanzai-card-container img');
  return {
    title: text('a.title-normal-box'),
    excerpt: text('.content-normal-box-text'),
    likes: text('.thumb-box .num'),
    favorites: text('.collect-box .num'),
    comments: text('.critic-box .num'),
    published_date: text('.article-date-box'),
    article_url: titleLink?.href || '',
    image_url: firstImage?.currentSrc || firstImage?.src || ''
  };
})
"""


def collect_snapshot(
    category_url: str,
    category: str,
    max_items: int,
    headful: bool,
    timeout_ms: int,
) -> Dict[str, Any]:
    category_url = require_public_category_url(category_url)
    check_robots(category_url)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise PublicSourceError(
            "缺少 Playwright。请先运行 scripts/Install-Browser-Collector.ps1"
        ) from error

    collected_at = datetime.now(timezone.utc).isoformat()
    raw_cards: List[Dict[str, Any]] = []
    status = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=not headful)
            context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
            page = context.new_page()
            response = page.goto(category_url, wait_until="domcontentloaded", timeout=timeout_ms)
            status = response.status if response else None
            try:
                page.locator(".feed-page-container").first.wait_for(state="visible", timeout=timeout_ms)
            except PlaywrightError as error:
                body = clean_text(page.locator("body").inner_text(), 500)
                raise PublicSourceError(
                    f"未出现公开内容卡片，可能触发验证或页面已改版（HTTP {status}）：{body}"
                ) from error
            body_text = clean_text(page.locator("body").inner_text(), 2_000)
            if any(term in body_text for term in ("验证码", "安全验证", "访问验证", "拖动滑块")):
                raise PublicSourceError("页面出现安全验证，采集器按规则停止；请勿自动绕过")
            raw_cards = page.locator(".feed-page-container").evaluate_all(CARD_SCRIPT)
            context.close()
            browser.close()
    except PublicSourceError:
        raise
    except PlaywrightError as error:
        raise PublicSourceError(f"浏览器采集失败：{error}") from error

    items: List[Insight] = []
    seen = set()
    validation_errors = []
    for raw in raw_cards:
        if len(items) >= max_items:
            break
        try:
            item = normalize_card(raw, len(items) + 1, category, collected_at)
        except PublicSourceError as error:
            validation_errors.append(str(error))
            continue
        if item.insight_id in seen:
            continue
        seen.add(item.insight_id)
        items.append(item)

    return {
        "schema_version": "1.0",
        "collection_mode": "public_category_browser_snapshot",
        "source": "什么值得买",
        "category": category,
        "source_url": category_url,
        "robots_url": ROBOTS_URL,
        "collected_at": collected_at,
        "http_status": status,
        "item_count": len(items),
        "validation_errors": validation_errors[:20],
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
    safe_category = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", payload["category"]).strip(" .-")[:50]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = output_directory / f"smzdm-{safe_category or 'category'}-{timestamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(Insight.__dataclass_fields__)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in payload["items"]:
            writer.writerow({field: safe_csv_value(item.get(field, "")) for field in fields})
    return json_path, csv_path


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="什么值得买公开分类消费者洞察采集器")
    parser.add_argument("--category", default="保温杯", help="输出中的分类名称")
    parser.add_argument("--url", default=DEFAULT_CATEGORY_URL, help="公开 /fenlei/ 分类地址")
    parser.add_argument("--max-items", type=int, default=30, choices=range(1, 31), metavar="1-30")
    parser.add_argument("--headful", action="store_true", help="显示 Edge 浏览器，便于诊断")
    parser.add_argument("--timeout", type=int, default=25, choices=range(5, 61), metavar="5-60")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        payload = collect_snapshot(
            category_url=args.url,
            category=args.category,
            max_items=args.max_items,
            headful=args.headful,
            timeout_ms=args.timeout * 1_000,
        )
        json_path, csv_path = write_outputs(args.output, payload)
    except PublicSourceError as error:
        print(f"[public-source-error] {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"采集完成：{payload['item_count']} 条国内消费洞察")
    print(f"JSON：{json_path}")
    print(f"CSV ：{csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
