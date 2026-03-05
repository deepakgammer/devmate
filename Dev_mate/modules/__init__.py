"""
DEVMATE – modules package
"""
from .memory_module import MemoryManager
from .llm_module import LLMModule
from .speech_module import SpeechModule
from .automation_module import AutomationModule
from .scheduler_module import SchedulerModule
from .ui_module import DevMateGUI
from .task_manager import TaskManager
from .controller import DevMateController

__all__ = [
    "MemoryManager",
    "LLMModule",
    "SpeechModule",
    "AutomationModule",
    "SchedulerModule",
    "DevMateGUI",
    "TaskManager",
    "DevMateController",
]
