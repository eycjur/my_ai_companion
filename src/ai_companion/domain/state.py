"""アプリケーション状態。"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    CONVERSING = "conversing"
    ERROR = "error"
