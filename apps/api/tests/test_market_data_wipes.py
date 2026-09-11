"""同步作业之间会不会互相把数据抹掉。

这一类 bug 有个共同点：**每个作业单独看都是对的**。底座作业忠实地写下了它拿到的
东西（一堆 NULL，因为源降级了），趋势作业忠实地重置了它负责的列——错在两者
凑在一起时，后跑的那个把先跑的成果抹掉了，而**谁都不会报错**。

单测各自的函数看不出这件事，所以这里专门测「跑完 A 再跑 B」。
"""

import pytest

from stock_decision.database import connection, now_iso


def _seed(symbol: str = "600519", **fields) -> None:
    columns = ["symbol", "name", "exchange", "board", "updated_at"] + list(fields)
    values = [symbol, "测试", "上交所", "主板", now_iso()] + list(fields.values())
    placeholders = ", ".join("?" for _ in columns)
    with connection() as conn:
        conn.execute(
            f"INSERT INTO market_universe ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values))


def _read(column: str, symbol: str = "600519"):
    with connection() as conn:
        row = conn.execute(
            f"SELECT {column} AS v FROM market_universe WHERE symbol = ?", (symbol,)).fetchone()
    return None if row is None else row["v"]


def test_a_degraded_snapshot_cannot_clear_what_a_working_source_filled():
    """**降级的行情源不该有权清空满源填好的字段。**

    全市场快照被挡之后会降级到新浪，而新浪不给换手率——provider 里显式写着
    `turnover_rate: None`。原来底座的 upsert 是 `turnover_rate = excluded.turnover_rate`
    （同一条语句里的财务字段全都包了 COALESCE，行情字段没有，这个不一致就是 bug），
    于是「全市场底座」每天把趋势作业刚填好的换手率冲成空。

    当时没爆只是因为调度顺序凑巧：底座(6) → 情绪面(7) → 趋势面(8)，趋势那步又补了
    回来。**手动重跑一次底座就没了，而且要等 24 小时才回来**——期间任何用换手率的
    自定义策略都会时灵时不灵，而没有任何报错。
    """
    _seed(turnover_rate=1.23, float_market_cap=9.9e9)

    # 模拟降级后的底座 upsert：这几列拿回来的一律是 None
    with connection() as conn:
        conn.execute(
            """INSERT INTO market_universe (symbol, name, exchange, board,
                   turnover_rate, float_market_cap, ytd_change, change_60d, updated_at)
               VALUES ('600519', '测试', '上交所', '主板', NULL, NULL, NULL, NULL, ?)
               ON CONFLICT(symbol) DO UPDATE SET
                   float_market_cap = COALESCE(excluded.float_market_cap, market_universe.float_market_cap),
                   turnover_rate = COALESCE(excluded.turnover_rate, market_universe.turnover_rate),
                   ytd_change = COALESCE(excluded.ytd_change, market_universe.ytd_change),
                   change_60d = COALESCE(excluded.change_60d, market_universe.change_60d),
                   updated_at = excluded.updated_at""",
            (now_iso(),))

    assert _read("turnover_rate") == 1.23, "降级的快照把换手率冲掉了"
    assert _read("float_market_cap") == 9.9e9


def test_the_real_upsert_in_the_repository_keeps_turnover(monkeypatch):
    """上面那条是照着 SQL 写的，这条跑的是**产品代码里那一句**。

    照抄 SQL 的测试有个老毛病：SQL 改了它不会红。所以这里直接调
    refresh_market_universe，喂一份降级的快照。
    """
    from stock_decision import repository

    _seed(turnover_rate=4.56)

    monkeypatch.setattr(repository, "fetch_market_spot", lambda: {
        "rows": [{"symbol": "600519", "name": "测试", "price": 10.0, "change_percent": 1.0,
                  "pe_ttm": None, "pb": None, "total_market_cap": None,
                  "float_market_cap": None, "turnover_rate": None,
                  "ytd_change": None, "change_60d": None}],
        "source": "新浪全市场快照（降级）", "degraded": True,
        "missing_fields": ["换手率"]})
    monkeypatch.setattr(repository, "fetch_market_fundamentals",
                        lambda period: {"rows": [], "source": None, "report_date": period})
    monkeypatch.setattr(repository, "fetch_index_members",
                        lambda: {"members": [], "source": None, "missing_indexes": []})
    monkeypatch.setattr(repository, "fetch_market_dividends",
                        lambda period: {"rows": [], "source": None})

    repository.refresh_market_universe()
    assert _read("turnover_rate") == 4.56, "跑完全市场底座之后换手率没了"


def test_a_partly_failed_trend_sync_keeps_the_columns_it_could_not_refresh(monkeypatch):
    """**四个榜单里挂了几个，不该让另外几个的数据被清零。**

    原来只要主力那份（量价齐升）成功就整表重置，于是另外三个挂掉时
    above_ma60 与 new_high_level 被刷成 0：「趋势突破型」和「创新高型」当天筛出
    0 只，作业还报「成功」，页面提示"先去数据状态页跑一次全市场趋势面"——
    而它刚跑过。**一个缺了两列的结果，看起来跟完整的一模一样。**
    """
    from stock_decision import repository

    _seed(above_ma60=1, new_high_level=3, volume_days=5, rising_days=2)

    monkeypatch.setattr(repository, "fetch_market_trend", lambda: {
        "rows": [{"symbol": "600519", "rising_days": 7, "stage_gain": 12.0,
                  "stage_turnover": 20.0, "above_ma60": 0, "new_high_level": 0,
                  "volume_days": 0}],
        # 只有量价齐升那一组到位
        "synced": ["rising"],
        "expected": ["breakout", "new_high", "rising", "volume"],
        "source": "同花顺榜单", "notes": ["向上突破榜失败"]})

    result = repository.refresh_market_trend()

    assert result["status"] == "部分失败", "缺了三组信号还报成功，页面就看不出来了"
    assert set(result["missing"]) == {"breakout", "new_high", "volume"}
    assert any("保留的是上一次的值" in note for note in result["notes"])
    # 到位的那一组照常刷新
    assert _read("rising_days") == 7
    # 没到位的三组保留原值，而不是被刷成 0
    assert _read("above_ma60") == 1, "突破榜没同步到，却把站上均线抹成了 0"
    assert _read("new_high_level") == 3, "创新高榜没同步到，却把档位抹成了 0"
    assert _read("volume_days") == 5


def test_a_fully_successful_trend_sync_does_reset_everything(monkeypatch):
    """全部到位时该重置就要重置——昨天上榜今天掉下来的票不能留着昨天的值。"""
    from stock_decision import repository

    _seed("600519", above_ma60=1, new_high_level=3, volume_days=5, rising_days=2)
    _seed("600036", above_ma60=1, new_high_level=2, volume_days=4, rising_days=6)

    monkeypatch.setattr(repository, "fetch_market_trend", lambda: {
        "rows": [{"symbol": "600519", "rising_days": 7, "stage_gain": 12.0,
                  "stage_turnover": 20.0, "above_ma60": 1, "new_high_level": 1,
                  "volume_days": 2}],
        "synced": ["breakout", "new_high", "rising", "volume"],
        "expected": ["breakout", "new_high", "rising", "volume"],
        "source": "同花顺榜单", "notes": []})

    result = repository.refresh_market_trend()
    assert result["status"] == "成功"
    # 600036 今天不在任何榜上 → 归零，而不是留着昨天的
    assert _read("above_ma60", "600036") == 0
    assert _read("new_high_level", "600036") == 0
    assert _read("rising_days", "600036") == 0
