from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest


WORKSPACE = Path(__file__).resolve().parents[1]
BASH_PATH = shutil.which("bash")
DOCKER_PATH = shutil.which("docker")
ENV_KEYS_TO_CLEAR = (
    "TZ",
    "PUBLIC_BASE_URL",
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_PROFILES",
)


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


def _sanitized_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in ENV_KEYS_TO_CLEAR:
        env.pop(key, None)
    return env


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
        "    env_file:\n"
        "      - .env\n",
        encoding="utf-8",
    )
    docker_bin = project_dir / "bin"
    docker_bin.mkdir()
    docker_stub = docker_bin / "docker"
    docker_stub.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s\\n' \"$*\" >> ./docker.log\n"
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
    env = _sanitized_environment()
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


def _open_install_process(project_dir: Path) -> subprocess.Popen[str]:
    bash_path = _require_bash()
    env = _sanitized_environment()
    env["PATH"] = f"{project_dir / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(project_dir / "home")
    env["USERPROFILE"] = str(project_dir / "home")
    Path(env["HOME"]).mkdir(exist_ok=True)
    return subprocess.Popen(
        [bash_path, "--noprofile", "--norc", "./install.sh"],
        cwd=project_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _compose_environment(project_dir: Path) -> dict[str, str]:
    env = _sanitized_environment()
    docker_config = project_dir / ".docker-config"
    docker_config.mkdir(exist_ok=True)
    env["DOCKER_CONFIG"] = str(docker_config)
    return env


def _load_compose_service_environment(project_dir: Path) -> dict[str, str]:
    docker_path = _require_docker()
    result = subprocess.run(
        [docker_path, "compose", "config", "--format", "json"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        env=_compose_environment(project_dir),
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    config = json.loads(result.stdout)
    return config["services"]["envtest"]["environment"]


def _load_compose_interpolation_environment(project_dir: Path) -> dict[str, str]:
    docker_path = _require_docker()
    result = subprocess.run(
        [docker_path, "compose", "config", "--environment"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        env=_compose_environment(project_dir),
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    environment: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        environment[key] = value
    return environment


def _compose_canonical_value(value: str) -> str:
    return value.replace("$", "$$")


def _docker_log_lines(project_dir: Path) -> list[str]:
    log_path = project_dir / "docker.log"
    if not log_path.exists():
        return []
    return log_path.read_text(encoding="utf-8").splitlines()


def _assert_no_compose_up(project_dir: Path) -> None:
    assert "compose up -d --build" not in _docker_log_lines(project_dir)


def _inputs_before_start_now(existing_env: bool) -> str:
    values = [
        "yes" if existing_env else None,
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
        "",
        "",
        "",
    ]
    return "\n".join(value for value in values if value is not None) + "\n"


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


def test_install_sh_round_trips_env_file_values_through_compose_config(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    expected = {
        "TWITCH_CLIENT_ID": r"back\slash",
        "TWITCH_CLIENT_SECRET": "${HOME}",
        "ADMIN_USERNAME": 'double"quote',
        "ADMIN_PASSWORD": " password with leading and trailing spaces ",
    }
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
            expected["TWITCH_CLIENT_ID"],
            expected["TWITCH_CLIENT_SECRET"],
            expected["ADMIN_USERNAME"],
            expected["ADMIN_PASSWORD"],
            "INFO",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout

    service_environment = _load_compose_service_environment(project_dir)
    interpolation_environment = _load_compose_interpolation_environment(project_dir)

    for key, value in expected.items():
        assert service_environment[key] == _compose_canonical_value(value)
        assert interpolation_environment[key] == value


def test_install_sh_round_trips_single_quotes_and_dollar_values(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    expected = {
        "TWITCH_CLIENT_ID": "client-id",
        "TWITCH_CLIENT_SECRET": "Bas$2026",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "single'quote",
    }
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
            expected["TWITCH_CLIENT_ID"],
            expected["TWITCH_CLIENT_SECRET"],
            expected["ADMIN_USERNAME"],
            expected["ADMIN_PASSWORD"],
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

    service_environment = _load_compose_service_environment(project_dir)
    interpolation_environment = _load_compose_interpolation_environment(project_dir)
    for key, value in expected.items():
        assert service_environment[key] == _compose_canonical_value(value)
        assert interpolation_environment[key] == value


def test_install_sh_round_trips_mixed_quotes_spaces_and_dollar_signs(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    expected_secret = "mix '$HOME' \\ \"test\""
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
            expected_secret,
            "password with spaces",
            "admin",
            expected_secret,
            "INFO",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout

    service_environment = _load_compose_service_environment(project_dir)
    interpolation_environment = _load_compose_interpolation_environment(project_dir)

    assert service_environment["TWITCH_CLIENT_ID"] == _compose_canonical_value(expected_secret)
    assert service_environment["TWITCH_CLIENT_SECRET"] == "password with spaces"
    assert service_environment["ADMIN_USERNAME"] == "admin"
    assert service_environment["ADMIN_PASSWORD"] == _compose_canonical_value(expected_secret)

    assert interpolation_environment["TWITCH_CLIENT_ID"] == expected_secret
    assert interpolation_environment["TWITCH_CLIENT_SECRET"] == "password with spaces"
    assert interpolation_environment["ADMIN_USERNAME"] == "admin"
    assert interpolation_environment["ADMIN_PASSWORD"] == expected_secret


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
    _assert_no_compose_up(project_dir)


def test_install_sh_rejects_whitespace_only_admin_password_without_leaking_value(tmp_path: Path):
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
            "   ",
            "",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    output = result.stderr + result.stdout
    assert result.returncode != 0
    assert "ADMIN_PASSWORD must contain at least one non-whitespace character." in output
    assert "   " not in output
    assert original_env.read_text(encoding="utf-8") == "KEEP_ME='yes'\n"
    assert list(project_dir.glob(".env.tmp.*")) == []
    _assert_no_compose_up(project_dir)


def test_install_sh_stops_on_input_end_without_writing_env(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    result = _run_install(project_dir, "server.local\n")
    output = result.stderr + result.stdout
    assert result.returncode != 0
    assert "Input ended. Installation cancelled." in output
    assert not (project_dir / ".env").exists()
    assert list(project_dir.glob(".env.tmp.*")) == []
    _assert_no_compose_up(project_dir)


@pytest.mark.parametrize("existing_env", [False, True])
def test_install_sh_stops_on_input_end_at_start_now_prompt_without_changing_env(tmp_path: Path, existing_env: bool):
    project_dir = _copy_installer_fixture(tmp_path)
    original_content = "KEEP_ME='yes'\n"
    if existing_env:
        (project_dir / ".env").write_text(original_content, encoding="utf-8")

    process = _open_install_process(project_dir)
    stdout, stderr = process.communicate(
        input=_inputs_before_start_now(existing_env),
        timeout=10,
    )

    output = stderr + stdout
    assert process.returncode != 0
    assert "Input ended. Installation cancelled." in output
    if existing_env:
        assert (project_dir / ".env").read_text(encoding="utf-8") == original_content
    else:
        assert not (project_dir / ".env").exists()
    assert list(project_dir.glob(".env.tmp.*")) == []
    _assert_no_compose_up(project_dir)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal behavior is tested on Unix")
def test_install_sh_handles_sigint_without_overwriting_existing_env(tmp_path: Path):
    project_dir = _copy_installer_fixture(tmp_path)
    original_env = project_dir / ".env"
    original_env.write_text("KEEP_ME='yes'\n", encoding="utf-8")
    process = _open_install_process(project_dir)
    assert process.stdin is not None
    process.stdin.write("yes\n")
    process.stdin.flush()
    time.sleep(0.5)
    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode in (130, -signal.SIGINT)
    assert "Installation cancelled." in (stderr + stdout)
    assert original_env.read_text(encoding="utf-8") == "KEEP_ME='yes'\n"
    assert list(project_dir.glob(".env.tmp.*")) == []
    _assert_no_compose_up(project_dir)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal behavior is tested on Unix")
@pytest.mark.parametrize(
    ("sig", "expected_returncode", "message"),
    [
        (signal.SIGINT, 130, "Installation cancelled."),
        (signal.SIGTERM, 143, "Installation terminated."),
    ],
)
@pytest.mark.parametrize("existing_env", [False, True])
def test_install_sh_handles_signal_at_start_now_prompt_without_changing_env(
    tmp_path: Path,
    sig: signal.Signals,
    expected_returncode: int,
    message: str,
    existing_env: bool,
):
    project_dir = _copy_installer_fixture(tmp_path)
    original_content = "KEEP_ME='yes'\n"
    if existing_env:
        (project_dir / ".env").write_text(original_content, encoding="utf-8")

    process = _open_install_process(project_dir)
    assert process.stdin is not None
    process.stdin.write(_inputs_before_start_now(existing_env))
    process.stdin.flush()
    time.sleep(0.5)
    process.send_signal(sig)
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode in (expected_returncode, -sig)
    assert message in (stderr + stdout)
    if existing_env:
        assert (project_dir / ".env").read_text(encoding="utf-8") == original_content
    else:
        assert not (project_dir / ".env").exists()
    assert list(project_dir.glob(".env.tmp.*")) == []
    _assert_no_compose_up(project_dir)
