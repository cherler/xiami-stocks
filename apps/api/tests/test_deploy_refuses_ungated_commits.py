"""上线之前必须核验门禁凭据。

**门禁在开发机上跑，部署在服务器上跑** —— 服务器没法知道你跑没跑过，
原来全靠"我记得跑"。现在 release-check.sh 过了会在提交上盖一个 git note，
deploy.sh 调 deploy/check-gate.sh 核验它。

这几条**真跑那支脚本**，在临时 git 仓里造出三种局面：没凭据、有凭据、
显式放行。不 grep 源码 —— 源码里有那几行，证明不了它真会拦住人。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GATE = REPO / "deploy" / "check-gate.sh"
STAMP = REPO / "scripts" / "stamp-gate.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    """一个有一个提交、没有 origin 的空仓。fetch 会失败，正是服务器上拉不到凭据那种局面。

    建在 tmp_path 的子目录里 —— 裸仓要建在它**外面**，
    否则裸仓自己成了工作区里的未跟踪文件，凭据就永远因"工作区脏"盖不上。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    tmp_path = repo
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "一个提交")
    return tmp_path


def _run(cwd: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **env_extra}
    return subprocess.run(
        ["bash", str(GATE)], cwd=cwd, capture_output=True, text=True, env=env
    )


def test_没有凭据就不给上线(scratch: Path) -> None:
    r = _run(scratch)
    assert r.returncode != 0, f"没盖凭据居然放行了：\n{r.stdout}"
    # 拦住之后要说清楚怎么办，否则人只会去找绕过的办法。
    assert "release-check.sh" in r.stdout


def test_盖了凭据就放行并原样打印它跑的是哪一档(scratch: Path) -> None:
    _git(scratch, "notes", "--ref=release-check", "add", "-m",
         "门禁通过｜仅前端（--auto 判定只动了 apps/web）｜2026-08-18 10:00:00", "HEAD")
    r = _run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    # "跳过了两个后端套件的全过"跟"真的全过"是两件事，档位必须原样透出来。
    assert "仅前端" in r.stdout


def test_凭据认的是提交_不是这个仓跑过就算(scratch: Path) -> None:
    """老提交上的凭据不能替新提交背书 —— 那正是我原来先跑门禁再提交的错法。"""
    _git(scratch, "notes", "--ref=release-check", "add", "-m", "门禁通过｜全套", "HEAD")
    (scratch / "b.txt").write_text("y")
    _git(scratch, "add", "-A")
    _git(scratch, "commit", "-qm", "门禁跑完之后又改的")
    r = _run(scratch)
    assert r.returncode != 0, f"上一个提交的凭据被拿来给新提交背书了：\n{r.stdout}"


def test_可以显式放行_但日志里留一行(scratch: Path) -> None:
    """回滚和救火要能上线。但绕过必须是显式的，而且事后看得出是谁绕的。"""
    r = _run(scratch, SKIP_GATE_CHECK="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP_GATE_CHECK" in r.stdout


def test_部署脚本真的调了它() -> None:
    # 只认**真会执行**的那一行。第一版写的是 `"deploy/check-gate.sh" in body`，
    # 我把那行注释掉之后这条测试照样绿 —— 注释里的字面量把它骗过去了。
    lines = (REPO / "deploy" / "deploy.sh").read_text().splitlines()
    code = [(i, ln) for i, ln in enumerate(lines) if not ln.lstrip().startswith("#")]

    def line_of(needle: str) -> int:
        for i, ln in code:
            if needle in ln:
                return i
        raise AssertionError(f"deploy.sh 里没有会执行的 `{needle}`")

    gate = line_of("deploy/check-gate.sh")   # 没有就直接抛，凭据是摆设
    # 必须在拉完代码之后 —— 拉之前 HEAD 还是上一版，核验的是错的提交。
    assert line_of("git pull") < gate
    # 也必须在装依赖、换目录、重启之前 —— 拦要拦在动线上环境之前。
    assert gate < line_of("pip install")


# ── 盖凭据那一头 ────────────────────────────────────────────────────
#
# 这几条也真跑 scripts/stamp-gate.sh。第一版盖凭据的代码写在 release-check.sh
# 末尾，要跑到它得先等十五分钟的全套测试 —— 于是它成了整支脚本里唯一没人验过
# 的一段，上线那天当场炸（`$scope｜` 里全角竖线的首字节被 bash 吃进了变量名，
# `set -u` 把脚本打断：七项全过、凭据没盖，而外层的 `| tail` 吞了退出码）。


def _stamp(cwd: Path, scope: str = "全套") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(STAMP), scope], cwd=cwd, capture_output=True, text=True
    )


@pytest.fixture()
def with_remote(scratch: Path, tmp_path: Path) -> Path:
    """给 scratch 接一个裸仓当 origin —— 凭据要推得上去才算数。"""
    bare = tmp_path / "origin.git"          # scratch 是 tmp_path/repo，裸仓在它旁边
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(scratch, "remote", "add", "origin", str(bare))
    _git(scratch, "push", "-q", "origin", "main")
    return scratch


def test_盖完凭据之后核验就能过(with_remote: Path) -> None:
    """两支脚本要对得上 —— 分开写最容易出的错就是各说各话。"""
    r = _stamp(with_remote, "全套")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "并推送" in r.stdout, r.stdout
    g = _run(with_remote)
    assert g.returncode == 0, g.stdout + g.stderr
    assert "全套" in g.stdout


def test_档位原样写进凭据(with_remote: Path) -> None:
    """"跳过了两个后端套件的全过"跟"真的全过"是两件事，核验那头要看得见。"""
    _stamp(with_remote, "仅前端（--auto 判定只动了 apps/web）")
    assert "仅前端" in _run(with_remote).stdout


def test_档位里的全角标点不会把脚本打断(with_remote: Path) -> None:
    """就是上线那天炸的那一下：全角字符的首字节被 bash 读进了变量名。"""
    r = _stamp(with_remote, "全套，跳过 SQLite（--fast）｜带全角竖线")
    assert r.returncode == 0, f"盖凭据被打断了：\n{r.stdout}\n{r.stderr}"
    assert "unbound variable" not in r.stderr, r.stderr
    assert "带全角竖线" in _run(with_remote).stdout


def test_工作区脏就不盖凭据(with_remote: Path) -> None:
    """凭据是给某一个提交的。工作区脏 = 跑的东西不对应任何提交。"""
    (with_remote / "c.txt").write_text("z")
    r = _stamp(with_remote)
    assert r.returncode == 0            # 不是失败，只是不盖
    assert "没有盖凭据" in r.stdout
    assert _run(with_remote).returncode != 0, "工作区脏的时候居然盖上了"


def test_推不上去要说出来_不能当成盖好了(scratch: Path) -> None:
    """服务器拉的是远端的 notes。只盖在本地等于没盖，不能报"已推送"。"""
    r = _stamp(scratch)                 # scratch 没有 origin
    assert "没推上去" in r.stdout, r.stdout
    assert "并推送" not in r.stdout


def test_门禁真的调了盖凭据() -> None:
    lines = (REPO / "scripts" / "release-check.sh").read_text().splitlines()
    code = [ln for ln in lines if not ln.lstrip().startswith("#")]
    assert any("scripts/stamp-gate.sh" in ln for ln in code), "门禁过了不盖凭据，等于没有凭据"
    # 必须在"有没有失败"判完之后 —— 否则没过也会盖。
    body = "\n".join(code)
    assert body.index("别上线") < body.index("scripts/stamp-gate.sh")
