"""这家公司在同行业里站在哪个位置。

## 为什么要有这个

档案里已经有一堆数字：PE 21.3、ROE 26.4%、毛利率 89.9%。**但单看一个数字
是判断不了贵贱好坏的**——21 倍对白酒算便宜、对银行算贵得离谱；89% 的毛利率
在白酒里普通，在制造业里是不可能的。一个业余投资者面对孤零零一个数字，
只能去猜，或者去搜"多少算高"，而答案总是"看行业"。

所以这里不给绝对值的评价，给**位置**：全行业 N 家公司的这项指标铺开，
你在从低到高的第几分位。这个问题有唯一答案，不需要任何人的观点。

## 分位数怎么取

p10 / p25 / p50 / p75 / p90 五个点，画成一条带子：中间半数（p25–p75）深一点，
两侧（p10–p90）浅一点。**掐掉两端的 10%** 是必须的——A 股每个行业都有几家
PE 三千倍的（微利或亏损边缘），全量铺开的话整条带子会被它们拉成一根针，
所有正常公司挤在最左边一个点上，什么也看不出来。

## 哪些指标能这样比，哪些不能

只放**同行业内可比**的：估值（PE/PB）、盈利能力（ROE、毛利率）。
不放市值、不放涨跌幅——大小与近期走势跟"这家公司好不好"不是一回事，
放进来只会让人把"跌得多"读成"便宜"。

负的 PE / PB 直接排除而不是当成 0：亏损公司的市盈率没有"低"的含义，
它就是没有意义，混进分布里会把中位数整个拉偏。
"""

from __future__ import annotations

from typing import Any

from .database import connection

# (库里的列, 显示名, 单位, 越大越好?)
METRICS: tuple[tuple[str, str, str, bool], ...] = (
    ("pe_ttm", "市盈率 TTM", "倍", False),
    ("pb", "市净率", "倍", False),
    ("roe", "净资产收益率", "%", True),
    ("gross_margin", "毛利率", "%", True),
)

# 至少要这么多同行才画。样本太小的话分位数是噪声：
# 三家公司的"第 75 分位"不是一个有意义的说法。
_MIN_PEERS = 8


def _quantile(values: list[float], fraction: float) -> float:
    """线性插值分位数。不引 numpy —— 就为这一个函数不值得。"""
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def position(company: dict[str, Any]) -> dict[str, Any]:
    """这家公司四项指标各自在同行业里的位置。"""
    symbol = company["symbol"]
    with connection() as conn:
        row = conn.execute(
            "SELECT industry FROM market_universe WHERE symbol = ?", (symbol,)).fetchone()
        # 全市场底座里的行业分类才是比较的依据；档案里那个是自己填的，
        # 两边不一致时以底座为准，否则"同行"里会混进别的行业。
        industry = (row["industry"] if row else None) or (company.get("industry") or "")
        if not industry:
            return {"industry": "", "peers": 0, "metrics": [],
                    "note": "全市场底座里没有这家公司的行业分类，比不了。先同步一次全市场底座。"}

        columns = ", ".join(name for name, *_ in METRICS)
        rows = conn.execute(
            f"SELECT symbol, name, {columns} FROM market_universe WHERE industry = ?",
            (industry,)).fetchall()

    mine = next((r for r in rows if r["symbol"] == symbol), None)
    metrics: list[dict[str, Any]] = []
    for column, label, unit, higher_is_better in METRICS:
        values = sorted(
            float(r[column]) for r in rows
            # 负的估值倍数没有"低"的含义，混进分布会把中位数整个拉偏
            if r[column] is not None and (float(r[column]) > 0 or unit == "%")
        )
        if len(values) < _MIN_PEERS:
            continue
        value = None if mine is None or mine[column] is None else float(mine[column])
        below = sum(1 for v in values if v < value) if value is not None else 0
        metrics.append({
            "key": column,
            "label": label,
            "unit": unit,
            "higher_is_better": higher_is_better,
            "value": value,
            "percentile": round(below / len(values) * 100) if value is not None else None,
            "p10": round(_quantile(values, 0.10), 2),
            "p25": round(_quantile(values, 0.25), 2),
            "p50": round(_quantile(values, 0.50), 2),
            "p75": round(_quantile(values, 0.75), 2),
            "p90": round(_quantile(values, 0.90), 2),
            "sample": len(values),
        })

    return {
        "industry": industry,
        "peers": len(rows),
        "metrics": metrics,
        "note": (
            f"同行业 {len(rows)} 家公司的分布，数据来自全市场底座最近一次同步。"
            "分位说的是「在同行里排第几」，不是「该不该买」——"
            "同行整体贵的时候，排在便宜的一头照样可能是贵的。"
            if metrics else
            f"「{industry}」在底座里的同行不足 {_MIN_PEERS} 家，或者这几项指标都没有数据，分布画不出来。"
        ),
    }


# 同业表里放几家。全行业铺开没有意义——银行 42 家、化工上百家，
# 一屏看不完，而看不完的表跟没有一样。
_TABLE_LIMIT = 12

_TABLE_COLUMNS = ("total_market_cap", "pe_ttm", "pb", "roe", "gross_margin",
                  "revenue_growth", "net_profit_growth", "dividend_yield")


def table(company: dict[str, Any]) -> dict[str, Any]:
    """同一行业里真正的同行，按市值排，本公司高亮。

    ## 为什么换掉原来那份

    原来的「同业对照」比的是**研究池里恰好同行业的那几家**。那不是同业，
    是"我碰巧关注的几家"——茅台旁边站着的可能只有一家洋河，也可能一家都没有，
    比出来的高低完全取决于我自己加了谁。样本是自己挑的，结论就没有意义。

    现在取全市场底座里同行业的公司（5537 只的分类来自申万二级，
    比档案里那个证监会门类细得多：档案写「酒、饮料和精制茶制造业」，
    底座写「白酒Ⅱ」——后者才是能比的那个粒度）。

    ## 为什么按市值排、只取前 12

    全行业铺开没有意义：银行 42 家、化工上百家，一屏看不完，
    而看不完的表跟没有一样。按市值排是因为「行业里最大的那几家」是有确定含义的
    参照系——不像"涨得最多的几家"，那个每天都在变。

    本公司**一定在表里**，哪怕它排不进前 12：这张表是给它当参照的，
    主角不在场就白做了。
    """
    symbol = company["symbol"]
    with connection() as conn:
        row = conn.execute(
            "SELECT industry FROM market_universe WHERE symbol = ?", (symbol,)).fetchone()
        industry = (row["industry"] if row else None) or ""
        if not industry:
            return {"industry": "", "total": 0, "rows": [], "median": {},
                    "note": "全市场底座里没有这家公司的行业分类，比不了。先同步一次全市场底座。"}

        columns = ", ".join(_TABLE_COLUMNS)
        rows = [dict(r) for r in conn.execute(
            f"SELECT symbol, name, {columns} FROM market_universe WHERE industry = ?",
            (industry,)).fetchall()]

    ranked = sorted(rows, key=lambda r: -(r["total_market_cap"] or 0))
    top = ranked[:_TABLE_LIMIT]
    mine = next((r for r in ranked if r["symbol"] == symbol), None)
    # 本公司排不进前 12 也要在表里 —— 这张表是给它当参照的
    if mine is not None and mine not in top:
        top = top[: _TABLE_LIMIT - 1] + [mine]

    # 中位数按**全行业**算，不是按表里这 12 家算：表是截断过的，
    # 拿截断后的样本算中位数会系统性偏向大公司。
    median = {}
    for column in _TABLE_COLUMNS:
        values = sorted(float(r[column]) for r in rows
                        if r[column] is not None and (float(r[column]) > 0 or column not in ("pe_ttm", "pb")))
        median[column] = round(_quantile(values, 0.5), 2) if values else None

    return {
        "industry": industry,
        "total": len(rows),
        "rows": [{
            "symbol": r["symbol"],
            "name": r["name"],
            "is_self": r["symbol"] == symbol,
            **{c: (None if r[c] is None else round(float(r[c]), 2)) for c in _TABLE_COLUMNS},
        } for r in top],
        "median": median,
        "note": (f"「{industry}」全行业 {len(rows)} 家，这里按总市值列前 {len(top)} 家。"
                 "中位数按全行业算，不是按表里这几家——表是截断过的，"
                 "拿截断后的样本算中位数会系统性偏向大公司。"
                 "行业分类来自全市场底座（申万二级），比档案里的证监会门类细。"),
    }
