#!/usr/bin/env bash
#
# 门禁全过之后，在当前提交上盖凭据并推上去。deploy/check-gate.sh 核验它。
#
#   bash scripts/stamp-gate.sh "全套"
#
# ## 为什么单独一支脚本
#
# 跟 check-gate.sh 一样，是为了能被测试**真跑一遍**。
# 塞在 release-check.sh 末尾的话，要跑到它得先等十五分钟的全套测试 ——
# 于是它成了整支脚本里唯一没人验过的一段。第一版就栽在这儿：
# `$scope｜` 里那个全角竖线的首字节 0xEF 在当前 locale 下 isalnum() 为真，
# bash 把变量名读成了 `scope\xef`，`set -u` 当场把脚本打断 ——
# 七项全过，凭据没盖，而外层的 `| tail` 把非零退出码吞了，看起来一切正常。
#
# 现在 scope 从参数进来，变量一律写成 ${...}。
set -uo pipefail

scope="${1:?用法：stamp-gate.sh <跑的是哪一档>}"

# **工作区必须干净，凭据才有意义。**
# 凭据说的是"这个提交跑过门禁"。先跑门禁再提交的话，note 会盖在**上一个**
# 提交上，而上线的是新提交，等于什么都没证明。所以顺序是：先提交，再门禁，再上线。
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "· 工作区还有改动，**没有盖凭据** —— 凭据是给某一个提交的。"
  echo "  先 commit，再跑一次门禁，然后才能 deploy。"
  exit 0
fi

head=$(git rev-parse HEAD 2>/dev/null) || { echo "· 不在 git 仓里，没盖凭据。"; exit 0; }
stamp=$(date '+%Y-%m-%d %H:%M:%S')

if ! git notes --ref=release-check add -f -m "门禁通过｜${scope}｜${stamp}" "${head}"; then
  echo "· 盖凭据失败 —— deploy.sh 会拒绝上线。"
  exit 1
fi

# 推不上去等于没盖：服务器拉的是远端的 notes。所以这里失败要说出来。
if git push -q origin refs/notes/release-check 2>/dev/null; then
  echo "· 已在提交 ${head:0:8} 上盖门禁凭据并推送（deploy.sh 会核验）"
else
  echo "· 凭据盖在本地了，但**没推上去** —— deploy.sh 拉不到，会拒绝上线。"
  echo "  推完代码之后补一次：git push origin refs/notes/release-check"
fi
