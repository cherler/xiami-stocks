"""把虾米看股助理装进本机的 nanobot。**可以重复跑**，改了规矩或配置就再跑一次。

    python3 apps/assistant/setup.py

做四件事：
1. 没有 nanobot 配置就先 `nanobot onboard` 建一份；
2. 往 ~/.nanobot/config.json 里写：模型（MiniMax）、工具权限、虾米看股的 MCP 工具；
3. 把 workspace/AGENTS.md（规矩）复制进 nanobot 的工作区；
4. 打印下一步（飞书扫码）。

## 为什么不改 nanobot 的源码

它几乎每天在更新。改了源码就等于分出一个自己的版本，以后每次升级都要手工合并，
助理又会变回负担。所以我们的东西全放在它外面，只走它留好的口子：配置、MCP、工作区文件。

## 权限为什么收这么紧

助理只需要两样东西：虾米看股的工具、联网搜索。**执行命令、读写文件、装命令行应用全关掉。**
它连着飞书和微信，任何一条进来的消息（包括它读到的公告原文）都可能夹带指令；
一个能在你电脑上执行命令的助理，被一句话骗动一次就够了。

## 密钥不进配置文件

配置里写的是 `${MINIMAX_API_KEY}` 这种占位，真值由 run-gateway.sh 在启动时从
虾米看股的 .env 读进环境变量。nanobot 的配置文件不进任何仓库，但也不该躺着明文密钥。
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NANOBOT_HOME = Path.home() / ".nanobot"
CONFIG = NANOBOT_HOME / "config.json"
WORKSPACE = NANOBOT_HOME / "workspace"
PINNED = "0.3.5"


def _nanobot() -> str:
    found = shutil.which("nanobot") or str(Path.home() / ".local" / "bin" / "nanobot")
    if not Path(found).exists():
        sys.exit(f"没找到 nanobot。先装（锁版本）：uv tool install --python 3.12 nanobot-ai=={PINNED}")
    version = subprocess.run([found, "--version"], capture_output=True, text=True).stdout.strip()
    if PINNED not in version:
        print(f"⚠ 装的是 {version}，验证过的是 {PINNED}。升级前先在这台机器上跑一遍 README 里的验收。")
    return found


def configure(config: dict) -> dict:
    defaults = config.setdefault("agents", {}).setdefault("defaults", {})
    defaults.update({
        "provider": "minimax_anthropic",
        "model": "MiniMax-M3",
        "modelPreset": None,
        "botName": "虾米",
        "botIcon": "🦐",
        "timezone": "Asia/Shanghai",
        # 飞书和微信是同一个人，共用一段对话：飞书上推的提醒，微信里回一句「核验」也接得上。
        "unifiedSession": True,
    })
    providers = config.setdefault("providers", {})
    providers.setdefault("minimaxAnthropic", {}).update({
        "apiKey": "${MINIMAX_API_KEY}",
        "apiBase": "https://api.minimaxi.com/anthropic",   # 大陆平台（minimaxi.com）
    })

    tools = config.setdefault("tools", {})
    tools.setdefault("exec", {})["enable"] = False
    tools.setdefault("file", {})["enable"] = False
    tools.setdefault("cliApps", {})["enable"] = False
    tools["restrictToWorkspace"] = True
    search = tools.setdefault("web", {}).setdefault("search", {})
    search.update({"provider": "tavily", "apiKey": "${TAVILY_API_KEY}"})
    tools.setdefault("mcpServers", {})["xiamimate"] = {
        "command": str(REPO / ".venv" / "bin" / "python"),
        "args": [str(HERE / "mcp_server.py")],
        "env": {"STOCK_API_BASE": "http://127.0.0.1:8108"},
        "toolTimeout": 60,
    }
    # 心跳关掉：「什么时候该开口」由虾米看股算（到价触发），不让模型每半小时自己琢磨一遍。
    config.setdefault("gateway", {}).setdefault("heartbeat", {})["enabled"] = False
    # 8765 在这台 Mac 上已有其他服务；使用单独端口，保留用户之后的自定义值。
    websocket = config.setdefault("channels", {}).setdefault("websocket", {})
    if websocket.get("port", 8765) == 8765:
        websocket["port"] = 18791
    return config


def install_workspace_files() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    # 规矩放 AGENTS.md：nanobot 的记忆整理会改写 SOUL.md / USER.md，但不碰 AGENTS.md。
    shutil.copyfile(HERE / "workspace" / "AGENTS.md", WORKSPACE / "AGENTS.md")
    # SOUL.md 只在还是出厂模板时换成我们的——它之后会被记忆整理慢慢改，别每次都抹掉。
    soul = WORKSPACE / "SOUL.md"
    if not soul.exists() or "I am nanobot" in soul.read_text(encoding="utf-8"):
        shutil.copyfile(HERE / "workspace" / "SOUL.md", soul)


def configure_bridge(config: dict, binary: str) -> bool:
    """Bind to the already-paired single-owner Feishu chat. Never guess a second user."""
    path = NANOBOT_HOME / "stock-assistant-bridge.json"
    workspace = Path(config.get("agents", {}).get("defaults", {}).get("workspace", str(WORKSPACE))).expanduser()
    try:
        pairing = json.loads((NANOBOT_HOME / "pairing.json").read_text())
        approved = pairing.get("approved", {}).get("feishu", [])
        triggers = json.loads((workspace / "triggers/triggers.json").read_text()).get("triggers", [])
    except (OSError, ValueError):
        print("助理写入尚未启用：先完成飞书配对与私聊提醒路由，再运行 setup。")
        return False
    routes = [t for t in triggers if t.get("enabled") and t.get("channel") == "feishu"]
    chats = {t.get("chatId") for t in routes if t.get("chatId")}
    if len(approved) != 1 or len(chats) != 1:
        print("助理写入尚未启用：需要唯一的已配对用户与私人飞书路由，不能自动选择多人中的一个。")
        return False
    current = json.loads(path.read_text()) if path.exists() else {}
    launcher = Path(binary).resolve().read_text().splitlines()[0]
    interpreter = launcher[2:] if launcher.startswith("#!/") else ""
    if not interpreter or not Path(interpreter).is_file():
        print("无法确定 nanobot 的 Python 环境，助理写入适配器未安装。")
        return False
    installer = shutil.which("uv")
    if not installer:
        print("需要 uv 将适配器安装到 nanobot 独立环境。")
        return False
    installed = subprocess.run([installer, "pip", "install", "--python", interpreter,
                                "--no-deps", "-e", str(HERE / "bridge")], capture_output=True, text=True)
    if installed.returncode:
        print("助理适配器安装失败，现有配置未改；检查 uv 安装环境。")
        return False
    current.update({"secret": current.get("secret") or secrets.token_hex(32),
                    "api_base": "http://127.0.0.1:8108", "channel": "feishu",
                    "chat_id": next(iter(chats)), "sender_ids": approved,
                    "workspace": str(workspace), "nanobot_python": interpreter})
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    print("✓ 助理写入已绑定到已有的私人飞书会话，密钥未输出")
    return True


def main() -> None:
    binary = _nanobot()
    if not CONFIG.exists():
        subprocess.run([binary, "onboard"], check=True, capture_output=True)
    config = configure(json.loads(CONFIG.read_text(encoding="utf-8")))
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    CONFIG.chmod(0o600)
    install_workspace_files()
    configure_bridge(config, binary)
    feishu = (config.get("channels") or {}).get("feishu") or {}
    print("✓ nanobot 已配好：MiniMax-M3、虾米看股工具、执行命令和读写文件已关")
    instances = feishu.get("instances", [feishu])
    if not any(instance.get("appId") for instance in instances):
        print("下一步：接飞书（扫码）\n    nanobot plugins enable feishu\n    nanobot channels login feishu")
    print(f"启动网关：{HERE / 'run-gateway.sh'}")


if __name__ == "__main__":
    main()
