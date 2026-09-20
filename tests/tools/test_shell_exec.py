"""Tests for the shell_exec tool.

These exercise the real subprocess path. They used to mock a native Rust
backend that short-circuited it, and in doing so they encoded that backend's
bugs as expected behaviour: four tests were skipped with the defect itself as
the skip reason ("Rust backend has no timeout", "inherits parent env", "has no
output truncation"), and test_nonzero_returncode asserted that `exit 42`
reports success. The fast path is gone, so these now assert what the tool
actually promises.
"""

from __future__ import annotations

import importlib
import os
import shlex
import subprocess
import sys
from unittest.mock import patch

import pytest

from nira.core import get_python_executable
from nira.tools.shell_exec import ShellExecTool


class TestShellExecTool:
    def test_registered_via_tools_package_import(self):
        import nira.tools as tools_pkg
        from nira.core.registry import ToolRegistry

        sys.modules.pop("nira.tools.shell_exec", None)
        importlib.reload(tools_pkg)

        assert ToolRegistry.contains("shell_exec")

    def test_spec(self):
        tool = ShellExecTool()
        assert tool.spec.name == "shell_exec"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds == 60.0
        assert "code:execute" in tool.spec.required_capabilities
        assert "command" in tool.spec.parameters["properties"]
        assert "command" in tool.spec.parameters["required"]

    def test_no_command(self):
        tool = ShellExecTool()
        result = tool.execute(command="")
        assert result.success is False
        assert "No command" in result.content

    def test_no_command_param(self):
        tool = ShellExecTool()
        result = tool.execute()
        assert result.success is False
        assert "No command" in result.content

    def test_simple_echo(self):
        result = ShellExecTool().execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.content
        assert "=== STDOUT ===" in result.content

    def test_capture_stderr(self):
        result = ShellExecTool().execute(command="echo error_msg >&2")
        assert "error_msg" in result.content
        assert "=== STDERR ===" in result.content

    def test_timeout_exceeded(self):
        result = ShellExecTool().execute(command="sleep 60", timeout=1)
        assert result.success is False
        assert "timed out" in result.content
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1

    def test_timeout_capped_at_max(self):
        result = ShellExecTool().execute(command="echo ok", timeout=999)
        assert result.success is True
        assert result.metadata["timeout_used"] == 300

    def test_working_dir(self, tmp_path):
        result = ShellExecTool().execute(command="pwd", working_dir=str(tmp_path))
        assert result.success is True
        assert str(tmp_path) in result.content
        assert result.metadata["working_dir"] == str(tmp_path)

    def test_working_dir_not_exists(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo hi", working_dir="/nonexistent/path")
        assert result.success is False
        assert "does not exist" in result.content

    def test_working_dir_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data", encoding="utf-8")
        tool = ShellExecTool()
        result = tool.execute(command="echo hi", working_dir=str(f))
        assert result.success is False
        assert "not a directory" in result.content

    def test_env_clearing(self):
        """Arbitrary host env vars must NOT reach the child."""
        marker = "NIRA_TEST_SECRET_12345"
        os.environ[marker] = "leaked"
        try:
            result = ShellExecTool().execute(command=f"echo ${marker}")
            assert result.success is True
            assert "leaked" not in result.content
        finally:
            os.environ.pop(marker, None)

    def test_env_passthrough(self):
        """Explicitly listed env vars ARE passed through."""
        marker = "NIRA_TEST_PASSTHROUGH_67890"
        os.environ[marker] = "allowed_value"
        try:
            result = ShellExecTool().execute(
                command=f"echo ${marker}",
                env_passthrough=[marker],
            )
            assert result.success is True
            assert "allowed_value" in result.content
        finally:
            os.environ.pop(marker, None)

    def test_returncode_in_metadata(self):
        result = ShellExecTool().execute(command="echo ok")
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_nonzero_returncode(self):
        """A failing command must be reported as a failure.

        The removed native fast path returned success=True/returncode=0 for
        every exit status, so an agent was told a command worked when it had
        not. That is the single most consequential thing this tool can get
        wrong, hence an explicit regression test.
        """
        result = ShellExecTool().execute(command="exit 42")
        assert result.success is False
        assert result.metadata["returncode"] == 42

    def test_max_output_truncation(self, tmp_path):
        """Stdout exceeding 100 KB is truncated."""
        result = ShellExecTool().execute(
            command=(
                f"{shlex.quote(get_python_executable())} -c \"print('A' * 200000)\""
            ),
        )
        assert "truncated" in result.content
        assert len(result.content) < 200_000

    def test_no_output(self):
        result = ShellExecTool().execute(command="true")
        assert result.success is True
        assert result.content == "(no output)"

    def test_tool_id(self):
        tool = ShellExecTool()
        assert tool.tool_id == "shell_exec"

    def test_to_openai_function(self):
        tool = ShellExecTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "shell_exec"
        assert "command" in fn["function"]["parameters"]["properties"]

    def test_default_timeout_metadata(self):
        result = ShellExecTool().execute(command="echo ok")
        assert result.metadata["timeout_used"] == 30

    def test_never_delegates_to_the_native_backend(self):
        """The native fast path must stay gone.

        It could not carry an exit status, a sanitised environment or a
        timeout across the PyO3 boundary, so re-introducing it silently
        reopens all three defects. Assert the bridge is never consulted.
        """
        with patch("nira._rust_bridge.get_rust_module") as get_rust:
            result = ShellExecTool().execute(command="exit 7")

        get_rust.assert_not_called()
        assert result.success is False
        assert result.metadata["returncode"] == 7

class TestSanitizedEnvWindowsKeys:
    """Regression for #789: the Python fallback's env allowlist was
    POSIX-focused ("PATH", "HOME", "USER", "LANG", "TERM") and omitted
    variables Windows needs for basic process bootstrapping -- missing
    SystemRoot breaks Winsock/DNS init for any network-touching command
    (git, curl, pip, npm all fail with "getaddrinfo() thread failed to
    start"), and missing LOCALAPPDATA makes the Windows Store Python
    launcher provision a ~170MB Python\\ folder in the cwd instead of
    finding the real interpreter.
    """

    def test_base_env_keys_include_windows_essentials(self):
        from nira.tools.shell_exec import _WINDOWS_ENV_KEYS

        for key in (
            "SystemRoot",
            "SystemDrive",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        ):
            assert key in _WINDOWS_ENV_KEYS, f"{key} missing from Windows keys"

    def test_windows_keys_are_only_enabled_on_windows(self):
        from nira.tools.shell_exec import _BASE_ENV_KEYS, _WINDOWS_ENV_KEYS

        if os.name == "nt":
            assert set(_WINDOWS_ENV_KEYS) <= set(_BASE_ENV_KEYS)
        else:
            assert set(_WINDOWS_ENV_KEYS).isdisjoint(_BASE_ENV_KEYS)

    @pytest.mark.skipif(os.name != "nt", reason="requires a real Windows child")
    def test_windows_env_vars_reach_the_subprocess(self, monkeypatch):
        """End-to-end: a Windows-critical variable present in the host
        environment must actually reach the child process rather than
        being stripped by the sanitised-env allowlist."""
        monkeypatch.setenv("SystemRoot", r"C:\Windows")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")

        captured: dict = {}

        def _fake_run(*args, **kwargs):
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

        tool = ShellExecTool()
        with patch("subprocess.run", side_effect=_fake_run):
            result = tool.execute(command="echo ok")

        assert result.success is True
        env = captured["env"]
        assert env is not None
        assert env.get("SystemRoot") == r"C:\Windows"
        assert env.get("LOCALAPPDATA") == r"C:\Users\tester\AppData\Local"

    @pytest.mark.skipif(os.name != "nt", reason="requires a real Windows child")
    def test_real_windows_child_bootstraps_and_resolves_localhost(
        self, tmp_path, monkeypatch
    ):
        """Exercise the actual sanitized environment and Windows process path."""
        import json

        local_app_data = str(tmp_path / "LocalAppData")
        monkeypatch.setenv("LOCALAPPDATA", local_app_data)
        probe = (
            "import json, os, socket; "
            "addresses = socket.getaddrinfo('localhost', 80); "
            "print(json.dumps({"
            "'SystemRoot': os.environ.get('SystemRoot'), "
            "'LOCALAPPDATA': os.environ.get('LOCALAPPDATA'), "
            "'dns_ok': bool(addresses)}))"
        )
        command = subprocess.list2cmdline([sys.executable, "-c", probe])

        result = ShellExecTool().execute(command=command)

        assert result.success is True, result.content
        stdout = result.content.split("=== STDOUT ===\n", 1)[1].splitlines()[0]
        payload = json.loads(stdout)
        assert payload["SystemRoot"] == os.environ["SystemRoot"]
        assert payload["LOCALAPPDATA"] == local_app_data
        assert payload["dns_ok"] is True
