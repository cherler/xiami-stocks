"""条件编辑器里 27 个字段，13 个被永久判成"完整度不足" —— 而数据是齐的。

`_field_coverage` 原来只量一张**写死的 11 列名单**。名单外的字段
`coverage.get(name, 0.0)` 取到默认 0，`usable = 0 >= 50` 恒为假，
于是永久不可用，而给出的理由是"底座里完整度不足"——一句不成立的话。

2026-08-15 线上实测，被关掉的 13 个里有 9 个数据是齐的：

    annual_roe 99.0%   annual_gross_margin 98.1%   dividend_yield 65.3%
    rising_days 100%   above_ma60 100%   new_high_level 100%
    volume_days 100%   turnover_rate 93.7%   dividend_per_10 65.3%

代价是实打实的：用户说「净资产收益率高于 12%」，能筛的只剩**单季** roe。

    贵州茅台  单季 10.57  年报 32.53
    山西汾酒  单季 12.57  年报 33.48

按单季筛，汾酒进了、茅台被排除 —— 跟他要的东西正好相反。
而文档里那套「待数据的股息现金流型」策略也是这么"待"下来的。
"""

import pytest

from stock_decision.repository import (DERIVED_FIELDS, DERIVED_SOURCES,
                                       FIELD_LABELS, _field_coverage, screen_fields)
from stock_decision.database import connection


def _real_columns() -> set[str]:
    """库里 market_universe 真有哪些列。逐列试，不靠表里有行。"""
    out = set()
    with connection() as conn:
        for field in FIELD_LABELS:
            try:
                conn.execute(f"SELECT {field} FROM market_universe LIMIT 1").fetchone()
                out.add(field)
            except Exception:  # noqa: BLE001
                pass
    return out


def test_every_listed_field_is_actually_measured():
    """**列出来就要量。** 量不到的默认 0，而 0 会被说成"完整度不足"。"""
    columns = _real_columns()
    with connection() as conn:
        coverage, total = _field_coverage(conn)
    if not total:
        pytest.skip("底座是空的，覆盖度无从谈起（这条要在有数据的库上跑）")
    for field in FIELD_LABELS:
        if field in DERIVED_FIELDS or field not in columns:
            continue
        assert field in coverage, f"{field} 在条件编辑器里列着，却从来没被量过覆盖度"


def test_every_derived_field_declares_its_sources():
    """派生字段漏登记 = 走到按列名量覆盖那条路 = 量到 0 = 永久关掉。

    earnings_yield 和 pb_over_roe 就是这么被关掉的。
    """
    columns = _real_columns()
    for field in FIELD_LABELS:
        if field in columns:
            continue
        assert field in DERIVED_FIELDS, f"{field} 库里没有这一列，却没登记成派生字段"
        assert DERIVED_SOURCES.get(field), f"{field} 登记了派生但没写来源"


def test_a_field_with_data_is_not_reported_as_missing():
    """有数据就不该说"完整度不足"。这条盯的是那句话的真假。"""
    fields = {f["field"]: f for f in screen_fields()}
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM market_universe").fetchone()["n"]
        if not total:
            return                                  # 空库跑不了这条
        columns = _real_columns()
        for name, info in fields.items():
            if info["usable"] or name not in columns:
                continue
            filled = conn.execute(
                f"SELECT COUNT({name}) AS n FROM market_universe").fetchone()["n"]
            assert filled / total * 100 < 50, \
                f"{name} 实际覆盖 {filled/total*100:.1f}%，却被判成不可用"
