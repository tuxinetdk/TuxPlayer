from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SH_PATH = Path(r"C:\Users\thoma\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\usr\bin\sh.exe")


def _copy_installer_fixture(tmp_path: Path) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shutil.copy2(WORKSPACE / "install.sh", project_dir / "install.sh")
    shutil.copy2(WORKSPACE / ".env.example", project_dir / ".env.example")
    (project_dir / "data").mkdir()
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
    chmod_stub = docker_bin / "chmod"
    chmod_stub.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s\\n' \"$*\" >> ./chmod.log\n"
        "exit 0\n",
        encoding="utf-8",
    )
    chmod_stub.chmod(0o755)
    return project_dir


def _run_install(project_dir: Path, user_input: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{project_dir / 'bin'}{os.pathsep}{SH_PATH.parent}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(project_dir / "home")
    env["USERPROFILE"] = str(project_dir / "home")
    Path(env["HOME"]).mkdir(exist_ok=True)
    return subprocess.run(
        [str(SH_PATH), "install.sh"],
        cwd=project_dir,
        input=user_input,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_install_sh_preserves_special_characters_and_sets_0600(tmp_path: Path):
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
    assert "TWITCH_CLIENT_ID='client-id'" in env_content
    assert "TWITCH_CLIENT_SECRET='Bas$2026'" in env_content
    assert "ADMIN_PASSWORD='single'\\''quote'" in env_content

    chmod_log = (project_dir / "chmod.log").read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("600 ") and ".env.tmp." in line for line in chmod_log)
    assert any(line.startswith("600 ") and line.endswith("/.env") for line in chmod_log)


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
    temp_files = list(project_dir.glob(".env.tmp.*"))
    assert temp_files == []


def test_install_sh_preserves_spaces_backslashes_and_variable_like_values(tmp_path: Path):
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
            "password with spaces",
            "INFO",
            "no",
        ]
    ) + "\n"
    result = _run_install(project_dir, user_input)
    assert result.returncode == 0, result.stderr + result.stdout
    env_content = (project_dir / ".env").read_text(encoding="utf-8")
    assert "TWITCH_CLIENT_ID='back\\slash'" in env_content
    assert "TWITCH_CLIENT_SECRET='${HOME}'" in env_content
    assert 'ADMIN_USERNAME=\'double"quote\'' in env_content
    assert "ADMIN_PASSWORD='password with spaces'" in env_content
