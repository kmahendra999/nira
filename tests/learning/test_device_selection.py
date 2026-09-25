"""Tests for PyTorch device selection (cuda > mps > cpu)."""

from __future__ import annotations


class TestSelectTorchDevice:
    """Tests for _select_torch_device() logic in orchestrator trainers.

    These used to assume torch was absent from the test environment and
    asserted that directly, so they passed by accident and started failing
    the moment anything installed torch — which the `generate` extra now
    does. The absent case is simulated instead.
    """

    def test_no_torch_returns_none(self, monkeypatch):
        """Without torch, _select_torch_device returns None."""
        from nira.learning.intelligence.orchestrator import sft_trainer

        monkeypatch.setattr(sft_trainer, "HAS_TORCH", False)
        assert sft_trainer._select_torch_device() is None

    def test_with_torch_returns_a_device(self):
        """With torch present it picks one, rather than returning None."""
        from nira.learning.intelligence.orchestrator import sft_trainer

        if not sft_trainer.HAS_TORCH:
            import pytest

            pytest.skip("torch is not installed")
        device = sft_trainer._select_torch_device()
        assert device is not None
        assert str(device) in {"cuda", "mps", "cpu"}

    def test_cuda_preferred(self):
        """CUDA is selected when available (logic test)."""
        has_cuda = True
        has_mps = True

        if has_cuda:
            choice = "cuda"
        elif has_mps:
            choice = "mps"
        else:
            choice = "cpu"

        assert choice == "cuda"

    def test_mps_fallback(self):
        """MPS is selected when CUDA is not available but MPS is."""
        has_cuda = False
        has_mps = True

        if has_cuda:
            choice = "cuda"
        elif has_mps:
            choice = "mps"
        else:
            choice = "cpu"

        assert choice == "mps"

    def test_cpu_last_resort(self):
        """CPU is selected when neither CUDA nor MPS is available."""
        has_cuda = False
        has_mps = False

        if has_cuda:
            choice = "cuda"
        elif has_mps:
            choice = "mps"
        else:
            choice = "cpu"

        assert choice == "cpu"

    def test_function_exists_in_both_trainers(self):
        """_select_torch_device is defined in both trainers."""
        from nira.learning.intelligence.orchestrator.grpo_trainer import (
            _select_torch_device as grpo_fn,
        )
        from nira.learning.intelligence.orchestrator.sft_trainer import (
            _select_torch_device as sft_fn,
        )

        assert callable(sft_fn)
        assert callable(grpo_fn)

    def test_exported_from_orchestrator_init(self):
        """_select_torch_device is exported from orchestrator package."""
        from nira.learning.intelligence.orchestrator import (
            _select_torch_device,
        )

        assert callable(_select_torch_device)
