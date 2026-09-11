"""从券商交割单/交易记录截图里读出交易流水。

**为什么值得做。** 手工录入是这个账本最大的摩擦：一年几十笔交易，加上分红、送转，
录到一半就不录了——而一个不完整的账本比没有账本更糟，因为它看起来是完整的，
所有基于它的复盘结论都会跟着错。

**为什么读完不直接写进去。** 模型认错一个数字，账本就永久错一笔，而错误会一路
传染到成本价、收益率、季度归因。所以这里只负责「读」，每一条都回到页面上等你确认；
读不准的地方明说读不准，而不是猜一个填上。这与本仓其他 AI 功能是同一条边界：
**模型负责把资料整理成可核对的形式，判断与落库永远是人的动作。**

## 长截图为什么一定要切开——这是这个功能此前不能用的全部原因

手机券商 App 的「交易记录」是一条长列表，滚动截图出来动辄一两万像素高。
实测一张 **1256 × 20748** 的格力交易明细：视觉接口会把长边压到 1568 像素以内，
于是它被缩成 **95 × 1568**——**宽度只剩 95 个像素**，每一行数字都糊成一道横杠。

要命的是它**不报错**：模型收到一张糊图，照样一本正经地返回 JSON，
只是里面的数字全是编的，或者干脆返回空列表。从外面看就是"识别失败"，
而真正的原因在图还没进模型之前就已经发生了。

所以这里先在本地切片，每片单独送。宽度只收到刚好还认得清数字的程度
（决定"认不认得出"），高度按接口上限装满（决定"要调几次"）——
此前把这两件事绑在一起，白白多花了三倍的调用。

## 模型会漏读，而且不报错

切片解决了清晰度，但没解决第二个问题：**同一片图连读两次，结果不一样**。
实测有一次少给了两笔卖出，从外面完全看不出来。账本少一笔交易，
成本价就永久错，而且再也查不回来。

所以重叠不是"够防切断就行"，而是**大到让每一行都完整落在两片里**。
两边取并集：一片漏了另一片还在。顺带多出一个东西——
只被读到一次的行可以标出来，让你知道哪几条没被印证过。

## 切开之后要在代码里补回来的事

1. **股票代码只在页头出现一次。** 个股交易记录页每一行都没有代码，
   第二片往后的模型根本不知道这是哪只票。页头从第一片提，
   再兜底用你在页面上选的那只票。
2. **日期是分组标题，一个日期都不许猜。** 见 `_merge` 里的长篇说明——
   第一版让缺日期的行继承上一行，结果造出了价量完全正确、日期却是错的
   假流水。漏一笔核对时能发现，**多一笔你会当成真的**。
3. **对账。** 页头那个「交易税费」合计是这张图上唯一的校验和，
   跟逐行费用一加对得上对不上，比任何主观感觉都硬。

## 隐私

截图里有账号、姓名、总资产。这些一律不入库、不进提示词之外的任何地方；
提示词里也明确要求模型不要复述它们。图片本身处理完即丢，不落盘。
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from . import llm
from .jsonio import Truncated, loads_or_reformat

# 重排时告诉模型该长成什么样。**跟主提示词末尾那个示例同形**——
# 两处写岔的话，重排会照着另一个形状改，改出来是合法 JSON、字段却对不上，
# 然后 _merge 静静地读出零行流水。
REFORMAT_SHAPE = (
    '{"page_symbol": "000651", "page_company": "格力电器", "page_fee_total": 1055.09, '
    '"trades": [{"side": "buy", "trade_date": "2026-03-14", "symbol": "600519", '
    '"company_name": "贵州茅台", "shares": 100, "price": 1680.5, "fee": 5.2, '
    '"cash_amount": null, "note": ""}], "warnings": ["…"]}')

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# **真正说了算的是这一组，不是上面那个。**
#
# 上面的 media_type 来自 `file.content_type` —— 那是**浏览器（或攻击者）自己填的**，
# 拦不住任何东西：声明 image/png、实际塞一个 TIFF / DDS / ICNS 进来，
# 上面那道闸门照样放行，然后 Pillow 会兴高采烈地去解码它。
# 而 Pillow 历年的高危漏洞几乎全在这些冷门解码器里。
#
# 所以真正的判据是**打开之后 Pillow 自己认出来的格式**，
# 白名单之外的一律拒绝——哪怕它能解开。
DECODABLE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "MPO"}     # MPO：部分手机拍的 JPEG

# 像素总量上限。**文件大小拦不住解压炸弹**：几十 KB 的 PNG 可以解开成
# 五万乘五万，一张就能把内存吃光，而它完全符合上面 12 MB 的限制。
# Pillow 自带的 MAX_IMAGE_PIXELS 只发一条 warning，默认不拦。
#
# 一亿像素约等于一张 6000 × 16000 的超长截图——比实测那张（2600 万）还宽裕一倍多。
MAX_IMAGE_PIXELS = 100_000_000

# 视觉接口对单张图的限制：长边不超过 1568 像素，总面积约 1.15 兆像素。
# 超了它**不报错，自己缩**——而缩完的长截图宽度只剩几十像素。
MAX_EDGE = 1568
MAX_PIXELS = 1_150_000

# 切片前先把宽度收到这个数。**手机截图的字大得离谱**：实测格力那张原图
# 单个汉字有 60 像素高，而认字用不了这么多——留到 30 像素照样一清二楚。
# 不收宽度的话每片只能装 915 像素高，两万像素的图要切二十八片、调二十八次模型；
# 收到 640 之后每片能装 1568 像素，同一张图九片就够了。
#
# **这不是在省清晰度，是在省重复。** 宽度决定每个数字有多少像素（认得出认不出），
# 高度决定一片装几行（要调几次）——两者是分开的，此前把它们绑在一起白花了三倍的钱。
TARGET_WIDTH = 640

# 低于这个宽度的原图，字本身就已经太小了，切不切都读不出来。
MIN_SOURCE_WIDTH = 480

# 一行流水在缩到 640 宽之后大概 60–260 像素高（带「派息…」说明的分红行最高）。
ROW_MAX_HEIGHT = 260

# **重叠要大到让每一行都完整地落在两片里。**
#
# 这不是为了防切断——防切断只要一行的高度就够。这是为了防**模型漏读**：
# 实测同一片图连读两次，一次给 6 行、一次给 4 行，中间两笔卖出凭空消失，
# 而外面完全看不出来。账本少一笔交易，成本价就永久错，且再也查不回来。
#
# 每行被两片各读一次之后，两边取并集——一片漏了另一片还在。
# 顺带还多出一个东西：**只被读到一次的行可以标出来**，
# 让你知道哪几条没有互相印证过，该重点核。
# 代价是片数翻倍（这张图 9 片变 17 片）。一笔漏掉的交易比这贵得多。
def _stride_for(tile_height: int) -> int:
    return max(1, (tile_height - ROW_MAX_HEIGHT) // 2)

# 切出来的片数上限。**这是花钱的闸门**，每片一次调用。
# 按 640 宽、双重覆盖算，32 片能装下约 42000 像素高的原图——一整年的记录都够。
MAX_SLICES = 32

# 同时并发几片。串行读二十片要好几分钟，而这是个前台等着的动作。
SLICE_CONCURRENCY = 4

SCAN_SYSTEM_PROMPT = """你在读一张券商的交割单/对账单/个股交易记录截图，把上面的每一行流水转成结构化数据。

你只做一件事：**如实转录**。不要计算，不要推断，不要补全看不清的数字。

## 这张图可能是从一张长截图上切下来的一段

所以：
- 上下边缘可能有被切掉一半的行。**半行不要猜，写进 warnings，不要转录**。
- 股票名称与代码可能只在整张长图的最上面出现过一次，这一段里看不到。
  看不到就把 page_symbol / page_company 留空，**不要从别处猜一个填上**。
- 日期通常是分组标题（一个日期下面挂着若干行）。如果某一行所属的分组标题
  不在这一段里（被切在上一段了），把它的 trade_date 留空，
  并在这一行的 note 里写「日期在上一段」。**留空是对的，猜一个日期是错的。**

## 转录规则

1. **只转录截图上真实存在的行**。看不清、被遮挡的行，不要猜，写进 warnings。
2. 数字原样抄。不要做单位换算，不要四舍五入，不要把「1,234.56」写成 1234.6。
3. 分不清是买入还是卖出时，不要二选一，把那一行写进 warnings。
4. side 只能用这五个：
   - buy：买入 / 证券买入 / 担保品买入 / 融资买入 / 「买」
   - sell：卖出 / 证券卖出 / 担保品卖出 / 融券卖出 / 「卖」
   - dividend：红利入账 / 股息入账 / 现金分红 / 「分红」
   - bonus：红股入账 / 送股 / 转增股本
   - rights：配股缴款
5. **这些不是持仓变动，一律不要转录**（它们经常和流水混排在同一张表里）：
   银证转账、资金存取、利息归本、融资利息、融券费用、**股息红利税补缴**、
   手续费返还、新股申购冻结/解冻、撤单、委托未成交。
6. 一行里通常是「价格 / 金额」一行、「数量 / 费用（或税费）」一行。
   - price 填**价格**（单价），shares 填**数量**，fee 填**费用**或**税费**。
   - 「金额」是成交总额，**不要填进 price，也不要填进 cash_amount**；
     要记的话写进 note。**cash_amount 只有分红行才填**，买入卖出行一律 null。
   - 只有金额和数量、没有单价时，price 留空，**不要自己除**。
7. **数量可能带负号**（卖出记 −500）。shares 一律填**正数**，
   买还是卖由 side 决定。带负号照抄会让账本上多出一笔负持仓。
8. 类型标题右边那个红色或绿色的大数字是**这一笔的盈亏**，不是成交金额，
   也不是价格。**一个字都不要转录它。**
9. 分红行（「分红」「红利入账」）：
   - cash_amount 填**金额**那一栏（税后实际到账）。
   - 这一行上的「价格」是除息基准价、「数量」通常是 0，**两个都不要填**。
   - 行下面那句「派息 XXXX 元。日期股价由 A 变为 B」是说明，不用转录。
   送股填 shares，不填 price。
10. **不要复述账号、姓名、身份证号、总资产、可用余额、浮动盈亏、当日盈亏、
    实现盈亏、持股天数、个股仓位。** 这些即使在截图上也不要写进输出。
11. 日期用 YYYY-MM-DD。截图上只有月日没有年份的，日期留空，note 里说明。
12. 页头如果有**「交易税费」合计**这一项（一个总数，不是某一行的费用），
    把它填进 page_fee_total。看不到就留空。这一项是用来跟逐行费用对账的，
    所以它是唯一一个要抄下来的汇总数字。

只输出一个 JSON 对象：
{"page_symbol": "000651", "page_company": "格力电器", "page_fee_total": 1055.09,
 "trades": [{"side": "buy", "trade_date": "2026-03-14", "symbol": "600519", "company_name": "贵州茅台",
             "shares": 100, "price": 1680.5, "fee": 5.2, "cash_amount": null, "note": ""}],
 "warnings": ["看不清或拿不准的地方，逐条说明"]}"""


# ------------------------------------------------------------------ 切片

def _slice(image_bytes: bytes) -> tuple[list[bytes], dict[str, Any]]:
    """把长截图切成若干片，每片都在视觉接口的限制以内。

    返回 (每片的 PNG 字节, 这次切片的说明)。图本来就在限制以内的，原样返回一片。
    """
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as source:
        # **格式与尺寸都要在解码之前查。** Image.open 只读文件头、不解像素，
        # 所以这两道闸门放在 convert() 前面才有意义——放后面就是先炸再拦。
        if (source.format or "").upper() not in DECODABLE_FORMATS:
            raise RuntimeError(
                f"这张图实际是 {source.format or '未知'} 格式，不是 PNG / JPEG / WebP。"
                "请另存成常见格式再传。")
        pixels = source.size[0] * source.size[1]
        if pixels > MAX_IMAGE_PIXELS:
            raise RuntimeError(
                f"图片有 {pixels / 1e6:.0f} 兆像素（{source.size[0]}×{source.size[1]}），"
                f"超过 {MAX_IMAGE_PIXELS / 1e6:.0f} 兆的上限。请分几段截。")
        image = source.convert("RGB")
        source_width, source_height = image.size
        width, height = source_width, source_height

        if max(width, height) <= MAX_EDGE and width * height <= MAX_PIXELS:
            return [image_bytes], {"sliced": False, "width": width, "height": height,
                                   "source_width": width, "source_height": height,
                                   "slices": 1, "scale": 1.0}

        # 先收宽度（决定认不认得出字），再按高度切（决定要调几次模型）。
        scale = min(1.0, TARGET_WIDTH / width)
        scaled_width = max(1, round(width * scale))
        # 单片高度：在宽度确定之后，同时满足长边与面积两条限制的最大值。
        tile_height = int(min(MAX_EDGE, MAX_PIXELS / scaled_width))
        if scale < 1.0:
            image = image.resize((scaled_width, max(1, round(height * scale))), Image.LANCZOS)
            width, height = image.size

        stride = _stride_for(tile_height)
        overlap = tile_height - stride
        # 最后一片要能盖住图的底部：range 的终点用 height 而不是 height-overlap，
        # 否则最后不到一个 stride 的那一段没有任何一片盖到——**而它就是最后几笔交易**。
        offsets = [top for top in range(0, height, stride) if top == 0 or top < height]
        while len(offsets) > 1 and offsets[-2] + tile_height >= height:
            offsets.pop()      # 倒数第二片已经盖到底了，最后一片纯属重复
        truncated = False
        if len(offsets) > MAX_SLICES:
            offsets = offsets[:MAX_SLICES]
            truncated = True

        tiles: list[bytes] = []
        for top in offsets:
            box = (0, top, width, min(height, top + tile_height))
            buffer = io.BytesIO()
            # PNG 无损：JPEG 二次压缩会在细小数字上留下振铃，而这里读的全是数字。
            image.crop(box).save(buffer, format="PNG", optimize=True)
            tiles.append(buffer.getvalue())

    return tiles, {
        "sliced": True, "width": width, "height": height,
        "source_width": source_width, "source_height": source_height,
        "slices": len(tiles), "tile_height": tile_height, "overlap": overlap,
        "scale": round(scale, 4), "truncated": truncated,
    }


def estimate_credits(image_bytes: bytes) -> dict[str, Any]:
    """这张图点下去要花多少。**在真正调模型之前算，切片是本地做的，不花钱。**

    实测那张 1256×20748 的长截图会切成 15 段、发 15 次请求，
    而界面上在点之前没有任何地方提过这件事。对按 token 计费的产品，
    "点了才知道多少钱"的结果不是省着用，是不敢用。
    """
    from . import llm

    try:
        tiles, geometry = _slice(image_bytes)
    except Exception:
        # 估不出来就说估不出来，别编一个数——真读的时候会再报一次真正的错。
        return {"slices": None, "credits": None, "note": "这张图读不出尺寸，估不了价。"}
    tokens = sum(4000 + len(tile) // 750 for tile in tiles)
    return {
        "slices": len(tiles),
        "credits": llm.credits_for(tokens),
        "width": geometry.get("source_width"),
        "height": geometry.get("source_height"),
        "note": (f"这是一张 {geometry.get('source_width')}×{geometry.get('source_height')} 的长截图，"
                 f"会切成 {len(tiles)} 段分别读" if geometry.get("sliced")
                 else "这张图不用切，一次读完"),
    }


# ------------------------------------------------------------------ 调模型

def _call_vision(image_bytes: bytes, media_type: str, hint: str, timeout: int) -> llm.Completion:
    """带图调一次模型。走与文本相同的计费闸口。

    图片 token 是文本的几十倍，所以估算按图片大小折算——冻结额宁可估高，
    结算永远按真实 usage，估高只影响可用余额、不会多收。
    """
    config = llm.load_env()
    if not config["MINIMAX_API_KEY"] or not config["MINIMAX_BASE_URL"]:
        raise RuntimeError("模型未配置：缺少 MINIMAX_API_KEY / MINIMAX_BASE_URL")

    module = config["XM_CREDIT_MODULE"] or "stocks"
    estimated = 4000 + len(image_bytes) // 750
    meter = llm.reserve(module, "ledger-scan", estimated)

    content: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.b64encode(image_bytes).decode("ascii")}},
        {"type": "text", "text": hint or "把这张截图上的流水逐行转录出来。"},
    ]
    body = json.dumps({
        "model": config["MINIMAX_MODEL"] or "MiniMax-M3",
        # 一片里最多十来行，8000 足够。**此前 4000 会在长表上截断输出**，
        # 而截断的 JSON 解出来是半张表——看起来"读到了 12 条"，其实后面还有 30 条。
        "max_tokens": 8000,
        "system": SCAN_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config["MINIMAX_BASE_URL"].rstrip("/") + "/v1/messages",
        data=body,
        headers={"content-type": "application/json", "x-api-key": config["MINIMAX_API_KEY"],
                 "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        meter.release()
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        if exc.code == 400 and ("image" in detail.lower() or "vision" in detail.lower()):
            raise RuntimeError(
                f"当前模型（{config['MINIMAX_MODEL'] or 'MiniMax-M3'}）似乎不接受图片输入。"
                f"换一个支持视觉的模型再试。原始返回：{detail}") from exc
        raise RuntimeError(f"模型请求失败（HTTP {exc.code}）：{detail}") from exc
    except BaseException as exc:
        meter.release()
        raise RuntimeError(f"模型请求失败：{exc}") from exc

    text = "".join(block.get("text", "") for block in payload.get("content", [])
                   if block.get("type", "text") == "text").strip()
    usage = payload.get("usage") or {}
    completion = llm.Completion(
        text=text,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        meter=meter,
    )
    meter.commit(completion.tokens)
    llm._record(meter, completion.tokens)
    return completion


_SYMBOL = re.compile(r"\d{6}")


def _match_company(entry: dict[str, Any], roster: list[dict[str, Any]]) -> tuple[int | None, str]:
    """把读出来的一行对到本地档案的公司上。

    先代码后名称：代码是唯一的，名称会有「贵州茅台」/「茅台」这类写法差异。
    对不上就返回 None —— 猜一个最像的会把流水记到别的公司头上，
    那种错误在页面上完全看不出来。
    """
    symbol = str(entry.get("symbol") or "").strip()
    match = _SYMBOL.search(symbol)
    if match:
        code = match.group(0)
        for company in roster:
            if company["symbol"] == code:
                return company["id"], f"代码 {code}"
    name = str(entry.get("company_name") or "").strip()
    if name:
        for company in roster:
            if company["name"] == name:
                return company["id"], f"名称「{name}」完全一致"
    return None, ""


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


VALID_SIDES = {"buy", "sell", "dividend", "bonus", "rights"}


def _dedupe_key(entry: dict[str, Any]) -> tuple:
    """重叠区里同一行会被两片各读一次。按内容去重，**代码做，不问模型**。

    问模型"这两行是不是同一笔"要它跨图记忆，而它不该被要求做这件事；
    而同一天同方向同价同量的两笔真实交易，本来在券商单上也是合并成一行的。
    """
    # 数字要先归一再比：两段里同一行可能一段读成 "47.640"、另一段读成 47.64，
    # 直接比字符串会当成两笔，账本上就凭空多一笔。
    return (str(entry.get("trade_date") or ""),) + _identity(entry)


def _identity(entry: dict[str, Any]) -> tuple:
    """一行流水**不看日期**的身份。用来把缺日期的那份认回它的正身。

    不含手续费：同一行在两段里可能一段读到了费、另一段被切掉了费，
    把费算进身份会让它们认不出彼此。
    """
    return (entry.get("side"),
            _as_float(entry.get("price")),
            abs(_as_float(entry.get("shares")) or 0.0),
            _as_float(entry.get("cash_amount")))


def _merge(pages: list[dict[str, Any]]) -> tuple[str, str, float | None, list[dict[str, Any]], list[str]]:
    """把各片的结果拼回一张表：补页头、去重、把没日期的那些认回它的正身。

    ## 为什么不给缺日期的行「继承上一行的日期」

    第一版就是这么干的，理由听起来很硬：列表是按日期排的，缺日期的行
    继承前一行就行。**但它造出了假流水。**

    两个原因：一是模型返回的行序并不稳定（实测同一张长图，有的段升序、
    有的段降序）；二是继承跨过了段边界，把上一段最后一行的日期按到了
    下一段第一行头上。结果是 `2024-10-17 卖出 47.99/1000` 这样一条——
    它其实是 10-22 那笔，价量费一模一样，只是日期被安错了。
    于是它跟真身对不上、去不掉重，**变成账本里凭空多出来的一笔**。

    漏一笔可以核对时发现；**多一笔会被你当成真的**，而且它的价量都对，
    你找不出破绽。所以这里一个日期都不猜。

    ## 换成什么

    切片是双重覆盖的：一行的分组标题就算在这一段里被切掉了，
    在相邻那一段里多半是完整的。所以同一行会有一个"有日期"的版本。
    把没日期的那份按（方向·价·量·现金）认回去，认不回来的**留着但标出来**，
    让你自己补日期——而不是替你填一个。
    """
    page_symbol = ""
    page_company = ""
    fee_total: float | None = None
    for page in pages:
        page_symbol = page_symbol or str(page.get("page_symbol") or "").strip()
        page_company = page_company or str(page.get("page_company") or "").strip()
        if fee_total is None:
            fee_total = _as_float(page.get("page_fee_total"))

    warnings: list[str] = []
    merged: list[dict[str, Any]] = []
    for index, page in enumerate(pages, 1):
        for raw in page.get("trades") or []:
            entry = dict(raw)
            # 价、量、现金三个数一个都没有的行，是被切在边缘只露出半截的。
            # 它承载不了任何信息，留着只会变成一笔空记录。
            if all(_as_float(entry.get(k)) in (None, 0) for k in ("price", "shares", "cash_amount")):
                continue
            merged.append(entry)
        for text in page.get("warnings") or []:
            warnings.append(f"第 {index} 段：{text}" if len(pages) > 1 else str(text))

    seen: set[tuple] = set()

    # 去重的同时数一数**每一行被几片读到**。切片是双重覆盖的，
    # 所以正常情况下每行应该出现两次；只出现一次的，说明有一片漏读了它——
    # 那一行没有被印证过，值得你重点核一眼。（最上面和最下面那几行例外：
    # 它们本来就只有一片盖得到。）
    unique = []
    index_of: dict[tuple, int] = {}
    # 有日期的先立起来，没日期的第二轮再去认正身——顺序反了就认不回去。
    for entry in sorted(merged, key=lambda e: not str(e.get("trade_date") or "").strip()):
        dated = bool(str(entry.get("trade_date") or "").strip())
        key = _dedupe_key(entry)
        if dated:
            if key in seen:
                unique[index_of[key]]["_seen_in"] += 1
                continue
            seen.add(key)
        else:
            # 没日期的：按（方向·价·量·现金）找有日期的那份。找到就并进去，
            # 它本来就是同一行，只是这一段没盖到它的分组标题。
            twin = next((row for row in unique if _identity(row) == _identity(entry)
                         and str(row.get("trade_date") or "").strip()), None)
            if twin is not None:
                twin["_seen_in"] += 1
                continue
        index_of[key] = len(unique)
        entry["_seen_in"] = 1
        unique.append(entry)
    return page_symbol, page_company, fee_total, unique, warnings


def scan_screenshot(image_bytes: bytes, media_type: str, roster: list[dict[str, Any]],
                    hint: str = "", timeout: int = 180,
                    company_id: int | None = None) -> dict[str, Any]:
    """读一张截图，返回待确认的流水。不写库。

    company_id 是你在页面上指定的「这张图是哪只票的」。
    **个股交易记录页上每一行都没有股票代码**，页头也常常只有名称没有代码
    （实测格力那张就是），所以指定一次比让模型猜二十次可靠得多。
    """

    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise RuntimeError(f"不支持这种图片格式（{media_type}）。请用 PNG、JPEG 或 WebP。")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise RuntimeError(f"图片太大（{len(image_bytes) // 1024 // 1024} MB）。"
                           f"请压到 {MAX_IMAGE_BYTES // 1024 // 1024} MB 以内，或分几张截。")

    try:
        tiles, geometry = _slice(image_bytes)
    except RuntimeError:
        # 切片自己抛的 RuntimeError 已经写清楚了是格式不对还是太大——
        # 再包一层「打不开或者格式不认识」只会把准确的话糊掉。
        raise
    except Exception as exc:
        raise RuntimeError(f"这张图打不开或者格式不认识：{exc}") from exc

    # 清晰度按**原图宽度**判断，不看文件大小。
    # 文件大小说明不了问题：一张三兆的长截图，每个字可能只有几个像素——
    # 此前那道「小于 40 KB 就拒绝」的闸门，正好放过了真正读不出来的那一类。
    if geometry["source_width"] < MIN_SOURCE_WIDTH:
        raise RuntimeError(
            f"截图只有 {geometry['source_width']} 像素宽，数字多半糊得读不出来。"
            "请在手机上放大到能看清每一位再截，或者用电脑网页版的交割单导出。")

    def read(tile: bytes) -> dict[str, Any]:
        # 切开之后每片都是 PNG（原图是 JPEG 也一样），媒体类型要跟着改，
        # 否则接口按 JPEG 解一段 PNG 字节，直接 400。
        text = _call_vision(
            tile, "image/png" if geometry["sliced"] else media_type, hint, timeout).text
        # **一片就是一次带图的真调用**（图片 token 是文本的几十倍，这是全站最贵的
        # 一次调用）。最后一段格式坏了就丢掉整片，等于把这一段的钱白花，
        # 而表现出来只是"这一段没有流水" —— 跟真的没有流水长得一模一样。
        payload, _ = loads_or_reformat(text, task="ledger-scan",
                                       shape=REFORMAT_SHAPE, timeout=timeout)
        return payload if isinstance(payload, dict) else {}

    def why(exc: Exception, index: int) -> str:
        """**没写完要单独说。** 它跟"读不出来"是两回事：

        没写完是这一段行数太多、输出被长度上限掐了，下一步是把这一段再截短一点
        重传；而"读不出来"多半是图糊。混成一句「没读成功」，
        使用者只会反复重传同一张图。
        """
        if isinstance(exc, Truncated):
            return (f"第 {index} 段行数太多，模型的输出被长度上限掐断了——"
                    f"这一段的流水**一条都没有**进下面的结果。"
                    f"把这一段单独截短一点再传一次。")
        return f"第 {index} 段没读成功（{exc}）——这一段的流水不在下面的结果里。"

    failures: list[str] = []
    if len(tiles) == 1:
        # **一片也要走同一条兜底。** 原来这条路是裸调用：一次坏 JSON 直接抛，
        # 而这次带图的调用已经付过钱了。
        try:
            pages = [read(tiles[0])]
        except Exception as exc:  # noqa: BLE001
            failures.append(why(exc, 1))
            pages = [{}]
    else:
        # 一片读失败不该让整张图白跑——把这一片记进 warnings，其余照常返回。
        def guarded(item: tuple[int, bytes]) -> dict[str, Any]:
            index, tile = item
            try:
                return read(tile)
            except Exception as exc:
                failures.append(why(exc, index))
                return {}

        # **上下文要显式带进线程，而且每个线程一份。**
        #
        # 计费主体和记账桶都在 contextvars 里，而 ThreadPoolExecutor **不会**
        # 复制调用方的 context —— 新线程拿到的是一份全新的。2026-08-16 实测：
        #
        #     主线程          记账桶在 True   计费主体在 True
        #     线程池里        记账桶在 False  计费主体在 False
        #
        # 后果不是"不计费"，是**记错人**：`llm.reserve` 取不到主体时会退回
        # `background_principal()`，也就是**站主**。于是别人跑一次多段读图，
        # 钱扣在站主账上；而 `_record` 同样取不到记账桶，任务行上的 credits
        # 停在 0 —— 他看到的是"这次没花钱"。
        #
        # 而**一份 Context 不能被多个线程同时进入**：复制一份共用会让除第一个
        # 线程外全部抛 "cannot enter context: ... is already entered"。
        # 所以每片各复制一份。（promises.py 里有同一段教训，那边先修的。）
        import contextvars

        contexts = [contextvars.copy_context() for _ in tiles]

        def in_context(item: tuple[int, bytes]) -> dict[str, Any]:
            return contexts[item[0] - 1].run(guarded, item)

        with ThreadPoolExecutor(max_workers=SLICE_CONCURRENCY) as pool:
            pages = list(pool.map(in_context, enumerate(tiles, 1)))

    page_symbol, page_company, fee_total, entries, warnings = _merge(pages)
    warnings.extend(failures)
    if geometry["sliced"]:
        warnings.insert(0, f"这是一张 {geometry['source_width']}×{geometry['source_height']} 的长截图"
                           f"（整张直接送模型会被压成 "
                           f"{round(geometry['source_width'] * MAX_EDGE / geometry['source_height'])} "
                           f"像素宽，字全糊掉），已切成 {geometry['slices']} 段分别读取。")
    if geometry.get("truncated"):
        warnings.insert(1, f"图太长，只读了最上面 {MAX_SLICES} 段。"
                           f"下半部分请另外截一张再传一次。")

    trades: list[dict[str, Any]] = []
    unmatched: list[str] = []
    forced = next((c for c in roster if c["id"] == company_id), None) if company_id else None
    if company_id and not forced:
        raise RuntimeError("指定的公司不在你的档案里。")

    for entry in entries:
        side = str(entry.get("side") or "").strip()
        if side not in VALID_SIDES:
            warnings.append(f"跳过一行：认不出的类型「{side}」（{entry.get('company_name') or entry.get('symbol')}）")
            continue
        # 个股交易记录页上每一行都没有代码，代码只在页头出现一次。
        # 不往下补的话，第二段往后的每一行都匹配不上公司——**这个功能就等于没有**。
        if not str(entry.get("symbol") or "").strip():
            entry["symbol"] = page_symbol
        if not str(entry.get("company_name") or "").strip():
            entry["company_name"] = page_company
        if forced:
            entry["symbol"], entry["company_name"] = forced["symbol"], forced["name"]
        matched_id, matched_by = _match_company(entry, roster)
        if forced:
            matched_id, matched_by = forced["id"], "你指定的公司"
        label = f"{entry.get('company_name') or ''}（{entry.get('symbol') or '无代码'}）".strip()
        if matched_id is None and label not in unmatched:
            unmatched.append(label)
        parsed_date = _as_date(entry.get("trade_date"))
        note = str(entry.get("note") or "")[:200]
        if parsed_date is None and entry.get("trade_date"):
            note = (note + " ｜ 日期读不出来，需要你补").strip(" ｜")
        # **数量取绝对值。** 卖出那几行的数量在券商 App 上带负号（−500），
        # 照抄进来账本就会多出一笔负持仓，而方向本来就由 side 表达了。
        shares = _as_float(entry.get("shares"))
        if shares is not None and shares < 0:
            shares = abs(shares)
            note = (note + " ｜ 原图上数量带负号，已取正").strip(" ｜")
        # **归一要做对称的两半，这里此前只做了一半。**
        #
        # 一、cash_amount 只有分红行有意义。模型很自然地会把买卖行的「成交金额」
        #    填进来（实测就是这样），而账本把这个字段当现金流入——
        #    一笔 22170 元的卖出会变成 22170 元的分红收入，收益率整个错掉。
        cash = _as_float(entry.get("cash_amount"))
        if side != "dividend" and cash is not None:
            note = (note + f" ｜ 成交金额 {cash:g}").strip(" ｜")
            cash = None
        # 二、**反过来也一样：分红行不该有股数与单价。**
        #    券商 App 的分红行「数量」栏印着一个 0、「价格」栏印着除息基准价，
        #    模型照抄下来（提示词说了不要填，但那两个数就摆在那儿）。
        #    而账本的 shares 是 gt=0 —— 一个 shares=0 的分红行会被校验直接打回，
        #    报「股数必须大于 0」。**漏的就是这一半**，症状是整批记不进去。
        price = _as_float(entry.get("price"))
        if side == "dividend":
            if shares is not None:
                note = (note + f" ｜ 原图数量栏 {shares:g}").strip(" ｜")
            if price is not None:
                note = (note + f" ｜ 原图价格栏 {price:g}（除息基准价）").strip(" ｜")
            shares, price = None, None
        trades.append({
            "side": side,
            "trade_date": parsed_date,
            "symbol": str(entry.get("symbol") or "")[:16],
            "company_name": str(entry.get("company_name") or "")[:60],
            "shares": shares,
            "price": price,
            "fee": _as_float(entry.get("fee")),
            "cash_amount": cash,
            "company_id": matched_id,
            "matched_by": matched_by,
            "seen_in": entry.get("_seen_in", 1),
            "cross_checked": geometry["sliced"] and entry.get("_seen_in", 1) >= 2,
            # 匹配不上、日期缺失、模型自己标了 note 的，都不算「读清楚了」
            "confidence": "待确认" if (matched_id is None or parsed_date is None or note) else "读到了",
            "note": note,
        })

    # ---- 两道确定性闸门。都不猜，只是把互相矛盾的东西挑出来。

    # 一、同一天、同价、同量、同费，却一条写着买、一条写着卖——
    # 这不是两笔交易，是同一笔被某一段读错了方向。留下互相印证过的那条。
    # （方向读错是最贵的一种错：一笔买被记成卖，持仓与成本同时错，
    # 而它在页面上看起来完全正常。）
    by_shape: dict[tuple, list[dict[str, Any]]] = {}
    for item in trades:
        if item["side"] in ("buy", "sell"):
            by_shape.setdefault(
                (item["trade_date"], item["price"], item["shares"], item["fee"]), []).append(item)
    dropped: list[dict[str, Any]] = []
    for shape, group in by_shape.items():
        if len(group) < 2 or len({item["side"] for item in group}) < 2:
            continue
        keep = max(group, key=lambda item: item["seen_in"])
        others = [item for item in group if item is not keep]
        # **只有在「一条被印证过、另一条没有」时才敢删。** 都没被印证的时候
        # 无从判断哪条对，删掉一半等于替你瞎猜——那就两条都留着、明说矛盾。
        decisive = keep["seen_in"] >= 2 and all(item["seen_in"] < keep["seen_in"] for item in others)
        if decisive:
            dropped.extend(others)
        warnings.append(
            f"{shape[0]} 价 {shape[1]} 量 {shape[2]} 这一笔，各段读出的方向不一致"
            f"（{'、'.join(sorted({i['side'] for i in group}))}）——"
            + (f"按互相印证的次数保留了「{keep['side']}」，**这一条务必自己核一眼**。"
               if decisive else
               "**两条都没有被印证过，所以都留着了——请自己看原图判断哪一条是真的。**"))

    # 二、既没日期又没价格的，是被切在段边缘只露出半截的残行。
    # 它既记不进账本（缺必填项），也无从核对，留在列表里只会挡视线。
    for item in trades:
        if item["trade_date"] is None and item["price"] is None and item["cash_amount"] is None:
            dropped.append(item)
    if dropped:
        # 按对象身份剔除，不按相等：两个内容一样的 dict 用 == 会互相误伤。
        removing = {id(item) for item in dropped}
        trades = [item for item in trades if id(item) not in removing]
        warnings.append(f"另有 {len(dropped)} 行被丢掉：要么方向自相矛盾、"
                        f"要么日期和金额都缺（切在段边缘只露出半截）。")

    # 交易记录页多半是倒序（新的在上面）。记账按时间正序看着顺。
    trades.sort(key=lambda item: (item["trade_date"] is None,
                                  item["trade_date"] or date.min))

    if not trades and not warnings:
        warnings.append(
            "没有从这张图里读出任何流水。常见原因：截图分辨率太低、"
            "只截到了汇总页而不是明细列表、或者表格被折叠了。")

    # **互相印证的结果要说出来。** 切片是双重覆盖的，正常每行会被两片各读一次；
    # 只被读到一次的，说明有一片漏了它。模型漏读是会发生的（实测同一片连读两次
    # 结果不同），而这是唯一能让"漏"从看不见变成看得见的地方。
    single = [t for t in trades if not t["cross_checked"]]
    if geometry["sliced"] and trades:
        if single:
            warnings.append(
                f"{len(trades) - len(single)} 条在相邻两段里都读到、互相印证过；"
                f"另外 {len(single)} 条只有一段读到（最上面和最下面几条本来就只有一段盖得到，"
                f"其余的说明有一段漏读了）。**只读到一次的请重点核对。**")
        else:
            warnings.append(f"全部 {len(trades)} 条都在相邻两段里读到过，互相印证一致。")

    # **对账：页头那个「交易税费」合计是这张图上唯一的校验和。**
    #
    # 逐行的费用加起来应该正好等于它。对不上就说明这次读的结果里有多的、
    # 有少的、或者有读错的——这是唯一一个不靠感觉、能直接算出来的完整性检查。
    # 差多少也一并说出来：差一笔卖出的印花税（几十块）和差一笔交易（上百块）
    # 是完全不同的两件事，而知道差额你自己就能猜到该往哪儿找。
    reconcile: dict[str, Any] | None = None
    if fee_total is None and trades:
        # **没有校验和这件事本身要说出来。**
        #
        # 上面这段注释自己写着「这是这张图上唯一的校验和」。有它的时候，
        # 对上了会说「读全了」、对不上会说差多少；而**没有它的时候这里一句话都没有**——
        # 于是"这次根本没法检验"在页面上长得跟"检验过了，没问题"一模一样。
        #
        # 这跟反证条件那次是同一种错：0 有两种意思，而界面上只有一个数。
        warnings.append(
            "这张图上没有找到页头的「交易税费」合计，所以**这次没有办法检验读全了没有**。"
            "想要这道检验的话，截图时把页头那一栏也截进来。")
    if fee_total is not None and trades:
        counted = round(sum(item["fee"] or 0 for item in trades), 2)
        gap = round(counted - fee_total, 2)
        reconcile = {"stated": fee_total, "counted": counted, "gap": gap,
                     "matched": abs(gap) < 0.05}
        if reconcile["matched"]:
            warnings.append(
                f"**对上了**：逐行费用合计 {counted:.2f}，与页头写的「交易税费 "
                f"{fee_total:.2f}」一致——这说明这张图上的流水读全了，也没有多读。")
        else:
            warnings.append(
                f"**对不上**：逐行费用合计 {counted:.2f}，页头写的「交易税费」是 "
                f"{fee_total:.2f}，差 {gap:+.2f}。说明这次读的结果里有漏的、多的或者读错的。"
                f"{'合计偏多，多半有一笔被读了两次。' if gap > 0 else '合计偏少，多半漏了一笔，或者某一行的费用没读到。'}"
                "先从上面标着「只有一段读到」的那几条查起。")

    return {
        "trades": trades,
        "unmatched": unmatched,
        "warnings": warnings,
        "geometry": geometry,
        "reconcile": reconcile,
        "model": llm.model_name(),
        "boundary": (
            "这些是从截图里读出来的，还没有记进账本。逐条核对之后再确认——"
            "模型认错一个数字，之后所有的成本价与收益率都会跟着错。"
            "截图本身没有保存，账号与资产信息也没有进入任何记录。"
        ),
    }
