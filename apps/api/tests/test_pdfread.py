"""读一份 PDF：一页一段、表格还是表格、读不到的说出来。

## 这个文件守的三件事

1. **空单元格不许消失。** 茅台 2026 半年报 11033 个单元格里 39% 是空的；
   纯文本抽取下它们直接消失，于是一行只剩一个数时，你没法知道它是本期还是上期。
   分不清「这一项是 0」和「这一项没有」，研究用途下这是硬伤。
2. **读法按页选，不按文件选。** layout 模式对表格更好、对双栏更糟，
   而普通模式正好相反 —— 券商研报大多是双栏。
3. **读不到的页要出现在结果里。** 静默降级跟"这份文件里没有这句话"长得一模一样。
"""

import pytest

from stock_decision import pdfread


def test_a_broken_file_is_not_silently_empty():
    """**打不开要抛，不能返回空列表。** 空列表会被读成"这份文件里什么都没有"。"""
    with pytest.raises(pdfread.PdfUnreadable):
        pdfread.read_pages(b"this is not a pdf at all")
    with pytest.raises(pdfread.PdfUnreadable):
        pdfread.read_pages(b"%PDF-1.4\n truncated garbage")


def test_two_column_pages_are_recognised_by_the_gap_in_the_middle():
    """双栏排版在 layout 模式下每一行中间都有一大段空白，单栏正文不会。

    判错了最坏是这一页读法不理想，**不会丢内容** —— 所以判据可以简单。
    """
    two_col = "\n".join(
        f"左栏第 {i} 行的一些正文内容        右栏第 {i} 行的另一些正文内容" for i in range(10))
    assert pdfread.looks_two_column(two_col) is True

    one_col = "\n".join(f"这是单栏正文的第 {i} 行，连续排下来没有中间的大段空白。" for i in range(10))
    assert pdfread.looks_two_column(one_col) is False

    # 行数太少时不判 —— 一页只有标题时，两个词之间的空格会被当成栏间距
    assert pdfread.looks_two_column("标题        页码") is False


def test_an_empty_cell_survives_as_an_empty_cell():
    """**这是整个文件的理由。** 「已赚保费」那一行三列全空，说明茅台没有这项收入；
    纯文本抽取下这一行只剩四个字，跟一个折行的标签长得一模一样。"""
    table = [["项目", "附注", "本期", "上期"],
             ["利息收入", "44", "1,574,811,118.73", "1,704,408,137.13"],
             ["已赚保费", None, None, None],
             [None, None, None, None]]                 # 整行皆空：分隔线，丢掉
    text = pdfread._rows_to_text(table)
    lines = text.split("\n")
    assert lines[2] == "已赚保费 |  |  | ", f"空列被吃掉了：{lines[2]!r}"
    assert lines[2].count("|") == 3, "四列就该有三个分隔符，少一个就说明有一列被吃了"
    assert len(lines) == 3, "整行皆空的分隔线不该占一行"
    assert "1,574,811,118.73 | 1,704,408,137.13" in lines[1], "两个数要分得开哪个是本期"


def test_the_summary_counts_what_could_not_be_read():
    """「读了 108 页、2 页是扫描件」和「读了 110 页」是两个完全不同的结论 ——
    而后者会让人以为那 2 页里没有他要找的东西。"""
    pages = [
        {"page": 1, "mode": "表格", "text": "甲 | 1", "tables": 1, "note": ""},
        {"page": 2, "mode": "扫描件", "text": "", "tables": 0, "note": "这一页没有文字层（扫描件或整页图片），读不出内容"},
        {"page": 3, "mode": "版面", "text": "一段正文", "tables": 0, "note": ""},
    ]
    got = pdfread.summarize(pages)
    assert got["pages"] == 3 and got["read"] == 2
    assert got["modes"] == {"扫描件": 1, "版面": 1, "表格": 1}
    # **给页码，不是给总数** —— 他要能自己去翻那一页
    assert got["unreadable"] == [{"page": 2, "why": pages[1]["note"]}]


def test_the_page_cap_is_reported_not_silent():
    """砍掉的页要报数。少读几页跟"这份文件里没有"长得一模一样。"""
    assert pdfread.MAX_PAGES >= 200, "招股书两三百页是常态，上限太低会天天截断"


# ------------------------------------------------------- 定价

def test_reading_a_document_is_priced_apart_from_the_generic_formula():
    """**通用公式把输入输出一视同仁，而读 PDF 99% 是输入。**

    那份 64 万字的年报按通用价 128 分（约 14 元），而模型真实成本不到 1 元 ——
    按通用价卖，这个功能没人敢用第二次。
    """
    from stock_decision.llm import credits_for, credits_for_document

    huge = 640_000
    assert credits_for(huge) == 128                       # 通用：14 元
    assert credits_for_document(huge, 3_000) <= 30        # 读文档：3 元出头
    # 便宜四倍以上，否则这个单独的定价就不值得存在
    assert credits_for_document(huge, 3_000) * 4 <= credits_for(huge)


def test_asking_the_same_document_a_second_question_is_nearly_free():
    """**命中缓存那一档是这个功能的关键。**「上传一份年报连着问五个问题」
    在通用定价下是五次全价；模型那边第二次起走前缀缓存，成本掉三十倍。"""
    from stock_decision.llm import credits_for_document

    first = credits_for_document(640_000, 3_000)
    again = credits_for_document(640_000, 1_500, cached=True)
    assert again * 4 <= first, f"追问 {again} 分 vs 首次 {first} 分，没体现出缓存"
    assert again >= 1, "不许标成 0 分 —— 0 会被当成 bug，而它确实还有成本"


def test_output_is_priced_higher_than_input_because_it_costs_more():
    """输出比输入贵三倍（$0.66 vs $0.22）。一视同仁的话，
    「读 64 万字给我一句话」和「读一句话给我 64 万字」会卖同一个价。"""
    from stock_decision.llm import credits_for_document

    assert credits_for_document(80_000, 0) < credits_for_document(0, 80_000)


# ------------------------------------------------- 读法真的按页选了吗

class _FakePage:
    def __init__(self, plain: str, layout: str) -> None:
        self.plain, self.layout = plain, layout

    def extract_text(self, extraction_mode: str = "plain") -> str:
        return self.layout if extraction_mode == "layout" else self.plain


class _FakeReader:
    is_encrypted = False

    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages


class _FakePlumberPage:
    def __init__(self, tables: list) -> None:
        self._tables = tables

    def extract_tables(self) -> list:
        return self._tables


class _FakePlumber:
    def __init__(self, pages: list[_FakePlumberPage]) -> None:
        self.pages = pages


TWO_COL_PLAIN = "\n".join(f"左栏第 {i} 行的正文" for i in range(10))
TWO_COL_LAYOUT = "\n".join(
    f"左栏第 {i} 行的一些正文内容        右栏第 {i} 行的另一些正文内容" for i in range(10))


def test_a_two_column_page_is_read_in_plain_mode_not_layout():
    """**这一条以前只测了判断函数，没测它有没有被用上。**

    变异测试里把 `if looks_two_column(...)` 改成 `if False`，八条测试全绿 ——
    守卫在它要守的那件事上正好是瞎的（本会话第三次）。

    layout 会把两栏交错读成一行（「左栏正文  右栏正文」），而普通模式先读完左栏
    再读右栏，是对的。券商研报大多是双栏。
    """
    page = pdfread._read_one(
        _FakeReader([_FakePage(TWO_COL_PLAIN, TWO_COL_LAYOUT)]),
        _FakePlumber([_FakePlumberPage([])]), 0)
    assert page["mode"] == "双栏"
    assert page["text"] == TWO_COL_PLAIN, "双栏页用了 layout —— 两栏会交错成一行"


def test_a_page_with_tables_keeps_both_the_table_and_the_text_around_it():
    """**表外的字也要留。**「单位：元 币种：人民币」写在表头外面，
    丢了它整张表的数量级就错了 —— 而那种错在图上完全看不出来。"""
    page = pdfread._read_one(
        _FakeReader([_FakePage("单位：元 币种：人民币", "单位：元 币种：人民币")]),
        _FakePlumber([_FakePlumberPage([[["项目", "本期"], ["营业总收入", "922.8"]]])]), 0)
    assert page["mode"] == "表格" and page["tables"] == 1
    assert "单位：元" in page["text"], "表外的单位说明被丢了"
    assert "营业总收入 | 922.8" in page["text"]


def test_a_page_with_no_text_layer_says_it_is_a_scan():
    """扫描件不是错误，是这一页本来就取不到文字。**但它必须出现在结果里。**"""
    page = pdfread._read_one(_FakeReader([_FakePage("", "")]),
                             _FakePlumber([_FakePlumberPage([])]), 0)
    assert page["mode"] == "扫描件" and page["text"] == ""
    assert "扫描件" in page["note"]


def test_one_broken_page_does_not_kill_the_whole_file():
    """一页解析失败就整份读不出来，是最没必要的一种失败。"""
    class _Boom(_FakePage):
        def extract_text(self, extraction_mode: str = "plain") -> str:
            raise ValueError("字体表坏了")

    page = pdfread._read_one(_FakeReader([_Boom("", "")]),
                             _FakePlumber([_FakePlumberPage([])]), 0)
    assert page["mode"] == "读不到" and "ValueError" in page["note"]


# ------------------------------------------------- 检索：先定位再读

from stock_decision import documents as doc  # noqa: E402

PAGES = [
    {"page": 1, "mode": "版面", "text": "公司概况与主营业务介绍", "tables": 0, "note": ""},
    {"page": 2, "mode": "表格", "text": "前五名客户合计销售金额 | 14.4% | 前五名供应商合计采购金额 | 32.75%",
     "tables": 1, "note": ""},
    {"page": 3, "mode": "表格", "text": "营业总收入 | 1711.2 | 营业成本 | 1196.4", "tables": 1, "note": ""},
]


def test_only_the_pages_that_hit_get_fed_to_the_model():
    """**先定位再读。** 64 万字全喂进去，模型答出来的东西你根本没法核对；
    喂十页，你能一页页翻回去 —— 而这一页的全部价值就在于能核对。"""
    got = doc.build_context(PAGES, "前五大客户占销售总额多少？")
    assert got["pages"] == [2], f"挑错页了：{got['pages']}"
    assert "第 2 页" in got["text"], "喂进去的内容要带页码，模型才写得出引用"


def test_nothing_found_says_so_instead_of_feeding_the_first_pages():
    """**一个都没命中时不许沉默地喂前几页。**

    那会答出一段跟问题无关、却长得很像回答的东西 —— 比说"没找到"糟得多，
    因为使用者没有任何线索知道它是编的。
    """
    got = doc.build_context(PAGES, "董事长的姓名")
    assert got["pages"] == [] and got["text"] == ""
    assert "没找到" in got["note"]


def test_a_word_that_appears_forty_times_in_a_table_does_not_win():
    """一页里「营业」出现四十次（表格里每行都有）不代表它回答了这个问题 ——
    **命中的不同关键词数**比总次数更能说明相关。"""
    noisy = {"page": 9, "mode": "表格", "text": "营业" * 40, "tables": 1, "note": ""}
    ranked = doc.rank_pages([*PAGES, noisy], "营业成本是多少")
    assert ranked[0]["page"] == 3, f"被词频刷上来了：{[p['page'] for p in ranked]}"


def test_pages_left_out_are_counted_not_hidden():
    """砍掉的要报数 —— 少喂几页跟"这份文件里没有"长得一模一样。"""
    many = [{"page": i, "mode": "表格", "text": f"营业成本 第 {i} 页", "tables": 1, "note": ""}
            for i in range(1, 26)]
    got = doc.build_context(many, "营业成本")
    assert len(got["pages"]) == doc.MAX_CONTEXT_PAGES
    assert "另有 15 页也命中了" in got["note"], got["note"]


def test_a_word_on_every_page_carries_no_information():
    """**「公司」在年报的每一页上都有。**

    不挡的话，「公司的比特币持仓」会命中十页 —— 而这份年报里一个字都没提比特币。
    那比答错更糟：使用者拿到一段跟问题无关、却引着真页码的回答，
    **没有任何线索知道它是编的**。
    """
    every = [{"page": i, "mode": "版面", "text": f"公司在第 {i} 页的一些内容", "tables": 0, "note": ""}
             for i in range(1, 11)]
    assert doc.build_context(every, "公司的比特币持仓")["pages"] == []
    # 而真的在里面的词照样找得到
    every[4]["text"] += " 比特币持仓 1200 枚"
    assert doc.build_context(every, "公司的比特币持仓")["pages"] == [5]


def test_a_vague_question_fails_towards_not_found():
    """**往"没找到"这边失败。**

    「公司情况如何」里的词在每一页上都有，等于没有信息量。说"没找到"会让人
    换个问法（便宜）；返回十页会让人拿到一段引着真页码、却跟问题无关的回答
    （贵得多，而且他没有线索知道它是编的）。所以提示里要教他怎么改。
    """
    every = [{"page": i, "mode": "版面", "text": "公司的经营情况", "tables": 0, "note": ""}
             for i in range(1, 6)]
    got = doc.build_context(every, "公司情况")
    assert got["pages"] == []
    assert "更具体的问法" in got["note"], got["note"]


def test_a_weak_hit_says_so_instead_of_looking_confident():
    """茅台半年报里根本没有「前五名客户」（那是年报才有的），而问它照样返回十页 ——
    「前五」「客户」「销售」各自在别处出现过。**检索挑的是候选，不是答案**，
    所以强度要如实报出来。"""
    pages = [{"page": 1, "mode": "版面", "text": "销售费用明细", "tables": 0, "note": ""},
             {"page": 2, "mode": "版面", "text": "其他内容", "tables": 0, "note": ""}]
    got = doc.build_context(pages, "前五名客户占销售总额多少")
    assert got["pages"], "至少要给出候选"
    assert "命中不强" in got["note"] and "可能根本没有" in got["note"], got["note"]


def test_the_prompt_forbids_quietly_computed_numbers():
    """**自己算出来的数必须标成推算，并写出算式。**

    实测茅台那份结果里有一句「毛利率约为 89.55%」—— 年报上根本没有这个数，
    是它拿营业收入减营业成本算的。读的人会拿去核年报，**核不到之后整份结果都不敢信了**。
    这一页的全部价值就是能核对，一个核不到的数比没有这个数糟得多。
    """
    assert "推算：算式" in doc.DIGEST_SYSTEM_PROMPT
    assert "核不到" in doc.DIGEST_SYSTEM_PROMPT


def test_the_prompt_pins_which_column_is_the_current_period():
    """**一行里两列数，左边是本期右边是上期。**

    读反了每一条结论都是反的（"增长 20%" 变成 "下降 17%"），而它看起来完全正常 ——
    没有任何一层会响。实测这一份读对了（上年同期 910.94 亿跟库里对得上），
    但那是运气，不是保证，所以写进提示词钉住。
    """
    assert "左边那列是本期、右边是上期" in doc.DIGEST_SYSTEM_PROMPT
    assert "读反了每一条结论都是反的" in doc.DIGEST_SYSTEM_PROMPT


def test_the_prompt_sends_grouped_numbers_to_a_table():
    """**成组的数字必须排成表，不许写成箭头串。**

    实测那份研报的结果里有一句：「营收（百万元）：2023A 709 → 2024E 1536 →
    2025E 2674 → 2026E 3342」。每个数都对、每个数都有页码，**但谁都对不齐** ——
    也就看不出增速是在哪一年掉下来的（116% → 74% → 25%），而那正是这一条要回答的事。

    使用者的原话：「你能不能做点 markdown 表格呢，要不然直接把文档表格直接复制过去」。
    他说的是同一件事：**一份研报里最值钱的部分本来就是表格，把它拆成句子是在毁掉信息。**
    """
    assert '"tables"' in doc.DIGEST_SYSTEM_PROMPT, "样例里要有 tables 这个字段"
    assert '"columns"' in doc.DIGEST_SYSTEM_PROMPT and '"rows"' in doc.DIGEST_SYSTEM_PROMPT
    assert "成组的数进" in doc.DIGEST_SYSTEM_PROMPT
    # 什么算成组要写清楚，不然模型只会在"明显是表"的时候用它
    assert "多个年份" in doc.DIGEST_SYSTEM_PROMPT and "多个分部" in doc.DIGEST_SYSTEM_PROMPT
    assert "箭头串" in doc.DIGEST_SYSTEM_PROMPT, "把反例写出来，比只说规矩管用"
    # 单位带在每一格里，那一列数字就对不齐了 —— 而对齐正是这张表存在的理由
    assert "不要每个格子都带单位" in doc.DIGEST_SYSTEM_PROMPT


def test_the_prompt_forces_figures_out_of_the_sentences():
    """**数字塞进句子里就又是一堵墙。**

    使用者说过不止一次：「我受够了一堆文字」「没有组织、没有层级」。
    上一版让模型写 markdown 段落，页面用 pre-wrap 排出来 —— 那就是一堵新的墙。
    现在结论限死一句话，数字**一个都不许留在句子里**：孤立的进 `figures`、
    成组的进 `tables`（见上一条测试），页面才排得出层级。
    """
    assert "`verdict` **是一句话**" in doc.DIGEST_SYSTEM_PROMPT
    assert "数字一个都不许留在句子里" in doc.DIGEST_SYSTEM_PROMPT
    # 实测线上那份研报出来的两种垃圾格：
    # 「风险条数 = 3 条」占一整格（那三条就写在结论里），
    # 以及 note 里塞一句「原文表述："2024—2026 年营业收入为 15.36/26.74/33.42 亿元"」
    # —— 后者那串数正是该进 tables 的东西，塞进 note 里只有一列宽度，折成五行小字。
    assert "这种计数不是数字" in doc.DIGEST_SYSTEM_PROMPT
    assert "不要把原文整句抄进来" in doc.DIGEST_SYSTEM_PROMPT
    assert "又变成一堵墙" in doc.DIGEST_SYSTEM_PROMPT
