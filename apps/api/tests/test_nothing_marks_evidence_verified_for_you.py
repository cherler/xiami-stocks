"""**系统不许替人盖「已核验」。**

## 线上实测出来的

280 条证据，**全部是「已核验」，没有一条被人看过**。
也就是说这个标记在整个库里没有任何信息量 —— 它永远是那个值。

来源：`archive_inbox_batch` 一次归档最多 500 条公告，而
`InboxArchive.verification` 的默认值就是「已核验」。
更刺眼的是那个类的文档写着「判断由用户做出，系统不代劳」，
默认值跟它正好相反 —— 而手工建证据的默认是「待核验」（schemas.py:132/154）。
也就是说**只有批量归档这一条路会替人盖章**。

## 为什么这条比"标签不好看"重

「已核验」是在说"这条我看过了、是真的"。一个没人看过的判断被标成看过了，
**比没有这个标记糟得多**：复盘时你不会再去核它。

这跟本仓反复守的那条是同一件事 —— 读文档存证据时写的注释就是：
「**不是"已核对"。** 这是模型读出来的，页码在出处里，核对那一步得他自己做 ——
替他标成已核对是这一页最不该干的事。」而归档公告这条路上没人守住它。
"""

from __future__ import annotations

import ast
import pathlib

API = pathlib.Path(__file__).resolve().parents[1] / "stock_decision"


def _default_of(model: str, field: str) -> str | None:
    """从 schemas.py 里取某个模型某个字段的默认值。"""
    tree = ast.parse((API / "schemas.py").read_text(encoding="utf-8"))
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == model), None)
    if cls is None:
        return None
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != field or node.value is None:
            continue
        src = ast.unparse(node.value)
        hit = [part for part in ("已核验", "待核验", "待补证") if part in src]
        return hit[0] if hit else src
    return None


def test_archiving_an_announcement_does_not_claim_you_checked_it():
    assert _default_of("InboxArchive", "verification") == "待核验", (
        "把公告归档为证据时默认盖了「已核验」——而那一批是机器搬进来的，"
        "没有人看过。这个类自己的文档写着「判断由用户做出，系统不代劳」。")
    # 手工建证据本来就是「待核验」，三条路要一致
    for model in ("EvidenceCreate", "EvidenceUpdate"):
        got = _default_of(model, "verification")
        if got is not None:
            assert got == "待核验", f"{model} 的默认核验状态是 {got}"


def test_the_batch_archiver_does_not_pass_verified_explicitly():
    """默认值改了还不够 —— 调用方显式传「已核验」照样绕过去。"""
    tree = ast.parse((API / "repository.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "archive_inbox_batch")
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "verification":
                continue
            value = ast.unparse(kw.value)
            assert "已核验" not in value, (
                f"archive_inbox_batch 显式传了 {value} —— 一次五百条，"
                f"没有一条被人看过")


def test_there_is_a_way_back_for_the_ones_already_stamped():
    """存量也要能退回来。**改了默认值不会追溯已经写进库的 280 条。**"""
    source = (API / "repository.py").read_text(encoding="utf-8")
    assert "def unverify_bulk_archived_evidence" in source, (
        "没有把存量退回「待核验」的路 —— 那 280 条会永远标着没人核过的核验")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "unverify_bulk_archived_evidence")
    body = ast.unparse(fn)
    # **判据是"能不能回点原文"，不是"来自哪个域名"。**
    #
    # 第一版按巨潮/交易所三个域名认，线上退回 125 条、剩下 155 条 ——
    # 而那 155 条一条链接都没有（同花顺分红方案、新浪限售解禁、年报抽出来的
    # 客户集中度），同样没人看过。按域名认漏掉了它们，因为它们压根没有域名。
    #
    # 仓里本来就有这条判据（_industry_chain_verification）：
    # 「已核验」必须同时有可辨认的来源名和**可回点的链接**。沿用它。
    # 比字面会被 ast.unparse 的引号归一化坑到（它把双引号统一成单引号）——
    # 所以只找关键片段，不比整句。
    assert "source_url" in body and ".strip()" in body and " not " in body, (
        "没有链接的证据不许留着「已核验」—— 核不回原文的东西，"
        "「我看过了」这个标记就没有意义")
    assert "cninfo.com.cn" in body, "巨潮/交易所那几个域名也要认（它们有链接但同样是机器搬的）"
    assert "待核验" in body and "UPDATE evidences" in body
