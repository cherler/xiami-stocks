#!/usr/bin/env python3
"""本地入口网关：按线上 Caddy 的规则做路径分流，用来在本机验证跳转链路。

线上是单域名 + 路径分流，本机默认是各跑各的端口——这个差异只有在部署后才会暴露，
而暴露的方式通常是「点进去一片空白」。这个脚本把线上那套规则原样搬到本机 :8090，
让「从虾米伙伴点进虾米看股」这条链路在推服务器之前就能走一遍。

规则与 deploy/caddy-snippet.conf 一一对应，改一边要改另一边：
    /stocks-api/*  → 剥前缀 → 127.0.0.1:8108   （虾米看股后端）
    /stocks/*      → 剥前缀 → 静态目录          （虾米看股前端，SPA 回退 index.html）
    /v1 /api /media/* → 127.0.0.1:8200          （主站后端，没起也不影响静态页）
    其余           → 主站静态目录               （必须最后兜底）
"""

from __future__ import annotations

import argparse
import http.server
import mimetypes
import selectors
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_STOCKS = "http://127.0.0.1:8108"
BACKEND_MAIN = "http://127.0.0.1:8200"

# urllib 默认会读 http_proxy 环境变量,把本机回环也送去代理,结果是 502。
# 显式用一个不带代理的 opener。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Gateway(http.server.BaseHTTPRequestHandler):
    # **必须声明 HTTP/1.1。** BaseHTTPRequestHandler 默认是 1.0，于是每个响应都不带
    # keep-alive、连接一发完就断。浏览器对每个资源重开一条 TCP，Next 开发模式下
    # 大量并发小请求会被这样拖垮——表现是页面渲染得好好的、客户端脚本却没跑起来，
    # 菜单点不开、按钮没反应，而控制台一条报错都没有。
    protocol_version = "HTTP/1.1"

    stocks_root: Path | None
    stocks_dev: str | None
    main_root: Path | None
    main_dev: str | None
    chrome_root: Path | None

    def log_message(self, fmt: str, *args) -> None:  # 只在出错时说话
        if not str(args[1] if len(args) > 1 else "").startswith("2"):
            super().log_message(fmt, *args)

    def _tunnel(self, upstream: str, path: str) -> bool:
        """WebSocket 直通。不是升级请求就返回 False，交给普通代理。

        **必须有这一条。** Next 与 Vite 的热更新都靠 websocket
        （`/_next/webpack-hmr`、`/@vite/ws`）。urllib 只会做普通 HTTP 请求，
        升级请求到它手里就变成一个普通 GET —— Next 回 404，浏览器每隔几秒重连一次。
        而 Next 的 App Router 在开发模式下依赖这条连接，连不上时**整页交互都是死的**：
        菜单点不开、按钮没反应，但页面本身渲染得好好的，看不出哪里坏了。

        做法是最朴素的那种：把握手原样转给上游，然后两个方向对拷字节。
        网关不理解 websocket 帧，也不需要理解。
        """
        if "websocket" not in self.headers.get("Upgrade", "").lower():
            return False

        target = urlsplit(upstream)
        try:
            upstream_sock = socket.create_connection(
                (target.hostname, target.port or 80), timeout=10)
        except OSError as exc:
            self.send_error(502, "Bad Gateway", f"websocket 上游不可达：{exc}")
            return True

        # 原样重放握手：逐字节转发，不做解释——少改一个头都可能让握手失败。
        request_line = f"{self.command} {path} HTTP/1.1\r\n"
        headers = "".join(f"{key}: {value}\r\n" for key, value in self.headers.items()
                          if key.lower() != "host")
        headers += f"Host: {target.hostname}:{target.port or 80}\r\n"
        try:
            upstream_sock.sendall((request_line + headers + "\r\n").encode("latin-1"))
        except OSError:
            upstream_sock.close()
            return True

        client_sock = self.connection
        client_sock.setblocking(False)
        upstream_sock.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(client_sock, selectors.EVENT_READ, upstream_sock)
        selector.register(upstream_sock, selectors.EVENT_READ, client_sock)
        try:
            while True:
                events = selector.select(timeout=300)
                # **这里必须显式判空，不能用 for...else。**
                # for...else 的 else 是「循环没被 break 就执行」——而这个循环从不 break，
                # 于是每处理完一批事件就走进 else 把连接关掉。表现是握手成功（101）、
                # 数据一个来回就断，Next 客户端每隔一两秒 [HMR] connected 一次，
                # 无限重连，而**整页交互是死的**：菜单点不开、按钮没反应、控制台没有报错。
                if not events:
                    return True                     # 真的闲置超时了，放掉
                for key, _ in events:
                    try:
                        chunk = key.fileobj.recv(65536)
                    except (BlockingIOError, InterruptedError):
                        continue
                    except OSError:
                        return True
                    if not chunk:                   # 对端关闭
                        return True
                    try:
                        key.data.sendall(chunk)
                    except OSError:
                        return True
        finally:
            selector.close()
            upstream_sock.close()
            self.close_connection = True

    def _proxy(self, upstream: str, path: str) -> None:
        if self._tunnel(upstream, path):
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
        request = urllib.request.Request(upstream + path, data=body, method=self.command)
        for key, value in self.headers.items():
            # accept-encoding 也不转发：让上游发未压缩的内容。
            # 网关只做字节搬运，转发压缩协商就得保证 Content-Encoding 与实际字节一致，
            # 多一层容易出错的环节，而本机开发不差这点带宽。
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}:
                request.add_header(key, value)
        try:
            with _OPENER.open(request, timeout=120) as response:
                payload, status, headers = response.read(), response.status, response.headers
        except urllib.error.HTTPError as exc:
            payload, status, headers = exc.read(), exc.code, exc.headers
        except Exception as exc:
            # send_error 的 message 会进 HTTP 状态行，http.server 按 latin-1 编码——
            # 中文直接 UnicodeEncodeError，客户端收到的是半截响应而不是 502。
            # 状态行保持 ASCII，中文细节放响应体里。
            self.send_error(502, "Bad Gateway", f"上游不可达：{exc}")
            return
        self.send_response(status)
        # send_response 已经自己发了 Server 与 Date；再把上游那份转发一遍，
        # 响应里就会出现两个 Date —— 这是协议违规，有些客户端会因此整条丢弃。
        skip = {"transfer-encoding", "connection", "content-length", "date", "server",
                "keep-alive"}
        for key, value in headers.items():
            if key.lower() not in skip:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _static(self, root: Path, rel: str, spa_fallback: str | None) -> None:
        """按 Caddy 的 try_files 顺序找文件。

        顺序要紧：Next 静态导出产出的是 `research.html` 而不是 `research/index.html`，
        但 `research/` 这个目录确实存在（放着 RSC 载荷和子页面）。
        先试目录就会命中一个没有 index.html 的空壳，直接掉进 404 ——
        而站内链接恰恰都带尾斜杠（href="/crossborder/research/"）。
        所以必须先试 `{path}.html`，再试 `{path}/index.html`。
        """

        clean = rel.split("?")[0]
        base = (root / clean.lstrip("/")).resolve()
        if not str(base).startswith(str(root.resolve())):      # 防目录穿越
            self.send_error(403)
            return

        # 与线上 handle 块一一对应（真源：wiki/19 §3）：
        #   @slash path_regexp ^(/.+)/$  →  rewrite 掉尾斜杠（内部重写，不是 302）
        #   try_files {path}.html {path} {path}/index.html
        # 尾斜杠这一步是关键：站内链接大量写成 /crossborder/research/，
        # 而导出产物里没有 research/index.html。少了它就会 404。
        rel_clean = clean.strip("/")
        if not rel_clean:
            candidates = [root / "index.html"]
        else:
            candidates = [
                root / f"{rel_clean}.html",
                root / rel_clean,
                root / rel_clean / "index.html",
            ]
        for candidate in candidates:
            if candidate.is_file():
                self._send(candidate.read_bytes(),
                           mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
                return

        if spa_fallback:                                        # SPA：任何路径都回 index.html
            target = root / spa_fallback
            if target.is_file():
                self._send(target.read_bytes(), "text/html; charset=utf-8")
                return
        # 找不到就如实返回 404。之前这里发的是 404 页面配 200 状态码，
        # 于是 curl 说 200、浏览器显示 404，把排查带偏了一整轮。
        not_found = root / "404.html"
        self._send(not_found.read_bytes() if not_found.is_file() else b"404",
                   "text/html; charset=utf-8", status=404)

    def _route(self) -> None:
        path = self.path
        if path.startswith("/stocks-api/"):
            self._proxy(BACKEND_STOCKS, path[len("/stocks-api"):])
        elif path == "/stocks":
            self.send_response(308); self.send_header("Location", "/stocks/"); self.end_headers()
        elif path.startswith("/stocks/"):
            # dev 模式直接转 Vite，热更新与 HMR 的 websocket 都能过去
            if self.stocks_dev:
                self._proxy(self.stocks_dev, path)
            else:
                self._static(self.stocks_root, path[len("/stocks"):] or "/", "index.html")
        elif path.startswith(("/v1/", "/api/", "/media/", "/health")):
            self._proxy(BACKEND_MAIN, path)
        elif path.startswith("/chrome/") and self.chrome_root:
            # 平台页眉页脚是**构建产物**，不是 Next 应用的一部分：
            # 它由 build-chrome-artifacts.mjs 生成到 out/chrome/，线上由 Caddy 直接发。
            # 开发时 Next dev server 不认识它，所以这里单独从目录里发——
            # 少了这一条，子应用加载页眉会 404，页面上就是「没有平台页眉」。
            self._static(self.chrome_root, path[len("/chrome"):] or "/", None)
        elif self.main_dev:
            # 主站跑的是 Next 开发服（有热更新）时转发过去。
            # 与 --main 指静态导出目录的区别：开发时改一行代码就能看到，
            # 不必先 build 一次；代价是它与线上的静态导出不完全等价，
            # 发布前的最终验证仍要用 --main out/ 走一遍真实形态。
            self._proxy(self.main_dev, path)
        else:
            self._static(self.main_root, path, None)

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = do_HEAD = _route


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--stocks", help="虾米看股的 dist 目录（验证发布形态用）")
    parser.add_argument("--stocks-dev", metavar="URL", help="转发到 Vite dev server（日常开发用，有热更新）")
    parser.add_argument("--main", help="主站的 out 目录（发布形态，最接近线上）")
    parser.add_argument("--main-dev", metavar="URL", help="转发到主站 Next 开发服（日常开发用）")
    parser.add_argument("--chrome", help="页眉页脚制品目录（主站 out/chrome）。"
                                         "配 --main-dev 时必须给：Next 开发服不发这些构建产物。")
    args = parser.parse_args()
    if not args.stocks and not args.stocks_dev:
        parser.error("--stocks 与 --stocks-dev 至少给一个")
    if not args.main and not args.main_dev:
        parser.error("--main 与 --main-dev 至少给一个")
    Gateway.stocks_root = Path(args.stocks).resolve() if args.stocks else None
    Gateway.stocks_dev = args.stocks_dev
    Gateway.main_root = Path(args.main).resolve() if args.main else None
    Gateway.main_dev = args.main_dev
    Gateway.chrome_root = Path(args.chrome).resolve() if args.chrome else None
    print(f"本地入口网关 http://127.0.0.1:{args.port}")
    print(f"  /stocks/*     → {Gateway.stocks_dev or Gateway.stocks_root}")
    print(f"  /stocks-api/* → {BACKEND_STOCKS}")
    if Gateway.chrome_root:
        print(f"  /chrome/*     → {Gateway.chrome_root}")
    print(f"  其余          → {Gateway.main_dev or Gateway.main_root}")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Gateway).serve_forever()


if __name__ == "__main__":
    main()
