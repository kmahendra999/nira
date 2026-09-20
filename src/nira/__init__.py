"""Nira — modular AI assistant backend with composable intelligence primitives."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nira.sdk import MemoryHandle, Nira, NiraSystem, SystemBuilder

try:
    __version__ = _pkg_version("nira")
except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
    __version__ = "0.0.0+unknown"

__all__ = ["Nira", "NiraSystem", "MemoryHandle", "SystemBuilder", "__version__"]

_SDK_EXPORTS = {"Nira", "NiraSystem", "MemoryHandle", "SystemBuilder"}


def __getattr__(name: str) -> Any:
    """Load SDK exports lazily so lightweight CLI diagnostics can start safely."""
    if name not in _SDK_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from nira import sdk

    value = getattr(sdk, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SDK_EXPORTS)
