"""The CI step that installs WeasyPrint's system libraries, run with apt stubbed.

``.github/workflows/ci.yml`` forgives exactly one apt failure: the install
cannot fetch a package because its mirror is unreachable, while Pango is
already on the runner. Everything else must fail the step. That is a claim
about shell code in a YAML file, so these tests cut the step out of the
workflow and run it — the text CI runs, not a copy — with ``sudo``,
``apt-get`` and ``dpkg`` replaced by stubs.

The "unreachable" output is what the runners printed on 2026-11-11, when
every job died in this step before any test ran.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
STEP_NAME = "Install WeasyPrint system libraries"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

UPDATE_OK = "Hit:1 http://azure.archive.ubuntu.com/ubuntu resolute InRelease\nReading package lists..."
UPDATE_MIRROR_DOWN = (
    "Err:5 https://security.ubuntu.com/ubuntu resolute-security InRelease\n"
    "  Temporary failure resolving 'archive.ubuntu.com'\n"
    "W: Failed to fetch mirror+file:/etc/apt/apt-mirrors.txt/dists/resolute/InRelease  "
    "Temporary failure resolving 'security.ubuntu.com'\n"
    "W: Some index files failed to download. They have been ignored, or old ones used instead."
)
#: Another source of the runner image is unreachable; the Ubuntu archive is fine.
UPDATE_OTHER_SOURCE_DOWN = (
    "Err:7 https://packages.microsoft.com/ubuntu/26.04/prod resolute InRelease\n"
    "  Could not connect to packages.microsoft.com:443 (13.82.67.141), connection timed out\n"
    "W: Failed to fetch https://packages.microsoft.com/ubuntu/26.04/prod/dists/resolute/InRelease  "
    "Could not connect to packages.microsoft.com:443\n"
    "W: Some index files failed to download. They have been ignored, or old ones used instead."
)
INSTALL_OK = "Setting up libharfbuzz-subset0:amd64 (12.3.2-2) ..."
INSTALL_MIRROR_DOWN = (
    "Err:2 https://security.ubuntu.com/ubuntu resolute/main amd64v3 libharfbuzz-subset0 amd64 12.3.2-2\n"
    "  Temporary failure resolving 'azure.archive.ubuntu.com'\n"
    "  Temporary failure resolving 'security.ubuntu.com'\n"
    "E: Failed to fetch https://security.ubuntu.com/ubuntu/pool/main/h/harfbuzz/"
    "libharfbuzz-subset0_12.3.2-2_amd64v3.deb  Temporary failure resolving 'security.ubuntu.com'\n"
    "E: Unable to fetch some archives, maybe run apt update or try with --fix-missing?"
)
INSTALL_PACKAGE_GONE = "E: Unable to locate package libharfbuzz-subset0"
INSTALL_BROKEN = (
    "dpkg: error processing package libharfbuzz-subset0:amd64 (--configure)\n"
    "E: Sub-process /usr/bin/dpkg returned an error code (1)"
)


def library_steps() -> list[str]:
    """The ``run`` script of every 'Install WeasyPrint system libraries' step."""
    text = CI.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"- name: {re.escape(STEP_NAME)}\n(?:[ ]+#.*\n)*[ ]+run: \|\n((?:[ ]{{10}}.*\n)+)")
    return [textwrap.dedent(block) for block in pattern.findall(text)]


def run_step(tmp_path: Path, *, update: tuple[int, str] = (0, UPDATE_OK),
             install: tuple[int, str] = (0, INSTALL_OK), pango: bool = True,
             ) -> subprocess.CompletedProcess[str]:
    """Run the step as the runner does (``bash -e``) with stubbed commands."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "update.out").write_text(update[1] + "\n", encoding="utf-8")
    (tmp_path / "install.out").write_text(install[1] + "\n", encoding="utf-8")
    stubs = {
        "sudo": 'exec "$@"\n',
        "apt-get": (
            f'echo "$1" >> "{tmp_path}/calls"\n'
            f'case "$1" in\n'
            f'  update) cat "{tmp_path}/update.out"; exit {update[0]} ;;\n'
            f'  install) cat "{tmp_path}/install.out"; exit {install[0]} ;;\n'
            f'esac\nexit 2\n'
        ),
        "dpkg": "exit 0\n" if pango else 'echo "dpkg-query: package is not installed" >&2\nexit 1\n',
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(library_steps()[0], encoding="utf-8")
    env = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin", "RUNNER_TEMP": str(tmp_path)}
    return subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True,
                          timeout=60)


def calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls").read_text(encoding="utf-8").split()


def test_both_jobs_run_the_same_step() -> None:
    steps = library_steps()
    assert len(steps) == 2, "the 'test' and the 'minimum' job each install the libraries"
    assert steps[0] == steps[1]
    assert "apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0\n" in steps[0]


def test_a_working_mirror_installs_and_says_nothing(tmp_path: Path) -> None:
    result = run_step(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::" not in result.stdout and "::error::" not in result.stdout
    assert calls(tmp_path) == ["update", "install"]


def test_an_unreachable_mirror_is_a_warning_when_pango_is_there(tmp_path: Path) -> None:
    result = run_step(tmp_path, update=(0, UPDATE_MIRROR_DOWN), install=(100, INSTALL_MIRROR_DOWN))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::The package mirror could not be reached" in result.stdout
    assert "::error::" not in result.stdout


def test_an_unreachable_mirror_fails_without_pango(tmp_path: Path) -> None:
    result = run_step(tmp_path, update=(0, UPDATE_MIRROR_DOWN),
                      install=(100, INSTALL_MIRROR_DOWN), pango=False)
    assert result.returncode != 0


@pytest.mark.parametrize("output", [INSTALL_PACKAGE_GONE, INSTALL_BROKEN],
                         ids=["package-gone", "broken-install"])
def test_any_other_install_failure_fails(tmp_path: Path, output: str) -> None:
    result = run_step(tmp_path, install=(100, output))
    assert result.returncode != 0
    assert "::error::" in result.stdout and "::warning::" not in result.stdout


@pytest.mark.parametrize("update", [UPDATE_OTHER_SOURCE_DOWN, UPDATE_MIRROR_DOWN],
                         ids=["another-source-down", "mirror-down"])
def test_what_update_printed_does_not_excuse_an_install_failure(tmp_path: Path, update: str) -> None:
    """An unreachable host in the output of 'apt-get update' must not turn a
    real install error into a warning: only the install's own error counts."""
    result = run_step(tmp_path, update=(0, update), install=(100, INSTALL_PACKAGE_GONE))
    assert result.returncode != 0
    assert "::error::" in result.stdout and "::warning::" not in result.stdout


def test_a_failing_update_fails_the_step_before_the_install(tmp_path: Path) -> None:
    result = run_step(tmp_path, update=(100, "E: The repository does not have a Release file."))
    assert result.returncode != 0
    assert calls(tmp_path) == ["update"]


def test_the_step_is_run_under_errexit_as_on_the_runner() -> None:
    # GitHub runs a step's script with 'bash -e'; the script adds pipefail itself,
    # or the pipe into tee would hide apt's exit status
    assert "set -o pipefail" in library_steps()[0]
