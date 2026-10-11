"""Fixed, causal price rules. No fitting, LLM, account data or network access.

All signals use completed closes and all simulated trades use the next open.
Public results may be cached across accounts; personal constraints never enter it.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from math import isfinite
from statistics import mean, pstdev

VERSION = "response-v1.0"
WARMUP = 120
BLOCK = 60
MIN_BARS = WARMUP + BLOCK * 3
BUY_COST = 0.0013  # commission/transfer allowance 3bp + slippage 10bp
SELL_COST = 0.0018  # additionally 5bp stamp duty


def positive(value):
    try:
        number = float(value)
        return number if isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def analyze(bars: list[dict], *, today: date | None = None) -> dict:
    day = today or date.today()
    records = []
    seen = set()
    for row in bars:
        stamp = str(row.get("trade_date", ""))[:10]
        try:
            parsed = date.fromisoformat(stamp)
        except ValueError:
            return {"ready": False, "note": "行情日期异常，暂停判断。", "chart": [], "strategies": []}
        if stamp in seen or parsed > day or not positive(row.get("close")):
            return {"ready": False, "note": "行情有重复、未来日期或无效价格，暂停判断。", "chart": [], "strategies": []}
        seen.add(stamp)
        records.append((stamp, positive(row.get("close")), positive(row.get("open_price")),
                        positive(row.get("high")), positive(row.get("low"))))
    records.sort()
    # The cache contains exclusively public bars and versioned fixed rules.
    return _analyze(tuple(records), day.isoformat(), VERSION)


def _signal(closes: list[float]) -> str:
    ma20, ma60 = mean(closes[-20:]), mean(closes[-60:])
    prior60 = mean(closes[-65:-5])
    # A 2% neutral buffer reduces flip-flopping near the moving average.
    if closes[-1] < ma60 * .98 and ma60 < prior60:
        return "down"
    if closes[-1] > ma60 * 1.02 and ma20 > ma60 and ma60 >= prior60:
        return "hot" if closes[-1] / ma20 > 1.12 else "up"
    return "range"


def simulate(records: tuple, start: int, end: int, strategy: str) -> dict:
    cash, units, peak, drawdown = 100000., 0., 100000., 0.
    trades, skipped, fees = 0, 0, 0.
    closes = [r[1] for r in records]
    for i in range(start, end):
        _, close, opening, high, low = records[i]
        previous = closes[:i]
        if strategy == "hold":
            target = 1.
        elif strategy == "staged":
            target = min(1., (1 + (i - start) // 20) / 3)
        else:
            signal = _signal(previous)
            target = 1. if signal in {"up", "hot"} else 0. if signal == "down" else .5
        # Missing OHLC, one-price bars and extreme gaps are not invented fills.
        executable = (opening and high and low and low <= min(opening, close)
                      and high >= max(opening, close) and high > low
                      and abs(opening / previous[-1] - 1) < .095)
        if executable:
            equity = cash + units * opening
            delta = equity * target - units * opening
            # Hold a target allocation until a material shift, not daily rebalancing.
            if abs(delta) > equity * .10:
                if delta > 0:
                    value = min(delta / (1 + BUY_COST), cash / (1 + BUY_COST))
                    cost = max(5., value * (BUY_COST - .001)) + value * .001
                    if value + cost > cash:
                        value = max(0., (cash - 5) / (1 + BUY_COST))
                        cost = max(5., value * (BUY_COST - .001)) + value * .001
                    cash -= value + cost
                    units += value / opening
                else:
                    value = min(-delta, units * opening)
                    cost = max(5., value * (SELL_COST - .0015)) + value * .0015
                    cash += value - cost
                    units -= value / opening
                trades += 1
                fees += cost
        else:
            skipped += 1
        equity = cash + units * close
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    return {"return_pct": round((equity / 100000 - 1) * 100, 2),
            "drawdown_pct": round(drawdown * 100, 2), "trades": trades,
            "skipped_days": skipped, "cost": round(fees, 2)}


@lru_cache(maxsize=128)
def _analyze(records: tuple, today: str, version: str) -> dict:
    closes = [r[1] for r in records]
    chart = [{"date": records[i][0], "close": closes[i],
              "ma60": round(mean(closes[i-59:i+1]), 2) if i >= 59 else None}
             for i in range(max(0, len(records)-120), len(records))]
    output = {"ready": False, "note": "至少需要 65 个交易日的有效收盘价。",
              "chart": chart, "strategies": [], "version": version,
              "as_of": records[-1][0] if records else None, "bars": len(records)}
    if len(records) < 65:
        return output
    stale = (date.fromisoformat(today) - date.fromisoformat(records[-1][0])).days > 7
    regime = _signal(closes)
    ma20, ma60 = mean(closes[-20:]), mean(closes[-60:])
    output.update(ready=not stale, regime=regime, note="行情超过 7 天未更新，暂不判断当前操作。" if stale else "",
                  price=closes[-1], ma20=round(ma20, 2), ma60=round(ma60, 2),
                  return20=round((closes[-1] / closes[-21] - 1) * 100, 2),
                  drawdown60=round((closes[-1] / max(closes[-60:]) - 1) * 100, 2),
                  volatility=round(pstdev([closes[i] / closes[i-1] - 1 for i in range(len(closes)-20, len(closes))]) * 252**.5 * 100, 1))
    output["comparison_note"] = f"不足 {MIN_BARS} 根日线，暂不做策略比较。"
    if len(records) < MIN_BARS:
        return output
    # Trailing 360 evaluation days, preceded by at least 120 warmup days.
    start, end = max(WARMUP, len(records) - 360), len(records)
    sample = records[start:end]
    gaps = any((date.fromisoformat(sample[i][0]) - date.fromisoformat(sample[i-1][0])).days > 14
               for i in range(1, len(sample)))
    missing = sum(not all(r[j] for j in (2, 3, 4)) or r[4] > min(r[1], r[2] or r[1])
                  or r[3] < max(r[1], r[2] or r[1]) for r in sample)
    if gaps or missing:
        output["comparison_note"] = "回测区间有长时间停牌、缺日线或无效开高低价，暂不展示收益比较。"
        return output
    strategies = []
    for key, label in (("hold", "买入后持有"), ("staged", "分三次参与"), ("trend", "随趋势调整")):
        result = simulate(records, start, end, key)
        blocks = []
        for left in range(start, end - BLOCK + 1, BLOCK):
            run = simulate(records, left, left + BLOCK, key)
            baseline = simulate(records, left, left + BLOCK, "hold")
            blocks.append({"from": records[left][0], "to": records[left+BLOCK-1][0],
                           "excess_pct": round(run["return_pct"] - baseline["return_pct"], 2)})
        strategies.append({"key": key, "label": label, **result, "blocks": blocks,
                           "better_blocks": sum(b["excess_pct"] > 0 for b in blocks)})
    for strategy in strategies:
        strategy["excess_pct"] = round(strategy["return_pct"] - strategies[0]["return_pct"], 2)
    output.update(strategies=strategies, comparison_from=records[start][0], comparison_to=records[-1][0],
                  comparison_note="固定规则，无参数寻优；最近最多 360 个交易日，另按连续 60 日分段检验。")
    return output
