#!/usr/bin/env bash
#
# 把后端从 root 降到专用账号。**在服务器上以 root 跑，幂等。**
#
#   ssh your-server 'bash /srv/xiami-stocks/app/deploy/harden-service.sh'
#
# ## 为什么单独一个脚本，而不是塞进 deploy.sh
#
# 这是**一次性的机器改造**（建用户、改属主、装 unit），不是每次发布都要做的事。
# 混进 deploy.sh 会让每次上线都带着一段“如果没有就创建”的逻辑，
# 而那种逻辑平时不跑、真跑的时候没人盯着。
#
# ## 顺序不能反
#
# unit 文件里写了 `User=xiamimate`。**用户不存在时 systemd 直接拒绝启动**——
# 那是一次实打实的停服。所以这里的次序是：建用户 → 铺权限 → 再装 unit → 重启 →
# 从入口验一遍。任何一步失败就停下，旧的 unit 还在原地，服务照常跑。
#
# ## 回滚
#
#   sudo sed -i '/^User=xiamimate$/d;/^Group=xiamimate$/d' /etc/systemd/system/xiamimate-stocks.service
#   sudo systemctl daemon-reload && sudo systemctl restart xiamimate-stocks

set -euo pipefail

USER_NAME=xiamimate
REPO=/srv/xiami-stocks/app
DATA=/srv/xiami-stocks/data
UNIT=/etc/systemd/system/xiamimate-stocks.service
SERVICE=xiamimate-stocks

[ "$(id -u)" = "0" ] || { echo "要用 root 跑"; exit 1; }

echo "── 1/5 建系统账号 ──────────────────────────"
if id "$USER_NAME" >/dev/null 2>&1; then
    echo "  $USER_NAME 已存在"
else
    # --system：不占普通用户 uid 段；不给家目录、不给登录 shell——
    # 这个账号只用来跑一个进程，能登录反而是多出来的攻击面。
    useradd --system --no-create-home --shell /usr/sbin/nologin "$USER_NAME"
    echo "  已建 $USER_NAME"
fi

echo
echo "── 2/5 数据目录交给它 ──────────────────────"
# **这是它唯一需要写的地方**：研究库（SQLite 形态时）与备份都落在这儿
# （backup.py 的 backup_dir() = database_path().parent / "backups"）。
mkdir -p "$DATA"
chown -R "$USER_NAME:$USER_NAME" "$DATA"
chmod 750 "$DATA"
ls -ld "$DATA"

echo
echo "── 3/5 .env 只让它读，别人读不到 ───────────"
# .env 里有 MINIMAX_API_KEY 和数据库口令。不改属主（部署仍以 root 写），
# 只把组给它并收掉 other 位：进程读得到，同机别的账号读不到。
if [ -f "$REPO/.env" ]; then
    chgrp "$USER_NAME" "$REPO/.env"
    chmod 640 "$REPO/.env"
    ls -l "$REPO/.env"
else
    echo "  !! 没找到 $REPO/.env —— 服务起来会缺配置，先确认这台机器是不是对的"
    exit 1
fi

echo
echo "── 4/5 装 unit ─────────────────────────────"
# 装之前先验一遍：unit 里写的用户必须已经存在（上面刚建过，这里是防止
# 有人改了 unit 里的名字却没改这个脚本）。
want=$(grep -E '^User=' "$REPO/deploy/systemd/xiamimate-stocks.service" | cut -d= -f2)
id "$want" >/dev/null 2>&1 || { echo "!! unit 里写的用户 $want 不存在，停"; exit 1; }
cp "$REPO/deploy/systemd/xiamimate-stocks.service" "$UNIT"
systemctl daemon-reload

echo
echo "── 5/5 重启并从入口验 ──────────────────────"
systemctl restart "$SERVICE"
sleep 4
systemctl is-active "$SERVICE"
systemctl show "$SERVICE" -p User -p Group

# **从入口验，不是从后端端口验**：权限不足时进程可能起来了但读不到 .env，
# 表现是接口 500 而不是服务挂掉。
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H 'Host: stocks.example.com' \
    'http://127.0.0.1:8080/stocks-api/health')
echo "  /stocks-api/health $code"
[ "$code" = "200" ] || { echo "!! 健康检查没过。回滚见本文件顶部的注释。"; exit 1; }

# 写权限也要当场验一次：备份目录建不出来的话，「立即备份」会在用户点下去
# 那一刻才报错——而那通常是他最需要它的时候。
sudo -u "$USER_NAME" test -w "$DATA" && echo "  $DATA 可写 ✓"

echo
echo "降权完成。进程现在跑在 $USER_NAME 上。"
