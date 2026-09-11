"""取回来的不是 PDF 时，要**说出它是什么**，并且换一个客户端再试一次。

## 这条是使用者报上来的

同一个链接（`https://pdf.dfcfw.com/pdf/H3_AP...pdf`）本地能读、线上报
「这不是 PDF 文件。现在只读得了 PDF。」——**那句话把原因指向了链接**，
于是他做的第一件事是反复核对链接对不对。

线上实测出来的真相：

  curl（同一台机器）  -> 200 application/pdf  1,579,680 字节  开头 %PDF-1.7
  urllib（我们的代码） -> 200 application/pdf        989 字节  开头 <script>

那 989 字节是腾讯云 EdgeOne 的反爬校验页：一段 JavaScript，让浏览器算两个 cookie
再重载。**响应头里的 content-type 照样写着 application/pdf**，所以连头都不能信，
只能看头几个字节。

逐项排除过：换 User-Agent 没用（curl 用我们这个 UA 也能过）、加 Accept /
Accept-Language 没用、什么头都不带也没用。区别在 TLS 指纹与 HTTP 版本
（curl 协商 h2，urllib 走 HTTP/1.1）。

## 所以守两件事

1. **消息要说出取回来的是什么。** 一句"不是 PDF"会让人去查链接 ——
   而链接是对的，问题在服务器出口。这个功能的价值全在"可核"，
   一句把人带到错误方向的报错比不报错更贵。
2. **直连拿不到 PDF 时要换 curl 再试一次。** 不解校验页（里面的数字每次都变，
   解它就是在绕过站点的机器人校验），只是换一个原站会正常服务的标准客户端，
   UA 保持我们自己的名字。
"""

from __future__ import annotations

import ast
import pathlib

from stock_decision import disclosure as dis

MAIN = pathlib.Path(__file__).resolve().parents[1] / "stock_decision" / "main.py"


def test_it_names_what_came_back_instead_of_just_saying_not_a_pdf():
    assert dis.describe_body(b"") == "什么都没取到（0 字节）"
    # 校验页：要说出"一段 JavaScript"，那是唯一能让人想到"服务器被拦了"的措辞
    challenge = b"<script>function a(a){var t=0;return t}</script>"
    assert "一段 JavaScript" in dis.describe_body(challenge)
    assert "网页" in dis.describe_body(b"<!DOCTYPE html><html><title>404</title>")
    assert "JSON" in dis.describe_body(b'{"error":"forbidden"}')
    # 真 PDF 但太短（截断、占位）也要说清是"是 PDF，但只有 N 字节"
    assert dis.describe_body(b"%PDF-1.4 x") == "是 PDF，但只有 10 字节"


def test_the_challenge_page_is_recognised_but_not_solved():
    """认出来只为了换客户端和把话说清。**解它就是绕过机器人校验，不做。**"""
    assert dis._looks_like_challenge(b"<script>var a=1;</script>")
    assert not dis._looks_like_challenge(b"%PDF-1.7 ...")
    # 一整个正常网页不算校验页（校验页是几百字节的一小段）
    assert not dis._looks_like_challenge(b"<html>" + b"x" * 5000)
    # 源码里不许出现"算 cookie 再重放"那套东西
    source = pathlib.Path(dis.__file__).read_text(encoding="utf-8")
    for banned in ("__tst_status", "EO_Bot_Ssid"):
        assert banned not in source, (
            f"{banned} 出现在源码里 —— 那是在解站点的机器人校验，这条线不越")


def test_the_error_message_does_not_blame_the_link():
    """**「这不是 PDF 文件」这句话不许再出现。**

    它把原因指向链接，而实测最常见的原因是服务器出口被拦 ——
    使用者照着这句话去反复核对了链接。
    """
    text = MAIN.read_text(encoding="utf-8")
    body = text[text.index("def _parse_and_save"):]
    body = body[:body.index("\n@app")] if "\n@app" in body else body
    # **只看会发给使用者的字符串，不看注释。** 那句话仍然留在注释里 ——
    # 记着"为什么改的"比守卫的方便重要，所以是守卫去适配注释，不是把注释删掉。
    code = "\n".join(line.split("#")[0] for line in body.splitlines())
    assert "这不是 PDF 文件" not in code, "又变回那句把人带错方向的消息了"
    assert "describe_body" in code, "报错要说出取回来的是什么"
    assert "拦了服务器的请求" in code, "要提示可能是站点拦了服务器，不是链接不对"


def test_curl_is_the_second_road_and_it_cannot_reach_file_urls():
    """第二条路要有，而且**不许能读本地文件**。

    url 是使用者给的。curl 默认乐意去读 `file://` 和 `gopher://` ——
    这个接口是登录后可用的，但那不是把 SSRF 面敞开的理由。
    """
    source = pathlib.Path(dis.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    curl = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_fetch_with_curl"), None)
    assert curl is not None, "第二条路没了 —— 东财那个域名就又读不了了"
    # **取参数要按 AST 取，不能按源文本 match 引号。** `ast.unparse` 会把双引号
    # 统一成单引号，照着源码的写法去断言当场就假红了一次。
    flags = [node.value for node in ast.walk(curl)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert "--proto" in flags and "=http,https" in flags, "curl 必须锁死 http/https"
    assert "--proto-redir" in flags, "跟随跳转时也要锁死"
    assert "--max-filesize" in flags and "--max-time" in flags, "要有大小与时间上限"
    kwargs = {kw.arg for node in ast.walk(curl) if isinstance(node, ast.Call)
              for kw in node.keywords}
    assert "shell" not in kwargs, "url 是使用者给的，绝不过 shell"
    # 直连成功就不该起第二条路（多一次请求对原站不礼貌，也慢）
    fetch = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "fetch_bytes")
    lines = ast.unparse(fetch).splitlines()
    ok = next(i for i, line in enumerate(lines) if "b'%PDF-'" in line and "return" not in line)
    second = next(i for i, line in enumerate(lines) if "_fetch_with_curl" in line)
    assert ok < second, "直连拿到 PDF 就要直接返回，不许再走一次 curl"
