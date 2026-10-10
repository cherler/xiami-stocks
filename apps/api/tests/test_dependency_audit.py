"""审计发现漏洞或无法连接时，发布检查必须失败。"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "audit-dependencies.sh"


def run_audit(tmp_path, mode, body):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(SCRIPT, scripts)
    executable = tmp_path / ("bin/npm" if mode == "frontend" else ".venv/bin/python")
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/usr/bin/env bash\n" + body)
    executable.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path / "bin") + os.pathsep + os.environ["PATH"]}
    return subprocess.run(["bash", str(scripts / SCRIPT.name), mode], env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("mode", ["frontend", "python"])
@pytest.mark.parametrize("message", ["2 vulnerabilities (1 moderate, 1 high)", "network unavailable"])
def test_failed_audit_stays_failed(tmp_path, mode, message):
    result = run_audit(tmp_path, mode, f"echo '{message}' >&2\nexit 1\n")
    assert result.returncode == 1
    assert message in result.stdout


@pytest.mark.parametrize("mode", ["frontend", "python"])
def test_clean_audit_passes(tmp_path, mode):
    assert run_audit(tmp_path, mode, "echo 'No known vulnerabilities'\nexit 0\n").returncode == 0


@pytest.mark.parametrize("fallback_status", [0, 1])
def test_mirror_fallback_preserves_official_registry_result(tmp_path, fallback_status):
    result = run_audit(tmp_path, "frontend", f'''if [[ "$1" == --registry=* ]]; then
echo 'official registry result'
exit {fallback_status}
fi
echo 'NOT_IMPLEMENTED audit endpoint returned an error'
exit 1
''')
    assert result.returncode == fallback_status
    assert "official registry result" in result.stdout
