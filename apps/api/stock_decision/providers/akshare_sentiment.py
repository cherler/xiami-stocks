"""全市场情绪面：一只票现在被多少人盯着。

## 为什么要有这一层

价值候选那五套策略全是基本面指标——它们回答"这门生意的账好不好看"，
回答不了"这只票是不是已经人尽皆知"。而后者决定了「现在开始研究它还来不来得及」。

## 人气要反着读

**高人气不是加分项。** 一只票排在人气前列，意味着它已经被充分讨论、
观点已经被交易过一轮，能想到的理由多半已经在价格里了。对着眼长期的研究者，
"别人还没看见"才是稀缺的东西。

这句话必须写在数据层，不能只写在打分层：拿到这张表的每一处都得知道这几个数
该怎么读，否则迟早有人把「关注指数 95」当成利好画上去。

## 来源分工

- **千股千评**（`stock_comment_em`）是主力：唯一一份全市场覆盖的（实测 5191 只），
  一次请求带回机构参与度、综合得分、关注指数与人气排名。
- **雪球关注人数**（`stock_hot_follow_xq`）是补充：只有一个数，但它是**绝对量**
  而不是排名——排名只说"比别人热"，绝对量能看出热的量级差多少。

**东财人气榜（`stock_hot_rank_em`）刻意没有接。** 它走 push2.eastmoney.com，
那条路在本仓的部署环境里是被挡的（全市场行情快照降级用的就是同一个原因）。
而且千股千评自带「目前排名」和「关注指数」，人气榜跟它是冗余的——
接进来只是多一个会失败的依赖，换不到新信息。

## 综合得分与机构参与度是别人算的

这两个数出自东财自己的模型，口径不公开。它们可以横向比较（同一套算法算出来的，
大小有意义），但**不能当成事实断言**，更不该拿去乘一个权重算进总分——
那等于把一个黑箱的输出当成客观指标。页面上标明出处，只做展示。
"""

from typing import Any

from .base import QuoteProviderError


def _number(value: Any) -> float | None:
    if value is None or value != value:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _text(value: Any) -> str | None:
    if value is None or value != value:
        return None
    text = str(value).strip()
    return text or None


def _plain_symbol(value: Any) -> str | None:
    """雪球给的是 SH600519 / SZ000001，本站一律用六位数字。"""
    text = _text(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else None


class AkShareSentimentProvider:
    provider_id = "akshare_sentiment"
    display_name = "AKShare / 东方财富千股千评·雪球"
    category = "全市场情绪"

    def fetch_sentiment(self) -> dict[str, Any]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步情绪面") from exc

        try:
            frame = ak.stock_comment_em()
        except Exception as exc:                      # noqa: BLE001 — 网络什么都可能抛
            raise QuoteProviderError(f"千股千评拉取失败：{exc}") from exc

        rows: dict[str, dict[str, Any]] = {}
        trade_date = None
        for record in frame.to_dict(orient="records"):
            symbol = _text(record.get("代码"))
            name = _text(record.get("名称"))
            if not symbol or not name:
                continue
            trade_date = trade_date or _text(record.get("交易日"))
            participation = _number(record.get("机构参与度"))
            rows[symbol] = {
                "symbol": symbol,
                # 名称里有全角空格（「万　科Ａ」），统一压掉，否则跟底座对不上
                "name": name.replace("　", ""),
                "trade_date": _text(record.get("交易日")),
                # 源数据给到小数点后十几位（11.125414772556）。那是算出来的，不是测出来的——
                # 一个"估算的主力成本"精确到 0.000000000001 元是假精度，
                # 照原样存下去会让人以为这个数比它实际上更可信。
                "main_cost": _round(_number(record.get("主力成本")), 2),
                # 源数据是 0–1 的小数（均值 0.246），东财页面上显示的是百分数。
                # 存百分数：整站的比率列都是百分数，混两种口径迟早有人少乘一个 100。
                "institution_participation": None if participation is None else round(participation * 100, 2),
                "comment_score": _round(_number(record.get("综合得分")), 2),
                # 换手率：底座自己的源（降级后的新浪快照）给不了这一列，库里长期 0% 覆盖。
                # 千股千评白送，顺手带上——趋势那几套策略和云图都在等它。
                "turnover_rate": _round(_number(record.get("换手率")), 2),
                "attention_rank": _number(record.get("目前排名")),
                "rank_change": _number(record.get("上升")),
                "attention_index": _number(record.get("关注指数")),
                "xq_followers": None,
            }

        # 雪球失败不算整体失败：它是补充，主力那份已经拿到了。
        follow_note = ""
        try:
            follow = ak.stock_hot_follow_xq()
        except Exception as exc:                      # noqa: BLE001
            follow_note = f"雪球关注人数拉取失败（不影响主体）：{exc}"
        else:
            for record in follow.to_dict(orient="records"):
                symbol = _plain_symbol(record.get("股票代码"))
                if symbol and symbol in rows:
                    rows[symbol]["xq_followers"] = _number(record.get("关注"))

        return {
            "rows": list(rows.values()),
            "trade_date": trade_date,
            "source": "东方财富千股千评" + ("" if follow_note else " + 雪球关注人数"),
            "note": follow_note,
        }
