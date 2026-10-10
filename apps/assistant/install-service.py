"""Mac 登录后自动启动助理；密钥仍由启动脚本从项目 .env 读取。"""

import os
from pathlib import Path
import plistlib
import subprocess
import sys

if sys.platform != "darwin":
    raise SystemExit("这个安装器用于 macOS。")

here = Path(__file__).resolve().parent
label = "com.xiamimate.stock-assistant"
target = f"gui/{os.getuid()}/{label}"
folder = Path.home() / "Library" / "LaunchAgents"
folder.mkdir(parents=True, exist_ok=True)
path = folder / f"{label}.plist"
logs = Path.home() / ".nanobot" / "logs"
logs.mkdir(parents=True, exist_ok=True)
config = {
    "Label": label,
    "ProgramArguments": [str(here / "run-gateway.sh"), "gateway", "--foreground"],
    "WorkingDirectory": str(here.parents[1]),
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 20,
    "StandardOutPath": str(logs / "stock-assistant.log"),
    "StandardErrorPath": str(logs / "stock-assistant.error.log"),
}
path.write_bytes(plistlib.dumps(config))
path.chmod(0o600)
subprocess.run(["launchctl", "bootout", target], capture_output=True)
subprocess.run([str(here / "run-gateway.sh"), "gateway", "stop"], check=True)
subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
print("助理已设为登录 Mac 后自动启动；日志：", logs / "stock-assistant.log")
