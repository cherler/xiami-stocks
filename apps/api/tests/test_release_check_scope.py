"""门禁自己那条「这次要跑哪几步」的判定，也要被测。

## 为什么专门测它

后端两个套件要十七分钟，前端那几步十几秒。`--auto` 按改动范围跳过后端，
**而这个判定错一次的代价是不对称的**：

  判成"全套"而其实只改了前端  → 多等十七分钟，烦
  判成"只跑前端"而后端改了    → 给你一份少跑两个套件的「全过」

后者是这支脚本存在的全部理由的反面。所以它不能只靠"我在终端里试了一下" ——
我试的那两次都是错的：一次 zsh 不做词分割（两个文件被当成一行），
一次 grep 被 shell 函数遮成了 ugrep。**验证方式本身出错，比被验的代码出错更隐蔽。**

判定通过 `bash scripts/release-check.sh --scope-of` 暴露出来（读 stdin 的文件清单，
打印 web 或 full），这里喂真实的文件名组合去对。
"""

from __future__ import annotations

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "release-check.sh"


def scope_of(paths: list[str]) -> str:
    done = subprocess.run(
        ["bash", str(SCRIPT), "--scope-of"],
        input="".join(f"{p}\n" for p in paths),
        capture_output=True, text=True, check=True, cwd=str(ROOT))
    return done.stdout.strip()


def test_only_web_changes_may_skip_the_backend():
    assert scope_of(["apps/web/src/styles.css"]) == "web"
    assert scope_of(["apps/web/src/styles.css", "apps/web/src/App.tsx",
                     "apps/web/src/components/Documents.tsx"]) == "web"


def test_anything_outside_apps_web_forces_the_full_run():
    """**一个后端文件就够了。** 判错这一格就是发一份少跑两个套件的「全过」。"""
    assert scope_of(["apps/api/stock_decision/main.py"]) == "full"
    # 混着改是最常见的一种，也是第一版判错的那一种
    assert scope_of(["apps/web/src/styles.css", "apps/api/stock_decision/main.py"]) == "full"
    assert scope_of(["apps/api/tests/test_x.py", "apps/web/src/App.tsx"]) == "full"
    # 门禁脚本、部署脚本、依赖清单——都不在 apps/web 里，一律全套
    for outsider in ("scripts/release-check.sh", "deploy/deploy.sh",
                     "pyproject.toml", "package.json", "apps/api/tests/conftest.py"):
        assert scope_of(["apps/web/src/App.tsx", outsider]) == "full", outsider


def test_the_web_prefix_is_matched_as_a_path_not_a_substring():
    """`apps/webhooks/` 不是 `apps/web/`。前缀判定要认路径分隔符。"""
    assert scope_of(["apps/webhooks/handler.py"]) == "full"
    assert scope_of(["docs/apps/web/note.md"]) == "full"
