from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


WORKSPACE = Path(__file__).resolve().parents[1]
BASH_PATH = shutil.which("bash")
DOCKER_PATH = shutil.which("docker")


def _require_bash() -> str:
    if BASH_PATH is None:
        pytest.skip("Bash is required for installer tests")
    result = subprocess.run(
        [BASH_PATH, "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Bash is required for installer tests")
    return BASH_PATH


def _require_docker() -> str:
    if DOCKER_PATH is None:
        pytest.skip("Docker is required for installer tests")
    return DOCKER_PATH


def _copy_installer_fixture(tmp_path: Path) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shutil.copy2(WORKSPACE / "install.sh", project_dir / "install.sh")
    shutil.copy2(WORKSPACE / ".env.example", project_dir / ".env.example")
    (project_dir / "install.sh").chmod(0o755)
    (project_dir / "data").mkdir()
    (project_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  envtest:\n"
        "    image: alpine\n"
        "    environment:\n"
        "      TWITCH_CLIENT_ID: ${TWITCH_CLIENT_ID}\n"
        "      TWITCH_CLIENT_SECRET: ${TWITCH_CLIENT_SECRET}\n"
        "      ADMIN_USERNAME: ${ADMIN_USERNAME}\n"
        "      ADMIN_PASSWORD: ${ADMIN_PASSWORD}\n",
        encoding="utf-8",
    )
    docker_bin = project_dir / "bin"
    docker_bin.mkdir()
    docker_stub = docker_bin / "docker"
    docker_stub.write_text(
        "#!/usr/bin/env sh\n"
        "if [ \"$1\" = \"compose\" ] && [ \"$2\" = \"version\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"compose\" ] && [ \"$2\" = \"up\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    return project_dir


def _run_install(project_dir: Path, user_input: str) -> subprocess.CompletedProcess[str]:
    bash_path = _require_bash()
    env = os.environ.copy()
    env["PATH"] = f"{project_dir / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(project_dir / "home")
    env["USERPROFILE"] = str(project_dir / "home")
    Path(env["HOME"]).mkdir(exist_ok=True)
    return subprocess.run(
        [bash_path, "--noprofile", "--norc", "./install.sh"],
        cwd=project_dir,
        input=user_input,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _compose_environment(project_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    docker_config = project_dir / ".docker-config"
    docker_config.mkdir(exist_ok=True)
    env["DOCKER_CONFIG"] = str(docker_config)
    return env


def _load_compose_environment(project_dir: Path) -> dict[str, str]:
    docker_path = _require_docker()
    parse_result = subprocess.run(
        [docker_path, "compose", "config", "--format", "json"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        env=_compose_environment(project_dir),
        check=False,
    )
    assert parse_result.returncode == 0, parse_result.stderr + parse_result.stdout
    json.loads(parse_result.stdout)

    environment_result = subprocess.run(
        [docker_path, "compose", "config", "--environment"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        env=_compose_environment(project_dir),
        check=False,
    )
    assert environment_result.returncode == 0, environment_result.stderr + environment_result.stdout

    environment: dict[str, str] = {}
    for line in environment_result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        environment[key] = value
    return environment


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not available on Windows")
def test_install_sh_sets_env_permissions_to_0600(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    user_input = "\n".join(
        [
            "server.local",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "client-id",
            "Bas$2026",
            "admin",
            "single'quote",
            "",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout
    mode = stat.S_IMODE((project_dir / ".env").stat().st_mode)
    assert mode == 0o600


def test_install_sh_round_trips_single_quotes_through_docker_compose(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    user_input = "\n".join(
        [
            "server.local",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "client-id",
            "Bas$2026",
            "admin",
            "single'quote",
            "",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout

    env_content = (project_dir / ".env").read_text(encoding="utf-8")
    assert "TWITCH_CLIENT_SECRET='Bas$2026'" in env_content
    assert "ADMIN_PASSWORD='single\\'quote'" in env_content
    assert "\\''" not in env_content

    environment = _load_compose_environment(project_dir)
    assert environment["TWITCH_CLIENT_ID"] == "client-id"
    assert environment["TWITCH_CLIENT_SECRET"] == "Bas$2026"
    assert environment["ADMIN_USERNAME"] == "admin"
    assert environment["ADMIN_PASSWORD"] == "single'quote"


def test_install_sh_rejects_half_admin_config_without_overwriting_existing_env(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    original_env = project_dir / ".env"
    original_env.write_text("KEEP_ME='yes'\n", encoding="utf-8")
    user_input = "\n".join(
        [
            "yes",
            "server.local",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "admin",
            "",
            "",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode != 0
    assert "Admin username and password must either both be provided or both be left empty." in (result.stderr + result.stdout)
    assert original_env.read_text(encoding="utf-8") == "KEEP_ME='yes'\n"
    assert list(project_dir.glob(".env.tmp.*")) == []


def test_install_sh_round_trips_compose_special_characters_without_interpolation(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    user_input = "\n".join(
        [
            "server.local",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "back\\slash",
            "${HOME}",
            'double"quote',
            " password with leading and trailing spaces ",
            "INFO",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout

    environment = _load_compose_environment(project_dir)
    assert environment["TWITCH_CLIENT_ID"] == r"back\slash"
    assert environment["TWITCH_CLIENT_SECRET"] == "${HOME}"
    assert environment["ADMIN_USERNAME"] == 'double"quote'
    assert environment["ADMIN_PASSWORD"] == " password with leading and trailing spaces "


def test_install_sh_round_trips_mixed_quotes_spaces_and_dollar_signs(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    user_input = "\n".join(
        [
            "server.local",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "mix '$HOME' \\ \"test\"",
            "password with spaces",
            "admin",
            "mix '$HOME' \\ \"test\"",
            "INFO",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout

    environment = _load_compose_environment(project_dir)
    assert environment["TWITCH_CLIENT_ID"] == "mix '$HOME' \\ \"test\""
    assert environment["TWITCH_CLIENT_SECRET"] == "password with spaces"
    assert environment["ADMIN_USERNAME"] == "admin"
    assert environment["ADMIN_PASSWORD"] == "mix '$HOME' \\ \"test\""
