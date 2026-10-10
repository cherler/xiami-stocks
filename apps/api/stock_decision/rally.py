"""这段上涨（或下跌）属于什么类型。

## 它要拆掉的那种焦虑

> 很多基本面很差的股票连续涨停，我看不懂，也不敢参与。
> 是不是我错过了什么？是不是价值投资失效了？

看不懂一只票为什么涨，和这只票不值得买，是两件事。**先把"它为什么涨"
answer 出来，再决定要不要参与**——而不是反过来，先焦虑、再找理由。

短期上涨至少有七种来路，它们对一个做基本面研究的人意味着完全不同的事：

    基本面驱动    公司真的赚得更多了
    估值修复      公司没变，市场愿意给的价格变了（从很低的位置）
    行业景气      整个板块在涨，它只是跟着
    事件催化      某一条公告/新闻之后开始涨
    题材情绪      涨得比同行多很多，量放大，但没有公告也没有新财报
    资金博弈      涨停接力、换手极高、盘子小
    无法解释      以上都不像

**最后一类必须敢写出来。** 一个什么都能解释的分类器等于没有分类器；
而"查不出原因"本身就是一条对决策有用的信息——它是"别碰"最诚实的理由。

## 规则先跑，模型只负责说人话

跟 `classification.py` 同一条纪律：**分类可以自动做，因为结果可核验。**
每一条判据都是一句能拿库里的数字当场验算的话（"行业中位涨幅 4.2%，
它涨了 31.5%，超额 27.3 个百分点"），所以规则层单独就能出结论。

模型那一层是可选的、要花积分的，而且**只能用规则层算出来的数字**——
它写的是一段解释，不是一个新判断。说出来的数字在事实表里找不到出处，
会被当场标出来（复用 devils_advocate 的那套核对）。

## 一条几乎总是成立、却几乎没人说的会计事实

价格 = 市盈率 × 每股收益。窗口里没有新财报发布的话，每股收益这一项**没有动过**，
于是这段涨幅在会计上 **100% 来自市盈率的变化**——也就是"市场愿意出的价"变了，
不是"公司赚得更多了"。

这句话对本仓的使用者特别要紧：它把「这只票涨了 30%，是不是基本面变好了」
在多数情况下直接判成「不是，是定价变了」，剩下的问题才是"定价为什么变"。
"""

from __future__ import annotations

import math
from typing import Any

WINDOWS: tuple[int, ...] = (5, 20, 60)

# 各板的涨跌停幅度。ST 单独判（按名称），它在哪个板都是 5%。
BOARD_LIMITS: dict[str, float] = {
    "主板": 10.0,
    "创业板": 20.0,
    "科创板": 20.0,
    "北交所": 30.0,
}


def limit_percent(board: str, name: str) -> float:
    if "ST" in (name or "").upper():
        return 5.0
    return BOARD_LIMITS.get(board, 10.0)


# ── 类型 ────────────────────────────────────────────────────────────────────

TYPES: tuple[dict[str, str], ...] = (
    {"key": "fundamental", "label": "基本面驱动",
     "means": "窗口里出了新财报，而且这段涨跌里盈利那一项占了大头。",
     "for_you": "这是唯一一种「公司真的赚得更多/更少了」。它值得你回去更新估值。"},
    {"key": "rerating", "label": "估值重定价",
     "means": "盈利没怎么动，市场愿意给的倍数变了，而且起点在一个极端位置。",
     "for_you": "涨的那一侧叫估值修复，跌的那一侧叫估值压缩。**它会在某个位置走完**，"
                "而走完之后价格还要靠盈利说话。"},
    {"key": "sector", "label": "行业性",
     "means": "同行业中位数同方向走，而且幅度解释了它一半以上。",
     "for_you": "该研究的是行业发生了什么，不是这一家。单看这一家会把行业 beta 当成公司 alpha。"},
    {"key": "catalyst", "label": "事件催化",
     "means": "窗口里有实质公告，而且波动明显集中在公告之后那几天。",
     "for_you": "去读那份公告。**它是不是改变了你的长期假设**，是这里唯一要回答的问题。"},
    {"key": "theme", "label": "情绪驱动",
     "means": "比同行多走很多，量能明显放大，但没有新财报也没有实质公告。",
     "for_you": "这是另一套游戏的规则。**它跟你的估值体系没有接口**——"
                "看不懂不是你的问题，是你们在算两样东西。"},
    {"key": "flow", "label": "资金博弈",
     "means": "涨跌停接力、换手极高、盘子偏小。价格由边际资金决定，不由企业价值决定。",
     "for_you": "短线参与者关心的是「明天还有没有人接」。**这条路上没有你的位置**，"
                "而错过它不叫错过。"},
    {"key": "unexplained", "label": "无法解释",
     "means": "上面几条的判据一条都没凑齐。",
     "for_you": "**「查不出原因」本身就是结论。** 它是「先别碰」最诚实的理由。"},
    {"key": "quiet", "label": "没什么事发生",
     "means": "这段窗口里的波动还不到归因门槛。",
     "for_you": "**不是每一段行情都有原因。** 给一段正常波动编一个故事，"
                "会让你在下一次真有事发生时也照着故事读。"},
)

TYPES_BY_KEY = {t["key"]: t for t in TYPES}


def _check(text: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"text": text, "ok": bool(ok), "detail": detail}


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:+.{digits}f}%"


# 归因门槛：窗口幅度小于这个数，不给它编原因。
#
# **不是每一段行情都有原因。** 20 个交易日里走 3%，在一只年化波动 25% 的票上
# 属于什么都没发生；给它编一个故事，会让人在下一次真有事发生时也照着故事读。
#
# ## 门槛要按这只票自己的波动定，不能是一个固定数
#
# 第一版是 `2 × √天数`（20 天 8.9%）—— **那是拍出来的**。同样走 12%，
# 在年化波动 20% 的大盘股上是件事，在年化波动 70% 的小盘股上是它每周都在做的事。
# 用一个固定数，前者会漏判、后者会被硬扣上一个故事。
#
# 所以有这只票自己的日波动率时按 1.2σ√T 算；**σ 必须取自窗口之前那一段**——
# 拿窗口自己的波动算门槛是循环的：一次大涨会把 σ 抬上去，于是它把自己压下去。
# 取不到（池子外的票只有二十来天数据，凑不出前置区间）就退回那个固定式子，
# 并在返回值里标明用的是哪一种。
FLOOR_SIGMAS = 1.2


def attribution_floor(window_days: int, daily_sigma: float | None = None) -> float:
    """窗口幅度要超过这个百分数才值得归因。

    `daily_sigma` 是**窗口之前**那一段的日涨跌幅标准差（小数，不是百分数）。
    """
    span = math.sqrt(max(window_days, 1))
    if daily_sigma and daily_sigma > 0:
        return round(FLOOR_SIGMAS * daily_sigma * span * 100, 1)
    return round(2.0 * span, 1)


def classify(facts: dict[str, Any]) -> dict[str, Any]:
    """规则层。**这里不碰数据库，也不调模型**——给同一组事实必须永远给同一个答案。

    每种类型都把自己的判据逐条列出来，命中的和没命中的一起报。
    只报"最终是哪一类"的话，使用者没办法自己复核，也没办法不同意。

    ## 涨和跌用同一套判据

    「为什么涨」和「为什么跌」是同一个问题的两面，判据也是同一批，
    只是方向要跟着翻。所以下面一律用**幅度**（abs）加**方向一致性**来判，
    不写两套 —— 写两套的结果是其中一套永远没人维护，
    而使用者最需要归因的那一次往往正好是下跌的那一次（"跌到我的买点了，
    是跌得有道理还是跌得没道理？"）。
    """
    change = facts.get("change")
    if change is None:
        return {"ok": False, "note": "这段窗口里没有可用的日线，算不出涨跌幅。"}

    window_days = facts.get("window_days") or 20
    prior_sigma = facts.get("prior_daily_sigma")
    floor = attribution_floor(window_days, prior_sigma)
    direction = 1 if change >= 0 else -1
    magnitude = abs(change)

    industry = facts.get("industry") or {}
    valuation = facts.get("valuation") or {}
    volume = facts.get("volume") or {}
    events = facts.get("events") or []

    peer_median = industry.get("median_change")
    # 超额一律按**方向**算：跌 15% 而同行跌 2%，超额是 -13（跌得比同行狠 13 个点）。
    excess = (change - peer_median) if peer_median is not None else None
    # 同向超额的幅度：判「比同行多走了多少」时用它，涨跌通用。
    excess_magnitude = (direction * excess) if excess is not None else None
    volume_ratio = volume.get("ratio")
    limit_days = facts.get("limit_up_days") or 0
    max_streak = facts.get("max_limit_streak") or 0
    turnover = facts.get("turnover_rate")
    float_cap = facts.get("float_market_cap")
    high_events = [e for e in events if e.get("relevance") == "高"]
    # **「取不到公告」不等于「没有公告」。**
    #
    # 池子外的票没有公告表，`events` 是空的。不区分的话，「窗口里没有实质性公告」
    # 这条判据会**白白通过**，于是任何一只查不到公告的票都往「情绪驱动」上靠——
    # 而那正是最需要谨慎的一类判定。跟 `none-has-two-sources` 同一个病。
    events_available = bool(facts.get("events_available", True))
    report_in_window = bool(valuation.get("report_in_window"))
    earnings_share = valuation.get("earnings_share")
    pe_percentile_start = valuation.get("pe_percentile_start")
    post_event = facts.get("post_event") or {}

    results: list[dict[str, Any]] = []

    # ── 基本面驱动 ──
    results.append({
        "key": "fundamental",
        "checks": [
            _check("窗口里发布过新的报告期", report_in_window,
                   "、".join(valuation.get("report_dates") or []) or "窗口内没有新报告期"),
            _check("盈利那一项贡献了这段涨跌的一半以上",
                   earnings_share is not None and earnings_share >= 0.5,
                   f"盈利贡献 {earnings_share * 100:.0f}%" if earnings_share is not None
                   else "EPS 在窗口内没有更新，会计上贡献为 0"),
        ],
    })

    # ── 估值重定价 ──
    # 起点分位的方向要跟着翻：**涨要从低位起（修复），跌要从高位起（压缩）**。
    # 不翻的话，"从 90% 分位涨上去"会被判成估值修复，而那正好是相反的事。
    if pe_percentile_start is None:
        extreme_start, extreme_detail = False, "没有足够的历史估值样本，算不出分位"
    elif direction > 0:
        extreme_start = pe_percentile_start <= 30
        extreme_detail = f"起点 PE 分位 {pe_percentile_start:.0f}%（涨要从低位起才叫修复）"
    else:
        extreme_start = pe_percentile_start >= 70
        extreme_detail = f"起点 PE 分位 {pe_percentile_start:.0f}%（跌要从高位起才叫压缩）"
    results.append({
        "key": "rerating",
        "checks": [
            _check("涨跌主要来自市盈率变化，不是盈利变化",
                   earnings_share is not None and earnings_share < 0.5,
                   f"估值贡献 {(1 - earnings_share) * 100:.0f}%" if earnings_share is not None
                   else "窗口内 EPS 没更新，会计上 100% 来自估值"),
            _check("起点的市盈率处在自己历史的极端位置", extreme_start, extreme_detail),
        ],
    })

    # ── 行业性 ──
    #
    # **对照组优先用产业链环节，不够才退回申万一级。**
    #
    # 申万「电力设备」有 377 家，里面混着光伏、风电、电网设备——拿它的中位数
    # 去问「只有它在跌吗」，答案被稀释掉了。产业链环节（宁德 → 动力电池·电芯）
    # 是一个准确得多的集合，只是它很小：实测 155 个环节里中位只有 2 家。
    # 所以够 3 家才拿来算中位，不够就只点名、仍旧用申万判。
    chain = facts.get("chain_peers") or {}
    chain_best = next((g for g in (chain.get("groups") or [])
                       if g.get("key") == chain.get("best")), None)
    if chain_best and chain_best.get("median_change") is not None:
        peer_median = chain_best["median_change"]
        peer_source = (f"{chain_best['chain_label']}·{chain_best['segment_label']}"
                       f"（{chain_best['peer_count']} 家同环节）")
        excess = change - peer_median
        excess_magnitude = direction * excess
    else:
        peer_source = (f"{industry.get('name') or '行业未知'}"
                       f"（申万一级，{industry.get('peer_count') or 0} 家）")

    same_direction = peer_median is not None and peer_median * direction > 0
    results.append({
        "key": "sector",
        "checks": [
            _check("同行中位数同方向走，而且幅度不小（≥3%）",
                   same_direction and abs(peer_median) >= 3.0,
                   f"{peer_source} 中位 {_pct(peer_median)}"
                   + (f"｜{industry['note']}" if industry.get("note") else "")),
            _check("同行的幅度解释了它一半以上",
                   same_direction and abs(peer_median) / magnitude >= 0.5 if magnitude else False,
                   f"它 {_pct(change)}，同行中位 {_pct(peer_median)}"
                   + (f"，超额 {_pct(excess)}" if excess is not None else "")),
        ],
    })

    # ── 事件催化 ──
    results.append({
        "key": "catalyst",
        "checks": [
            _check("窗口里有实质性公告（分级为「高」）",
                   events_available and bool(high_events),
                   (f"{len(high_events)} 条：" + "；".join(e["title"][:24] for e in high_events[:3]))
                   if high_events else
                   ("窗口内没有分级为「高」的公告" if events_available
                    else "**这只票不在你的档案里，取不到它的公告**——这一条判不了")),
            # **判的是提升倍数，不是占比。** 占比会被公告密度骗过去：
            # 九条公告把 20 天盖掉 15 天，"公告后贡献 72%" 听着像集中，
            # 其实比 75% 的覆盖率还低 —— 那几天反而比平均值弱。
            _check("涨跌明显集中在公告之后的三个交易日（幅度占比 ÷ 天数占比 ≥ 1.5）",
                   post_event.get("lift") is not None and post_event["lift"] >= 1.5
                   and post_event.get("day_share", 1) <= 0.6,
                   (f"公告后三天覆盖 {post_event['covered_days']}/{post_event['tradable_days']} 天"
                    f"（{post_event['day_share'] * 100:.0f}%），贡献了 {post_event['share'] * 100:.0f}% 的幅度，"
                    f"提升 {post_event['lift']:.2f} 倍"
                    + ("。**公告太密，盖满了大半个窗口，这个问题在这段时间里答不了。**"
                       if post_event.get("day_share", 0) > 0.6 else ""))
                   if post_event.get("lift") is not None else "没有可对齐的公告日"),
        ],
    })

    # ── 情绪驱动 ──
    results.append({
        "key": "theme",
        "checks": [
            _check("比同行业中位数多走 10 个百分点以上",
                   excess_magnitude is not None and excess_magnitude >= 10.0,
                   f"同向超额 {excess_magnitude:+.1f} 个百分点" if excess_magnitude is not None
                   else "缺同行对照"),
            _check("成交量比前一段放大 1.5 倍以上",
                   volume_ratio is not None and volume_ratio >= 1.5,
                   f"放大 {volume_ratio:.2f} 倍" if volume_ratio is not None else "缺成交量数据"),
            _check("窗口里没有实质性公告，也没有新财报",
                   events_available and not high_events and not report_in_window,
                   ("有实质公告或新财报，说明波动有出处" if (high_events or report_in_window)
                    else "确实没有") if events_available else
                   "**取不到这只票的公告，所以「没有公告」这句话说不出口**——"
                   "查不到不等于没有，这一条按不通过算"),
        ],
    })

    # ── 资金博弈 ──
    limit = facts.get("limit_percent") or 10.0
    results.append({
        "key": "flow",
        "checks": [
            _check(f"窗口里出现过涨跌停（该板幅度为 {limit:g}%）", limit_days >= 1,
                   f"{limit_days} 天触及，最长连续 {max_streak} 天" if limit_days
                   else "窗口内没有触及涨跌停"),
            _check("有过连续两天以上", max_streak >= 2, f"最长连续 {max_streak} 天"),
            _check("换手率偏高（≥5%）", turnover is not None and turnover >= 5.0,
                   f"最新换手率 {turnover:.2f}%" if turnover is not None else "缺换手率数据"),
            _check("流通盘偏小（流通市值 < 200 亿）",
                   float_cap is not None and float_cap < 2e10,
                   f"流通市值 {float_cap / 1e8:.0f} 亿" if float_cap else "缺流通市值数据"),
        ],
    })

    for item in results:
        spec = TYPES_BY_KEY[item["key"]]
        item["label"] = spec["label"]
        item["means"] = spec["means"]
        item["for_you"] = spec["for_you"]
        hits = [c for c in item["checks"] if c["ok"]]
        item["hit_count"] = len(hits)
        item["total"] = len(item["checks"])
        # **全部判据都命中才算命中。** 用"满足一半就算"的打分会让每一类都亮一点，
        # 最后看起来像"什么都沾边"——而那正是这个功能要消灭的状态。
        item["hit"] = len(hits) == len(item["checks"])

    order = {t["key"]: i for i, t in enumerate(TYPES)}

    if magnitude < floor:
        quiet = TYPES_BY_KEY["quiet"]
        primary = {"key": "quiet", "label": quiet["label"], "means": quiet["means"],
                   "for_you": quiet["for_you"], "hit": True, "hit_count": 0, "total": 0,
                   "checks": [_check(
                       f"这 {window_days} 个交易日的幅度要超过 {floor:g}% 才值得归因",
                       False,
                       f"实际只有 {magnitude:.1f}%｜门槛是"
                       + (f"这只票自己的波动算的（窗口之前日波动 {prior_sigma * 100:.2f}%，"
                          f"{FLOOR_SIGMAS} 倍标准差）" if prior_sigma
                          else "通用式子 2×√天数 算的（缺窗口之前那段日线，"
                               "算不出这只票自己的波动）"))]}
        results.append(primary)
        hit = [primary]
        # 其他判据照常算、照常显示，但页面要知道它们**没有被采信**：
        # 一边写着「没什么事发生」一边亮着三个 ✔，读起来像系统自相矛盾。
        suppressed = True
    else:
        suppressed = False
        hit = [item for item in results if item["hit"]]
        if not hit:
            unexplained = TYPES_BY_KEY["unexplained"]
            primary = {"key": "unexplained", "label": unexplained["label"],
                       "means": unexplained["means"], "for_you": unexplained["for_you"],
                       "checks": [], "hit": True, "hit_count": 0, "total": 0}
            results.append(primary)
            hit = [primary]
        hit.sort(key=lambda x: (-x["hit_count"], order.get(x["key"], 99)))

    # **主判定必须排在第一张卡。**
    #
    # 第一版按「命中数从多到少」排，于是幅度没到门槛时页面长这样：
    # 标题写着「没什么事发生」，而第一张卡是命中 2/2 的「估值重定价」——
    # 读起来像系统自己跟自己打架。排序键因此把 primary 拎到最前面。
    primary_key = hit[0]["key"]

    return {
        "ok": True,
        "primary": primary_key,
        "hit_types": [h["key"] for h in hit],
        "floor": floor,
        "floor_basis": "这只票自己的波动" if prior_sigma else "通用式子（缺前置日线）",
        "peer_source": peer_source,
        "peer_median": peer_median,
        "prior_daily_sigma": prior_sigma,
        "suppressed_by_floor": suppressed,
        "magnitude": magnitude,
        "types": sorted(results, key=lambda x: (x["key"] != primary_key, not x["hit"],
                                                -x["hit_count"], order.get(x["key"], 99))),
        "headline": _headline(facts, hit, excess, direction, peer_median, peer_source),
        "accounting_note": _accounting_note(valuation, change),
    }


def _headline(facts: dict[str, Any], hit: list[dict[str, Any]],
              excess: float | None, direction: int,
              peer_median: float | None = None, peer_source: str = "") -> str:
    """**每个数字的方向跟着它自己的符号走。**

    第一版把同行业那句话的"涨/跌"也照着个股的方向写，于是
    「它跌了 3.8%，同行业中位跌了 3.6%」——而行业中位其实是 +3.5%。
    一个方向词写错，读者会得出完全相反的结论，而页面上看不出任何异常。
    """
    change = facts["change"]
    days = facts.get("window_days")
    verb = "涨" if change >= 0 else "跌"
    labels = "、".join(h["label"] for h in hit)
    head = f"近 {days} 个交易日{verb}了 {abs(change):.1f}%。判下来是**{labels}**。"
    median = peer_median
    if median is not None and excess is not None:
        peer_verb = "涨" if median >= 0 else "跌"
        gap = direction * excess
        relation = "多" if gap >= 0 else "少"
        head += (f"{peer_source or '同行'}中位{peer_verb}了 {abs(median):.1f}%，"
                 f"它比同行{relation}{verb}了 {abs(gap):.1f} 个百分点。")
    return head


def _accounting_note(valuation: dict[str, Any], change: float) -> str:
    """那条会计恒等式。**不命中任何类型时它也成立**，所以单独一栏。"""
    if valuation.get("report_in_window"):
        share = valuation.get("earnings_share")
        if share is None:
            return "窗口内出过新报告期，但缺 EPS 数据，拆不开估值与盈利。"
        return (f"窗口内发布过新报告期。价格 = 市盈率 × 每股收益，这段涨跌里"
                f"盈利贡献 {share * 100:.0f}%、估值贡献 {(1 - share) * 100:.0f}%。")
    if valuation.get("pe_start") is None or valuation.get("pe_end") is None:
        return ("窗口内没有发布新的报告期，每股收益这一项没有动过——"
                "所以这段涨跌在会计上 **100% 来自市盈率的变化**，"
                "也就是「市场愿意出的价」变了，不是「公司赚得更多了」。"
                "（库里缺这段的 PE 序列，所以没法把倍数变化本身列出来。）")
    pe_start, pe_end = valuation["pe_start"], valuation["pe_end"]
    tail = "（终点的 PE 是按恒等式推出来的，不是查出来的：EPS 没动，它只能跟着价格走。）" \
        if valuation.get("pe_end_derived") else ""
    return (f"窗口内没有发布新的报告期，每股收益这一项没有动过——"
            f"所以这段涨跌在会计上 **100% 来自市盈率的变化**："
            f"PE(TTM) 从 {pe_start:.1f}（{valuation.get('pe_start_date') or '日期不明'}）"
            f"到 {pe_end:.1f}。市场愿意出的价变了，不是公司赚得更多了。{tail}")


def earnings_share(price_change: float, pe_change: float | None) -> float | None:
    """盈利在这段涨幅里占多少。

    口径写死在这里，别处不许再算一遍：

        ln(P₁/P₀) = ln(PE₁/PE₀) + ln(EPS₁/EPS₀)

    取对数是为了让两项能相加——用百分比的话 30% 的估值扩张加 10% 的盈利增长
    不等于 40% 的涨幅（实际是 43%），而那个差额会被硬塞进某一项里。

    返回 None = 缺 PE 序列，拆不开。
    """
    if pe_change is None:
        return None
    if price_change <= -100 or pe_change <= -100:
        return None
    price_log = math.log1p(price_change / 100.0)
    pe_log = math.log1p(pe_change / 100.0)
    if abs(price_log) < 1e-9:
        return None
    return (price_log - pe_log) / price_log


# ── 模型那一层（可选、要花积分）─────────────────────────────────────────────

SYSTEM = """你在帮一个做基本面研究的个人投资者读懂「这只票最近这段涨跌是怎么来的」。

规则层已经算完了所有数字并给出了分类。你的任务**只有一件**：把它讲成一段人话。

硬约束：
1. **只能用给你的事实表里的数字。** 不许引用你记忆里的任何公司信息、行业数据、
   新闻或价格。事实表里没有的数字一律不许出现。
2. **不许说该不该买卖**，也不许给目标价。使用者的仓位和成本你都不知道。
3. 不许把分类改掉。规则层判成什么就是什么；你可以说"判据卡在哪一条"，
   但不能说"其实我觉得是另一类"。
4. 如果分类是「无法解释」，就直说查不出来，**不要硬编一个故事**。
   编出来的解释比没有解释更糟——他会照着它做决定。

输出 JSON，不要任何别的文字：
{
  "story": "一段 80-160 字的话，讲清楚这段涨跌是怎么来的",
  "what_it_means_for_value_investor": "一到两句：对一个只做基本面的人，这意味着什么",
  "what_to_check": ["接下来该自己核的两三件事，每条一句"]
}"""


def build_prompt(facts: dict[str, Any], verdict: dict[str, Any]) -> str:
    import json

    return (
        "事实表（你只能用这里面的数字）：\n"
        + json.dumps(facts, ensure_ascii=False, indent=2, default=str)
        + "\n\n规则层的判定：\n"
        + json.dumps({"primary": verdict["primary"], "hit_types": verdict["hit_types"],
                      "types": verdict["types"]}, ensure_ascii=False, indent=2, default=str)
    )


def narrate(facts: dict[str, Any], verdict: dict[str, Any]) -> dict[str, Any]:
    """让模型把规则层的结论讲成人话。**要花积分，所以是单独一步。**

    三道闸：

    1. 分类不许改。规则层判成什么就是什么——模型只写解释。
       返回值里原样带回 `primary`，页面显示的永远是规则层那个。
    2. 说出来的数字在事实表里找不到出处，当场标出来（复用 devils_advocate
       那套核对）。**标出来而不是删掉**：它可能是两个数相减算出来的，
       但值得你自己核一眼。
    3. 分类是「无法解释」或「没什么事发生」时**不调模型**。
       那两种情况下能写出来的只能是编的，而编出来的解释比没有解释更糟——
       他会照着它做决定。
    """
    from . import llm
    from .devils_advocate import _numbers_in, _untraceable
    from .jsonio import loads_or_reformat

    if verdict.get("primary") in ("unexplained", "quiet"):
        return {
            "ok": False,
            "skipped": True,
            "note": "规则层判成「" + TYPES_BY_KEY[verdict["primary"]]["label"] + "」，"
                    "这一步不调模型：能写出来的只能是编的，而编出来的解释比没有解释更糟。",
        }
    available, why = llm.ai_available()
    if not available:
        return {"ok": False, "skipped": True, "note": why}

    completion = llm.call(SYSTEM, build_prompt(facts, verdict),
                          task="rally-narrate", max_tokens=900)
    payload = loads_or_reformat(completion.text, task="rally-narrate")
    if not isinstance(payload, dict):
        return {"ok": False, "note": "模型这一轮返回的不是可解析的 JSON。"}

    seen = _numbers_in({"facts": facts, "verdict": verdict})
    story = str(payload.get("story") or "").strip()
    meaning = str(payload.get("what_it_means_for_value_investor") or "").strip()
    checks = [str(x).strip() for x in (payload.get("what_to_check") or []) if str(x).strip()]
    untraceable = sorted(set(
        _untraceable(story, seen) + _untraceable(meaning, seen)
        + [n for item in checks for n in _untraceable(item, seen)]))

    return {
        "ok": True,
        "story": story,
        "meaning": meaning,
        "what_to_check": checks[:5],
        "untraceable": untraceable,
        "model": llm.model_name(),
        "credits": completion.meter.cost if completion.meter else None,
    }
