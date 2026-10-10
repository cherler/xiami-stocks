# 虾米看股私人助理

飞书是对话入口，nanobot 负责理解问题和调用工具，虾米看股保存数据与执行纪律。
现有 earth-atlas 报告直接读取，用户不用再录一遍。

## 能做什么

- 「我的票」：读取观察池、候选池、已有逻辑、决策卡和持仓的并集。
- 「总结我对工业富联的研究」：搜索 earth-atlas 原文，读取日期与出处，按需补公司资料。
- 「工业富联现金流怎么了」：按问题读取财务序列、分部、估值、公告正文与原判断。
- 「我想买宁德，按我的计划核验」：执行核验返回原有规则的计算结果。
- 「我买了……」：提出成交登记，确认后保存；登记可以撤销，不改持仓股数。
- 「你还在盯吗」：查看扫描记录与提醒入队情况。

研究意见不会自动改写计划，也没有自动下单能力。报告中的历史价格必须带日期。
现在还没有把用户粘贴的报告自动存成决策卡的工具；助理必须说清“已整理”与“已入库”。

## 本机配置

验证版本：nanobot-ai 0.3.5，MiniMax-M3。框架源码保持原样。

```sh
uv tool install --python 3.12 nanobot-ai==0.3.5
.venv/bin/pip install -e '.[assistant]'
python3 apps/assistant/setup.py
nanobot plugins enable feishu
nanobot channels login feishu
apps/assistant/run-gateway.sh gateway --background
```

手机飞书扫码创建应用；第一次私聊取得配对码，在本机批准。
扫码后的 `channels.feishu` 可能是 `instances` 数组，安装器保留这一结构。

```sh
apps/assistant/run-gateway.sh agent -m '/pairing approve 配对码'
```

Mac 登录后自动启动：

```sh
python3 apps/assistant/install-service.py
```

登录服务为 `com.xiamimate.stock-assistant`，运行项目的启动脚本；密钥不写入服务配置。
服务安装后更新工具或规则：先运行 setup，再执行：

```sh
launchctl kickstart -k gui/$(id -u)/com.xiamimate.stock-assistant
```

虾米看股 API 要保持运行（127.0.0.1:8108）；Mac 关机或休眠时不能接收消息或盯盘。
nanobot 健康检查在 18790，管理界面在 18791（避开本机已经占用的 8765）。
服务日志在 `~/.nanobot/logs/stock-assistant.log`。

## 主动提醒

在已配对的飞书私聊发 `/trigger 虾米看股到价提醒` 可创建路由；
也可通过 nanobot 的 LocalTriggerStore 将路由绑定到已验证的私聊。
把返回的 ID 写进项目 `.env`：

```dotenv
STOCK_ASSISTANT_TRIGGER=你的触发器ID
STOCK_ASSISTANT_WATCH=true
```

API 启动时读取 WATCH 开关，开启后需重启 API。交易时段每 3 分钟扫描一次。
默认 earth-atlas 目录为兄弟项目 `earth-atlas/research`，可用 MCP 环境变量
`STOCK_RESEARCH_DIR` 指定替代目录。目录权限只开放这些 Markdown 与配套出处文件。

提醒流程为 API → nanobot 本地队列 → 飞书。`queued` 只表示入队，**不冒充已送达**。
当前股票库尚未回写 nanobot 的最终投递回执；排查最终状态查看 nanobot 的触发器运行记录
和飞书消息。初次接通时必须发明确标注的测试提醒并确认收到。

## 验证

```sh
.venv/bin/python -m pytest apps/api/tests/test_assistant.py apps/api/tests/test_assistant_research.py apps/api/tests/test_bands_from_valuation.py -q
```

验证用户隔离、价格触发去重、核验不改计划、提醒失败记录、研究原文分页与路径限制。
实机还需核对：MCP 连接、研究原文工具调用、飞书私聊回复、主动提醒收到。
