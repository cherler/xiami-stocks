"""本地数据比代码旧了没有。

## 为什么需要这个

同一天里被同一个问题卡了两次，根因都不是代码：

1. 方法体检报「缺营业成本、应收、存货，九问打分只能答五项」——我以为要换数据源。
   实测数据源好好的，102 期全部字段都有值。**是库里那批数据在这些字段被加进代码
   之前同步的。** 重新同步一次就补上了，效果立竿见影：九问打分从「判不了」变成
   「四项恶化，只能拿 4-5 分」。
2. 五个选股策略全部筛出 0 家——看上去像条件太严。实际是 `annual_roe`、
   `annual_gross_margin`、`dividend_yield` 三列全库为空，而每个策略都至少依赖其中之一。

**这两次的共同点是「看不出来」。** 表上有 102 期财报、5535 只股票，数量看着很齐全；
缺的是列，而列缺了不会报错，只会让下游的判断悄悄失去依据——然后表现成
「模型说数据不足」或「策略太严」，把人引向完全错误的方向。

## 判定方式

不猜、不记时间戳，直接数：**这一列在这张表里有几行不是 NULL**。
一列的填充率接近 0，而代码里明明在写它，那就是数据比代码旧。

阈值定在 5%：完全为 0 是典型的「加了列没重灌」，而个别行业天然没有某些科目
（银行没有营业成本和存货，实测平安与工行 89 期全空），留一点余量避免把行业差异
报成故障。
"""

from __future__ import annotations

from typing import Any

from .database import connection

# 代码会填、因此期望有值的列。**加了新字段要同步加到这里**，
# 否则它缺了照样没人知道——那正是这个模块要解决的问题。
EXPECTED: dict[str, tuple[str, ...]] = {
    "financial_periods": (
        "revenue", "net_profit", "operating_cash_flow", "operating_cost",
        "total_assets", "total_liabilities", "equity",
        "receivables", "inventory", "interest_bearing_debt", "rnd_expense", "capex",
    ),
    "market_universe": (
        "pe_ttm", "pb", "roe", "gross_margin", "revenue_growth", "net_profit_growth",
        "annual_roe", "annual_gross_margin", "dividend_yield", "total_market_cap",
    ),
}

# 低于这个填充率就算「基本没有」。留余量是因为个别行业天然缺某些科目：
# 银行没有营业成本和存货（实测平安、工行 89 期全空），那不是故障。
_EMPTY_RATIO = 0.05


def check() -> dict[str, Any]:
    """逐列数填充率，报出「代码在写但库里基本没有」的那些。"""
    findings: list[dict[str, Any]] = []
    with connection() as conn:
        for table, columns in EXPECTED.items():
            total = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            if not total:
                continue
            for column in columns:
                filled = conn.execute(f"SELECT count({column}) AS n FROM {table}").fetchone()["n"]
                ratio = filled / total
                if ratio < _EMPTY_RATIO:
                    findings.append({
                        "table": table, "column": column,
                        "filled": filled, "total": total,
                        "ratio": round(ratio * 100, 1),
                    })

    by_table: dict[str, list[str]] = {}
    for item in findings:
        by_table.setdefault(item["table"], []).append(item["column"])

    hints = {
        "financial_periods": "在公司档案的「财务」页点「更新财务数据」，或跑一次「定期报告」同步作业。",
        "market_universe": "在价值候选页点「重算估值字段」，或跑一次「全市场底座」同步作业。",
    }
    return {
        "stale": bool(findings),
        "findings": findings,
        "actions": [{"table": table, "columns": columns, "how": hints.get(table, "重新同步一次")}
                    for table, columns in by_table.items()],
        "note": ("这些列代码里在写，库里却基本没有——多半是数据在这些字段加进代码之前同步的。"
                 "缺列不会报错，只会让下游判断悄悄失去依据，然后表现成「模型说数据不足」"
                 "或「策略筛不出东西」。"
                 if findings else "代码期望的列都有数据。"),
    }
