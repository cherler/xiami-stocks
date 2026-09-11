"""报价公式被写了两份：Python 一份，TypeScript 一份。

## 2026-08-16 主动排查（第二轮：数字阈值）抓到的

    后端 assessment.estimate_candidate_credits
         tokens = 1500 + count * 200 + min(count * 120, 3000)
         return max(1, ceil(tokens / 5000))

    前端 App.tsx
         Math.max(1, Math.ceil((1500 + width * 200 + Math.min(width * 120, 3000)) / 5000))

**一模一样的算术，两种语言各写一遍。** 前端那行上面的注释自己写着后果：

    「两边算法要一致，否则页面说 2 分、实际扣 3 分。」

现在两边确实一致 —— 所以这不是一个已经在坏的 bug。但它是一个
**只要有人改一边就会坏、而且坏了不报错**的地方：页面照常显示一个数，
扣的是另一个数，谁也不会发现，直到有人对账。

## 为什么是守卫而不是重构

把报价挪到后端接口是"正确"的做法，但这条路上跑的是**真金白银的报价**，
而且它随滑块实时变（每动一下要一次往返）。为一个此刻并没有坏的地方
去改一条计费链路，风险大于收益。

所以这里做的是：**把前端那一行的四个数抠出来，跟后端的常量逐个对**。
改一边而不改另一边，这条就红。
"""

import math
import re
from pathlib import Path

import pytest

from stock_decision.assessment import estimate_candidate_credits

APP = Path(__file__).resolve().parents[2] / "web" / "src" / "App.tsx"


def _frontend_formula() -> tuple[int, int, int, int]:
    """把前端那一行里的四个数抠出来：固定开销 / 每家 / 封顶 / 每分多少 token。"""
    source = APP.read_text(encoding="utf-8")
    hit = re.search(
        r"Math\.max\(1,\s*Math\.ceil\(\(\s*(\d+)\s*\+\s*\w+\s*\*\s*(\d+)"
        r"\s*\+\s*Math\.min\(\w+\s*\*\s*\d+,\s*(\d+)\)\s*\)\s*/\s*(\d+)\)\)",
        source)
    assert hit, (
        "在 App.tsx 里找不到那条报价公式了。\n"
        "  它要么被挪走了（那很好——挪到后端接口就不需要这条守卫，把这个文件删掉），\n"
        "  要么被改成了另一种写法（那就把这里的正则跟着改）。\n"
        "  **别直接跳过**：这条守卫在的理由是「页面说 2 分、实际扣 3 分」不报错。")
    return tuple(int(g) for g in hit.groups())  # type: ignore[return-value]


def test_the_two_implementations_use_the_same_numbers():
    """四个数逐个对。改一边而不改另一边，这条就红。"""
    fixed, per, cap, per_credit = _frontend_formula()
    assert (fixed, per, cap, per_credit) == (1500, 200, 3000, 5000), (
        f"前端报价公式的数变了：固定 {fixed} / 每家 {per} / 封顶 {cap} / 每分 {per_credit}\n"
        f"  后端 assessment.estimate_candidate_credits 里那份没跟着改。")


@pytest.mark.parametrize("count", [1, 2, 3, 5, 8, 10, 12, 20, 25, 30, 40, 60, 100])
def test_both_sides_quote_the_same_number(count):
    """**算出来的分数要一样**，不只是常量一样。

    只对常量是不够的：括号位置、封顶用在哪一项、向上还是向下取整，
    任何一处不同都会在某个区间上分叉 —— 而分叉的那个区间未必是你测的那几个数。
    """
    fixed, per, cap, per_credit = _frontend_formula()
    frontend = max(1, math.ceil((fixed + count * per + min(count * 120, cap)) / per_credit))
    assert frontend == estimate_candidate_credits(count), (
        f"候选 {count} 家时两边报价不一致：前端 {frontend} 分、后端 "
        f"{estimate_candidate_credits(count)} 分。\n"
        f"  页面上写的是前端那个数，实际扣的是后端那个。")


def test_the_frontend_says_where_the_other_copy_lives():
    """两份实现之间必须有一句话互相指认。

    没有那句话的话，改的人根本不知道另一头还有一份 ——
    这也是这一整轮排查里反复出现的那个形状。
    """
    source = APP.read_text(encoding="utf-8")
    assert "estimate_candidate_credits" in source, (
        "前端那份报价公式没有指出后端的对应实现叫什么名字。")


# ------------------------------------------- 同一轮排查的第三处：资料档位两份名单

def test_the_report_legend_knows_every_tier_the_backend_can_emit():
    """深度报告那条「资料可信度构成」的条，前端自己列了一份档位次序
    （DeepReport.tsx 的 KIND_ORDER）。后端能产出的档位一旦多一个，
    它就不进那条 —— 而那条的全部意义就是"一手占多少"。

    少算一块的后果是给出一个**偏高**的一手占比，且百分比加起来不到 100
    也没人会注意。现在认不出的会排在最后照旧显示（不再 filter 掉），
    这条守的是「两份名单别再漂」。
    """
    import inspect
    import re

    from stock_decision import websearch

    backend = set(re.findall(r'return "([^"]+)"', inspect.getsource(websearch.source_kind)))
    backend.add("本地已归档")     # repository 拼引用清单时加的那一档

    front = Path(__file__).resolve().parents[2] / "web" / "src" / "components" / "DeepReport.tsx"
    order = re.search(r"const KIND_ORDER = \[([^\]]+)\]", front.read_text(encoding="utf-8"))
    assert order, "DeepReport.tsx 里找不到 KIND_ORDER 了"
    listed = set(re.findall(r'"([^"]+)"', order.group(1)))

    missing = sorted(backend - listed)
    assert not missing, (
        f"后端会产出这几档，而前端的 KIND_ORDER 里没有：{missing}\n"
        f"  它们不会出现在覆盖率条上 —— 而那条读的是「一手占多少」。")
