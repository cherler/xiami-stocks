#!/usr/bin/env bash
#
# 核验「这个提交跑过发布门禁」。deploy.sh 在拉完代码之后调它。
#
#   bash deploy/check-gate.sh          # 过了打印凭据，没过 exit 1
#   SKIP_GATE_CHECK=1 …                # 放行（回滚、救火），但日志里留一行
#
# ## 为什么单独一支脚本
#
# **门禁在开发机上跑，部署在服务器上跑** —— 这边没法知道那边跑没跑过。
# 原来全靠"我记得跑"，而门禁那支脚本存在的理由恰恰是"没人记得跑哪几个"。
#
# 所以 release-check.sh 过了会在提交上盖一个 git note 推上来，这里核验它。
# 拆出来是为了能被测试**真跑一遍** —— 塞在 deploy.sh 里的话，
# 它前面是 git pull、后面是 pip install，测试没法只跑中间这一段，
# 只能去 grep 源码；而 grep 源码证明不了这段逻辑真会拦住人。
set -uo pipefail

echo "── 门禁凭据 ────────────────────────────────"

# 凭据存在 refs/notes/release-check，默认的 git fetch 不带 notes，要显式拉。
git fetch -q origin "refs/notes/release-check:refs/notes/release-check" 2>/dev/null || true

note=$(git notes --ref=release-check show HEAD 2>/dev/null || true)
if [ -n "$note" ]; then
  # 凭据里写着跑的是哪一档 —— "跳过了两个后端套件的全过"跟"真的全过"是两件事，
  # 所以原样打出来给人看，不在这里做二次解释。
  echo "  ✓ $note"
  exit 0
fi

if [ "${SKIP_GATE_CHECK:-0}" = "1" ]; then
  echo "  ⚠ 这个提交没有门禁凭据，**被 SKIP_GATE_CHECK=1 放行**。"
  echo "    （回滚和救火可以这么做，但这一行会留在日志里。）"
  exit 0
fi

echo "  ✗ 这个提交没有门禁凭据，不上线。"
echo
echo "    在开发机上："
echo "      git commit …           # 先提交（凭据是给某一个提交的）"
echo "      bash scripts/release-check.sh --auto"
echo "      git push"
echo "    然后再跑这支脚本。真要绕过：SKIP_GATE_CHECK=1 bash deploy/deploy.sh"
exit 1
