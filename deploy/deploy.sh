#!/usr/bin/env bash
#
# 虾米看股上线。**在服务器上跑,代码只从 GitHub 来。**
#
#   ssh your-server 'bash /srv/xiami-stocks/app/deploy/deploy.sh'
#
# ## 为什么要有这个脚本
#
# 2026-08-12：「从公告里找承诺」上线以来一次都没有产出过。查到最后是服务器 venv
# 里没装 pypdf —— 而 `pyproject.toml` 里明明写着 `pypdf>=6,<7`。
#
# **因为部署从来只做 git pull + 前端构建,没有一步同步 Python 依赖。**
# 加一个依赖是在本机装的,本机能跑、测试全绿、代码推上去,服务器上却少一个包;
# 而表现出来只是"这个功能没结果",不报错、不告警,查起来离真正的原因很远。
#
# 同一天还发现另一处:构建产物在 apps/web/dist,而 Caddy 的根是
# /srv/xiami-stocks/site/current —— 只 pull + build 而不换目录,线上一点变化都没有。
#
# 这两件事都不该靠记忆。写进脚本,顺序和检查都固定下来。

set -euo pipefail

REPO=/srv/xiami-stocks/app
SITE=/srv/xiami-stocks/site
SERVICE=xiamimate-stocks

cd "$REPO"

echo "── 1/5 拉代码 ──────────────────────────────"
git pull --ff-only origin main
git --no-pager log --oneline -1

# 核验「这个提交跑过发布门禁」。逻辑在单独一支脚本里，那样测试能真跑它。
echo
bash deploy/check-gate.sh

echo
echo "── 2/5 同步 Python 依赖 ────────────────────"
# 用 pip install -e . 而不是逐个装:pyproject 是唯一真源,新增的依赖自动跟上。
cloud_mode=$(./.venv/bin/python - <<'PY'
from pathlib import Path
values = dict(line.split('=', 1) for line in Path('.env').read_text().splitlines()
              if '=' in line and not line.lstrip().startswith('#'))
print('1' if values.get('STOCK_ASSISTANT_WEB_MODE', '').strip() == 'cloud' else '0')
PY
)
if [ "$cloud_mode" = "1" ]; then
    ./.venv/bin/pip install -q -e '.[cloud-assistant]' 2>&1 | tail -3
    ./.venv/bin/python -c 'import lark_oapi, cryptography, qrcode; assert hasattr(lark_oapi, "register_app")'
else
    ./.venv/bin/pip install -q -e . 2>&1 | tail -3
fi
# **装完必须验一遍能不能 import。** pip 说安装成功、import 却失败是有的
# (架构不匹配、C 扩展缺系统库),而那种情况下功能照样静静地不工作。
./.venv/bin/python - <<'PY'
import importlib, re, sys
block = open("pyproject.toml", encoding="utf-8").read().split("dependencies = [", 1)[1].split("]", 1)[0]
deps = [ln.strip().strip(",").strip('"') for ln in block.splitlines() if ln.strip().startswith('"')]
alias = {"beautifulsoup4": "bs4", "python-dateutil": "dateutil", "pillow": "PIL",
         "psycopg2-binary": "psycopg2", "pyyaml": "yaml", "stock-sdk": "stock_sdk",
         "python-multipart": "multipart"}
missing = []
for dep in deps:
    name = re.split(r"[<>=!\[; ]", dep)[0]
    try:
        importlib.import_module(alias.get(name, name.replace("-", "_")))
    except Exception as exc:
        missing.append(f"{dep} → {type(exc).__name__}")
if missing:
    print("导入不了:", *missing, sep="\n  ")
    sys.exit(1)
print(f"{len(deps)} 个声明依赖全部可导入")
PY

echo
echo "── 3/5 构建前端 ────────────────────────────"
# **npm ci 只在仓库根跑。** 这是 workspaces,在 apps/web 里跑会把根依赖剪掉
# (stock-sdk 会消失)。依赖没动时连 ci 都不用跑。
if ! git diff --quiet HEAD@{1} HEAD -- package-lock.json package.json 2>/dev/null; then
    echo "package-lock 变了,重装依赖"
    npm ci
fi
# VITE_BASE 必须是 /stocks/ —— 线上是单域名路径分流,漏了这个变量,
# 产物里的资源路径会指向域名根,页面一片空白。
VITE_BASE=/stocks/ npm run build --workspace @xiamimate-stock-lab/web | tail -3
# **首屏预算是一道闸，不是一句提醒。** 有人在 App.tsx 顶部直接 import 一个
# 画图的组件，首屏就会多出六百多 kB —— 页面看着一切正常，只是慢，
# 而慢是没人会报的 bug。超了就别上线（scripts/check-bundle.mjs 里写了怎么改）。
node scripts/check-bundle.mjs apps/web/dist

echo
echo "── 4/5 换静态站 ────────────────────────────"
# Caddy 的根是 $SITE/current,不是仓库里的 dist。**换目录这一步不能省。**
STAMP=$(date +%Y%m%d-%H%M%S)
mv "$SITE/current" "$SITE/backup-$STAMP"
cp -r "$REPO/apps/web/dist" "$SITE/current"
echo "旧版本留在 $SITE/backup-$STAMP(回滚:mv 回 current)"

echo
echo "── 5/5 重启后端并自检 ──────────────────────"
systemctl restart "$SERVICE"
sleep 4
systemctl is-active "$SERVICE"
if [ "$cloud_mode" = "1" ]; then
    cp deploy/systemd/xiamimate-stock-assistant.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable xiamimate-stock-assistant
    systemctl restart xiamimate-stock-assistant
    sleep 3
    systemctl is-active xiamimate-stock-assistant
elif systemctl is-active --quiet xiamimate-stock-assistant; then
    systemctl stop xiamimate-stock-assistant
fi

# 从入口验,不是从后端端口验 —— 路径分流那一层出错时后端是好的,用户看到的却是白页。
for path in /stocks/ /stocks-api/health; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'Host: stocks.example.com' "http://127.0.0.1:8080$path")
    printf '  %-22s %s\n' "$path" "$code"
    [ "$code" = "200" ] || { echo "!! $path 不是 200,检查上面的日志"; exit 1; }
done
# 页面引的 js 必须是刚构建出来的那一份,否则说明第 4 步没生效。
served=$(curl -s --max-time 15 -H 'Host: stocks.example.com' http://127.0.0.1:8080/stocks/ | grep -oE 'assets/index-[A-Za-z0-9_-]+\.js')
built=$(grep -oE 'assets/index-[A-Za-z0-9_-]+\.js' "$REPO/apps/web/dist/index.html")
[ "$served" = "$built" ] || { echo "!! 线上还是旧产物:$served ≠ $built"; exit 1; }
echo "  线上产物 $served ✓"

echo
echo "上线完成。"
