"""明显不可能的输入不该进库。

2026-08-19 巡检换角度：不看正常路径，直接往接口上打边界值。

**一笔 1e15 股就把整个账本变成废纸：**

    持仓成本 100,000,000,000,020,000 元
    市值     1,307,880,000,000,261,600 元
    浮动盈亏 +1,207,880%

下限一直是硬的（负数、零、坏日期都拒了，「成交价要大于 0。」还是人话），
**上限却一直是空的**。挡的是"手滑多打几个零"和"把总金额填进单价"，不是挡真实交易。

另一条：`ABCDEF`、`60051🍤` 都能建成公司档案，而且被 exchange_for_symbol
推断出了交易所 —— 那个函数的注释写着「exchange is a deterministic property of
the six-digit code」，而这个前提从来没人保证。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from stock_decision.schemas import CompanyFromQuoteInput, CompanyInput, TradeCreate, WatchlistImportRow


def _trade(**extra):
    return TradeCreate(**{"company_id": 1, "side": "buy", "shares": 100, "price": 100, **extra})


@pytest.mark.parametrize("field,value", [("shares", 1e15), ("price", 1e9), ("fee", 1e12)])
def test_大得不可能的数要拒(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _trade(**{field: value})


def test_正常量级照旧能过() -> None:
    """上限不能挡住真实交易：一百万股、一千三一股（茅台）、一万块手续费。"""
    _trade(shares=1_000_000, price=1300, fee=10_000)


def test_交易日期不能填未来() -> None:
    """未来的一笔会排在流水最前面，让"最近一笔"和移动加权成本都跟着错。"""
    with pytest.raises(ValidationError):
        _trade(trade_date=date.today() + timedelta(days=1))
    _trade(trade_date=date.today())          # 今天可以


def test_下次复核可以是未来() -> None:
    """那个字段本来就该指向未来 —— 别把两件事一起拦了。"""
    _trade(review_due=date.today() + timedelta(days=90))


@pytest.mark.parametrize("symbol", ["ABCDEF", "60051🍤", "6005190", "60051", "", " "])
def test_不是六位数字的代码不许建档(symbol: str) -> None:
    with pytest.raises(ValidationError):
        CompanyInput(symbol=symbol, name="测试", industry="待补充")
    with pytest.raises(ValidationError):
        CompanyFromQuoteInput(symbol=symbol)


@pytest.mark.parametrize("symbol", ["600519", "000001", "688256", "430047"])
def test_六位数字照旧(symbol: str) -> None:
    CompanyInput(symbol=symbol, name="测试", industry="待补充")


def test_批量导入不在模型上拦() -> None:
    """导入是逐条处理、逐条报告的：坏代码在行情校验那步被拒，并原样列给用户看。

    在模型上拦的话，整批会在构造时崩掉 —— 用户反倒不知道坏在哪条。
    （试过一次，`test_watchlist_import_validates_every_symbol` 当场红。）
    """
    WatchlistImportRow(symbol=" ")
    WatchlistImportRow(symbol="ABCDEF")
