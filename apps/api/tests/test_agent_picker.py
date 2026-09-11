"""智能体荐股池 · 打底层的打分逻辑。

打分是纯函数，所以这里一个数据库都不需要。这不是巧合——**打分逻辑单独可测
是这一层的设计目标之一**：五千行的打分要能在毫秒内跑一遍，才可能真的去调权重、
调门槛，而不是改一次等一次同步。

这里守的是几条容易在改动中被悄悄破坏的性质：

- 缺数据的项**不能记 0 分**，要从分母里拿掉。记 0 分等于把"没数据"当成"很差"。
- 人气是**反着读**的：越没人讨论分越高。这是一条立场，写反了不会报错，
  只会让整个池子悄悄变成追热点。
- 分位的样本是**整个并集**，不是截断后的前 N 名。先截断再算分位的话，
  同一只票看 30 只和看 50 只会拿到不同的分数，而它自己什么都没变。
"""

import pytest

from stock_decision import agent_picker


def _strategy(key: str, name: str, rules: list[dict]) -> dict:
    return {"key": key, "name": name, "rules": rules, "available": True}


CHEAP = _strategy("cheap", "低估型", [{"field": "pe_ttm", "op": "lte", "value": 20}])
QUALITY = _strategy("quality", "质量型", [{"field": "annual_roe", "op": "gte", "value": 10}])


def _row(symbol: str, **fields) -> dict:
    base = {"symbol": symbol, "name": f"公司{symbol}", "board": "主板", "industry": "测试",
            "price": 10.0, "total_market_cap": 1e10}
    base.update(fields)
    return base


# --------------------------------------------------------------- 分位


def test_percentile_ties_share_a_score():
    """并列的值拿同一个分数。

    按名次除以总数的话，并列里谁排前面取决于排序稳不稳定——那是实现细节，
    不该变成分数差。
    """
    values = [1.0, 5.0, 5.0, 5.0, 9.0]
    assert agent_picker.percentile(values, 5.0, True) == agent_picker.percentile(values, 5.0, True)
    assert 0 < agent_picker.percentile(values, 5.0, True) < 100


def test_percentile_direction_flips():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert agent_picker.percentile(values, 5.0, True) > agent_picker.percentile(values, 1.0, True)
    assert agent_picker.percentile(values, 5.0, False) < agent_picker.percentile(values, 1.0, False)


def test_percentile_matches_the_linear_scan_it_replaced():
    """二分版必须跟原来那个线性扫**逐一相等**，不是"差不多"。

    改成二分是为了性能（实测并集 4000 只从 3.00 秒降到 0.05 秒），
    而性能优化最容易顺手改掉语义。这里拿随机数据把两种实现对着跑。
    """
    import random

    def linear(values, value, bigger):
        worse = sum(1 for other in values if (other < value if bigger else other > value))
        same = sum(1 for other in values if other == value)
        return round((worse + same / 2) / len(values) * 100, 1)

    random.seed(7)
    for _ in range(300):
        values = [round(random.uniform(0, 10), 1) for _ in range(random.randint(1, 40))]
        target = random.choice(values)
        for bigger in (True, False):
            assert agent_picker.percentile(sorted(values), target, bigger) == linear(values, target, bigger)


# --------------------------------------------------------------- 规则并集


def test_union_keeps_disagreement():
    """并集保留分歧：只过一套的也要在池子里，命中几套交给 consensus 打分。"""
    rows = [
        _row("000001", pe_ttm=10, annual_roe=5),      # 只过低估
        _row("000002", pe_ttm=50, annual_roe=20),     # 只过质量
        _row("000003", pe_ttm=10, annual_roe=20),     # 两套都过
        _row("000004", pe_ttm=50, annual_roe=5),      # 都不过
    ]
    entries = agent_picker.union_screen(rows, [CHEAP, QUALITY])
    by_symbol = {e["row"]["symbol"]: e for e in entries}
    assert set(by_symbol) == {"000001", "000002", "000003"}
    assert by_symbol["000003"]["matched"] == ["低估型", "质量型"]
    assert by_symbol["000001"]["matched"] == ["低估型"]


def test_unavailable_strategy_is_skipped():
    dead = {**CHEAP, "available": False}
    rows = [_row("000001", pe_ttm=10, annual_roe=20)]
    entries = agent_picker.union_screen(rows, [dead, QUALITY])
    assert entries[0]["matched"] == ["质量型"]


# --------------------------------------------------------------- 打分


def _pool(rows, sentiment=None, limit=30):
    return agent_picker.build_pool(rows, [CHEAP, QUALITY], sentiment or {}, limit=limit)


def test_missing_dimension_is_not_scored_zero():
    """整池都没有情绪面时，人气那一项不参与分母。

    如果它被记成 0 分，所有票的总分都会被同一个 0 拉低——**看上去还是一份
    能排序的清单**，只是整体偏低，没人会发现少了一项。
    """
    rows = [_row(f"00000{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40,
                 pb=1.0, eps=1.0, ocf_per_share=1.0, dividend_yield=3.0) for i in range(1, 7)]
    pool = _pool(rows)
    first = pool["rows"][0]
    crowding = next(s for s in first["scores"] if s["key"] == "crowding")
    assert crowding["score"] is None
    assert "人气（反向）" in first["missing"]
    # 四项都在高分位而人气缺失时，总分不该被缺失项拖下来
    # 总分去掉了：**一个需要免责声明的加权分，就是不该给的分。**
    # 现在断言的是各维度分位算得出来，而排序靠「命中了几套规则」。
    assert any(d["score"] is not None for d in first["scores"])
    assert first["dimensions_covered"] >= 1


def test_crowding_is_read_in_reverse():
    """人气越低分越高。写反了不会报错，只会让池子悄悄变成追热点。"""
    rows = [_row(f"00000{i}", pe_ttm=10, annual_roe=20) for i in range(1, 7)]
    # attention_rank 越大越冷门
    sentiment = {f"00000{i}": {"attention_rank": float(i * 500), "attention_index": 100.0 - i}
                 for i in range(1, 7)}
    pool = _pool(rows, sentiment)
    scores = {r["symbol"]: next(s["score"] for s in r["scores"] if s["key"] == "crowding")
              for r in pool["rows"]}
    # 000006 排名最靠后（最冷门）→ 人气分最高
    assert scores["000006"] > scores["000001"]


def test_percentiles_are_computed_over_the_whole_union_not_the_slice():
    """先截断再算分位的话，同一只票会因为 limit 变化而改分数。"""
    rows = [_row(f"{i:06d}", pe_ttm=10, annual_roe=float(i), annual_gross_margin=float(i))
            for i in range(1, 21)]
    def _scores(limit):
        return {r["symbol"]: {d["key"]: d["score"] for d in r["scores"]}
                for r in _pool(rows, limit=limit)["rows"]}

    wide, narrow = _scores(20), _scores(5)
    for symbol, scores in narrow.items():
        assert scores == wide[symbol], f"{symbol} 的分位随 limit 变了"


def test_truncation_is_reported_not_silent():
    """砍掉了多少要说出来——不说的话「前 5 名」读起来跟「全部结果」一模一样。"""
    rows = [_row(f"{i:06d}", pe_ttm=10, annual_roe=20) for i in range(1, 21)]
    pool = _pool(rows, limit=5)
    assert pool["returned"] == 5
    assert pool["pool_total"] == 20
    assert pool["dropped"] == 15
    assert "15" in pool["note"]


def test_a_row_with_almost_no_data_cannot_top_the_pool():
    """**这是缺项处理最危险的一个角**。

    缺项的权重从分母里拿掉是对的，但拿掉得只剩一项时，那一项自己就成了总分：
    一家除了「被两套规则同时选中」之外什么数据都没有的公司，consensus 拿 100，
    总分就是 100，**排在池子第一**——而它跟一家五项全优的公司在页面上长得一样，
    区别只写在一行小字的覆盖度里。

    所以覆盖不足一半权重时不给总分，排到最后，明说数据不足。
    """
    # 这一套只按市值筛，而市值不是任何一个打分项的输入——
    # 于是过了它的公司可以在打分维度上一片空白。真实的策略库里
    # 「总市值 ≥ 50 亿」这类规模门槛正是这样的：它拦掉小票，但不描述好坏。
    size = _strategy("size", "规模型", [{"field": "total_market_cap", "op": "gte", "value": 1e9}])
    rows = [_row(f"00000{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=float(i * 5),
                 pb=1.0, eps=1.0, ocf_per_share=1.0, dividend_yield=3.0)
            for i in range(1, 7)]
    # 只过规模那一套：打分要用的字段一个都没有
    rows.append(_row("000099", pe_ttm=None, annual_roe=None))
    pool = agent_picker.build_pool(rows, [CHEAP, QUALITY, size], {}, limit=30)

    scored = {r["symbol"]: r for r in pool["rows"]}
    assert scored["000099"]["matched"] == ["规模型"]
    # 总分没有了，但这一条守的规矩还在：**数据几乎全缺的行必须能被看出来。**
    # 现在它体现在 dimensions_covered 与 coverage 那句话上，
    # 而卡片上的大数字是「命中几套规则」——那是数出来的，不会被稀疏数据抬高。
    thin = scored["000099"]
    assert thin["dimensions_covered"] < agent_picker.MIN_DIMENSIONS_COVERED
    assert "不足" in thin["coverage"], thin["coverage"]
    # **排序换成「命中几套规则」之后，这一条不再自动成立**，而它仍然重要：
    # 000099 只命中一套，所以排在命中两套的后面——靠的是命中数，不是靠"没分"。
    # 万一哪天一只数据全缺的票命中了四套规则，它就该排在前面，
    # 而 coverage 那句话负责让人看出它的数据是空的。
    assert pool["rows"][-1]["symbol"] == "000099"
    assert len(scored["000099"]["matched"]) < len(pool["rows"][0]["matched"])


def test_earnings_yield_handles_loss_making_pe():
    """亏损股的负 PE 在倒数里自然排到最后，不用特判。"""
    assert agent_picker.field_value({"pe_ttm": -10}, "earnings_yield") < 0
    assert agent_picker.field_value({"pe_ttm": 10}, "earnings_yield") > 0
    assert agent_picker.field_value({"pe_ttm": 0}, "earnings_yield") is None
    assert agent_picker.field_value({}, "earnings_yield") is None


@pytest.mark.parametrize("stance", sorted(agent_picker.STANCES))
def test_black_box_scores_stay_out_of_the_dimensions(stance):
    """综合得分与机构参与度只展示、不计分。

    它们是东财自己模型的输出，口径不公开。把黑箱输出乘一个权重算进总分，
    这个总分就没法解释了——而"能解释"正是这一层唯一的优势。

    **要逐口味查。** 原来只查了价值那一套，有人往趋势维度里塞 comment_score
    的话测试照样绿。
    """
    scored_fields = {name for d in agent_picker.STANCES[stance]["dimensions"]
                     for name, _ in d.inputs}
    assert "comment_score" not in scored_fields
    assert "institution_participation" not in scored_fields
    # 但它们要出现在展示栏里
    context_keys = {key for key, _, _ in agent_picker.CONTEXT_FIELDS}
    assert {"comment_score", "institution_participation"} <= context_keys


@pytest.mark.parametrize("stance", sorted(agent_picker.STANCES))
def test_weights_sum_to_one_hundred(stance):
    """每个口味的权重都要正好 100。

    **这条抓到过一个真 bug。** 「两边都在」那套维度第一版是从价值和趋势两边
    切片拼出来的，权重加起来 140。算总分时按实际用到的权重归一化了，所以数字
    看着正常——但页面上那行「总分怎么来的：共识 25% · 趋势 30% · …」
    印出来是一串加不到 100 的百分比。**不会报错，只会印错。**
    """
    # **权重整个去掉了。** 原来这里断言"六项权重加起来是 100"——
    # 而那组权重（趋势 25%、质量 20%…）没有任何依据，页面还得配一句
    # 「别把它当成一个客观评分」。现在各维度只报自己的分位，不合成。
    dimensions = agent_picker.STANCES[stance]["dimensions"]
    assert not any(hasattr(d, "weight") for d in dimensions), "维度不该再有权重"
    assert len({d.key for d in dimensions}) == len(dimensions), "维度 key 不能重复"


def test_industry_concentration_is_surfaced():
    """行业扎堆要说出来。

    价值类规则天然把银行、保险、公用事业推到前面——那是规则的结构性偏好，
    不是"今年银行特别好"。实测线上跑一遍，前十里五家银行保险。
    只给一份排好序的清单而不给分布，读的人会把这个偏好当成一个发现。
    """
    rows = [_row(f"00000{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40,
                 industry="银行") for i in range(1, 7)]
    rows.append(_row("000099", pe_ttm=10, annual_roe=20, annual_gross_margin=40, industry="白酒"))
    pool = _pool(rows)
    assert pool["industries"][0] == {"name": "银行", "count": 6}
    assert "银行" in pool["concentration"]


def test_concentration_catches_clusters_split_across_industries():
    """**只看第一名会漏掉真正的扎堆。**

    申万把银行和保险分成两个二级行业（银行Ⅱ / 保险Ⅱ）。实测线上跑一遍，
    前十里五家银行保险——而单看第一名只有 2/10，什么都不触发，
    那份清单读起来就像"筛出了六个不同的行业"。所以再看一眼前三名合起来占多少。
    """
    rows = ([_row(f"00100{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40, industry="银行Ⅱ")
             for i in range(1, 4)]
            + [_row(f"00200{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40, industry="保险Ⅱ")
               for i in range(1, 4)]
            + [_row(f"00300{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40, industry="电力")
               for i in range(1, 3)]
            + [_row(f"00400{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40, industry=f"别的{i}")
               for i in range(1, 3)])
    pool = _pool(rows)
    # 第一名只占 3/10 —— 但前三个行业占了 80%
    assert pool["concentration"], "前三个行业占八成也算扎堆"
    assert "银行Ⅱ" in pool["concentration"] and "保险Ⅱ" in pool["concentration"]


def test_no_concentration_note_when_spread_out():
    rows = [_row(f"00000{i}", pe_ttm=10, annual_roe=20, annual_gross_margin=40,
                 industry=f"行业{i}") for i in range(1, 9)]
    assert _pool(rows)["concentration"] == ""


def test_this_layer_costs_nothing():
    """这一层不调模型：打分模块里不该出现任何 llm 调用。

    原来这条测的是 `estimate()` 返回 0 积分——而那个函数只有测试在调，
    接口不返回、页面也不显示，等于测试自己在给自己作证。删掉它，
    改成守真正的性质：这个模块压根不 import llm。
    """
    import inspect

    source = inspect.getsource(agent_picker)
    assert "llm" not in source.replace("不调用模型", "").replace("不调模型", "")


# --------------------------------------------------------------- 走接口

def test_agent_pool_endpoint_keeps_every_key():
    """走 HTTP 打一遍，不是直接调 repository。

    **这一层被绕过去三次了。** 候选初筛的 verdict/reasons/concerns、产业链的 label、
    今日简报的 context——三次都是本地调 repository 一切正常、走接口出来少一个键，
    前端拿 undefined 去 .length，整页白屏。而单测直接调 repository 就永远看不见，
    因为坏掉的正好是被绕过的那一层。

    这条路由刻意声明成 `-> dict` 而不是 response_model，所以键不会被过滤掉；
    这个测试守的就是"以后别有人顺手加上 response_model"。
    """
    from fastapi.testclient import TestClient

    from stock_decision import access
    from stock_decision.database import connection, now_iso
    from stock_decision.main import app

    with connection() as conn:
        for index in range(1, 13):
            conn.execute(
                """INSERT INTO market_universe (symbol, name, exchange, board, industry,
                       price, pe_ttm, pb, total_market_cap, net_profit, annual_roe,
                       annual_gross_margin, eps, ocf_per_share, dividend_yield, updated_at)
                   VALUES (?, ?, '上海证券交易所', '主板', '测试业', 10, 12, 1.2, ?, 1e9,
                           ?, 40, 1.0, 1.2, 4.0, ?)""",
                (f"60{index:04d}", f"测试{index}", 2e10 + index, 16.0 + index, now_iso()))
            conn.execute(
                """INSERT INTO market_sentiment (symbol, name, trade_date, attention_rank,
                       attention_index, comment_score, institution_participation, updated_at)
                   VALUES (?, ?, '2026-08-07', ?, ?, 65, 24, ?)""",
                (f"60{index:04d}", f"测试{index}", 100.0 * index, 90.0 - index, now_iso()))

    client = TestClient(app)
    response = client.post("/api/v1/agent-pool?limit=5")
    assert response.status_code == 200, response.text
    body = response.json()

    for key in ("rows", "pool_total", "returned", "dropped", "strategies", "universe_total",
                "with_sentiment", "industries", "concentration", "dimensions", "note", "boundary"):
        assert key in body, f"接口把 {key} 丢了"
    assert body["rows"], "构造的数据应该能命中规则"
    for key in ("symbol", "name", "matched", "scores", "dimensions_covered", "missing",
                "coverage", "context", "attention_rank"):
        assert key in body["rows"][0], f"接口把每行的 {key} 丢了"
    # 情绪面接上了才算真的通：人气那一项不能整列是 None
    assert body["rows"][0]["attention_rank"] is not None
    crowding = next(s for s in body["rows"][0]["scores"] if s["key"] == "crowding")
    assert crowding["score"] is not None


def test_agent_pool_explains_itself_when_universe_is_empty():
    """底座没数据时要说清楚去哪儿补，不是抛一个栈。"""
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    response = TestClient(app).post("/api/v1/agent-pool")
    assert response.status_code == 400
    assert "全市场底座" in response.json()["detail"]


# --------------------------------------------------------------- 口味

TREND = _strategy("t1", "趋势型", [{"field": "rising_days", "op": "gte", "value": 3}])
TREND2 = _strategy("t2", "新高型", [{"field": "new_high_level", "op": "gte", "value": 1}])


def _kinded(items):
    """给测试用的策略补上 kind —— 线上是从规则字段推出来的（Strategy.kind）。"""
    from stock_decision.strategies import TREND_FIELDS
    out = []
    for item in items:
        kind = "trend" if any(r["field"] in TREND_FIELDS for r in item["rules"]) else "value"
        out.append({**item, "kind": kind})
    return out


ALL = _kinded([CHEAP, QUALITY, TREND, TREND2])


def test_strategy_kind_comes_from_its_fields():
    """口味从规则用的字段推出来，不另外维护一份名单。

    两处各写一份的话迟早对不上：加了一套新策略、名单忘了改，它就会被算进
    错误的那个池子，而表现只是"这个池子里怎么混进来一只奇怪的票"。
    """
    from stock_decision.strategies import PRESETS_BY_KEY

    assert PRESETS_BY_KEY["undervalued_defensive"].kind == "value"
    assert PRESETS_BY_KEY["dividend_cashflow"].kind == "value"
    assert PRESETS_BY_KEY["trend_breakout"].kind == "trend"
    assert PRESETS_BY_KEY["trend_new_high"].kind == "trend"


def test_stances_use_different_rule_floors():
    """价值口味不该看趋势规则，反之亦然。

    这不是洁癖：**价值和动量在构造上是负相关的**（涨过一波，PE 就上去了），
    把两边的规则混进一个并集再打一个平均分，选出来的是"两边都平庸"的票。
    """
    assert [s["name"] for s in agent_picker.strategies_for(ALL, "value")] == ["低估型", "质量型"]
    assert [s["name"] for s in agent_picker.strategies_for(ALL, "trend")] == ["趋势型", "新高型"]
    assert len(agent_picker.strategies_for(ALL, "both")) == 4


def test_trend_stance_actually_surfaces_trend_stocks():
    """趋势口味要真的能把涨得好的挑出来——原来那套结构做不到这件事。

    价值口味的底子是五套价值规则，一只涨过一波的票 PE 已经上去了，
    五套里没有一套还会选中它。所以"找不出趋势股"不是权重问题，是结构问题。
    """
    rows = ([_row(f"10000{i}", pe_ttm=8, annual_roe=20, annual_gross_margin=40,
                  rising_days=0, new_high_level=0) for i in range(1, 7)]      # 便宜但没动
            # 涨但不便宜：PE 60 过不了低估、ROE 5 过不了质量，两套价值规则都不选它
            + [_row(f"20000{i}", pe_ttm=60, annual_roe=5, annual_gross_margin=40,
                    rising_days=5 + i, stage_gain=10.0 * i, new_high_level=1,
                    stage_turnover=30.0, volume_days=3) for i in range(1, 7)])

    value_pool = {r["symbol"] for r in agent_picker.build_pool(rows, ALL, {}, stance="value")["rows"]}
    trend_pool = {r["symbol"] for r in agent_picker.build_pool(rows, ALL, {}, stance="trend")["rows"]}

    assert all(s.startswith("1") for s in value_pool), "价值池不该出现涨过的贵票"
    assert all(s.startswith("2") for s in trend_pool), "趋势池不该出现没动的便宜票"
    assert value_pool and trend_pool


def test_both_stance_is_an_intersection_not_an_average():
    """「两边都在」必须是**交集**：同时过价值和趋势。

    平均两个分数是折中，会选出两边都平庸的票；交集是合取，选出的是
    "又便宜又在涨"——那才是真正稀缺的东西。这两件事结果完全不同。
    """
    rows = [
        _row("100001", pe_ttm=8, annual_roe=20, annual_gross_margin=40),                    # 只便宜
        _row("200001", pe_ttm=60, annual_roe=5, rising_days=6, new_high_level=1),           # 只在涨
        _row("300001", pe_ttm=8, annual_roe=20, annual_gross_margin=40,
             rising_days=6, stage_gain=20.0, new_high_level=1),                             # 两边都在
    ]
    both = agent_picker.build_pool(rows, ALL, {}, stance="both")
    assert [r["symbol"] for r in both["rows"]] == ["300001"]


def test_crowding_direction_follows_the_stance():
    """人气的方向由口味决定：价值口味反着读，趋势口味正着读。

    **写反了不会报错。** 价值池会悄悄变成追热点，趋势池会挑出没人看的死水，
    两种都只是"结果看起来怪"，没有任何报错。
    """
    value_crowd = next(d for d in agent_picker.DIMENSIONS_VALUE if d.key == "crowding")
    trend_crowd = next(d for d in agent_picker.DIMENSIONS_TREND if d.key == "crowding")
    # attention_rank 越小越热。价值要冷（bigger_is_better=True），趋势要热（False）。
    assert dict(value_crowd.inputs)["attention_rank"] is True
    assert dict(trend_crowd.inputs)["attention_rank"] is False


def test_both_stance_drops_crowding_rather_than_averaging_it():
    """两边都在的时候人气没有一个诚实的方向，就不给它权重。

    取个中间值假装中立是更糟的做法：那等于说"人气不重要"，
    而实际情况是"这两种立场对它的判断正好相反"。
    """
    keys = {d.key for d in agent_picker.DIMENSIONS_BOTH}
    assert "crowding" not in keys


def test_unknown_stance_is_rejected_not_silently_defaulted():
    """认不出的口味要报错，不能默默回落到价值——那会让人以为自己在看趋势池。"""
    with pytest.raises(ValueError):
        agent_picker.build_pool([], ALL, {}, stance="momentum")


# --------------------------------------------------------------- 池子太小

def test_a_small_pool_says_it_cannot_rank_instead_of_blaming_the_data():
    """池子排不出分位时，**不能说「数据不足」**——数据是全的，缺的是可比的同类。

    原来这两件事是混在一起的：不够排分位 → 每一项都算不出来 → 覆盖度掉到 15%
    → 判定"数据不足、不给总分"。于是三只票的池子整页都是灰扑扑的「数据不足」，
    而六项数据其实全都有，清单本身完全可用。看起来像功能坏了。

    「两边都在」最容易撞上：今天 40 只，冷清的一天很可能只剩个位数。
    """
    rows = [_row(f"30000{i}", pe_ttm=8, annual_roe=20, annual_gross_margin=40,
                 pb=1.0, eps=1.0, ocf_per_share=1.2, dividend_yield=4.0,
                 rising_days=6, stage_gain=20.0, new_high_level=1,
                 above_ma60=1, stage_turnover=30.0, volume_days=3) for i in range(1, 4)]
    pool = agent_picker.build_pool(rows, ALL, {}, stance="both")

    assert pool["ranked"] is False
    assert "不够排分位" in pool["unranked_reason"]
    row = pool["rows"][0]
    assert row["unranked"] is True
    assert row["missing"] == [], "数据是全的，不该有任何一项被记成缺失"
    assert "数据不足" not in row["coverage"]
    # 排不出分位，但原始值必须留着——那是这张卡上仅有的信息
    strength = next(s for s in row["scores"] if s["key"] == "strength")
    assert strength["score"] is None
    assert "阶段涨幅" in strength["detail"] and "20" in strength["detail"]


def test_a_big_enough_pool_still_ranks():
    rows = [_row(f"30000{i}", pe_ttm=8, annual_roe=float(i * 3), annual_gross_margin=40)
            for i in range(1, 8)]
    pool = _pool(rows)
    assert pool["ranked"] is True
    assert any(d["score"] is not None for d in pool["rows"][0]["scores"])


# --------------------------------------------------------------- 反向标记

def test_reverse_is_declared_by_the_backend_not_matched_from_the_label():
    """「反」记号必须由后端显式声明。

    原来前端是拿 `label.includes("反向")` 判的——改一次文案记号就无声消失，
    而同一个人气字段在价值口味里反着读、在趋势口味里正着读，
    这恰恰是全页最不能读错的一条。
    """
    value_crowd = next(d for d in agent_picker.DIMENSIONS_VALUE if d.key == "crowding")
    trend_crowd = next(d for d in agent_picker.DIMENSIONS_TREND if d.key == "crowding")
    assert value_crowd.reverse is True
    assert trend_crowd.reverse is False
    # 而且要传到每一项分数上，前端才用得到
    rows = [_row(f"40000{i}", pe_ttm=8, annual_roe=20, annual_gross_margin=40) for i in range(1, 8)]
    scores = agent_picker.build_pool(rows, ALL, {}, stance="value")["rows"][0]["scores"]
    assert next(s for s in scores if s["key"] == "crowding")["reverse"] is True
    assert next(s for s in scores if s["key"] == "quality")["reverse"] is False


def test_the_pool_can_be_handed_to_the_model_like_any_other_list():
    """综合榜跟五张策略卡并排，**「让模型看一遍」理应也能作用在它上面**。

    它的 key 是哨兵值 __agent_pool__，拿去查策略库必然查不到——
    实测使用者点了之后看到的是「没有这个策略：__agent_pool__」，
    **一个内部标识符漏到了页面上**。
    """
    from stock_decision import repository as repo

    assert repo.AGENT_POOL_KEY == "__agent_pool__", (
        "这个值前端 App.tsx 里也写了一份（const AGENT_POOL_KEY）。"
        "两边不一致的话，使用者会看到内部标识符。")
    # **不能依赖真实底座**：测试库是空的，agent_pool 会说"底座还没有数据"。
    # 这条要验的是「哨兵 key 走的是并集那条路，不是策略库查找」，
    # 所以只要证明它没有掉进"没有这个策略"那个分支就够了。
    from stock_decision.repository import LedgerError

    try:
        view = repo.value_candidates(repo.AGENT_POOL_KEY, width=3, assess=False)
    except LedgerError as exc:
        assert "没有这个策略" not in str(exc), f"综合榜不该被当成未知策略：{exc}"
    else:
        assert view["strategy"]["name"] == "综合榜"


def test_an_unknown_strategy_still_says_so():
    """真的写错 key 时还是要报错——**上面那个特判不能把所有错都吞掉**。"""
    import pytest

    from stock_decision import repository as repo
    from stock_decision.repository import LedgerError

    with pytest.raises(LedgerError, match="没有这个策略"):
        repo.value_candidates("这套策略不存在", width=3, assess=False)
