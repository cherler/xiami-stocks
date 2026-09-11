"""能下载的东西必须真的下载下来。

## 为什么单独写一条

「导出研究池」那个入口是前端的一个裸 `<a href="/api/v1/companies/export">`，
没有 download 属性。接口返回 200、内容也完全正确 —— 但少了
`Content-Disposition`，浏览器就照 application/json 直接渲染：
**点一下，整个应用被一屏 JSON 顶掉，人得按浏览器后退才能回来，
而且一个文件都没拿到。**

2026-08-19 全站巡检实测：点完 url 变成 /stocks-api/api/v1/companies/export，
页面开头是 `[{"symbol":"002948","name":"青岛银行",...`。
而导入那一栏写的是「选择"导出研究池"下载到的 JSON 文件」——
导出→导入这条闭环从第一步就是断的。

**状态码测不出这一类。** 200 是对的、JSON 是对的，坏的是"它算不算一个文件"。
所以这里测响应头。
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from stock_decision.main import app

# 会下载文件的接口。新增一个下载入口就往这里加一条。
DOWNLOADS = [
    "/api/v1/companies/export",
]


def test_下载接口都带了_content_disposition() -> None:
    client = TestClient(app)
    for path in DOWNLOADS:
        response = client.get(path)
        assert response.status_code == 200, f"{path} 没通"
        disposition = response.headers.get("content-disposition", "")
        assert disposition.startswith("attachment"), (
            f"{path} 没有 Content-Disposition: attachment —— "
            "浏览器会把它当页面渲染，用户点完看到的是一屏 JSON，不是一个文件。\n"
            f"实际：{disposition or '（没有这个头）'}"
        )


def test_下载的文件名带日期() -> None:
    """研究池会变。两次导出叫同一个名字，存到本地就分不出哪份是哪天的。"""
    client = TestClient(app)
    for path in DOWNLOADS:
        disposition = client.get(path).headers.get("content-disposition", "")
        name = re.search(r'filename="([^"]+)"', disposition)
        assert name, f"{path} 的 Content-Disposition 里没有 filename：{disposition}"
        assert re.search(r"\d{4}-\d{2}-\d{2}", name.group(1)), (
            f"{path} 的文件名里没有日期：{name.group(1)}"
        )


def test_前端那个入口还指着同一个地址() -> None:
    """上面测的是接口。入口要是改了地址，这条测试就在测一个没人用的接口。"""
    from pathlib import Path

    app_tsx = (Path(__file__).resolve().parents[3] / "apps/web/src/App.tsx").read_text()
    assert 'href={apiUrl("/api/v1/companies/export")}' in app_tsx, (
        "「导出研究池」的地址变了 —— 把 DOWNLOADS 里的路径一起改掉"
    )
