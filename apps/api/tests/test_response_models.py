"""repository 返回的键，接口不能悄悄丢掉。

**同一个坑今天踩了三次。**

1. 候选初筛加了 verdict / reasons / concerns 三列，库里存了、repository 也返回
   了，但 FastAPI 的响应模型只输出自己声明过的键——接口出去就是没有，
   前端拿 undefined 去 .length，/stocks/tasks 整页白屏。
2. 产业链加了 label（图上的短名），一模一样：本地调 repository 一切正常，
   走接口出来就少一个键，图画不出节点。

两次的共同点是**它不报错**。少一个键不会 500、不会告警，只会让页面静静地
坏掉，而单测如果直接调 repository 就永远看不见——那一层正好被绕过去了。

3. 今日简报加了 context（页面靠它画图），一模一样：接口出去就是没有，
   图画不出来，页面回落成一大坨文字——而那正是这次改动要解决的问题。

4. 策略加了 kind（价值口味还是趋势口味），**又是一模一样**。这次是测试先红
   而不是页面白屏：荐股池按 kind 分池子，接口丢了这个键之后所有策略都会被
   当成价值型——趋势池会静静地混进价值股，而它看起来只是"结果有点怪"。
   这一条正好说明这份清单的价值：它是手维护的，而这次维护及时了。

所以这里不测业务，只测一件事：**这些函数返回的键，响应模型都认。**
加了新字段忘了同步声明，这里会红，而不是等页面白屏。

**加了新字段就往下面的清单里加一行。** 这份清单是手维护的——
自动比对做不到，因为 repository 返回什么取决于运行时数据。
手维护的代价是可能漏；漏了的代价是页面静静地少一块，而这一年里已经发生三次。

## 上面那句「自动比对做不到」只对了一半（2026-08-16 补）

对**这份清单管的那一半**是对的：模型不在源码里被构造，FastAPI 拿它去过滤
一个运行时才成形的字典，静态确实查不了。

但还有另一种形状是查得了的：`DashboardSummary(..., promises_due=...)` 这种
**在源码里带关键字构造**的。那一半现在由 `test_response_model_fields.py`
用语法树自动扫，扫到 115 处。

所以两边的分工是：**能静态查的它扫，查不了的这份清单守。**
删任何一边之前先读这一段。
"""

import pytest
from pydantic import BaseModel

from stock_decision import schemas


def _declared(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields.keys())


# (响应模型, 这个模型要覆盖的键) —— 键取自 repository 实际返回的形状。
# 加字段时把它加进这里，忘了声明就会在这条测试上红。
CONTRACTS: list[tuple[type[BaseModel], set[str]]] = [
    # **清流水是全站破坏力最大的接口**，它的响应形状要钉死：
    # deleted 少一个字段，页面就说不出"到底删掉了几条"，
    # 而删 0 条和删 34 条在界面上长得一模一样。
    (schemas.TradePurgeResult, {"deleted", "companies"}),
    (schemas.PurgedCompany, {"company_id", "name", "symbol", "trades"}),
    (schemas.ResearchTaskItem, {
        "id", "task_id", "symbol", "name", "industry", "evidence", "status", "note",
        "verdict", "reasons", "concerns",          # 白屏那次少的就是这三个
        "company_id", "brief", "brief_source", "links", "reports", "updated_at",
    }),
    (schemas.ResearchReport, {
        "id", "company_id", "company_name", "symbol", "version", "title", "body",
        "business", "changes", "implications",     # 研究简报的三节
        "citations", "unknowns", "source_count", "model", "created_at",
        # 深度报告：结论卡、分章、主题、来源、库里的数字
        "kind", "cards", "sections", "themes", "sources", "queries", "facts",
    }),
    (schemas.DailyBriefing, {
        "as_of", "headline", "market", "holdings", "pending", "watchlist",
        "actions", "gaps",
        "context",                                 # 页面靠它画图，丢了就只剩文字
        "boundary", "model", "created_at",
    }),
    (schemas.ResearchTaskItem, {
        "assessment", "assessed_at",               # 候选的方法体检结果
        "conclusion",                              # 模型初筛的结论（跟用户的 note 分开）
    }),
    (schemas.SupplyChainLink, {
        "id", "company_id", "relation", "counterpart",
        "label",                                   # 图上的短名，画节点全靠它
        "segment", "detail", "confidence", "source", "evidence_id", "created_at",
    }),
    (schemas.ThesisItem, {
        "id", "company_id", "symbol", "company_name", "claim", "status",
        "evidence_count", "counter_evidence_count", "next_review_trigger",
        # company_id：决策总览要一键跳到公司页（让反方驳一驳这条）。
        # 库里查出来一直有，是响应模型没声明——**第五次踩同一个坑之前拦住它**。
    }),
    (schemas.NewsItem, {
        "id", "feed_key", "feed_name", "title", "url", "summary", "published_at",
        "company_id", "company_name", "symbol", "match_confidence", "match_reason",
        "match_source", "status", "read_at",
    }),
    (schemas.NewsPage, {
        "items", "total", "linked", "boundary", "all", "pending", "archived", "ignored",
        "read", "unread",
    }),
    (schemas.DashboardSummary, {
        "drift_questions",      # 假设漂移：藏起来这个机制就废了
        "counter_hits",         # 侧栏徽章靠它——丢了徽章就永远是 0，没人会发现
        "inbox_backlog",        # 「中」级积压：收件箱页面要交代，但不进首页待办
    }),
    (schemas.ScreenStrategy, {
        "key", "name", "summary", "provenance", "biases", "rules",
        "sort_field", "sort_desc", "sort_label", "preset",
        "kind",            # 第四次了：荐股池按它分价值池/趋势池，丢了就全算价值型
        "forked_from", "required_fields", "available", "unavailable_reason",
    }),
]


@pytest.mark.parametrize("model,keys", CONTRACTS, ids=lambda x: getattr(x, "__name__", ""))
def test_the_response_model_declares_every_key(model: type[BaseModel], keys: set[str]) -> None:
    missing = keys - _declared(model)
    assert not missing, (
        f"{model.__name__} 没有声明这些字段：{sorted(missing)}。"
        "响应模型会把没声明的键静默丢掉——库里有、repository 也返回，接口出去就是没有，"
        "而前端拿 undefined 去 .length 就是一屏白。"
    )


def test_ai_text_never_leaks_raw_floats():
    """模型产出里不许出现 12 位小数。

    **这条要在读的时候守，不是只在写的时候守。** 「喂进提示词之前先取整」
    只在生成那一刻有效——生成器修好之前存下的东西会一直那样显示下去。
    实测：库里存过 97 处小数位 ≥ 4 的数（「营收同比 200.596381199%」
    「每股经营现金流 5.685126589991 元」），而生成器早两天就修好了。

    一个 12 位小数的同比增速传达的唯一信息，是没有人看过这段输出。
    """
    from stock_decision.jsonio import tidy_decimals

    assert tidy_decimals("营收同比 200.596381199%") == "营收同比 200.6%"
    assert tidy_decimals("每股经营现金流 5.685126589991 元") == "每股经营现金流 5.69 元"
    # 已经体面的数字不动
    assert tidy_decimals("净利润同比 7835.06% 极高") == "净利润同比 7835.06% 极高"
    # **日期、代码、版本号不许被误伤**——它们不是测量值
    assert tidy_decimals("报告期 2026-08-04，代码 600519，版本 1.2.3") == \
        "报告期 2026-08-04，代码 600519，版本 1.2.3"
    assert tidy_decimals("") == ""
