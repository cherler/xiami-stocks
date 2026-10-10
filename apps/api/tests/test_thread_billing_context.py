"""并发跑的活，**计费上下文必须显式带进线程**。

## 2026-08-16 实测

`ThreadPoolExecutor` **不复制**调用方的 context —— 新线程拿到的是全新的一份：

    主线程      记账桶在 True   计费主体在 True
    线程池里    记账桶在 False  计费主体在 False

后果不是"不计费"，是**记错人**：`llm.reserve` 取不到主体时会退回
`background_principal()`，也就是**站主**。于是别人跑一次多段读图，
钱扣在站主账上；而 `_record` 同样取不到记账桶，任务行上的 credits 停在 0 ——
他看到的是"这次没花钱"。

交割单读图是全站最贵的一次调用（图片 token 是文本的几十倍），
而它当时正是这么写的。promises.py 和 devils_advocate.py 早就修过同一处，
注释也写得很清楚 —— 当时 ledger_scan 没跟上（那个模块后来随读图功能一起删了）。

## 这个文件守的是「别再漏掉下一个」

不点名某一处的写法，而是把三个并发模块一起扫：**开了线程池就必须
在同一个函数里出现 copy_context**。新加一个并发模块而忘了带上下文，这里就红。
"""

import contextvars
import inspect
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from stock_decision import access, devils_advocate, llm, promises

# 用了线程池的模块 → 那个函数
CONCURRENT = [
    (promises, "extract"),
    (devils_advocate, "_cross_check"),
]


def test_a_plain_thread_pool_really_does_lose_the_context():
    """先把前提钉住：这条守卫的全部理由就是这个事实。

    哪天 Python 改了行为（线程自动继承 context），这条会红 ——
    那时候下面几条守卫就可以删了，而不是继续养着。
    """
    token = llm.start_accounting()
    llm.set_principal(llm.Principal(cookie="ck"))
    try:
        def peek(_):
            return (llm._accounting.get() is not None, llm._principal.get() is not None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            got = list(pool.map(peek, range(2)))
        assert all(bucket is False and principal is False for bucket, principal in got), (
            "线程池现在会继承 context 了 —— 那就把这个文件删掉，别留着装样子。")
    finally:
        llm.reset_accounting(token)
        llm.set_principal(None)


@pytest.mark.parametrize("module,func", CONCURRENT, ids=[f"{m.__name__.split('.')[-1]}.{f}" for m, f in CONCURRENT])
def test_every_concurrent_module_carries_its_context(module, func):
    """**开了线程池就必须带上下文。** 新加一个并发模块而忘了带，这里红。"""
    source = inspect.getsource(getattr(module, func))
    if "ThreadPoolExecutor" not in source:
        pytest.skip(f"{module.__name__}.{func} 已经不并发了")
    assert "copy_context" in source, (
        f"{module.__name__}.{func} 开了线程池，却没有 copy_context ——\n"
        f"  计费主体取不到时会退回 background_principal()，也就是**站主**：\n"
        f"  别人跑的活，钱扣在站主账上，而任务行上的 credits 停在 0。")


@pytest.mark.parametrize("module,func", CONCURRENT, ids=[f"{m.__name__.split('.')[-1]}.{f}" for m, f in CONCURRENT])
def test_each_thread_gets_its_own_copy(module, func):
    """**一份 Context 不能被多个线程同时进入。**

    复制一份共用，除第一个线程外全部抛
    "cannot enter context: ... is already entered" —— 而那个错的表现是
    「12 批只有 1 批有结果」，且少掉的那几批不报错、只是没有内容。
    所以必须是**每个任务一份**，判据是复制那一句在一个推导式里。
    """
    source = inspect.getsource(getattr(module, func))
    if "copy_context" not in source:
        pytest.skip("上一条会先红")
    assert re.search(r"\[\s*contextvars\.copy_context\(\)\s+for\b", source), (
        f"{module.__name__}.{func} 只复制了一份 Context 给多个线程共用 ——\n"
        f"  除第一个线程外会全部抛 cannot enter context，而表现是「大半批没有结果」。")


def test_the_owner_is_who_pays_when_the_principal_is_missing():
    """把「记错人」这件事本身钉住：没有主体时退回的是站主，不是不计费。

    这也是为什么上面那条不能降级成 warning —— 它错了钱有人付，只是付的人不对。
    """
    source = inspect.getsource(llm.reserve)
    assert "background_principal()" in source
    assert "XM_OWNER_USER_ID" in inspect.getsource(llm.background_principal)
