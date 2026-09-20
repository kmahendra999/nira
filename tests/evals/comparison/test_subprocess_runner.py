"""Tests for nira.evals.backends.external._subprocess_runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nira.evals.backends.external._subprocess_runner import (
    EnergySample,
    SubprocessResult,
    run_one_shot,
)


class TestSubprocessResult:
    def test_dataclass_fields(self) -> None:
        result = SubprocessResult(
            stdout="hello",
            stderr="",
            exit_code=0,
            latency_seconds=1.5,
            energy_joules=100.0,
            peak_power_w=20.0,
            sampler_method="nvml",
            parsed_json={"content": "x"},
        )
        assert result.stdout == "hello"
        assert result.exit_code == 0
        assert result.energy_joules == 100.0
        assert result.parsed_json == {"content": "x"}


class TestEnergySample:
    def test_dataclass_fields(self) -> None:
        s = EnergySample(timestamp=1.0, watts=15.5)
        assert s.timestamp == 1.0
        assert s.watts == 15.5


class TestRunOneShot:
    def test_successful_run_returns_parsed_json(self, tmp_path: Path) -> None:
        output_json = tmp_path / "out.json"
        output_json.write_text(
            json.dumps(
                {
                    "content": "hello",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "trajectory": [],
                    "tool_calls": 0,
                    "turn_count": 1,
                    "error": None,
                }
            )
        )
        with patch("subprocess.Popen") as MockPopen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("done", "")
            mock_proc.returncode = 0
            MockPopen.return_value = mock_proc

            result = run_one_shot(
                cmd=["echo", "ok"],
                env={},
                timeout=10.0,
                output_json_path=output_json,
            )
        assert result.exit_code == 0
        assert result.parsed_json["content"] == "hello"
        assert result.error is None

    def test_nonzero_exit_records_crash(self, tmp_path: Path) -> None:
        output_json = tmp_path / "out.json"
        with patch("subprocess.Popen") as MockPopen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "boom")
            mock_proc.returncode = 139
            MockPopen.return_value = mock_proc

            result = run_one_shot(
                cmd=["false"],
                env={},
                timeout=10.0,
                output_json_path=output_json,
            )
        assert result.exit_code == 139
        assert result.error == "subprocess_crash"
        assert "boom" in result.stderr

    def test_timeout_kills_process(self, tmp_path: Path) -> None:
        import subprocess as sp

        output_json = tmp_path / "out.json"
        with patch("subprocess.Popen") as MockPopen:
            mock_proc = MagicMock()
            mock_proc.communicate.side_effect = [
                sp.TimeoutExpired(cmd="x", timeout=10),
                ("", ""),
            ]
            mock_proc.returncode = -9
            MockPopen.return_value = mock_proc

            result = run_one_shot(
                cmd=["sleep", "100"],
                env={},
                timeout=10.0,
                output_json_path=output_json,
            )
        assert result.error == "timeout"
        mock_proc.terminate.assert_called_once()

    def test_malformed_json_recorded(self, tmp_path: Path) -> None:
        output_json = tmp_path / "out.json"
        output_json.write_text("not json {{{")
        with patch("subprocess.Popen") as MockPopen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            MockPopen.return_value = mock_proc

            result = run_one_shot(
                cmd=["echo"],
                env={},
                timeout=10.0,
                output_json_path=output_json,
            )
        assert result.error == "malformed_runner_output"

    def test_missing_output_json_recorded(self, tmp_path: Path) -> None:
        output_json = tmp_path / "never_created.json"
        with patch("subprocess.Popen") as MockPopen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            MockPopen.return_value = mock_proc

            result = run_one_shot(
                cmd=["echo"],
                env={},
                timeout=10.0,
                output_json_path=output_json,
            )
        assert result.error == "invalid_runner_output"


class TestEnergySampler:
    def test_fallback_chain_reaches_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When all samplers fail to initialize, return the null sampler."""
        from nira.evals.backends.external import _subprocess_runner as m

        # Force every probe to fail
        monkeypatch.setattr(m, "_try_start_nvml", lambda: None)
        monkeypatch.setattr(m, "_try_start_powermetrics", lambda: None)
        monkeypatch.setattr(m, "_try_start_rocm_smi", lambda: None)
        monkeypatch.setattr(m, "_try_start_rapl", lambda: None)

        sampler = m._start_sampler()
        assert sampler.method == "unavailable"
        assert sampler.stop() == []

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permissions, so 0400 stays readable",
    )
    def test_rapl_declines_when_file_exists_but_is_unreadable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A present-but-unreadable energy_uj must not raise.

        Since CVE-2020-8694 (PLATYPUS) mainstream distributions ship
        energy_uj as root-only 0400, so it exists while being unreadable to
        an ordinary user. Probing with exists() rather than a read let a
        PermissionError escape _start_sampler and abort every external eval
        on such a host.
        """
        from nira.evals.backends.external import _subprocess_runner as m

        energy_uj = tmp_path / "energy_uj"
        energy_uj.write_text("123456", encoding="utf-8")
        energy_uj.chmod(0o000)

        monkeypatch.setattr(m, "Path", lambda _p: energy_uj)
        try:
            assert m._try_start_rapl() is None
        finally:
            energy_uj.chmod(0o600)

    def test_rapl_declines_on_non_integer_contents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from nira.evals.backends.external import _subprocess_runner as m

        energy_uj = tmp_path / "energy_uj"
        energy_uj.write_text("not-a-number", encoding="utf-8")
        monkeypatch.setattr(m, "Path", lambda _p: energy_uj)

        assert m._try_start_rapl() is None

    def test_a_raising_probe_does_not_break_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Metering must never fail the run it is only measuring."""
        from nira.evals.backends.external import _subprocess_runner as m

        def _explode() -> None:
            raise PermissionError("energy interface present but unusable")

        monkeypatch.setattr(m, "_try_start_nvml", _explode)
        monkeypatch.setattr(m, "_try_start_powermetrics", lambda: None)
        monkeypatch.setattr(m, "_try_start_rocm_smi", lambda: None)
        monkeypatch.setattr(m, "_try_start_rapl", lambda: None)

        sampler = m._start_sampler()
        assert sampler.method == "unavailable"

    def test_a_raising_probe_still_allows_a_later_one_to_win(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from nira.evals.backends.external import _subprocess_runner as m

        def _explode() -> None:
            raise OSError("nvml broken")

        working = m._NullSampler()
        working.method = "rapl"

        monkeypatch.setattr(m, "_try_start_nvml", _explode)
        monkeypatch.setattr(m, "_try_start_powermetrics", lambda: None)
        monkeypatch.setattr(m, "_try_start_rocm_smi", lambda: None)
        monkeypatch.setattr(m, "_try_start_rapl", lambda: working)

        assert m._start_sampler() is working
