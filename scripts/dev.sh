#!/usr/bin/env bash
# 一条命令把开发环境起全：后端 :8108 + 前端 :5217。
#
# ## 为什么要有这个脚本
#
# 从 :3000 进虾米看股的时候，页面来自 Vite（:5217），接口由主站的 rewrite
# 转给 :8108。少起后端那一半，页面照常渲染、导航照常点，只有接口全挂 ——
# 而 **Next 的 rewrite 遇到连不上的上游回的是 500**，不是 502 也不是连接错误，
# 正文只有一句 "Internal Server Error"。前端于是显示「请求失败（500）」，
# 读起来像是后端算错了，第一反应是去翻后端日志，而那里什么都没有。
#
# 前端那边已经改成认得出这种 500（api.ts 的 unreachable）；这个脚本是另一半：
# 让「只起了一半」这件事根本不发生。
#
# ## 已经在跑的不重起
#
# 常态是「Vite 一直开着，忘了起后端」。第一版不管三七二十一两个都起，于是
# Vite 撞端口退出，脚本按「谁先退出就一起收摊」把刚起来的后端也收了 ——
# `npm run dev` 看着跑了一下就没了，页面照旧 500。**它把要修的病又犯了一遍。**
# 现在先看端口：占着的就用现成的，缺哪个补哪个。
#
# ## 只用 bash 3.2 写得出来的东西
#
# macOS 自带的 /bin/bash 是 3.2（2007 年，GPLv2 那一版，苹果不会再升），而
# package.json 里写的是 `bash scripts/dev.sh`，走的就是它。第一版用了 `wait -n`
# ——bash 4.3 才有的——直接报 "wait: -n: invalid option"，set -e 让脚本退出，
# trap 又把两个进程一起收掉。**能用**：数组、+=、trap、$(...)；
# **不能用**：wait -n、mapfile、declare -A、${x^^}。

set -euo pipefail
cd "$(dirname "$0")/.."

API_PORT="${STOCK_API_PORT:-8108}"
WEB_PORT="${STOCK_WEB_PORT:-5217}"

# 端口上有没有人在听。lsof 在 macOS 自带，Linux 上装了才有 —— 探不到就当没占，
# 大不了退回到"撞端口"，比因为探测手段缺席而拒绝启动强。
listening() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

api_pid=""
web_pid=""

cleanup() {
  trap - EXIT INT TERM
  # **只收自己起的。** 复用的那个是别人的进程，不许动。
  [ -n "$api_pid" ] && kill "$api_pid" 2>/dev/null || true
  [ -n "$web_pid" ] && kill "$web_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if listening "$API_PORT"; then
  echo "后端 :$API_PORT 已经在跑，用现成的。"
else
  if [ ! -x .venv/bin/uvicorn ]; then
    echo "没找到 .venv/bin/uvicorn。先建虚拟环境：python3 -m venv .venv && ./.venv/bin/pip install -e ." >&2
    exit 1
  fi
  ./.venv/bin/uvicorn stock_decision.main:app --reload --app-dir apps/api --port "$API_PORT" &
  api_pid=$!
fi

if listening "$WEB_PORT"; then
  echo "前端 :$WEB_PORT 已经在跑，用现成的。"
else
  npm run dev --workspace @xiamimate-stock-lab/web &
  web_pid=$!
fi

if [ -z "$api_pid" ] && [ -z "$web_pid" ]; then
  echo "两边本来就都在跑，这条命令没事可做。"
  exit 0
fi

echo "后端 http://127.0.0.1:${API_PORT}　前端 http://127.0.0.1:${WEB_PORT}/stocks/　（从主站进：http://127.0.0.1:3000/stocks/）"

# 自己起的那些谁先退出就一起收摊 —— 后端崩了而前端还转着，正是这个脚本要根治的
# 半死状态。轮询代替 `wait -n`：一秒一次，够快，而且 bash 3.2 认得。
while true; do
  [ -n "$api_pid" ] && ! kill -0 "$api_pid" 2>/dev/null && break
  [ -n "$web_pid" ] && ! kill -0 "$web_pid" 2>/dev/null && break
  sleep 1
done
