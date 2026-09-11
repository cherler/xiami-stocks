#!/usr/bin/env bash
#
# 发布门禁。**上线之前把该跑的一次跑完，别靠记忆。**
#
#   bash scripts/release-check.sh            # 全套（两个数据库各跑一遍，约 15 分钟）
#   bash scripts/release-check.sh --fast     # 跳过 SQLite 那一遍
#
# ## 为什么要有它
#
# 这个仓已经有很多检查了，问题从来不是"没有"，是**没人记得跑哪几个**：
# 响度归一的脚本写好了没接进流水线，八支片就全漏了；导出链接的守卫只看
# `fetch(`，三个下载入口就一直是坏的。检查散着放 = 没有检查。
#
# ## 为什么两个数据库都要跑
#
# 线上是 PostgreSQL，测试默认也是 PG（2026-08-10 起）。但 SQLite 那条路
# 仍然活着（本地单机、备份还原、迁移脚本），而两边的 SQL 方言不一样：
# `INSERT OR REPLACE`、`row[0]`、`HAVING` 引用别名、`sqlite_master`、
# `datetime('now','-10 minutes')`——每一条都是"一边全绿、另一边炸"。
# 今天写熔断时差点又踩一次（时间窗本来想写在 SQL 里）。
#
# 冒烟测试（scripts/smoke.mjs）**不在这里面**：它要一套跑起来的服务和一个
# 浏览器，属于"部署形态"那一层。这支脚本管的是代码本身。

set -uo pipefail
cd "$(dirname "$0")/.."

FAST=0
ONLY_WEB=0
case "${1:-}" in
  --fast) FAST=1 ;;
  --auto) ;;   # 下面按改动范围自己判
esac

# ── 按改动范围决定跑哪几步 ────────────────────────────────────────────
#
# **默认仍然是全套。** 分层只在 `--auto` 下生效，而且判据是
# 「跟上游分叉点相比动了哪些文件」，不是让人自己声明改了什么 ——
# 人会记错，而记错的那一次正好就是该跑全套的那一次。
#
# 后端那一步要十五分钟，前端那几步加起来十几秒。今天改一行 CSS 也等了十五分钟，
# 等了十几次。但**省掉的那一步必须是真的无关**：
#   动了 apps/api/** 或 scripts/** 或 .venv 里的依赖 → 全套
#   只动 apps/web/** → 跳过两个后端套件
# 别的（比如 deploy/、docs/）保守起见也跑全套 —— 判不准就往全套那边错。
# 判定本身用 shell 内建的 case，**不依赖 PATH 上是哪个 grep**。
#
# 第一版写的是 `! echo "$changed" | grep -qvE "^apps/web/"`。它可能没错，
# 但**我没法便宜地证明它没错**：开发机上 grep 被一个 shell 函数遮成了 ugrep，
# 而 ugrep 的 `-q` 与 `-v` 合用返回的东西跟 GNU grep 不一样。
# 于是"这条判定对不对"取决于谁在什么 shell 里跑它。
#
# 这个判定错一次的代价是不对称的：**判成"只跑前端"而后端其实改了，
# 会给你一份少跑两个套件的"全过"** —— 而这支脚本存在的全部理由就是拦静默变绿。
# 不对称的判定不该建在"看你机器上装的哪个 grep"上面。
# case 是 POSIX 内建，没有第三方实现的余地。
scope_of() {
  local only=1 line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in
      apps/web/*) ;;
      *) only=0 ;;
    esac
  done
  [ "$only" = "1" ] && echo web || echo full
}

# 给测试用：`bash scripts/release-check.sh --scope-of < 文件清单`
if [ "${1:-}" = "--scope-of" ]; then scope_of; exit 0; fi

if [ "${1:-}" = "--auto" ]; then
  base=$(git merge-base HEAD origin/main 2>/dev/null || echo HEAD)
  changed=$( { git diff --name-only "$base" --; git diff --name-only --cached; \
               git ls-files --others --exclude-standard; } 2>/dev/null | sort -u)
  if [ -z "$changed" ]; then
    echo "（--auto：跟 origin/main 比没有改动，按全套跑）"
  elif [ "$(printf '%s\n' "$changed" | scope_of)" = "web" ]; then
    ONLY_WEB=1
    echo "（--auto：只动了 apps/web/**，跳过两个后端套件 —— 后端一步要十五分钟）"
    printf '%s\n' "$changed" | sed 's/^/    /'
  else
    echo "（--auto：动了 apps/web 以外的东西，按全套跑）"
  fi
fi

PASS=(); FAIL=()
step() {
  local name="$1"; shift
  echo
  echo "── $name ────────────────────────────────"
  if "$@"; then PASS+=("$name"); else FAIL+=("$name"); echo "!! $name 没过"; fi
}

# **每一段都要带 pipefail。** 第一版各步写成 `cmd 2>&1 | tail -3`，
# 记下来的是 tail 的退出码 —— npm audit 明明报了错，这一步照样绿。
# 我写这支脚本就是为了拦"静默变绿"，结果它自己先犯了一次。
run() { bash -o pipefail -c "$1"; }

py() { ./.venv/bin/python "$@"; }

if [ "$ONLY_WEB" = "0" ]; then
step "后端测试（PostgreSQL，线上用的就是它）" \
  run "cd apps/api && ../../.venv/bin/python -m pytest -q 2>&1 | tail -3"
fi

if [ "$FAST" = "0" ] && [ "$ONLY_WEB" = "0" ]; then
  # **SQLite 这一遍不能省。** 本地单机、备份还原、迁移脚本都走它，
  # 而方言差异只会在真跑到那一边时才暴露。
  step "后端测试（SQLite，本地单机与还原走这条路）" \
    run "cd apps/api && STOCK_TEST_SQLITE=1 ../../.venv/bin/python -m pytest -q 2>&1 | tail -3"
fi

step "前端类型与单测" run "npm run test:web 2>&1 | tail -3"
step "品牌 token 与对比度" run "npm run check:tokens && npm run check:contrast 2>&1 | tail -2"

step "构建 + 首屏预算" run "VITE_BASE=/stocks/ npm run build 2>&1 | tail -2 && node scripts/check-bundle.mjs apps/web/dist | tail -2"

# 依赖安全：只看**生产依赖**。dev 依赖里的漏洞不上线上机器，
# 把它们一起报出来只会让这一步天天红着，然后被无视。
#
# **这台机器的 npm 指向 npmmirror，而它没实现 audit 接口**（实测 404
# `[NOT_IMPLEMENTED] /-/npm/v1/security/*`）。查不了就得说查不了 ——
# 不能因为"命令没报错"就当成没有漏洞，那是这支脚本最不该犯的错。
audit_frontend() {
  local out registry
  registry=$(npm config get registry)
  out=$(npm audit --omit=dev --audit-level=high 2>&1) || true
  # 镜像源查不了就自动换官方源再试一次（实测官方源可达、返回 0 vulnerabilities）。
  # 两边都不行才算没查成 —— 而"没查成"是失败，不是通过。
  if echo "$out" | grep -q "NOT_IMPLEMENTED\|audit endpoint returned an error"; then
    echo "   $registry 不支持 audit，换官方源再试一次…"
    out=$(npm --registry=https://registry.npmjs.org audit --omit=dev --audit-level=high 2>&1) || true
  fi
  echo "$out" | tail -5
  if echo "$out" | grep -q "NOT_IMPLEMENTED\|audit endpoint returned an error"; then
    echo "   官方源也没查成 —— **这一项是空的**，别当成通过了。"
    return 1
  fi
  echo "$out" | grep -qE "found [1-9][0-9]* (high|critical)" && return 1
  return 0
}
step "前端生产依赖漏洞" audit_frontend

if ./.venv/bin/python -c "import pip_audit" 2>/dev/null; then
  step "Python 依赖漏洞" bash -c "./.venv/bin/python -m pip_audit --progress-spinner off 2>&1 | tail -5"
else
  echo
  echo "── Python 依赖漏洞 ──────────────────────"
  echo "   跳过：没装 pip-audit（.venv/bin/pip install pip-audit）"
  echo "   **这一项是空的**，不要把它当成通过了。"
fi

echo
echo "════════════════════════════════════════"
# `set -u` 下空数组展开会直接把脚本打断（实测：全过的那一次反而崩在这里，
# 连"全过"两个字都没打印出来）。${arr[@]+...} 是空数组安全的写法。
for name in ${PASS[@]+"${PASS[@]}"}; do echo "✓ $name"; done
for name in ${FAIL[@]+"${FAIL[@]}"}; do echo "✗ $name"; done
# **跳过了什么要说出来。** 一份悄悄少跑两步的"全过"比没跑更危险：
# 它读起来跟真的全过一模一样，而这支脚本存在的全部理由就是拦"静默变绿"。
if [ "$ONLY_WEB" = "1" ]; then
  echo "· 后端两套没跑（--auto 判定这次只动了 apps/web/**）"
  echo "  动了后端就必须跑全套：bash scripts/release-check.sh"
fi
if [ "$FAST" = "1" ]; then
  echo "· SQLite 那一遍没跑（--fast）"
fi
if [ ${#FAIL[@]} -gt 0 ]; then
  echo
  echo "${#FAIL[@]} 项没过，别上线。"
  exit 1
fi
# ── 全过之后留个凭据 ─────────────────────────────────────────────────
#
# **门禁在这台机器上跑，而部署在服务器上跑** —— 服务器没法知道你跑没跑过。
# 原来全靠"我记得跑"，而这一整支脚本存在的理由恰恰是"没人记得跑哪几个"。
#
# 盖凭据的逻辑在 scripts/stamp-gate.sh 里，那样测试能真跑它 ——
# 留在这儿的话，要跑到它得先等十五分钟的全套测试，
# 于是它会成为整支脚本里唯一没人验过的一段（第一版就是这么炸的）。
#
# 档位要写进凭据：**"跳过了两个后端套件的全过"跟"真的全过"是两件事。**
scope="全套"
[ "$ONLY_WEB" = "1" ] && scope="仅前端（--auto 判定只动了 apps/web）"
[ "$FAST" = "1" ] && scope="${scope}，跳过 SQLite（--fast）"
bash scripts/stamp-gate.sh "${scope}"

echo
echo "全过。接下来跑部署形态的冒烟："
echo "  PLAYWRIGHT_PATH=… node scripts/smoke.mjs --base http://127.0.0.1:8092"
