"""做 T 的规律检验与机器模拟。

## 这个模块要回答的那一句话

> 格力每天一涨一跌，我没做 T，是不是少赚了？

**「没做 T」不等于「少赚」，它可能只是少交易了。** 差别在于：那条"一天涨一天跌"
的规律到底存不存在；就算存在，赚到的够不够付手续费和印花税。

这两问都不需要判断力，只需要数数。所以这一整个模块**不调模型**，
只有算术；每个数字都能拿同一份日线自己复核一遍。

## 为什么本仓原来写着"不做回测"

`docs/agentpickerplan.md` 第七节写着不做回测，理由是「没有历史行情的完整快照，
回测出来的数字会比真实情况好看得多」。那句话针对的是**选股策略回测**——
在全市场里回头挑股票，幸存者偏差、停牌、退市、前复权口径全都会让结果虚高。

这里做的是另一件事：**一只已经在你手上的股票，它自己的日线**。
没有选择的余地，也就没有可以作弊的余地。

但仍有三件必须说清楚的事，它们全部写进返回值里、显示在页面上：

1. **日线只有四个价**（开、高、低、收）。盘中任何一笔成交都看不见，
   所以模拟里的买卖只能发生在开盘或收盘，不能假装"我会在 38.10 接住"。
2. **前复权序列会随着每次分红送股整体重算**。历史上某一天的复权价
   跟当天真实的报价不一样，做 T 的绝对收益因此只能当量级看，不能当账算。
3. **T+1**。A 股当天买进的不能当天卖出，所以做 T 只有两种合法形态，
   两种都要求你本来就有底仓（见下面 STRATEGIES 的说明）。

## 天花板策略是这个模块最有用的东西

`oracle` 每天都在**当日最低点买、最高点卖**——没有人能做到，
它也不打算让人做到。它的用处是给"做 T 这件事"定一个上限：

> 就算你每一天都神操作，一年下来扣掉成本还剩多少？

如果连这个上限都不够看，那么"我没做 T 少赚了"这句话从根上就是假的，
后面所有的策略调参都不必开始。**先量天花板，再谈手艺。**
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

# 一年按 242 个交易日折年化。A 股近十年实际在 242~245 之间，取下限偏保守。
TRADING_DAYS_PER_YEAR = 242

# 允许的回看窗口（交易日）。`0` = 有多少用多少。
WINDOWS = (120, 250, 500, 0)


# ── 成本 ────────────────────────────────────────────────────────────────────
#
# 默认值按 2026 年散户常见档位写，**每一项都标了口径**，页面上可改。
# 把成本写死在代码里是这类工具最容易犯的错：费率差一倍，结论会反过来。
DEFAULT_COSTS: dict[str, float] = {
    # 佣金：双边收，万 2.5 是目前常见档；券商普遍有单笔最低 5 元。
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    # 印花税：**只在卖出时收**，千分之一（2023-08-28 起由千一减半为万五，
    # 这里留 0.0005）。
    "stamp_tax_rate": 0.0005,
    # 过户费：沪深两市都按成交金额万分之0.1 双边收。
    "transfer_fee_rate": 0.00001,
    # 冲击成本 / 滑点：默认 0，因为它不是一个可以查到的费率，是你自己的估计。
    # **默认给 0 是刻意的**——给一个编出来的滑点，会让结论看起来更精确，
    # 而它其实只是我随手填的数。要算就自己填。
    "slippage_rate": 0.0,
}

COST_LABELS: dict[str, str] = {
    "commission_rate": "佣金费率（双边）",
    "commission_min": "单笔最低佣金（元）",
    "stamp_tax_rate": "印花税（仅卖出）",
    "transfer_fee_rate": "过户费（双边）",
    "slippage_rate": "滑点 / 冲击成本（你自己估）",
}


def _cost(side: str, amount: float, costs: dict[str, float]) -> float:
    """一笔成交的全部费用。side 取 'buy' / 'sell'。"""
    if amount <= 0:
        return 0.0
    fee = max(amount * costs["commission_rate"], costs["commission_min"])
    fee += amount * costs["transfer_fee_rate"]
    fee += amount * costs["slippage_rate"]
    if side == "sell":
        fee += amount * costs["stamp_tax_rate"]
    return fee


# ── 统计工具 ────────────────────────────────────────────────────────────────


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def binomial_p_value(k: int, n: int, p0: float) -> float | None:
    """双侧精确二项检验。

    判据跟 R 的 `binom.test` 一致：把所有「出现概率不高于实际观测值」的结果
    的概率加起来。**不用正态近似**——条件样本常常只有几十个，
    近似在那个规模上会把 0.08 算成 0.04，而结论正好卡在这条线上。

    返回 None 表示样本不足以做检验（n < 10）。
    """
    if n < 10 or not 0.0 < p0 < 1.0:
        return None
    observed = _log_binom_pmf(k, n, p0)
    # 浮点容差：等概率的对侧尾巴会因为最后一位的误差被漏掉。
    threshold = observed + 1e-9
    total = 0.0
    for i in range(n + 1):
        value = _log_binom_pmf(i, n, p0)
        if value <= threshold:
            total += math.exp(value)
    return min(1.0, total)


def _autocorrelation(values: Sequence[float], lag: int = 1) -> float | None:
    """滞后 lag 的自相关系数。

    **这是整份统计里最该先看的一个数。** 「一天涨一天跌」用人话说就是
    「今天的涨跌跟昨天反着来」，翻成数字就是一阶自相关为负。
    它显著为负才谈得上有规律；贴着 0 的话，你看到的是随机序列长出来的花纹——
    随机序列**一定**会长出花纹，这是它的性质，不是它的例外。
    """
    n = len(values)
    if n <= lag + 2:
        return None
    mean = sum(values) / n
    denominator = sum((v - mean) ** 2 for v in values)
    if denominator <= 0:
        return None
    numerator = sum((values[i] - mean) * (values[i + lag] - mean) for i in range(n - lag))
    return numerator / denominator


def _stdev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _runs(signs: Sequence[int]) -> dict[str, Any]:
    """最长连涨 / 连跌，以及各长度连续段出现了几次。"""
    up_runs: list[int] = []
    down_runs: list[int] = []
    current, length = 0, 0
    for sign in signs:
        if sign == current and sign != 0:
            length += 1
            continue
        if current > 0 and length:
            up_runs.append(length)
        elif current < 0 and length:
            down_runs.append(length)
        current, length = sign, (1 if sign != 0 else 0)
    if current > 0 and length:
        up_runs.append(length)
    elif current < 0 and length:
        down_runs.append(length)

    def histogram(runs: list[int]) -> list[dict[str, int]]:
        counts: dict[int, int] = {}
        for run in runs:
            counts[run] = counts.get(run, 0) + 1
        return [{"length": k, "times": counts[k]} for k in sorted(counts)]

    return {
        "max_up": max(up_runs, default=0),
        "max_down": max(down_runs, default=0),
        "up_histogram": histogram(up_runs),
        "down_histogram": histogram(down_runs),
    }


# ── 日线预处理 ──────────────────────────────────────────────────────────────


def prepare(bars: Iterable[dict[str, Any]], window: int = 250) -> list[dict[str, Any]]:
    """按日期升序排好，算出每日涨跌幅与振幅，截到窗口长度。

    涨跌幅一律**自己用相邻收盘价算**，不读 price_bars 里那一列：
    那一列只有最近一成的行有值（实测 990171 行里 116880 行非空），
    混着用会让窗口里一半的日子悄悄消失。前复权序列的相邻收盘价本来就可比，
    自己算反而是更完整、更一致的那一份。
    """
    rows = [b for b in bars if b.get("trade_date") and isinstance(b.get("close"), (int, float))]
    rows.sort(key=lambda b: str(b["trade_date"]))
    out: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        close = float(row["close"])
        if close <= 0:
            previous = None
            continue
        item: dict[str, Any] = {
            "date": str(row["trade_date"])[:10],
            "close": close,
            "open": float(row["open_price"]) if isinstance(row.get("open_price"), (int, float)) else None,
            "high": float(row["high"]) if isinstance(row.get("high"), (int, float)) else None,
            "low": float(row["low"]) if isinstance(row.get("low"), (int, float)) else None,
        }
        if previous is not None and previous["close"] > 0:
            item["return"] = close / previous["close"] - 1.0
            item["prev_close"] = previous["close"]
            if item["high"] is not None and item["low"] is not None:
                item["amplitude"] = (item["high"] - item["low"]) / previous["close"]
        previous = item
        out.append(item)
    # 第一根没有前收，算不出涨跌幅，不进窗口。
    out = [row for row in out if "return" in row]
    if window and len(out) > window:
        out = out[-window:]
    return out


def _is_locked(row: dict[str, Any]) -> bool:
    """一字板：全天只有一个价，挂单成交不了。

    判法是 high == low 而不是"涨跌幅到 9.9%"——后者在 ST 股（±5%）
    和创业板科创板（±20%）上各是一个数，而 high == low 对哪个板都成立，
    也顺便把停牌后复牌当天那种极端行情一起挡住。
    """
    return (row.get("high") is not None and row.get("low") is not None
            and abs(row["high"] - row["low"]) < 1e-9)


# ── 一、规律检验 ────────────────────────────────────────────────────────────


def rhythm(bars: Iterable[dict[str, Any]], window: int = 250) -> dict[str, Any]:
    """「一天涨一天跌」到底成不成立。

    只回答事实，不给建议。判词也只有三种：样本不足 / 看不出规律 / 有统计意义
    的反转倾向——**最后一种仍然不等于"可以做 T"**，能不能做要看下面的模拟
    扣完成本还剩什么。
    """
    rows = prepare(bars, window)
    n = len(rows)
    if n < 30:
        return {
            "enough": False,
            "days": n,
            "note": f"只有 {n} 个交易日的日线，判断不了任何节奏。至少要 30 天，看得准要 120 天以上。",
        }

    returns = [row["return"] for row in rows]
    signs = [1 if r > 0 else (-1 if r < 0 else 0) for r in returns]
    ups = sum(1 for s in signs if s > 0)
    downs = sum(1 for s in signs if s < 0)
    flats = n - ups - downs

    base_up = ups / n
    base_down = downs / n

    # 条件概率：今天涨 → 明天跌；今天跌 → 明天涨。
    # **分母只数"下一天存在"的那些天**，最后一天没有明天。
    after_up_total = sum(1 for i in range(n - 1) if signs[i] > 0)
    after_up_down = sum(1 for i in range(n - 1) if signs[i] > 0 and signs[i + 1] < 0)
    after_down_total = sum(1 for i in range(n - 1) if signs[i] < 0)
    after_down_up = sum(1 for i in range(n - 1) if signs[i] < 0 and signs[i + 1] > 0)

    def conditional(hits: int, total: int, base: float, label: str) -> dict[str, Any]:
        rate = hits / total if total else None
        return {
            "label": label,
            "hits": hits,
            "total": total,
            "rate": rate,
            "base": base,
            # 提升：条件概率比"什么都不看"的基准高出多少个百分点。
            # **基准是这里的关键**：A 股任何一只票的次日下跌概率本来就接近 50%，
            # 「涨完之后 52% 会跌」听起来像规律，跟 51% 的基准比就什么都不是。
            "lift": (rate - base) if rate is not None else None,
            "p_value": binomial_p_value(hits, total, base) if total else None,
        }

    rho1 = _autocorrelation(returns, 1)
    rho2 = _autocorrelation(returns, 2)

    amplitudes = [row["amplitude"] for row in rows if row.get("amplitude") is not None]
    daily_sigma = _stdev(returns)

    def annualised(values: Sequence[float]) -> float | None:
        sigma = _stdev(values)
        return sigma * math.sqrt(TRADING_DAYS_PER_YEAR) if sigma is not None else None

    reversal = conditional(after_up_down, after_up_total, base_down, "今天涨 → 明天跌")
    rebound = conditional(after_down_up, after_down_total, base_up, "今天跌 → 明天涨")

    # 判词。**两个检验一起看的时候门槛要收紧**：同时问两个问题，
    # 只要有一个碰巧落在 5% 以内的概率接近 10%。所以这里用 0.025（Bonferroni）。
    alpha = 0.025
    significant = [c for c in (reversal, rebound)
                   if c["p_value"] is not None and c["p_value"] < alpha and (c["lift"] or 0) > 0]
    rho_negative = rho1 is not None and rho1 < -0.1

    # **自相关算不出来是一种真实情况，不是一个不可能。**
    #
    # 每日涨跌幅方差为 0 时（整段窗口一个价没动过——长期停牌复牌、
    # 极端冷门股，或者一段被前复权抹平的历史）`_autocorrelation` 返回 None，
    # 而下面三句判词全都直接 `f"{rho1:.3f}"`，当场
    # `TypeError: unsupported format string passed to NoneType.__format__`。
    # 整个接口 500，而页面上只会看到「请求失败」。
    rho_text = "算不出来（这段窗口里价格没有波动）" if rho1 is None else f"{rho1:.3f}"

    if significant and rho_negative:
        verdict = "有反转倾向"
        headline = (f"这 {n} 个交易日里，{'、'.join(c['label'] for c in significant)}"
                    f"确实比基准高，一阶自相关 {rho_text} 也是负的——**两个口径对上了**。")
    elif significant:
        verdict = "证据不一致"
        headline = (f"条件概率看着偏高（{significant[0]['label']}），但一阶自相关是 "
                    f"{rho_text}，**没有跟着往负的走**。两个口径对不上的时候，别当规律用。")
    else:
        verdict = "看不出规律"
        headline = (f"这 {n} 个交易日里，涨跌交替的频率跟随机序列没有可区分的差别"
                    f"（一阶自相关 {rho_text}）。你看到的「一天涨一天跌」，"
                    f"是随机序列本来就会长出来的花纹。")

    return {
        "enough": True,
        "days": n,
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "verdict": verdict,
        "headline": headline,
        "up_days": ups,
        "down_days": downs,
        "flat_days": flats,
        "base_up": base_up,
        "base_down": base_down,
        "reversal": reversal,
        "rebound": rebound,
        "alpha": alpha,
        "autocorrelation_1": rho1,
        "autocorrelation_2": rho2,
        "mean_abs_return": sum(abs(r) for r in returns) / n,
        "mean_amplitude": (sum(amplitudes) / len(amplitudes)) if amplitudes else None,
        "amplitude_days": len(amplitudes),
        "daily_sigma": daily_sigma,
        "volatility_5d": annualised(returns[-5:]) if len(returns) >= 5 else None,
        "volatility_20d": annualised(returns[-20:]) if len(returns) >= 20 else None,
        "volatility_window": annualised(returns),
        "runs": _runs(signs),
    }


# ── 二、机器模拟 ────────────────────────────────────────────────────────────

STRATEGIES: dict[str, dict[str, Any]] = {
    "reverse_t": {
        "label": "反 T（先卖后买）",
        "needs_open": True,
        "blurb": "昨天涨够了，今天开盘卖掉一部分底仓，收盘再买回来。仓位当天回到原样。",
        "why": "这是 T+1 下唯一能在「涨完之后」动手的形态——卖的是昨天就有的票。",
    },
    "forward_t": {
        "label": "正 T（先买后卖）",
        "needs_open": True,
        "blurb": "昨天跌够了，今天开盘买一份，收盘卖掉等量的底仓。仓位当天回到原样。",
        "why": "当天买进的不能当天卖，所以卖掉的必须是底仓——没有底仓就做不了正 T。",
    },
    "always_reverse": {
        "label": "每天都做反 T",
        "needs_open": True,
        "blurb": "不看条件，每天开盘卖、收盘买回。",
        "why": "「严重做 T」的字面版本。它测的是交易频率本身值不值，而不是择时手艺。",
    },
    "oracle": {
        "label": "天花板：每天最低买、最高卖",
        "needs_open": False,
        "blurb": "每天都在当日最低点买入、最高点卖出。**没有人能做到。**",
        "why": "它给做 T 这件事定上限：连这个数都不够看的话，后面的调参不必开始。",
    },
}


def simulate(bars: Iterable[dict[str, Any]], *, strategy: str = "reverse_t",
             window: int = 250, trigger_percent: float = 1.0,
             base_shares: int = 10000, tactical_percent: float = 20.0,
             costs: dict[str, float] | None = None) -> dict[str, Any]:
    """按一条明确规则在历史日线上逐日走一遍，扣完成本，报净收益。

    ## 基准就是 0，这不是偷懒

    上面四条策略在**日终都把仓位还原**（卖多少买回多少），所以"不做 T"的
    那条路的收益跟做了 T 完全一样——底仓该涨涨、该跌跌。两条路唯一的差别
    就是这些日内买卖的价差与费用。

    所以这里报出来的净收益**本身就是超额**：正数是做 T 真的多赚了，
    负数是做 T 亏掉的钱。不需要再去跟一条买入持有曲线相减，
    也就没有"基准算错了"这个常见的出错口子。

    ## 一字板当天不交易

    全天一个价的日子挂单成交不了。跳过的天数会原样报出来——
    **被跳过的机会不许算进收益里**，那正是回测虚高最常见的来源。
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"不认识的策略：{strategy}")
    spec = STRATEGIES[strategy]
    costs = {**DEFAULT_COSTS, **(costs or {})}

    rows = prepare(bars, window)
    if len(rows) < 30:
        return {"ok": False, "days": len(rows),
                "note": f"只有 {len(rows)} 个交易日的日线，模拟不出有意义的结果。"}

    shares = max(1, int(round(base_shares * tactical_percent / 100.0)))
    trigger = trigger_percent / 100.0

    trades: list[dict[str, Any]] = []
    net = 0.0
    gross = 0.0
    fees = 0.0
    skipped_locked = 0
    skipped_no_open = 0
    not_triggered = 0

    for index, row in enumerate(rows):
        previous_return = rows[index - 1]["return"] if index > 0 else None

        if strategy == "reverse_t":
            if previous_return is None or previous_return < trigger:
                not_triggered += 1
                continue
        elif strategy == "forward_t":
            if previous_return is None or previous_return > -trigger:
                not_triggered += 1
                continue

        if _is_locked(row):
            skipped_locked += 1
            continue

        if strategy == "oracle":
            low, high = row.get("low"), row.get("high")
            if low is None or high is None or low <= 0:
                skipped_no_open += 1
                continue
            buy_price, sell_price = low, high
        else:
            open_price = row.get("open")
            if open_price is None or open_price <= 0:
                skipped_no_open += 1
                continue
            if strategy in ("reverse_t", "always_reverse"):
                sell_price, buy_price = open_price, row["close"]
            else:                                     # forward_t
                buy_price, sell_price = open_price, row["close"]

        buy_amount = buy_price * shares
        sell_amount = sell_price * shares
        trade_fee = _cost("buy", buy_amount, costs) + _cost("sell", sell_amount, costs)
        trade_gross = sell_amount - buy_amount
        trade_net = trade_gross - trade_fee

        gross += trade_gross
        fees += trade_fee
        net += trade_net
        trades.append({
            "date": row["date"], "buy": buy_price, "sell": sell_price,
            "gross": trade_gross, "fee": trade_fee, "net": trade_net,
        })

    if not trades:
        return {
            "ok": True, "strategy": strategy, "label": spec["label"], "days": len(rows),
            "start": rows[0]["date"], "end": rows[-1]["date"],
            "trades": 0, "note": _no_trade_note(strategy, trigger_percent, skipped_no_open, skipped_locked),
            "skipped_locked": skipped_locked, "skipped_no_open": skipped_no_open,
            "not_triggered": not_triggered,
        }

    wins = sum(1 for t in trades if t["net"] > 0)
    base_value = rows[0]["close"] * base_shares

    # **做一次 T，价差至少要有多少才不亏。**
    #
    # 这是整张表里唯一一个能直接拿去对照盘面的数：算出来是 0.16% 的话，
    # 一只日均振幅 1.5% 的票，理论上确实有空间；算出来是 0.6% 的话，
    # 你得每次都咬掉当天振幅的小一半才回本，而那要靠运气不是靠手艺。
    #
    # 口径：一次完整的买 + 卖的费用，摊到成交金额上。
    average_amount = sum((t["buy"] + t["sell"]) / 2 * shares for t in trades) / len(trades)
    breakeven_spread = (fees / len(trades)) / average_amount if average_amount else None

    # ── 这个结果跟运气分得开吗 ────────────────────────────────────────────
    #
    # **一个好看的回测最容易让人下重注**（本仓 agentpickerplan 第七节的原话）。
    # 所以只要结果是正的，就必须同时给出"它可能只是运气"的那个数——
    # 否则页面上只剩一个诱人的收益率。
    #
    # 两个口径，因为它们问的不是同一件事：
    #   · 胜率检验：赢的次数比抛硬币多吗（精确二项，基准 50%）
    #   · t 值：单笔净收益的均值离 0 有几个标准误
    # 一条正一条不正的时候，这个结果就不该被当成规律。
    nets = [t["net"] for t in trades]
    win_p = binomial_p_value(wins, len(trades), 0.5)
    sigma = _stdev(nets)
    t_stat = ((sum(nets) / len(nets)) / (sigma / math.sqrt(len(nets)))) if sigma else None
    # 回撤按"做 T 这条现金流自己"的曲线算，不掺底仓的涨跌——
    # 掺进去之后看到的是股价的回撤，跟做 T 做得好不好没关系。
    curve, running, peak, drawdown = [], 0.0, 0.0, 0.0
    for trade in trades:
        running += trade["net"]
        peak = max(peak, running)
        drawdown = min(drawdown, running - peak)
        curve.append({"date": trade["date"], "cumulative": running})

    return {
        "ok": True,
        "strategy": strategy,
        "label": spec["label"],
        "blurb": spec["blurb"],
        "days": len(rows),
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "base_shares": base_shares,
        "tactical_shares": shares,
        "tactical_percent": tactical_percent,
        "base_value": base_value,
        "trades": len(trades),
        "wins": wins,
        "win_rate": wins / len(trades),
        "gross": gross,
        "fees": fees,
        "net": net,
        # 相对底仓市值的百分比。**这才是能跟"持有一年涨了多少"比的口径**——
        # 一个"多赚了 3800 元"听起来不少，摊到 38 万的底仓上是 1%。
        "net_percent": net / base_value * 100 if base_value else None,
        "net_per_trade": net / len(trades),
        "fee_share": (fees / abs(gross)) if gross else None,
        "breakeven_spread": breakeven_spread,
        "win_rate_p_value": win_p,
        "t_stat": t_stat,
        # **样本够不够**。71 笔在统计上是个小样本，而页面上它看起来跟 710 笔一样。
        "small_sample": len(trades) < 100,
        "max_drawdown": drawdown,
        "curve": curve,
        "skipped_locked": skipped_locked,
        "skipped_no_open": skipped_no_open,
        "not_triggered": not_triggered,
        "costs": costs,
    }


def _no_trade_note(strategy: str, trigger_percent: float, no_open: int, locked: int) -> str:
    """一次都没触发，跟"触发了但没数据"是两回事，说法也必须不一样。"""
    if no_open:
        return (f"这个窗口里有 {no_open} 天缺开盘价，规则触发了也成交不了。"
                f"先在公司档案点一次「同步行情历史」把开盘价补齐再跑。")
    if locked:
        return f"触发的那几天全是一字板（{locked} 天），挂单成交不了。"
    if strategy in ("reverse_t", "forward_t"):
        return f"这个窗口里没有一天满足「昨日涨/跌超过 {trigger_percent}%」，规则一次都没触发。"
    return "这个窗口里没有可成交的日子。"


def compare(bars: Iterable[dict[str, Any]], *, window: int = 250,
            trigger_percent: float = 1.0, base_shares: int = 10000,
            tactical_percent: float = 20.0,
            costs: dict[str, float] | None = None) -> dict[str, Any]:
    """四条策略一起跑，连同规律检验。页面上一次看全。

    **天花板排在最后一行不是排版**：它是用来读前面三行的尺子。
    """
    bars = list(bars)
    runs = [simulate(bars, strategy=key, window=window, trigger_percent=trigger_percent,
                     base_shares=base_shares, tactical_percent=tactical_percent, costs=costs)
            for key in STRATEGIES]
    stats = rhythm(bars, window)

    ceiling = next((r for r in runs if r.get("strategy") == "oracle" and r.get("trades")), None)
    realistic = [r for r in runs if r.get("strategy") != "oracle" and r.get("trades")]
    best = max(realistic, key=lambda r: r["net"], default=None)

    if ceiling and ceiling.get("net_percent") is not None:
        ceiling_line = (f"**天花板是 {ceiling['net_percent']:.1f}%**"
                        f"（{ceiling['days']} 个交易日，每天都在最低点买、最高点卖，"
                        f"扣完成本）。谁也做不到这个数，它只用来量"
                        f"「做 T 这件事最多值多少」。")
    else:
        ceiling_line = "天花板算不出来（缺最高/最低价）。"

    if best and best.get("net_percent") is not None:
        # **全亏的时候不能说"最好的是某某"。** 那句话会被读成推荐，
        # 而它其实是"输得最少的那一条"。这两件事差得很远。
        if best["net"] > 0:
            # **正收益必须当场配上「它可能只是运气」那个数。**
            # 不配的话，这一页上唯一留在脑子里的就是那个收益率。
            marks = []
            if best.get("win_rate_p_value") is not None:
                marks.append("胜率" + ("跟抛硬币分得开" if best["win_rate_p_value"] < 0.05
                                       else f"跟抛硬币分不开（p={best['win_rate_p_value']:.3f}）"))
            if best.get("t_stat") is not None:
                marks.append(f"单笔收益的 t 值 {best['t_stat']:.2f}"
                             + ("（超过 2，不像纯运气）" if abs(best["t_stat"]) > 2
                                else "（不到 2，跟 0 分不开）"))
            hedge = "；".join(marks)
            best_line = (f"三条能照着做的规则里，**{best['label']}**是唯一/最好的正收益："
                         f"{best['trades']} 次交易多赚 {best['net']:.0f} 元"
                         f"（底仓的 {best['net_percent']:.2f}%），"
                         f"手续费与印花税吃掉 {best['fees']:.0f} 元。"
                         + (f"　**但是**：{hedge}。" if hedge else "")
                         + ("　样本只有 {} 笔，统计上算少。".format(best["trades"])
                            if best.get("small_sample") else ""))
        else:
            # **「费用吃掉了」和「方向做反了」是两个病，药也不一样。**
            # 毛收益还是正的、被费用吃光 → 降频率、提门槛可能救得回来；
            # 毛收益本身就是负的 → 规则的方向就是错的，调费率没有用。
            if best["gross"] > 0:
                cause = (f"毛价差还是赚的（{best['gross']:.0f} 元），"
                         f"但 {best['fees']:.0f} 元的手续费与印花税比它还多——"
                         f"这一条是**交易频率**的问题。")
            else:
                cause = (f"毛价差本身就是负的（{best['gross']:.0f} 元），"
                         f"手续费只是又加了 {best['fees']:.0f} 元——"
                         f"这一条是**方向做反了**，调费率救不回来。")
            best_line = (f"**三条能照着做的规则在这个窗口里全部是亏的。**"
                         f"输得最少的是{best['label']}：{best['trades']} 次交易"
                         f"亏 {abs(best['net']):.0f} 元（底仓的 {abs(best['net_percent']):.2f}%）。"
                         + cause)
    else:
        best_line = "三条能照着做的规则在这个窗口里都没有触发过。"

    # 成本到底是不是瓶颈。**这一句能把话题一分为二**：
    # 打平所需价差远小于日均振幅 → 做 T 亏钱不怪手续费，怪的是你猜不准方向；
    # 两者接近 → 就算方向全猜对也没多少肉，这件事本身不值得做。
    spread = next((r.get("breakeven_spread") for r in runs
                   if r.get("strategy") == "always_reverse" and r.get("breakeven_spread")), None)
    amplitude = stats.get("mean_amplitude") if stats.get("enough") else None
    if spread and amplitude:
        ratio = spread / amplitude
        if ratio < 0.25:
            cost_line = (f"做一次 T 的成本只要 **{spread * 100:.2f}%** 的价差就能打平，"
                         f"而这只票日均振幅 {amplitude * 100:.2f}%——"
                         f"**成本不是瓶颈**。做 T 亏钱的话，亏在猜方向上。")
        else:
            cost_line = (f"做一次 T 要 **{spread * 100:.2f}%** 的价差才打平，"
                         f"而日均振幅只有 {amplitude * 100:.2f}%——"
                         f"就算方向全猜对，能咬到的肉也不比成本多多少。")
    else:
        cost_line = ""

    return {
        "rhythm": stats,
        "runs": runs,
        "ceiling_line": ceiling_line,
        "cost_line": cost_line,
        "best_line": best_line,
        "strategies": {key: {"label": v["label"], "blurb": v["blurb"], "why": v["why"]}
                       for key, v in STRATEGIES.items()},
        "cost_labels": COST_LABELS,
        "caveats": [
            # **这一条排第一是刻意的。** 上面那几条讲的是模拟本身的局限，
            # 而这一条讲的是使用者会怎么骗自己 —— 它比前面几条更容易发生。
            "**门槛和仓位是你在这一段数据上调出来的。** 调到收益变好为止，"
            "调出来的只是这一段历史的形状，不是规律。真要验，得拿没调过的另一段时间跑一遍——"
            "这一页不替你做那件事，因为做了你会更信它。",
            "日线只有开、高、低、收四个价。模拟里的买卖只能发生在开盘或收盘，"
            "不能假装你会在盘中某个价位接住。",
            "前复权序列每次分红送股都会整体重算，历史某一天的复权价跟当天的真实报价不一样。"
            "绝对金额只能当量级看。",
            "一字板当天不计入交易，被跳过的天数在每条策略里单列。",
            "这是一只你已经持有的股票自己的日线，没有挑股票的余地，"
            "所以没有幸存者偏差；但它也**只对这一只、这一段时间成立**。",
        ],
    }
