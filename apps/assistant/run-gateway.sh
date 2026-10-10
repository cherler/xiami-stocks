#!/usr/bin/env bash
# 起 nanobot 网关（助理的「嘴」）：收发飞书 / 微信消息，调虾米看股的 MCP 工具。
#
# 密钥从虾米看股的 .env 读进环境变量，**不写进 nanobot 的配置文件**——
# 配置里只有 ${MINIMAX_API_KEY} 这种占位（见 setup.py）。
#
# 本地终端里试一句话（不经飞书）：
#   apps/assistant/run-gateway.sh agent -m "我想买宁德"
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$REPO/.env"

value() {
  # 取 .env 里 KEY= 后面的值；没有就是空串（nanobot 会在启动时点名缺了哪个）。
  /usr/bin/grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

export MINIMAX_API_KEY="${MINIMAX_API_KEY:-$(value MINIMAX_API_KEY)}"
export TAVILY_API_KEY="${TAVILY_API_KEY:-$(value TAVILY_API_KEY)}"

NANOBOT="$(command -v nanobot || echo "$HOME/.local/bin/nanobot")"
if [ "$#" -eq 0 ]; then
  exec "$NANOBOT" gateway
fi
exec "$NANOBOT" "$@"
