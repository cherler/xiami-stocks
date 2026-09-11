"""接口写好了、前端一次都没调过 —— 这一类失败后端全绿，页面上什么都没有。

2026-08-15 普查：178 条 API 路由里，前端源码一处都搜不到的有 12 条。
多数是运维接口（未计费台账、RUM、全市场内部数据），本来就不该有页面入口。
但其中两条是**用户功能的最后一步**，缺了它整条链就是单向门：

    POST /counter-hits/{id}/acknowledge   反证命中的"我处理过了"
    POST /inbox/{id}/reopen               误忽略了拿回来

第一条尤其讽刺：`acknowledged` 只有那个接口能置 1，所以命中一旦出现就永远
挂在侧栏徽章上。而这个徽章当初的设计理由写在 schemas.py 里 ——
「未读公告长期停在 646，一个永远清不完的红点第三天就成了背景色」。
为了避开那件事而做的徽章，自己成了一个永远清不完的红点。

这个文件盯的是**有没有调用方**，不是接口对不对。
"""

import pathlib
import re

import pytest

from test_idor import client, owned  # noqa: F401

WEB = pathlib.Path(__file__).resolve().parents[2] / "web" / "src"
SRC = "\n".join(p.read_text(encoding="utf8")
                for p in list(WEB.rglob("*.ts")) + list(WEB.rglob("*.tsx")))

# 路径 → 为什么它必须有前端入口
MUST_BE_REACHABLE = {
    "/api/v1/counter-hits/{}/acknowledge":
        "没有它，反证命中永远挂在徽章上——而这个徽章就是为了不变成常驻红点才做的",
    "/api/v1/inbox/{}/reopen":
        "没有它，忽略是个单向门；而自动整理会成批地忽略程序性文件",
}


@pytest.mark.parametrize("path,why", sorted(MUST_BE_REACHABLE.items()))
def test_the_frontend_can_actually_reach_it(path, why):
    probe = re.escape(path).replace(r"\{\}", r"[^\"'`]*")
    assert re.search(probe, SRC), f"{path} 没有任何前端调用方 —— {why}"


def test_ignored_inbox_items_are_not_invisible():
    """收件箱原来把状态写死成「待核验」：忽略掉的条目从界面上彻底消失。

    接口一直支持按状态查，是前端没给入口。**能忽略、看不见、拿不回来**
    是三件事叠在一起才成了单向门，所以这一条盯的是"看得见"那一半。
    """
    assert re.search(r'getInbox\(\s*box\b', SRC) or '"已忽略"' in SRC, \
        "收件箱看不到已忽略的条目"


# ---------------------------------------------- 「已忽略」那一档不能是空壳

def test_the_ignored_box_actually_lists_the_ignored(client, owned):  # noqa: F811
    """**默认只看"值得看"那几档，只对「待核验」成立。**

    翻「已忽略」的时候，要看的恰恰就是被扫走的程序性文件（relevance = 低）。
    拿"值得看"的档位去筛它，列表必然是空的，而计数还照实显示 23 条 ——
    页面上就成了"说有 23 条、一条都不给看"。2026-08-15 线上实测就是这样，
    而那一版的状态切换是我自己刚加的。
    """
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import list_inbox

    client.as_user(access.OWNER_SCOPE)
    with connection() as conn:
        conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at,
                inbox_status, relevance)
               VALUES (?, '公告', ?, ?, '测试', ?, '已忽略', '低')""",
            (owned["company"], "第三届董事会第七次会议决议公告",
             "2026-08-15", "2026-08-15"))

    box = list_inbox("已忽略", limit=40, days=None)
    assert box["total"] >= 1
    assert box["items"], "计数说有，列表却是空的 —— 那比不给这一档还糟"


def test_the_pending_box_still_hides_procedural_files(client, owned):  # noqa: F811
    """反过来也要成立：收件箱本身还是要替你挡掉程序性文件。"""
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import list_inbox

    client.as_user(access.OWNER_SCOPE)
    with connection() as conn:
        conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at,
                inbox_status, relevance)
               VALUES (?, '公告', ?, ?, '测试', ?, '待核验', '低')""",
            (owned["company"], "第二届监事会第二十八次会议决议公告",
             "2026-08-15", "2026-08-15"))

    titles = [i["title"] for i in list_inbox("待核验", limit=40, days=None)["items"]]
    assert not any("监事会" in t for t in titles), "程序性文件不该占用待核验这一档"


# ------------------------------ 首页是唯一一个反证命中看不见的页面

def test_the_counter_hit_banner_is_not_excluded_from_the_home_page():
    """**它原来在首页被豁免了，而首页是所有人落地的第一屏。**

    豁免的理由写在代码里：「那一屏的 Headline 已经把同一条命中放大到整屏了」。
    这个理由在 Headline 被挪进折叠区之后就不成立 —— `<Fold>` 是
    `{open && children}`，收起来时连 DOM 都没有。于是首页成了唯一一个
    反证命中什么都不显示的页面。

    Headline 自己的说明写得更清楚：它当初就是把这条横幅和反方入口
    **合并成一块放到第一屏**的，理由是"两块加起来正好是这个产品的全部卖点，
    却被摊在一列十二块面板里，谁都不显眼"。合并之后整块沉进了折叠区。
    """
    assert 'page !== "dashboard" && <Suspense fallback={null}><CounterHitBanner' not in SRC, \
        "首页又把反证命中横幅豁免掉了"
    assert "CounterHitBanner onOpenCompany" in SRC


def test_things_buried_in_the_fold_at_least_announce_themselves():
    """折叠区里那几件事**没有第二个入口**，所以标题上得带数。

    折叠状态下 children 不渲染 —— 用户不会去展开一个他不知道里面有什么的分区。
    反证比对、缺认错条件、假设漂移，三件都只活在这一个折叠区里。
    """
    for token in ("条公告还没比对过认错条件", "条判断还差认错条件", "个假设漂移还没回答"):
        assert token in SRC, f"折叠标题上没有「{token}」，里面那件事就没人知道"
