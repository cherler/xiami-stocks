# 虾米看股私人助理

网页右上角“问助手”和飞书都是入口，nanobot 理解自然语言，虾米看股保存研究、计算规则和检查变化。
用户不用学“看、记、盯、核”口令，也不用把聊天结果重新填进网页。

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
