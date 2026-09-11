"""标题从第一页读出来，不用文件名。

## 使用者报的

贴链接读进来的文件在列表里叫 `H3_AP202405221634315503_1.pdf` ——
**对读的人零信息量**，两份研报并排放着分不出哪份是哪份。而文件自己第一页上
就印着标题。

## 下面这四段是线上四份文件的第一页原文，一字未改

它们的排版**互不相同**，这就是为什么这件事需要一点逻辑而不是"取第一行"：

  年报   第 0 行就是完整标题，后面还会居中重排一遍
  公告   第 0 行是「证券代码：… 公告编号：…」，标题拆成三行排版
  研报   第 0 行是免责声明套话，第 5 行才是标题，第 6 行是副标题

拿掉套话和元数据行之后取第一行，短了就往下接 —— 而判"接够了没有"要看**结尾**：
第一版按长度（24 字）截，公告那份正好断在「…募集资金存放、管理与实际」，
后面还有「使用情况的专项报告」。中国披露文件的标题几乎总以「报告/公告/说明/
意见/议案」这类文书名收尾，按这个判就对了。
"""

from __future__ import annotations

from stock_decision import documents as doc

FILENAME = "H3_AP202405221634315503_1.pdf"

ANNUAL_MOUTAI = """贵州茅台酒股份有限公司2026年半年度报告


公司代码：600519                     公司简称：贵州茅台




          贵州茅台酒股份有限公司
             2026  年半年度报告
"""

ANNUAL_CAMBRICON = """中科寒武纪科技股份有限公司2026年半年度报告


公司代码：688256                         公司简称：寒武纪


        中科寒武纪科技股份有限公司
             2026 年半年度报告
"""

# 这一段是线上那份公告第一页的原文，**一直抄到正文里去**——
# 因为坑就在正文里：第 17 行之后有「〔2023〕424号」和到账日期，
# 而它们看起来跟文档日期一模一样。
ANNOUNCEMENT = """证券代码：688256      证券简称：寒武纪         公告编号：2026-027


          中科寒武纪科技股份有限公司
关于公司     2026年半年度募集资金存放、管理与实际
              使用情况的专项报告

  本公司董事会及全体董事保证本公告内容不存在任何虚假记载、误导性陈述
或者重大遗漏，并对其内容的真实性、准确性和完整性承担法律责任。




   一、募集资金基本情况

  （一）实际募集资金金额和资金到账时间
  1、2022年度向特定对象发行股票情况
  经上海证券交易所审核同意，并根据中国证券监督管理委员会出具的《关于
同意中科寒武纪科技股份有限公司向特定对象发行股票注册的批复》（证监许可
〔2023〕424号），中科寒武纪科技股份有限公司2022年度向特定对象发行A股
股票13,806,042股，募集资金已于2023年4月6日全部到账。
"""

RESEARCH = """本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明 证券研究报告 1




寒武纪-U（688256.SH）首次覆盖报告
预期差较大的国产 AI 芯片引领者
 2024 年 05 月 22 日

➢ 中国 AI 芯片龙头，智能算力行业领导者。寒武纪能提供云边端一体、软硬
"""


def _pages(text: str) -> list[dict[str, object]]:
    return [{"page": 1, "mode": "版面", "text": text, "tables": 0, "note": ""}]


def test_the_title_comes_from_the_first_page_not_the_filename():
    assert doc.guess_title(_pages(ANNUAL_MOUTAI), FILENAME) == \
        "贵州茅台酒股份有限公司2026年半年度报告"
    assert doc.guess_title(_pages(ANNUAL_CAMBRICON), FILENAME) == \
        "中科寒武纪科技股份有限公司2026年半年度报告"
    # 研报：第 0 行是套话，要跳过；副标题和日期不要接进来
    assert doc.guess_title(_pages(RESEARCH), FILENAME) == "寒武纪-U（688256.SH）首次覆盖报告"


def test_a_split_announcement_title_is_joined_to_the_end():
    """**这一条是那个 bug 本身。**

    公告的标题是拆开排版的三行。按长度截会断在「与实际」——
    而「…管理与实际」和「…管理与实际使用情况的专项报告」看起来都像个标题，
    没有任何地方会响。
    """
    got = doc.guess_title(_pages(ANNOUNCEMENT), FILENAME)
    assert got == "中科寒武纪科技股份有限公司关于公司2026年半年度募集资金存放、管理与实际使用情况的专项报告"
    assert got.endswith("专项报告"), "标题断在了半句上"
    assert "本公司董事会" not in got, "接过头了，把正文接进来了"
    assert "公告编号" not in got, "元数据行不是标题"


def test_it_falls_back_to_the_filename_when_there_is_nothing_to_read():
    assert doc.guess_title([], FILENAME) == FILENAME
    assert doc.guess_title(_pages(""), FILENAME) == FILENAME
    # 整页都是套话时也退回文件名，不硬取一行
    assert doc.guess_title(_pages("请务必阅读最后一页免责声明\n证券研究报告 1"), FILENAME) == FILENAME


def test_the_tags_say_what_kind_who_and_which_period():
    """标签是**类型 · 是谁 · 哪一期** —— 用来一眼分辨两份文件。

    刻意不放页数字数（facts 那行已经有），更不放解析器的内部计数
    （「双栏 4」「表格 11」那种上一版撤掉过：读的人拿它做不了任何判断）。
    """
    tags = doc.guess_tags(_pages(ANNUAL_MOUTAI), "年报")
    assert tags == ["年报", "600519 贵州茅台", "2026 半年报"], tags

    # **公告用编号，不去正文里捞日期。** 实测那份被打上了 `2023-04-06` ——
    # 那是募集资金到账的日子，不是这份公告的日期。一个看起来完全正常的错标签。
    tags = doc.guess_tags(_pages(ANNOUNCEMENT), "公告")
    assert tags == ["公告", "688256 寒武纪", "公告 2026-027"], tags
    assert not any("2023" in tag for tag in tags), "把正文里的到账日当成文档日期了"

    # 研报没有报告期，有出版日期；第一页上没有简称，就只给代码
    tags = doc.guess_tags(_pages(RESEARCH), "研报")
    assert tags == ["研报", "688256", "2024-05-22"], tags


def test_a_tag_is_omitted_rather_than_guessed():
    """**抽不到就不给。** 猜错一个标签会让人打开错的那份文件。"""
    assert doc.guess_tags([], "年报") == []
    # 只认出类型，其余一个都抽不到
    assert doc.guess_tags(_pages("某份没有代码没有日期的文件"), "文件") == ["文件"]
    # 不许把页码、金额之类的数字误当成股票代码
    tags = doc.guess_tags(_pages("第 123456 行 合计 987654 元"), "")
    assert tags == [], tags


def test_retitle_keeps_a_hand_written_title_and_only_fills_the_tags():
    """**人自己起的标题不动，只补标签。**

    线上那四份的标题是手工给的 ——「民生证券：寒武纪-U 首次覆盖报告」带了
    第一页上根本没有的券商名。按第一页重认会把那个信息抹掉，
    而它们缺的只是标签。

    这一条守的是 `post_document_retitle` 里那个判断，用 AST 查：
    只有标题以 .pdf 结尾（或者空）时才允许替换。
    """
    import ast
    import pathlib

    main = (pathlib.Path(__file__).resolve().parents[1] / "stock_decision" / "main.py")
    tree = ast.parse(main.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "post_document_retitle")
    body = ast.unparse(fn)
    assert "endswith('.pdf')" in body or 'endswith(".pdf")' in body, (
        '重认标题不再看「标题是不是文件名」了 —— 那会把手工起的标题抹掉')
    assert "guess_tags" in body, "标签总是要补的"


# 一份**标题底下没印日期**的研报，而正文表格里有日期。
# 现实里很常见（很多券商把日期放在页脚或封面图上）。
RESEARCH_NO_DATE = """本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明 证券研究报告 1

某某科技（300xxx.SZ）深度报告
成长逻辑与产能节奏

➢ 核心观点：公司主营业务稳健。
财务数据摘要（截至 2023 年 12 月 31 日）：
营业收入 12.34 亿元，同比增长 20%。
"""


def test_the_date_tag_only_comes_from_the_title_block():
    """**日期只在标题块里找，不去正文里捞。**

    正文里的日期看起来跟文档日期一模一样：批复文号的年份、募集资金到账日、
    财务数据的截止日。给一份 2024 年的研报打上 `2023-12-31`，
    列表上完全正常，而它是错的。

    这一条是补的：公告那份改成"有编号就用编号"之后，
    `_head_block` 就没有任何用例在管了 —— 把它换回全文搜索照样绿。
    """
    tags = doc.guess_tags(_pages(RESEARCH_NO_DATE), "研报")
    assert not any("2023" in tag for tag in tags), \
        f"把正文里的财报截止日当成了文档日期：{tags}"
    # 顺带确认它没因为找不到日期就乱给别的：只剩类型这一个标签
    assert tags == ["研报"], tags


# 线上使用者自己读的那份（2026-08-18），第一页原文。
# **它跟寒武纪那份的编号写法完全不同** —— 这就是为什么要拿两家的真文件来测：
#   寒武纪   `公告编号：2026-027`
#   贵州茅台 `编号：临  2026－031`  ← 只写「编号」、值以「临」打头、全角破折号、内部有空格
ANNOUNCEMENT_MOUTAI = """证券简称：贵州茅台        证券代码：600519      编号：临  2026－031

             贵州茅台酒股份有限公司
      关于召开    2026年半年度业绩说明会的公告

  本公司董事会及全体董事保证本公告内容不存在任何虚假记载、误导性陈述或者重
大遗漏，并对其内容的真实性、准确性和完整性承担法律责任。

  重要内容提示：
  ●会议召开时间：2026   年8 月21日（星期五）15:00－16:00
"""


def test_a_second_companys_announcement_number_is_written_differently():
    """**两家公司的编号写法不一样，两种都要认。**

    这一条是评审时从线上真数据里查出来的：使用者自己读的那份茅台公告只拿到两个
    标签，少了编号 —— 因为正则要求字面「公告编号」，而茅台写的是「编号：临 2026－031」
    （少了「公告」两个字、值以汉字打头、破折号是全角、中间还有排版空格）。

    少一个标签不是错（抽不到就不给），但**照着一家公司的格式写正则**是错的。
    """
    pages = _pages(ANNOUNCEMENT_MOUTAI)
    title = doc.guess_title(pages, FILENAME)
    assert title == "贵州茅台酒股份有限公司关于召开2026年半年度业绩说明会的公告", title
    tags = doc.guess_tags(pages, doc.detect_kind(title, pages))
    assert tags == ["公告", "600519 贵州茅台", "公告 临2026-031"], tags
    # 全角破折号和排版空格要归一 —— 不然同一家两份公告的标签长得不一样
    assert "－" not in tags[2] and " " not in tags[2].removeprefix("公告 ")


def test_the_announcement_number_is_not_picked_up_from_the_body():
    """编号跟日期一样只在标题块里找。正文里引用别家公告的编号看起来一模一样。"""
    body_ref = """证券代码：688256      证券简称：寒武纪

          某某公司关于回购股份的公告

   一、回购方案
   详见公司于 2025 年披露的《回购报告书》（编号：2025-088）。
"""
    tags = doc.guess_tags(_pages(body_ref), "公告")
    assert not any("2025-088" in tag for tag in tags), f"把正文里引用的别家编号当成本文编号了：{tags}"
