"""清单一条都没命中时，说的必须是事实，不是猜测。

2026-08-19 全站巡检撞到：一份**标着「公告」、读出了 0.1 万字**的文件，
读完给出的解释是「多半不是年报/公告/研报这几类，或者它整份都读不出字」——
两个猜测都被同一屏上的信息当场否掉（标签写着公告，字数写着 0.1 万字）。
人看完只会更糊涂，然后去怀疑自己传错了文件。

类型是 detect_kind 判出来的、字数数一下就有 —— 两件事都在手上，不用猜。
"""
from __future__ import annotations

from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / "stock_decision" / "main.py").read_text()


def _empty_branch() -> str:
    """取出「一条都没命中」那个分支的**代码**，注释剥掉。

    第一版没剥：新代码的注释里引用了旧文案（「原来这句是……」），
    守卫当场把注释读成了代码，红在一个已经改好的地方。
    """
    at = MAIN.index('if not context["pages"]:')
    lines = MAIN[at:at + 2200].splitlines()
    return "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))


def test_不再拿类型和可读性去猜() -> None:
    branch = _empty_branch()
    for guess in ("多半不是年报/公告/研报这几类", "或者它整份都读不出字"):
        assert guess not in branch, (
            f"又在猜了：「{guess}」—— 类型和字数都是手上已有的事实"
        )


def test_扫描件和读得出字的说法不一样() -> None:
    """一页都读不出字 vs 读出来了但清单没命中，是两件事，该做的也不同。"""
    branch = _empty_branch()
    assert "readable" in branch, "没有区分「读不出字」和「读出来了但没命中」"
    assert "扫描件" in branch, "真是扫描件的时候要说清楚，那是换一份文件的信号"


def test_读出来了就要告诉人还能问它() -> None:
    """文件已经在库里、页也读出来了 —— 这时候最该说的是"可以直接问它"。"""
    branch = _empty_branch()
    assert "问它" in branch, "读进来了却不告诉人下一步能做什么，等于把人堵在这儿"
    # 类型要报出来：清单是按类型选的，人得知道它按哪张清单找的。
    assert 'f"按「{kind}」' in branch, "没说按哪张清单检索的"
