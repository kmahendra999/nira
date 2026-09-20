"""Operators — persistent, scheduled autonomous agents."""

from nira.operators.loader import load_operator
from nira.operators.manager import OperatorManager
from nira.operators.types import OperatorManifest

__all__ = ["OperatorManifest", "OperatorManager", "load_operator"]
