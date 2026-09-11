"""交割单读图：切片、去重、对账。

这个功能此前**完全不能用**，而原因在图还没进模型之前就已经发生了：
一张 1256×20748 的手机长截图，视觉接口会把它压成 95 像素宽再交给模型。
95 像素宽的表格，每一行数字都是一道横杠——而它不报错，模型照样一本正经地
返回 JSON，只是里面的数字全是编的。

所以这里守的第一件事就是：**长图必须被切开，而且切完要盖满。**

后面几条守的是切开之后新长出来的风险。它们都不是假想的，
每一条都对应实测中真的发生过一次的事故。
"""

import io

import pytest

from stock_decision import ledger_scan as ls


def _png(width: int, height: int) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------ 切片

def test_a_long_screenshot_must_be_sliced():
    """**这是整个功能能不能用的分水岭。**

    不切的话，接口会把长边压到 1568 像素，20748 高的图于是只剩 95 像素宽。
    """
    tiles, geometry = ls._slice(_png(1256, 20748))
    assert geometry["sliced"] is True
    assert len(tiles) > 1
    # 反过来算一遍：不切会被压成多少宽。这个数就是这个功能坏掉的全部原因。
    assert round(1256 * ls.MAX_EDGE / 20748) < 100


def test_every_tile_fits_the_vision_limits():
    """每一片都要真的在限制以内——超一点点就又会被悄悄缩一次。"""
    from PIL import Image
    tiles, _ = ls._slice(_png(1256, 20748))
    for tile in tiles:
        with Image.open(io.BytesIO(tile)) as image:
            assert max(image.size) <= ls.MAX_EDGE
            assert image.size[0] * image.size[1] <= ls.MAX_PIXELS


def test_the_slices_cover_the_whole_image():
    """**最后一段必须盖到底。**

    第一版的偏移量算到 `height - overlap` 就停了，于是图最下面不到一个步长的
    那一截没有任何一片盖到——而那一截正是最早的几笔建仓记录。
    """
    _, geometry = ls._slice(_png(1256, 20748))
    stride = ls._stride_for(geometry["tile_height"])
    last_top = (geometry["slices"] - 1) * stride
    assert last_top + geometry["tile_height"] >= geometry["height"], "最后一段没盖到图的底部"


def test_every_row_lands_in_two_tiles():
    """重叠要大到让一整行同时落在两片里，不只是"别切断"。

    这是防**模型漏读**用的：实测同一片图连读两次，一次 6 行一次 4 行，
    中间两笔卖出凭空消失。两片各读一次再取并集，一片漏了另一片还在。
    """
    _, geometry = ls._slice(_png(1256, 20748))
    stride = ls._stride_for(geometry["tile_height"])
    assert stride * 2 + ls.ROW_MAX_HEIGHT <= geometry["tile_height"]


def test_the_declared_content_type_is_not_trusted():
    """**`file.content_type` 是浏览器自己填的，拦不住任何东西。**

    声明 image/png、实际塞一个 TIFF 进来，那道闸门照样放行，
    然后 Pillow 会去解码它——而 Pillow 历年的高危漏洞几乎全在冷门解码器里。
    真正的判据是打开之后它自己认出来的格式。
    """
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (900, 3000), (255, 255, 255)).save(buffer, format="TIFF")
    with pytest.raises(RuntimeError, match="实际是 TIFF"):
        ls._slice(buffer.getvalue())


def test_a_decompression_bomb_is_refused_before_it_is_decoded():
    """**文件大小拦不住解压炸弹。**

    几十 KB 的 PNG 可以解开成五万乘五万，一张就把内存吃光，
    而它完全符合 12 MB 的限制。Image.open 只读文件头，
    所以这道闸门放在 convert() 前面才有意义——放后面就是先炸再拦。
    """
    from PIL import Image
    buffer = io.BytesIO()
    # 纯色大图压完只有几十 KB，正是炸弹的形状
    Image.new("L", (12000, 12000)).save(buffer, format="PNG")
    payload = buffer.getvalue()
    assert len(payload) < ls.MAX_IMAGE_BYTES, "这张图小得能过体积闸门，正是重点"
    with pytest.raises(RuntimeError, match="兆像素"):
        ls._slice(payload)


def test_a_small_image_is_left_alone():
    tiles, geometry = ls._slice(_png(800, 1200))
    assert geometry["sliced"] is False and len(tiles) == 1


def test_width_is_traded_for_height_not_thrown_away():
    """宽度决定认不认得出数字，高度决定要调几次模型——**这是两件事**。

    第一版按原始分辨率切，一片只装得下 915 像素高，同一张图要切 28 片、
    调 28 次。收宽度到刚好还认得清，片数立刻降到一半以下。
    """
    _, geometry = ls._slice(_png(1256, 20748))
    assert geometry["width"] == ls.TARGET_WIDTH
    assert geometry["slices"] < 20


# ------------------------------------------------------------------ 合并

def _page(trades, **extra):
    return {"trades": trades, "warnings": [], **extra}


def test_the_same_row_read_by_two_tiles_becomes_one():
    row = {"side": "sell", "trade_date": "2025-07-14", "price": 47.64, "shares": 500, "fee": 17.52}
    _, _, _, rows, _ = ls._merge([_page([row]), _page([dict(row)])])
    assert len(rows) == 1
    assert rows[0]["_seen_in"] == 2, "两段都读到了，要能数出来"


def test_a_number_written_two_ways_is_still_one_row():
    """一段读成 "47.640"、另一段读成 47.64——直接比字符串会当成两笔。"""
    a = {"side": "sell", "trade_date": "2025-07-14", "price": "47.640", "shares": "500"}
    b = {"side": "sell", "trade_date": "2025-07-14", "price": 47.64, "shares": 500}
    _, _, _, rows, _ = ls._merge([_page([a]), _page([b])])
    assert len(rows) == 1


def test_no_date_is_ever_invented():
    """**这一条是这个文件里最重要的测试。**

    第一版让缺日期的行继承上一行的日期，理由听起来很硬（列表按日期排序）。
    但模型返回的行序并不稳定，而且继承会跨过段边界——结果造出了一条
    `2024-10-17 卖出 47.99/1000`，它其实是 10-22 那笔，价量费一模一样，
    只有日期是错的。于是它跟真身对不上、去不掉重，**变成账本里凭空多出的一笔**。

    漏一笔核对时能发现；**多一笔你会当成真的**，因为它的价和量都对。
    """
    dated = {"side": "sell", "trade_date": "2024-10-22", "price": 47.99, "shares": 1000}
    orphan = {"side": "buy", "trade_date": "", "price": 43.21, "shares": 1100}
    _, _, _, rows, _ = ls._merge([_page([dated]), _page([orphan])])
    orphaned = [r for r in rows if not r.get("trade_date")]
    assert len(orphaned) == 1
    assert orphaned[0]["price"] == 43.21, "没日期的行不许被安上前一行的日期"


def test_a_row_missing_only_its_date_is_matched_back_to_itself():
    """切片盖不到分组标题时，同一行会有一个"没日期"的版本。

    按（方向·价·量·现金）认回它的正身——认回去，而不是猜一个日期填上。
    """
    dated = {"side": "sell", "trade_date": "2025-07-14", "price": 47.64, "shares": 500, "fee": 17.52}
    headless = {"side": "sell", "trade_date": "", "price": 47.64, "shares": 500}
    _, _, _, rows, _ = ls._merge([_page([dated]), _page([headless])])
    assert len(rows) == 1
    assert rows[0]["trade_date"] == "2025-07-14"
    assert rows[0]["_seen_in"] == 2


def test_half_rows_at_the_slice_edge_are_dropped():
    """价、量、现金一个都没有的行是被切在边缘只露出半截的，留着只会变成空记录。"""
    _, _, _, rows, _ = ls._merge([_page([{"side": "buy", "trade_date": "2025-01-01"}])])
    assert rows == []


def test_the_page_header_is_picked_up_from_whichever_tile_has_it():
    """代码只在整张长图最上面出现一次，后面每一段都没有。"""
    symbol, company, _, _, _ = ls._merge([
        _page([], page_symbol="000651", page_company="格力电器"),
        _page([{"side": "buy", "trade_date": "2025-01-01", "price": 40, "shares": 100}]),
    ])
    assert (symbol, company) == ("000651", "格力电器")


def test_the_fee_checksum_is_carried_out():
    """页头的「交易税费」合计是这张图上唯一的校验和，必须带出来。"""
    _, _, fee_total, _, _ = ls._merge([_page([], page_fee_total=1055.09), _page([])])
    assert fee_total == 1055.09


# ------------------------------------------------------------------ 走整条路（不调模型）

class _Fake:
    """按固定脚本回答的假模型：第 i 次调用返回第 i 页。

    只为验证合并与闸门，不验证模型认字。**串行调用**（见 _run 里把并发设成 1），
    否则第几次调用拿到哪一页是不确定的，测试会时红时绿。
    """

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = 0

    def __call__(self, image_bytes, media_type, hint, timeout):
        import json as _json
        page = self.pages[self.calls] if self.calls < len(self.pages) else {"trades": []}
        self.calls += 1
        return type("C", (), {"text": _json.dumps(page)})()


ROSTER = [{"id": 7, "symbol": "000651", "name": "格力电器"}]


def _height_for(tiles: int) -> int:
    """找出正好切成 tiles 片的原图高度。

    切片的步长与收边逻辑不是一句公式，写死一个高度会在参数一改动就整片变红——
    而那时你会去改测试，不是去想参数改得对不对。
    """
    for height in range(1000, 60000, 200):
        _, geometry = ls._slice(_png(1256, height))
        if geometry.get("slices") == tiles and geometry["sliced"]:
            return height
    raise AssertionError(f"找不到能切成 {tiles} 片的高度")


def _run(monkeypatch, pages, **kwargs):
    monkeypatch.setattr(ls, "SLICE_CONCURRENCY", 1)
    monkeypatch.setattr(ls, "_call_vision", _Fake(pages))
    return ls.scan_screenshot(_png(1256, _height_for(len(pages))), "image/png", ROSTER, **kwargs)


def test_a_negative_quantity_is_made_positive(monkeypatch):
    """卖出那几行的数量在券商 App 上带负号（−500）。

    照抄进账本就是一笔负持仓，而方向本来就由 side 表达了。
    """
    result = _run(monkeypatch, [_page([
        {"side": "sell", "trade_date": "2025-07-14", "price": 47.64, "shares": -500, "fee": 17.52}])])
    assert result["trades"][0]["shares"] == 500
    assert "带负号" in result["trades"][0]["note"]


def test_a_trade_amount_never_becomes_cash_income(monkeypatch):
    """模型很自然地会把买卖行的「成交金额」填进 cash_amount（实测就是这样）。

    而账本把这个字段当现金流入——一笔 22170 元的卖出会变成 22170 元的分红收入，
    收益率整个错掉。
    """
    result = _run(monkeypatch, [_page([
        {"side": "sell", "trade_date": "2025-06-23", "price": 44.34, "shares": 500,
         "fee": 16.31, "cash_amount": 22170.0}])])
    assert result["trades"][0]["cash_amount"] is None
    assert "22170" in result["trades"][0]["note"]


def test_a_dividend_never_carries_shares_or_price(monkeypatch):
    """**归一的另一半，第一版漏了。**

    券商 App 的分红行「数量」栏印着 0、「价格」栏印着除息基准价，模型照抄下来
    （提示词说了不要填，但那两个数就摆在那儿）。而账本的 shares 是 gt=0——
    一个 shares=0 的分红行会被校验直接打回，报「股数必须大于 0」，
    **而且会连累整批记不进去**。症状离原因很远：图读得好好的，就是存不进去。
    """
    result = _run(monkeypatch, [_page([
        {"side": "dividend", "trade_date": "2025-05-14", "price": 46.9, "shares": 0,
         "fee": 0, "cash_amount": 4800.0}])])
    row = result["trades"][0]
    assert row["shares"] is None, "分红行带着 shares=0 会被 gt=0 挡回来"
    assert row["price"] is None, "那是除息基准价，不是成交价"
    assert row["cash_amount"] == 4800.0
    # 原图上确实印着那两个数，去掉之后要在备注里说一声，别让人以为读漏了
    assert "数量栏" in row["note"] and "除息基准价" in row["note"]


def test_a_dividend_keeps_its_cash(monkeypatch):
    result = _run(monkeypatch, [_page([
        {"side": "dividend", "trade_date": "2025-05-14", "cash_amount": 4800.0, "fee": 0}])])
    assert result["trades"][0]["cash_amount"] == 4800.0


def test_conflicting_sides_are_never_silently_kept_both_ways(monkeypatch):
    """同一天、同价、同量、同费，一条写买一条写卖——这不是两笔，是读错了一次。

    **方向读错是最贵的一种错**：持仓与成本同时错，而页面上看起来完全正常。
    """
    good = {"side": "sell", "trade_date": "2025-08-05", "price": 46.69, "shares": 500, "fee": 17.17}
    bad = {**good, "side": "buy"}
    result = _run(monkeypatch, [_page([good]), _page([good]), _page([bad])])
    assert len(result["trades"]) == 1
    assert result["trades"][0]["side"] == "sell", "该留下被两段印证过的那条"
    assert any("方向不一致" in w for w in result["warnings"])


def test_an_undecidable_conflict_keeps_both_and_says_so(monkeypatch):
    """两条都没被印证过的时候，删掉一半等于替人瞎猜——那就都留着、明说矛盾。"""
    good = {"side": "sell", "trade_date": "2025-08-05", "price": 46.69, "shares": 500, "fee": 17.17}
    bad = {**good, "side": "buy"}
    result = _run(monkeypatch, [_page([good]), _page([bad])])
    assert len(result["trades"]) == 2
    assert any("都没有被印证过" in w for w in result["warnings"])


def test_rows_read_by_only_one_tile_are_flagged(monkeypatch):
    """没被印证过的行要标出来——这是唯一能让"漏读"从看不见变成看得见的地方。"""
    a = {"side": "buy", "trade_date": "2025-01-05", "price": 40.0, "shares": 100, "fee": 5}
    b = {"side": "buy", "trade_date": "2025-01-06", "price": 41.0, "shares": 100, "fee": 5}
    result = _run(monkeypatch, [_page([a, b]), _page([a])])
    by_date = {str(t["trade_date"]): t for t in result["trades"]}
    assert by_date["2025-01-05"]["cross_checked"] is True
    assert by_date["2025-01-06"]["cross_checked"] is False
    assert any("只有一段读到" in w for w in result["warnings"])


def test_the_fee_total_is_reconciled(monkeypatch):
    """**这是唯一一个不靠感觉、能直接算出来的完整性检查。**"""
    row = {"side": "buy", "trade_date": "2025-01-05", "price": 40.0, "shares": 100, "fee": 5.0}
    matched = _run(monkeypatch, [_page([row], page_fee_total=5.0)])
    assert matched["reconcile"]["matched"] is True

    off = _run(monkeypatch, [_page([row], page_fee_total=16.0)])
    assert off["reconcile"]["matched"] is False
    assert off["reconcile"]["gap"] == -11.0
    assert any("对不上" in w and "漏了一笔" in w for w in off["warnings"])


def test_no_checksum_is_said_out_loud(monkeypatch):
    """**「没法检验」不能长得像「检验过了，没问题」。**

    上面那条是唯一一个不靠感觉的完整性检查。有页头合计时，对上了会说读全了、
    对不上会说差多少；而**没有页头合计时这里原来一句话都没有** ——
    于是"这次根本没检验"和"检验过了没问题"在页面上一模一样。

    跟反证条件那次是同一种错：0 有两种意思，界面上只有一个数。
    """
    row = {"side": "buy", "trade_date": "2025-01-05", "price": 40.0, "shares": 100, "fee": 5.0}
    result = _run(monkeypatch, [_page([row])])          # 页头没有「交易税费」

    assert result["reconcile"] is None
    assert any("没有办法检验" in w for w in result["warnings"]), result["warnings"]
    # 还要给出下一步：光说"没法检验"他不知道能怎么办
    assert any("把页头那一栏也截进来" in w for w in result["warnings"])


def test_a_named_company_can_be_pinned_by_hand(monkeypatch):
    """个股交易记录页每一行都没有代码，页头也常常只有名称。

    指定一次比让模型猜二十次可靠——实测格力那张页头就没有代码。
    """
    result = _run(monkeypatch, [_page([
        {"side": "buy", "trade_date": "2025-01-05", "price": 40.0, "shares": 100}])],
        company_id=7)
    assert result["trades"][0]["company_id"] == 7
    assert result["trades"][0]["symbol"] == "000651"
    assert result["unmatched"] == []


def test_one_bad_tile_does_not_sink_the_whole_image(monkeypatch):
    """一段读失败不该让整张图白跑——那一段记进 warnings，其余照常返回。"""
    calls = {"n": 0}

    def flaky(image_bytes, media_type, hint, timeout):
        import json as _json
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("模型请求失败（HTTP 500）")
        return type("C", (), {"text": _json.dumps(_page([
            {"side": "buy", "trade_date": "2025-01-05", "price": 40.0, "shares": 100, "fee": 5}]))})()

    monkeypatch.setattr(ls, "_call_vision", flaky)
    result = ls.scan_screenshot(_png(1256, 6000), "image/png", ROSTER)
    assert result["trades"], "其余段的结果要照常返回"
    assert any("没读成功" in w for w in result["warnings"])


def test_a_tiny_screenshot_is_refused_up_front(monkeypatch):
    """糊得读不出来的图，现在就说清楚该怎么办，别花一次调用再返回空。

    判据用**原图宽度**，不是文件大小——一张三兆的长截图每个字也可能只有几像素，
    而此前那道「小于 40 KB 就拒绝」的闸门正好放过了真正读不出来的那一类。
    """
    monkeypatch.setattr(ls, "_call_vision", _Fake([_page([])]))
    with pytest.raises(RuntimeError, match="像素宽"):
        ls.scan_screenshot(_png(320, 9000), "image/png", ROSTER)


# ------------------------------------------------------------------ 记完之后

def test_the_scan_result_does_not_come_back_after_it_is_recorded(monkeypatch):
    """**记完再进来，同一批流水原样还在——点两次就记两遍。**

    「回来还能接上」是有意做的（读图在服务端跑几分钟，切页面不该白跑），
    但它没有区分"还没记"和"已经记过"。而账本里两笔一模一样的交易，
    事后没有任何办法分辨哪一笔是多的。
    """
    from fastapi.testclient import TestClient

    from stock_decision import repository as repo
    from stock_decision.database import connection, now_iso
    from stock_decision.main import app

    client = TestClient(app)
    with connection() as conn:
        conn.execute(
            """INSERT INTO background_jobs (user_id, kind, target_id, label, status, progress,
                                            total, note, error, created_at, updated_at, result_json)
               VALUES ('__owner__', 'ledger_scan', 0, '读交割单', '已完成', 0, 0, '', '', ?, ?, ?)""",
            (now_iso(), now_iso(), '{"trades": [{"side": "buy"}, {"side": "sell"}], "warnings": []}'))

    # 还剩一条没记：结果留着，但只剩那一条
    assert client.post("/api/v1/ledger/scan/keep",
                       json={"trades": [{"side": "sell"}]}).json()["kept"] == 1
    job = client.get("/api/v1/jobs/ledger_scan/0").json()
    assert len(job["result"]["trades"]) == 1

    # 一条不剩：整个结果清掉，再进来不会又冒出来
    assert client.post("/api/v1/ledger/scan/keep", json={"trades": []}).json()["kept"] == 0
    job = client.get("/api/v1/jobs/ledger_scan/0").json()
    assert job["result"] is None, "记完之后不该还留着，否则点两次记两遍"


def test_rows_already_in_the_ledger_are_recognised():
    """**补录时最容易出的事。**

    上次只记了勾上的那些，这次回来补剩下的，一个「全选」就把已经记过的又记一遍。
    而账本里两笔一模一样的交易，事后没有任何办法分辨哪一笔是多的——
    它不报错，只是让成本价一直偏。
    """
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    portfolio = client.post("/api/v1/portfolios",
                            json={"name": "补录", "amount_mode": "full"}).json()
    company = client.post("/api/v1/companies", json={
        "symbol": "000651", "name": "格力电器", "industry": "白色家电"}).json()
    client.post(f"/api/v1/portfolios/{portfolio['id']}/trades", json={
        "company_id": company["id"], "side": "buy", "trade_date": "2026-01-05",
        "shares": 500, "price": 40.0, "fee": 5.0, "rationale": "上次记过的那笔"})

    body = client.post("/api/v1/ledger/scan/known", json={
        "portfolio_id": portfolio["id"], "trades": [
            {"side": "buy", "trade_date": "2026-01-05", "shares": 500, "price": 40.0,
             "company_id": company["id"]},                       # 已经有了
            {"side": "buy", "trade_date": "2026-01-06", "shares": 500, "price": 41.0,
             "company_id": company["id"]},                       # 还没记
            {"side": "sell", "trade_date": "2026-01-05", "shares": 500, "price": 40.0,
             "company_id": company["id"]},                       # 同日同价同量但方向不同
        ]}).json()
    assert body["known"] == [0], body


def test_an_identical_trade_is_flagged_not_blocked():
    """同一天拆单成交出两笔完全相同的记录是真会发生的。

    **只标记，不拦截**——替人决定不记就是替人做主。
    """
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    portfolio = client.post("/api/v1/portfolios",
                            json={"name": "拆单", "amount_mode": "full"}).json()
    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    row = {"company_id": company["id"], "side": "buy", "trade_date": "2026-01-05",
           "shares": 100, "price": 1500.0, "fee": 5.0, "rationale": "拆单第一笔"}
    for _ in range(2):
        assert client.post(f"/api/v1/portfolios/{portfolio['id']}/trades",
                           json=row).status_code == 201
    assert client.get(f"/api/v1/portfolios/{portfolio['id']}").json()["trade_count"] == 2
