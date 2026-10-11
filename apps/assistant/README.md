# 虾米看股私人助理

网页右上角“问助手”和飞书都是入口，nanobot 理解自然语言，虾米看股保存研究、计算规则和检查变化。
用户不用学“看、记、盯、核”口令，也不用把聊天结果重新填进网页。

## 线上入口与本地助手

线上“问助手”提供安装与飞书接入指引，用户在自己的电脑运行自己的助手。
已有的本地飞书绑定继续有效，无需重新绑定。新用户连接自己的飞书应用并完成私聊配对。
线上与本地数据库不会自动同步；本地网页与该电脑的飞书助手共用本地研究资料。

共享网站部署请设置环境变量 `STOCK_ASSISTANT_WEB_MODE=guide` 并重启 API。
此模式只返回公开指引，关闭网页聊天、聊天记录和飞书绑定接口，不读取站主的助手配置。
本地不设置该变量即可维持原来的聊天与飞书功能。

## 第一版能做什么

| 直接说 | 实际行为 |
|---|---|
| 我的票怎么样 | 查观察池、持仓、判断、随手记和主动跟踪的并集 |
| 海光信心最近怎么样 | 名称纠错候选；代码不做模糊替换，写入有歧义时先问 |
| 工业富联这段想法帮我记下来 | 保存到公司档案的研究报告，带整理正文与用户原话 |
| 我刚才说错了，改成…… | 追加修订、保留旧版；可以撤销，网页同步可见 |
| 它跟上次比呢 | 按当前会话公司，比较上次查阅后库内财报与公告的变化，并读原判断 |
| 宁德到270元以下提醒我 | 单独保存价格条件，不修改买入计划；支持暂停、恢复和改价 |
| 帮我盯工业富联的新财报和公告，我主要关心现金流 | 建立资料基线，有新内容才提醒，附当初关注理由 |
| 我想买宁德，按我的计划核验 | 沿用原有核验计算，不把“符合计划”翻译成可以买 |
| 我买了…… | 显示成交草稿；本人回复“确认”后登记，可撤销，不改持仓 |

第一次对比会建立基线，不会声称“没有变化”。研究跟踪以已经同步进股票库的数据为准，
当前推送的是“新资料 + 原关注点”，不自动判定投资逻辑成立或失效。
粘贴报告正文可以保存；图片/文件的完整识别与自动导入不在本次实现范围。

## 网页使用

右上角 **问助手** 打开聊天侧栏，不需要跳出正在看的页面。
在公司档案里打开，会自动带上当前公司，也可以点“清除”。用户明确说出的公司优先。

- 消息在服务端保存。关闭侧栏后处理继续，重新打开可看结果；最近 60 条在网页展示。
- 保存研究后显示实际回执和“查看公司记录”，公司资料随之更新；原有飞书记录继续可读。
- 断线会显示结果尚未确认，避免把已经执行的写入当成没发生而自动重做。
- 下方“连接飞书 / 接入与帮助”展开三步引导：打开 nanobot 管理页扫码连接、批准私聊配对，
  在机器人私聊发送 `/trigger 虾米看股到价提醒`，回网页点“完成飞书绑定”。
  只接受唯一的已批准用户与路由，不自动替换已有的不同绑定；已有绑定无需重新扫码。
- 网页展示网页消息，飞书展示飞书消息；两边共用助手及股票研究数据，不承诺镜像显示两边全部聊天记录。

这版供本机主人使用。多人网站的其他用户不能调用站主的模型或读取私人聊天。
本机运行虾米看股和助手后可用；安装只需做一次，不需要在网页填写模型密钥。

网页 API 通过 `web_chat.py` 调用现有 nanobot WebUI WebSocket，不修改上游。
API 持有连接身份与令牌，浏览器只拿消息和状态；可信写入另核验数据库中的原始消息。
`assistant_web_messages` 有用户域过滤与 PostgreSQL RLS。原话、公司背景、回复、失败状态和动作回执分别保存。
网关中断或 API 重启后的长任务不会自动重放；过期未完成记录会标成中断，需要先核对写入回执。

## 架构

- 读取与研究：`apps/assistant/mcp_server.py`，只读 MCP 工具。
- 理解方式：`workspace/AGENTS.md`，自然输入、代词、改口、复合意图和少打扰规则。
- 可信写入：`bridge/` 是 nanobot 官方外部工具入口的轻量插件，工具名 `stock_assistant`。
  它从框架 `RequestContext` 取得真实发送人、会话、消息编号和原话并签名，模型不能提供这些字段。
- 执行：API `assistant_agent.py`。动作、修订、偏好和条件落库，重启后继续；同一消息重试不重复保存。
- 提醒：`assistant.py` 检查条件，`assistant_delivery.py` + `delivery.py` 用现有飞书应用直接发送计算好的文本，
  不经过模型改写。保存平台消息回执，稳定 UUID 去重，失败退避重试，超过重试窗口停止自动重发。
- 数据：沿用 `research_reports`、`decision_fills`；新增 `assistant_actions`、`assistant_memory`、
  `assistant_subscriptions`，三张表均有 PostgreSQL 行级隔离。

不修改 nanobot 上游源码。官方工具入口只负责补上 stdio MCP 没有的可信消息上下文；
研究查询仍走 MCP，换框架时股票规则和数据不需要重写。

## 安装 / 更新

验证运行环境：nanobot-ai 0.3.5，MiniMax-M3；API 在 127.0.0.1:8108。

```sh
uv tool install --python 3.12 nanobot-ai==0.3.5
.venv/bin/pip install -e '.[assistant]'
python3 apps/assistant/setup.py
```

安装器配置模型与 MCP、关闭 shell/任意文件/CLI 工具、更新工作区规则；
安装器将 `bridge/` 安装到 nanobot 独立 Python 环境，先接通网页；
已有唯一的飞书配对用户和私聊路由时，同时保留飞书绑定。创建权限 0600 的 `~/.nanobot/stock-assistant-bridge.json`。
其中签名密钥和用户绑定不进仓库，不会打印。多用户/多私聊不自动猜选。

首次接入先完成飞书配对和路由，再运行一次安装器：

```sh
nanobot plugins enable feishu
nanobot channels login feishu
apps/assistant/run-gateway.sh gateway --background
apps/assistant/run-gateway.sh agent -m '/pairing approve 配对码'
```

在已配对的飞书私聊发 `/trigger 虾米看股到价提醒`，把路由 ID 配进项目 `.env`：

```dotenv
STOCK_ASSISTANT_TRIGGER=你的触发器ID
STOCK_ASSISTANT_WATCH=true
```

新版本在完整 bridge 配置下直接取得飞书投递回执；未安装 bridge 的旧运行环境仍走原 trigger 队列，
`queued` 只表示入队，不能冒充送达。`sent` 表示飞书平台返回成功消息编号，不代表用户已读。

更新结构和工具后重启 API 及助手：

```sh
launchctl kickstart -k gui/$(id -u)/com.xiamimate.stock-assistant
```

助理健康检查 18790，管理界面 18791。Mac 登录后自启用 `python3 apps/assistant/install-service.py`。
本机或 API 关闭、休眠时仍不能工作；这版没有迁移到全天在线服务器。
交易时段刷新行情，每3分钟检查；非交易时段继续检查库内研究变化和提醒状态。

## 边界

- 随手记是个人研究记录，不擅自变成正式交易规则；偏好也不覆盖计划和持仓。
- 成交草稿15分钟有效；新草稿使旧草稿失效；确认前计划被网页修改，要求重新核对。
- 绑定私聊、主人网页里的真实用户消息才能确认；触发器、其他人、CLI 和模型不能代确认。
- 成交登记与撤销只影响 `decision_fills`，不下单、不改持仓。
- 到价回差避免门槛附近反复提醒。同一轮同一公司的研究与自定义价格提醒合并。
- 暂停或改价会移除尚未发送的旧提醒；同条消息内其他有效跟踪保留。已交给飞书发送的消息无法撤回。
- 动作和草稿持久化不等于所有长篇模型研究都可断点续写；模型会话恢复沿用 nanobot。
- 研究资料中的指令没有授权效力；数值和证券代码不自动补零、改小数点或模糊替换。

## 验证

```sh
.venv/bin/python -m pytest apps/api/tests/test_assistant_web.py apps/api/tests/test_assistant_agent.py apps/api/tests/test_assistant.py apps/api/tests/test_assistant_research.py apps/api/tests/test_decision_board_order.py -q
STOCK_TEST_SQLITE=1 .venv/bin/python -m pytest apps/api/tests/test_assistant_web.py apps/api/tests/test_assistant_agent.py apps/api/tests/test_assistant.py apps/api/tests/test_assistant_research.py -q
```

适配器和投递测试（用 nanobot 环境的 Python；不发送真实飞书消息）：

```sh
PYTHONPATH=apps/assistant/bridge ~/.local/share/uv/tools/nanobot-ai/bin/python -m unittest discover -s apps/assistant/bridge/tests -v
```

覆盖身份签名、用户隔离、模型不能代确认、改口/过期/计划变更、并发去重、网页可见、撤销修订、
数值不乱改、价格回差、研究增量、投递回执与稳定重试编号。
真实自然语言理解仍需在飞书试用：普通错字、含糊代词、复杂否定和截图识别不能仅凭这些程序测试宣称完全正确。

## 云端托管助手

`STOCK_ASSISTANT_WEB_MODE=cloud` 启用共享服务。网页登录账户决定数据归属；飞书扫码创建应用、回到网页确认后，只有飞书返回的应用创建者能发起私聊。没有“首个发消息的人认领账户”的入口。网页和飞书消息进入同一持久队列、共享本人聊天历史和研究档案。本地 `local` 模式与 nanobot 配置保持独立。

部署前在服务器生成 `STOCK_CLOUD_ENCRYPTION_KEY`（Fernet），保存进受保护的 `.env` 并备份。此密钥用于加密飞书应用密钥，不能轮换后丢弃旧密钥。不要将密钥、应用凭据或生产数据提交到仓库。

运行 `python -m stock_decision.assistant_cloud_worker`；生产使用 `deploy/systemd/xiamimate-stock-assistant.service`。必须使用 PostgreSQL 且强制行级隔离有效，否则拒绝启动。网页 API 只入队，独立 worker 运行模型，不启动每用户一套 nanobot。飞书使用同一事件循环上的轻量连接。

默认限制：全站同时处理 2 条消息、排队最多 64 条；每用户同时 1 条、滚动 24 小时最多 60 条。每天按北京时间限制全站 200 万、每用户 20 万模型 token。调用前预留保守用量，成功后按真实用量退回差额；不明用量不退。积分服务不可达、拒绝或未识别用户时不调用模型，不转记到站主账户。token 上限不是人民币报价。

扫码注册最多同时 2 个，使用异步请求，3 分钟超时；用户断开时取消旧请求，不长时间占用模型线程池。忙时明确提示稍后再接入，网页聊天不受扫码排队影响。网页对话空闲时降低刷新频率，避免大量空轮询。

单条消息最多 12000 字、4 轮模型调用，每轮最多 4 个工具，最多 1600 个输出 token。仅开放股票业务白名单工具，不提供文件系统、任意网络、终端或通用 MCP。行情与财报共用现有缓存；到价检查统一刷新去重后的股票代码，无须每用户重复请求。

服务配置 1 核 CPU 配额、1.5GB 内存软限制、2GB 硬限制，优先终止助手而非网页；仍与网页共享数据库和磁盘，应监控网页响应。队列和原文持久保存，重启后只恢复排队任务；运行中任务标为中断，不自动重放写入。聊天保留 90 天，已存公司研究不随聊天清理。应用凭据不进入用户研究导出。投递失败最多重试 5 次，网页保留回答。

升级飞书 SDK 时必须复查 `assistant_cloud_feishu.Connections`：SDK 1.7.3 的公开 `start()` 自行管理事件循环，本实现固定版本并适配其异步连接方法，以共享传输循环。扫码注册来自[飞书官方 SDK](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/README.zh.md#一键创建应用)；企业管理员审批可能增加接入步骤。当前云端飞书入口处理文字，图片、文件不作为已支持功能宣传。

停用：将 `STOCK_ASSISTANT_WEB_MODE` 改回 `guide`，停止 `xiamimate-stock-assistant` 并重启网页 API。不要删除云端绑定密钥和资料。本地私人助手不需要任何配置变更。
