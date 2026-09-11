"""第一天：对着一个全新的库，应用能不能起来。

**这是最少被跑到的状态，也因此是最容易坏的。** 线上那套表早就建好了，
所以启动顺序错了几个月都没人知道——直到换一台机器、或者从备份重建。

实测过的症状：`sqlite3.OperationalError: no such table: background_jobs`，
然后 `Application startup failed. Exiting.` —— 不是降级，是整个起不来。
"""

import os
import sqlite3

import pytest


def test_the_app_starts_against_a_brand_new_database(tmp_path, monkeypatch):
    """**建表必须排在所有读写之前。**

    lifespan 里原来是 recover_stale_jobs() 排在 initialize_database() 前面，
    而它第一句就查 background_jobs。空库上必炸。
    """
    from fastapi.testclient import TestClient

    from stock_decision import database

    fresh = tmp_path / "brand_new.db"
    assert not fresh.exists(), "这条测试的前提就是「库还不存在」"

    monkeypatch.setattr(database, "_database_path", fresh)
    monkeypatch.setattr(database, "backend", lambda: "sqlite")

    from stock_decision.main import app

    # 走完整的 lifespan：TestClient 作为上下文管理器时才会触发 startup
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    with sqlite3.connect(fresh) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "background_jobs" in tables, "启动之后这张表就该在了"
    assert "companies" in tables


def test_the_startup_order_is_not_quietly_reversed():
    """顺序是这条 bug 的全部内容，所以直接盯住顺序。

    上面那条测试在 PostgreSQL 后端下测不出来（schema 是共享的、早就建好了），
    而线上跑的正是 PG —— 所以补一条不依赖后端的：读源码确认先后。
    """
    import inspect

    from stock_decision import main

    body = inspect.getsource(main.lifespan)
    assert body.index("initialize_database()") < body.index("recover_stale_jobs()"), \
        "建表必须排在 recover_stale_jobs 之前，否则空库上直接起不来"
