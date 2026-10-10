#!/usr/bin/env bash
# 保留审计命令的退出码；截短输出不能把漏洞或网络失败变成通过。
set -uo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  frontend)
    status=0
    out=$(npm audit --omit=dev --audit-level=high 2>&1) || status=$?
    case "$out" in
      *NOT_IMPLEMENTED*|*"audit endpoint returned an error"*)
        echo "镜像源无法审计，改用 npm 官方源。"
        status=0
        out=$(npm --registry=https://registry.npmjs.org audit --omit=dev --audit-level=high 2>&1) || status=$?
        ;;
    esac
    printf '%s\n' "$out" | tail -8
    exit "$status"
    ;;
  python)
    ./.venv/bin/python -m pip_audit --progress-spinner off 2>&1 | tail -8
    ;;
  *) echo "usage: $0 frontend|python" >&2; exit 2 ;;
esac
