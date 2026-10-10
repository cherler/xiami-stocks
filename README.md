# 虾米看股 · 长期研究工作台

记下关注一家公司的理由，跟踪财务、估值与后续变化。

[在线使用](https://xiamimate.com/stocks/) · [助理接入说明](apps/assistant/README.md) · [产品文档](docs/PRODUCT.md)

## 当前功能

- **公司研究**：A 股行情、财务序列、公告与证据，保留判断及修改记录。
- **找票与对比**：条件筛选、市场云图、产业链地图与同环节公司比较。
- **估值与执行记录**：分层估值、价格区间、决策闭环、成交登记、持仓账本与纪律复盘。
- **行情分析**：涨跌归因、做 T 回测；数据缺失时明确展示缺口。
- **私人助理（可选）**：通过 MCP 接入 nanobot 与飞书，读取研究、核验已有计划、发送配置好的价格提醒。研究文件可以从本地目录读取，无需复制录入。
- **数据管理**：SQLite 单机模式、PostgreSQL 后端、备份恢复和用户数据隔离。

助理接入、飞书应用和主动提醒需要另行配置；代码同步并不代表这些服务已在你的机器上启用。本项目没有券商下单功能。

## 本地运行

需要 **Node.js 22+、Python 3.10+**。可选 nanobot 助理的安装使用 Python 3.12，见独立说明。

```sh
git clone https://github.com/cherler/xiami-stocks.git
cd xiami-stocks
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci
cp .env.example .env
npm run dev
```

打开 **http://127.0.0.1:5217/**。API 在 `http://127.0.0.1:8108`，接口文档在 `/docs`。

默认使用 SQLite，数据写入 `var/stock_decision.db`。单机运行不依赖虾米伙伴主站；`.env` 中 `XM_API_BASE` 留空即可。模型功能需要配置自己的模型密钥，行情、财务等数据同步需要联网，数据源可能出现限流或缺项。

可分别启动两端：

```sh
npm run dev:api
npm run dev:web
```

## 可选：飞书研究助理

按 [apps/assistant/README.md](apps/assistant/README.md) 配置模型、MCP、飞书配对与提醒。

默认读取兄弟目录 `earth-atlas/research`，也可通过 `STOCK_RESEARCH_DIR` 指定自己的研究目录。仓库不包含个人研究文件、账户凭据或持仓数据库。本机助理依赖电脑与 API 持续运行。

## 验证

```sh
# 单机后端测试（临时数据库）
STOCK_TEST_SQLITE=1 .venv/bin/python -m pytest -q

# 前端测试、类型检查与构建
npm run test:web
npm run build
node scripts/check-bundle.mjs apps/web/dist
```

默认后端测试使用 PostgreSQL，需要另外准备测试数据库连接和可创建测试角色的管理员账号。完整发布检查见 `scripts/release-check.sh`；检查脚本也会核验依赖漏洞与构建预算。

## 部署

`deploy/` 提供 systemd、Caddy 和发布检查模板，默认示例目录为 `/srv/xiami-stocks/`，示例域名为 `stocks.example.com`。部署前按自己的服务器修改这些模板，并配置 `.env.production.example` 中的账号和数据库连接。

这些模板沿用虾米伙伴的 `/stocks/` 挂载方式及登录服务集成，**不是独立服务器的一键安装器**。本地单机运行使用上面的快速开始即可。已有服务器发布前需要完成依赖安装、服务账号与目录初始化，并通过发布检查。

```sh
VITE_BASE=/stocks/ npm run build
```

不要把本地开放访问模式直接暴露到公网；对外服务应配置访问控制。

## 同步与许可

本次开源快照更新于 **2026-10-10**，包含当前应用代码、测试和助理接口。开源仓库保留独立提交历史；部署地址采用示例值，不包含运行配置、密钥、数据库或个人研究资料。`docs/` 与 `wiki/` 的早期设计记录可能落后于当前实现，以代码和本 README 的运行方式为准。

采用 [GNU AGPL-3.0](LICENSE)。研究工具不构成投资建议。
