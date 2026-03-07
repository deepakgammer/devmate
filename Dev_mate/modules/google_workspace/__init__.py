"""
DEVMATE – Google Workspace Integration Package
Provides Google Workspace automation via the `gws` CLI.
"""
from .gws_manager import GWSManager
from .gws_parser import detect_gws_intent

__all__ = ["GWSManager", "detect_gws_intent"]
