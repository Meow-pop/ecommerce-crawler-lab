"""Deterministic evidence-linked market report for normalized product data."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


class ReportError(RuntimeError):
    """Invalid or incomplete research payload."""


def money(value: float) -> str:
    return f"¥{value:,.2f}"


def price_band(value: float) -> str:
    if value < 50:
        return "50元以下"
    if value < 100:
        return "50–99元"
    if value < 200:
        return "100–199元"
    return "200元及以上"


def markdown_table(headers: List[str], rows: Iterable[Iterable[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    rendered = ["| " + " | ".join(map(cell, headers)) + " |"]
    rendered.append("| " + " | ".join("---" for _ in headers) + " |")
    rendered.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(rendered)


def require_payload(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    if payload.get("schema_version") != "1.0":
        raise ReportError("只支持 schema_version 1.0")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ReportError("数据集中没有商品")
    valid = [item for item in items if isinstance(item, dict) and item.get("title")]
    if not valid:
        raise ReportError("数据集中没有有效商品")
    return valid


def build_report(payload: Mapping[str, Any]) -> str:
    items = require_payload(payload)
    query = str(payload.get("query") or "未命名关键词")
    prices = [float(item["price_cny"]) for item in items if item.get("price_cny") is not None]
    if not prices:
        raise ReportError("没有可用于价格分析的商品")

    band_counts = Counter(price_band(value) for value in prices)
    store_counts = Counter(str(item.get("store_name") or "未展示店铺") for item in items)
    material_counts = Counter(
        material
        for item in items
        for material in item.get("mentioned_materials", [])
        if material
    )
    capacity_counts = Counter(
        int(item["capacity_ml"])
        for item in items
        if item.get("capacity_ml") is not None
    )
    sponsored_count = sum(bool(item.get("is_sponsored")) for item in items)
    completeness = payload.get("field_completeness") or {}
    top_products = sorted(
        items,
        key=lambda item: (int(item.get("review_count_lower_bound") or 0), -int(item.get("rank") or 0)),
        reverse=True,
    )[:5]

    lines = [
        f"# “{query}”国内电商市场快照",
        "",
        f"> 数据源：{payload.get('source', '未知')}公开搜索首屏  ",
        f"> 采集时间：{payload.get('collected_at', '未知')}  ",
        f"> 样本量：{len(items)} 件；该报告描述当前公开样本，不代表平台完整销量。",
        "",
        "## 结论摘要",
        "",
        f"- 展示价中位数为 **{money(statistics.median(prices))}**，范围为 **{money(min(prices))}–{money(max(prices))}**。",
        f"- 最大价格带是 **{band_counts.most_common(1)[0][0]}**，包含 {band_counts.most_common(1)[0][1]} 件商品。",
        f"- 首屏广告/推广卡片 {sponsored_count} 件，占样本的 {sponsored_count / len(items):.1%}。",
        f"- 店铺集中度：出现最多的店铺占 {store_counts.most_common(1)[0][1] / len(items):.1%}；分析竞品时应避免把首屏排序误当成市场份额。",
        "",
        "## 价格带",
        "",
        markdown_table(
            ["价格带", "商品数", "占有率"],
            (
                [band, band_counts.get(band, 0), f"{band_counts.get(band, 0) / len(prices):.1%}"]
                for band in ("50元以下", "50–99元", "100–199元", "200元及以上")
            ),
        ),
        "",
        "## 店铺、材质与容量信号",
        "",
        markdown_table(
            ["店铺", "首屏商品数"],
            ([name, count] for name, count in store_counts.most_common(8)),
        ),
        "",
        markdown_table(
            ["标题中明确提及的材质", "商品数"],
            ([name, count] for name, count in material_counts.most_common()) or [["未明确提及", 0]],
        ),
        "",
        markdown_table(
            ["标题中明确提及的容量", "商品数"],
            ([f"{capacity} ml", count] for capacity, count in capacity_counts.most_common(10))
            or [["未明确提及", 0]],
        ),
        "",
        "## 评价信号较高的商品",
        "",
        markdown_table(
            ["商品", "价格", "评价下限", "店铺", "证据"],
            (
                [
                    item.get("title", ""),
                    money(float(item["price_cny"])) if item.get("price_cny") is not None else "未展示",
                    item.get("review_count_display") or "未展示",
                    item.get("store_name") or "未展示",
                    f"[商品页]({item.get('product_url', '')})",
                ]
                for item in top_products
            ),
        ),
        "",
        "## 数据质量",
        "",
        markdown_table(
            ["字段", "完整率"],
            [
                ["价格", f"{float(completeness.get('price', 0)):.1%}"],
                ["店铺", f"{float(completeness.get('store', 0)):.1%}"],
                ["评价", f"{float(completeness.get('reviews', 0)):.1%}"],
            ],
        ),
        "",
        "## 使用边界",
        "",
        "- 展示价可能受地区、促销、库存和采集时间影响。",
        "- 评价数中的“+”表示下限，不应当作精确值。",
        "- 标题未提及材质或容量不等于商品没有该属性。",
        "- 本报告不含成交量，不能据此计算真实市场份额。",
        f"- 原始来源：[苏宁公开搜索页]({payload.get('source_url', '')})。",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成可追溯的国内市场调研 Markdown 报告")
    parser.add_argument("input", type=Path, help="苏宁采集器输出的 JSON")
    parser.add_argument("--output", type=Path, help="报告路径；默认与输入同名并添加 .report.md")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        payload: Dict[str, Any] = json.loads(args.input.read_text(encoding="utf-8"))
        report = build_report(payload)
        output = args.output or args.input.with_suffix(".report.md")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    except (OSError, json.JSONDecodeError, ReportError) as error:
        print(f"[report-error] {error}")
        return 2
    print(f"市场报告：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
