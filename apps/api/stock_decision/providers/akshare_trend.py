"""全市场趋势面：谁在涨、涨得有没有量。

## 为什么必须绕开东财

底座的行情快照**已经降级到新浪**（`price_source` 实测全是「新浪全市场快照（降级）」），
而新浪只给价格和当日涨跌幅。于是 `change_60d`、`ytd_change`、`turnover_rate`
这三列在库里的覆盖率是 **0%**——不是没同步，是这条源根本没有这些字段。

东财那两条能给区间涨跌的路都被挡着：
- `push2.eastmoney.com`（全市场快照）
- `push2his.eastmoney.com`（单只日线，`stock_zh_a_hist` 实测 ProxyError）

所以**真实的 20 日 / 60 日涨幅算不出来**，自建的全市场日线又只累积了两天。
这不是暂时的：荐股池里任何写成「60 日涨幅 ≥ 20%」的规则，在这套部署下
永远是「暂不可用」。

## 换成同花顺的榜单

同花顺那几个榜单本身就是趋势筛选，而且是**算好的**：

| 榜单 | 给什么 | 实测条数 |
|---|---|---|
| `stock_rank_ljqs_ths` 量价齐升 | 天数、阶段涨幅、累计换手率 | 1651 |
| `stock_rank_xstp_ths` 向上突破均线 | 站上 60 日均线的名单 | 1492 |
| `stock_rank_cxg_ths` 创新高 | 月/半年/一年/历史 四档 | 387/22/17/5 |
| `stock_rank_cxfl_ths` 持续放量 | 放量天数 | 325 |

## 部分失败必须能看出来

四个榜单是四个独立的请求，**任何一个挂了都不该让另外三个的数据被清零**。
所以这里返回 `synced`：哪几组列这一轮真的取到了。写库那边只重置取到的那几组，
没取到的保留上一次的值（并留着上一次的日期）。

第一版不是这样的：只要主力那份（量价齐升）成功就整表重置，于是另外三个挂掉时
`above_ma60` 与 `new_high_level` 被刷成 0，「趋势突破型」和「创新高型」当天筛出
**0 只**，而作业还报「成功」、页面提示"先去跑一次全市场趋势面"——它刚跑过。

## 代价要说清楚

这些是**榜单，不是连续指标**，跟「60 日涨幅」不是一回事：

1. **阶段涨幅的窗口每只都不一样**（是它自己那段量价齐升持续了几天），
   所以两只票的阶段涨幅严格来说不可直接比。当排序用可以，当收益率读就错了。
2. **榜单是当日快照**，明天就换一批。它描述的是「今天这一刻的状态」，
   不是一段可回溯的历史。
3. **不在榜上要记 0，不是记空**。「不在量价齐升榜上」是一个事实
   （= 0 天），而「没同步过」是另一回事。混在一起的话，规则筛会把
   两者都当成不合格，而数据源挂了这件事就没人知道了。

## 换手率顺手补上

`turnover_rate` 在库里是 0% 覆盖，而千股千评（`stock_comment_em`，已经在同步了）
给了全市场 5191 只的换手率。顺手把这一列填上——云图和好几处都在等它。
"""

from typing import Any

from .base import QuoteProviderError

# 站上哪根均线。60 日是中期趋势的常用口径：5/10 日太短，一根阴线就翻，
# 250 日又太钝，等它翻过来趋势多半走完了。
MA_WINDOW = "60日均线"

# 新高的四档，从宽到严。存成序数，规则里就能写「新高档位 ≥ 2」。
NEW_HIGH_TIERS = (("创月新高", 1), ("半年新高", 2), ("一年新高", 3), ("历史新高", 4))

# 每个榜单负责哪几列。**写库时只重置这一轮真取到的那几组**——
# 一个榜单挂了不该让另外三个的数据被刷成 0。
COLUMN_GROUPS: dict[str, tuple[str, ...]] = {
    "rising": ("rising_days", "stage_gain", "stage_turnover"),
    "breakout": ("above_ma60",),
    "new_high": ("new_high_level",),
    "volume": ("volume_days",),
}
# 重置成什么。计数类归 0（「今天不在榜上」是个事实），
# 连续值归 NULL（没上榜就没有"阶段涨幅"这回事，0 会被当成"涨了 0%"）。
RESET_VALUES: dict[str, Any] = {
    "rising_days": 0, "stage_gain": None, "stage_turnover": None,
    "above_ma60": 0, "new_high_level": 0, "volume_days": 0,
}


def _number(value: Any) -> float | None:
    if value is None or value != value:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _symbol(value: Any) -> str | None:
    if value is None or value != value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else None


class AkShareTrendProvider:
    provider_id = "akshare_trend"
    display_name = "AKShare / 同花顺榜单"
    category = "全市场趋势"

    def fetch_trend(self) -> dict[str, Any]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步趋势面") from exc

        rows: dict[str, dict[str, Any]] = {}
        notes: list[str] = []
        # 这一轮真正取到了哪几组列。写库那边据它决定重置哪些——
        # 没取到的不重置，保留上一次的值，而不是刷成 0 装作"今天没上榜"。
        synced: set[str] = set()

        def slot(symbol: str) -> dict[str, Any]:
            return rows.setdefault(symbol, {
                "symbol": symbol, "rising_days": 0, "stage_gain": None,
                "stage_turnover": None, "above_ma60": 0, "new_high_level": 0,
                "volume_days": 0,
            })

        # 量价齐升是主力：条数最多，而且带阶段涨幅与累计换手率两个连续值。
        # 它失败就整体失败——其余三个都是补充，撑不起一个趋势口味。
        try:
            frame = ak.stock_rank_ljqs_ths()
        except Exception as exc:                      # noqa: BLE001
            raise QuoteProviderError(f"量价齐升榜拉取失败：{exc}") from exc
        synced.add("rising")
        for record in frame.to_dict(orient="records"):
            symbol = _symbol(record.get("股票代码"))
            if not symbol:
                continue
            item = slot(symbol)
            item["rising_days"] = _number(record.get("量价齐升天数")) or 0
            item["stage_gain"] = _number(record.get("阶段涨幅"))
            item["stage_turnover"] = _number(record.get("累计换手率"))

        # 下面三个各自失败只丢自己那一列，不影响整体。
        try:
            frame = ak.stock_rank_xstp_ths(symbol=MA_WINDOW)
        except Exception as exc:                      # noqa: BLE001
            notes.append(f"向上突破{MA_WINDOW}榜失败：{exc}")
        else:
            synced.add("breakout")
            for record in frame.to_dict(orient="records"):
                symbol = _symbol(record.get("股票代码"))
                if symbol:
                    slot(symbol)["above_ma60"] = 1

        for tier_name, level in NEW_HIGH_TIERS:
            try:
                frame = ak.stock_rank_cxg_ths(symbol=tier_name)
            except Exception as exc:                  # noqa: BLE001
                notes.append(f"{tier_name}榜失败：{exc}")
                continue
            # **以最宽那一档（创月新高）为准判定这组到没到。**
            # 它决定「有没有创新高」这件事本身；更严的几档只是把档位往上抬，
            # 少一档的后果是有票被低估一级，而少了最宽这一档就是整列失真。
            if level == NEW_HIGH_TIERS[0][1]:
                synced.add("new_high")
            for record in frame.to_dict(orient="records"):
                symbol = _symbol(record.get("股票代码"))
                if symbol:
                    # 四档从宽到严依次覆盖：一只创了历史新高的票也在创月新高榜上，
                    # 取最高那一档才是它真正的成色。
                    slot(symbol)["new_high_level"] = max(slot(symbol)["new_high_level"], level)

        try:
            frame = ak.stock_rank_cxfl_ths()
        except Exception as exc:                      # noqa: BLE001
            notes.append(f"持续放量榜失败：{exc}")
        else:
            synced.add("volume")
            for record in frame.to_dict(orient="records"):
                symbol = _symbol(record.get("股票代码"))
                if symbol:
                    slot(symbol)["volume_days"] = _number(record.get("放量天数")) or 0

        return {
            "rows": list(rows.values()),
            "synced": sorted(synced),
            "expected": sorted(COLUMN_GROUPS),
            "source": "同花顺榜单（量价齐升 / 向上突破均线 / 创新高 / 持续放量）",
            "notes": notes,
        }
