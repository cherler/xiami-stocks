"""三份示例公司档案：让新用户第一眼看到的不是一个空产品。

使用者截了一屏承诺台账说"没有结果和一堆的解释说明"——那一屏是结论两行、
解释五段，而它显得那么啰嗦，一大半原因是**它是空的**：四段说明包着一句
「还没有记录任何承诺」。一个空的研究台没法解释自己。

这里守四件事：
- **不覆盖使用者自己的档案**：已经有同代码公司的跳过。
- **删得掉**。不能删的示例等于强塞。
- **看得出是示例**：companies.is_sample 与 theses.is_sample 两个标记。
- **示例里的数字必须是真的**——它是新用户学"一条判断长什么样"的样本，
  数字错了等于教他写一条核不对的判断。
"""

from __future__ import annotations

from stock_decision import access
from stock_decision import repository as repo
from stock_decision.samples import SAMPLES


def _in_scope(scope: str, fn):
    token = access.set_scope(scope)
    try:
        return fn()
    finally:
        access.reset_scope(token)


def test_samples_are_created_and_marked():
    result = _in_scope("t-samples-1", repo.load_samples)
    assert len(result["created"]) == len(SAMPLES)

    def _check():
        with repo.connection() as conn:
            companies = repo._rows(conn.execute(
                "SELECT name, is_sample FROM companies WHERE user_id = ?",
                ("t-samples-1",)).fetchall())
            theses = repo._rows(conn.execute(
                """SELECT t.is_sample FROM theses t JOIN companies c ON c.id = t.company_id
                   WHERE c.user_id = ?""", ("t-samples-1",)).fetchall())
        return companies, theses

    companies, theses = _in_scope("t-samples-1", _check)
    assert len(companies) == len(SAMPLES)
    assert all(row["is_sample"] == 1 for row in companies), "示例要看得出是示例"
    assert all(row["is_sample"] == 1 for row in theses), "那条判断也要带标记"


def test_samples_never_overwrite_the_users_own_company():
    """**已经有同代码档案的跳过。** 覆盖掉使用者自己写的判断是不可接受的。"""
    from stock_decision.schemas import CompanyInput

    def _seed_own():
        repo.create_company(CompanyInput(
            symbol=SAMPLES[0]["symbol"], name="我自己建的", industry="白酒"))
        return repo.load_samples()

    result = _in_scope("t-samples-2", _seed_own)
    assert SAMPLES[0]["name"] in result["skipped"]

    def _check():
        with repo.connection() as conn:
            return repo._one_or_none(conn.execute(
                "SELECT name, is_sample FROM companies WHERE user_id = ? AND symbol = ?",
                ("t-samples-2", SAMPLES[0]["symbol"])).fetchone())

    row = _in_scope("t-samples-2", _check)
    assert row["name"] == "我自己建的", "使用者自己的档案被覆盖了"
    assert row["is_sample"] == 0


def test_samples_can_be_removed():
    """**不能删的示例等于强塞。**"""
    _in_scope("t-samples-3", repo.load_samples)
    result = _in_scope("t-samples-3", repo.remove_samples)
    assert len(result["removed"]) == len(SAMPLES)

    def _left():
        with repo.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM companies WHERE user_id = ?",
                ("t-samples-3",)).fetchone()["n"]

    assert _in_scope("t-samples-3", _left) == 0


def test_removing_samples_leaves_the_users_own_companies_alone():
    """一键删除只删示例。**误删他自己的档案是不可挽回的。**"""
    from stock_decision.schemas import CompanyInput

    def _mixed():
        repo.load_samples()
        repo.create_company(CompanyInput(symbol="000002", name="我自己建的", industry="房地产"))
        return repo.remove_samples()

    _in_scope("t-samples-4", _mixed)

    def _left():
        with repo.connection() as conn:
            return repo._rows(conn.execute(
                "SELECT name FROM companies WHERE user_id = ?", ("t-samples-4",)).fetchall())

    left = _in_scope("t-samples-4", _left)
    assert [row["name"] for row in left] == ["我自己建的"]


def test_every_sample_thesis_has_a_checkable_counter_condition():
    """**示例同时是模板和教学。**

    这个产品的核心产出是「一句可以被证伪的主张 + 一条能真去查的认错条件」。
    示例里的认错条件如果写成「基本面恶化」这种，等于教人写一条永远不会触发的。
    """
    import re

    for sample in SAMPLES:
        counter = sample["thesis"]["counter_condition"]
        assert re.search(r"\d", counter), f"{sample['name']} 的认错条件里没有一个数字"
        assert sample["thesis"]["next_review_trigger"], f"{sample['name']} 没写复核触发"
        for vague in ("基本面恶化", "长期看好", "前景不明"):
            assert vague not in counter, f"{sample['name']} 用了空话：{vague}"
