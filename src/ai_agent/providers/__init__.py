"""Normalized adapters for model-provider SDKs."""

from .base import ModelClient
from .echo import EchoModelClient

__all__ = ["EchoModelClient", "ModelClient"]
