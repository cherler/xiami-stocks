"""本仓自己的日志要跟 uvicorn 走同一条出口，否则 journal 里看不到。

uvicorn 只配置它自己那几个 logger。本仓各模块用的是
`logging.getLogger(__name__)` —— 没有 handler、默认级别 WARNING，
于是所有 `logger.info` 都进不了 journal。实测撞到的：调度器每跑一个任务
都会打一行 info，线上一行都没有。

## 这几条为什么要用 uvicorn 真正的 LOGGING_CONFIG

第一版守卫自己往 `uvicorn.error` 上挂了个 handler 来"模拟 uvicorn"，
三条全绿、上线之后一行日志都没多出来 —— 因为 uvicorn 的配置里
`uvicorn.error` **自己没有 handler**，handler 挂在父 logger `uvicorn` 上，
靠冒泡输出。测的是我的假设，不是 uvicorn 的行为。

所以这里 import uvicorn 自己的 LOGGING_CONFIG 走一遍 dictConfig。
uvicorn 哪天改了结构，这几条会跟着红。
"""
from __future__ import annotations

import logging
import logging.config
from contextlib import contextmanager
from typing import Iterator

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
OURS = "stock_decision"


@contextmanager
def _clean_logging() -> Iterator[None]:
    """借走再还回去 —— 这几条会真改全局 logger 状态。"""
    saved = {
        name: (list(logging.getLogger(name).handlers),
               logging.getLogger(name).level,
               logging.getLogger(name).propagate)
        for name in (*UVICORN_LOGGERS, OURS)
    }
    for name in (*UVICORN_LOGGERS, OURS):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(logging.NOTSET)
    try:
        yield
    finally:
        for name, (handlers, level, propagate) in saved.items():
            lg = logging.getLogger(name)
            lg.handlers = handlers
            lg.setLevel(level)
            lg.propagate = propagate


def _as_uvicorn_would() -> None:
    """照 uvicorn 启动时那样配置 logging —— 不是我捏的近似。"""
    from uvicorn.config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)


def test_跑在_uvicorn_下时应用日志真的有出口() -> None:
    from stock_decision.main import _attach_app_logs_to_uvicorn

    with _clean_logging():
        _as_uvicorn_would()
        # 这一句是整条测试的支点：uvicorn.error 自己是没有 handler 的。
        # 只看它就会漏掉 —— 那正是上线时炸的那一下。
        assert not logging.getLogger("uvicorn.error").handlers

        _attach_app_logs_to_uvicorn()

        ours = logging.getLogger(OURS)
        assert ours.handlers, "应用日志没有出口，journal 里看不到"
        assert ours.level <= logging.INFO, "级别还是 WARNING，info 一行都出不去"


def test_子模块的_info_能一路走到出口() -> None:
    """调度器用的是 stock_decision.scheduler，靠冒泡到父 logger 出去。"""
    from stock_decision.main import _attach_app_logs_to_uvicorn

    with _clean_logging():
        _as_uvicorn_would()
        _attach_app_logs_to_uvicorn()

        seen: list[str] = []

        class Probe(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                seen.append(record.getMessage())

        probe = Probe()
        logging.getLogger(OURS).addHandler(probe)
        logging.getLogger("stock_decision.scheduler").info("running scheduled sync job %s", "universe")

    assert seen == ["running scheduled sync job universe"], seen


def test_不重复挂_也不打两遍() -> None:
    from stock_decision.main import _attach_app_logs_to_uvicorn

    with _clean_logging():
        _as_uvicorn_would()
        _attach_app_logs_to_uvicorn()
        first = list(logging.getLogger(OURS).handlers)
        _attach_app_logs_to_uvicorn()
        assert logging.getLogger(OURS).handlers == first, "接了两次，每行会打两遍"
        # 自己有 handler 了还往上冒，root 那头也会再打一遍。
        assert logging.getLogger(OURS).propagate is False


def test_不是_uvicorn_起的时候保持安静() -> None:
    """测试、脚本、迁移工具里不该自作主张改全局 logging。"""
    from stock_decision.main import _attach_app_logs_to_uvicorn

    with _clean_logging():
        _attach_app_logs_to_uvicorn()
        assert not logging.getLogger(OURS).handlers


def test_root_上的_handler_不算数() -> None:
    """pytest 和 basicConfig 都会往 root 挂 handler —— 那不是"跑在 uvicorn 下"。

    认了它，脚本和测试里也会被当成 uvicorn，把全局 logging 改掉。
    """
    from stock_decision.main import _attach_app_logs_to_uvicorn

    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        root.handlers = [logging.NullHandler()]
        with _clean_logging():
            _attach_app_logs_to_uvicorn()
            assert not logging.getLogger(OURS).handlers
    finally:
        root.handlers = saved
