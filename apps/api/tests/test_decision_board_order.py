"""决策看板的排序：**「命中」排到了「还没写下判断」下面。**

## 2026-08-16 实测

`_ACTION_WEIGHT` 里有五种待办（反证/复核/公告/补全/无），而 `decision_board`
实际会产出**七种** —— 少的两种是「命中」和「体检」。
`.get(kind, 9)` 的兜底恰好是「无」（今天不用管）那一档，于是：

    1. [公告] 美的集团 — 3 条实质公告还没核验
    2. [补全] 格力电器 — 还没写下判断
    3. [命中] 贵州茅台 — 公告命中了你写的反证条件      ← 排在这里
    4. [无]   宁德时代 — 今天不用管

而这张表下面十几行就写着：「**命中排在最前面**。别的待办是「该去看看」，
这一条是「你写下的卖出条件被触发了」—— 它是唯一一件不处理就等于假装没看见的事。」

它连排在「今天不用管」前面都只是巧合：两者权重都是 9，
只因为那只票恰好在持仓里，第二个排序键才把它抬了一位。
换一只没持仓的票，「命中」就会按名字排到最后。

## 同一个概念，两份名单

首页那个红点此前犯过一模一样的错（只数「反证」不数「命中」）。
改的时候只补了**计数**，没补**排序**：

    App.tsx   byKind("命中") + byKind("反证")      ← 已经修过
    repository _ACTION_WEIGHT = {"反证": 0, ...}   ← 没跟上

所以这里守的不是"把两种补进去"，而是**这张表必须覆盖代码会产出的每一种**。
"""

import ast
import inspect
import textwrap

import pytest

from stock_decision import repository


def _kinds_the_code_can_produce() -> set[str]:
    """从 decision_board 的源码里把所有 `action, kind = (…, "…")` 抠出来。

    **不手写一份清单** —— 手写的那份正是这次出错的原因（两处各写一份，
    改了一处忘了另一处）。

    **用 ast，不用正则。** 我第一版写的是正则 `kind\\s*=\\s*\\(?[^,\\n]*,\\s*"…"`，
    它抠出六种、独独漏了「命中」—— 因为那一条的 action 串跨了两行，
    而正则里那个 `[^,\\n]*` 过不去换行。于是这条守卫在**它唯一真正要守的那一种**
    上是瞎的：修之前它照样绿。语法树不认换行也不认缩进。
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(repository.decision_board)))
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            # 形如 `action, kind = (..., "命中")`
            if (isinstance(target, ast.Tuple)
                    and [getattr(n, "id", None) for n in target.elts] == ["action", "kind"]
                    and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
                    and isinstance(node.value.elts[1], ast.Constant)):
                kinds.add(node.value.elts[1].value)
    return kinds


def test_every_kind_the_board_produces_has_a_weight():
    """**新加一种待办而权重表没跟上，这里就红。**

    不是"补上那两种"，而是让它下次漏不掉。
    """
    produced = _kinds_the_code_can_produce()
    assert produced, "没从源码里抠到任何 kind —— 赋值形状变了，这条守卫要跟着改"

    missing = sorted(produced - set(repository._ACTION_WEIGHT))
    assert not missing, (
        f"这几种待办会被产出，但排序表里没有：{missing}\n"
        f"  `.get(kind, 9)` 的兜底跟「无」（今天不用管）是同一档 ——\n"
        f"  也就是说它们会被排到最后，跟「没事可做」混在一起。")


def test_a_counter_hit_sorts_above_everything_else():
    """代码注释说得很明白：命中是**唯一一件不处理就等于假装没看见的事**。
    排序必须跟那句话一致。"""
    weight = repository._ACTION_WEIGHT
    assert weight["命中"] == min(weight.values())
    for other in ("反证", "复核", "公告", "补全", "体检", "无"):
        assert weight["命中"] < weight[other], other


def test_the_order_is_the_one_the_comments_describe():
    """反证 > 复核 > 公告 > 补全 —— 前端的待办分组也是照这个次序排的
    （App.tsx 那句「次序与后端 _ACTION_WEIGHT 一致」）。两处不能各定一套。"""
    weight = repository._ACTION_WEIGHT
    order = ["命中", "反证", "复核", "公告", "补全", "体检"]
    values = [weight[kind] for kind in order]
    assert values == sorted(values) and len(set(values)) == len(values), \
        f"次序乱了或有并列：{dict(zip(order, values))}"


def test_nothing_to_do_still_sorts_last():
    """「今天不用管」必须排在所有真待办后面 —— 否则这一页的头几行会是空的。"""
    weight = repository._ACTION_WEIGHT
    assert weight["无"] == max(weight.values())
    assert weight["无"] > weight["体检"], "体检是真待办，不能跟「今天不用管」并列"


def test_the_hit_goes_first_even_when_it_is_not_held():
    """**这一条钉住的是那次巧合。**

    修之前「命中」排在「今天不用管」前面，靠的是第二个排序键（持仓在前），
    不是权重。换一只没持仓的票，它就掉到最后了。
    """
    rows = [
        {"action_kind": "命中", "name": "寒武纪", "held": False},
        {"action_kind": "公告", "name": "美的集团", "held": True},
        {"action_kind": "补全", "name": "格力电器", "held": True},
        {"action_kind": "无", "name": "宁德时代", "held": True},
    ]
    rows.sort(key=lambda item: (repository._ACTION_WEIGHT.get(item["action_kind"], 9),
                                not item["held"], item["name"]))
    assert rows[0]["action_kind"] == "命中", [r["action_kind"] for r in rows]
