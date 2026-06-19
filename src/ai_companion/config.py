"""設定ロード — `.env` を型付きオブジェクトに集約する。

環境変数が一次情報源。必須依存（python-dotenv）は在る前提。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .domain.persona import Persona
from .logging_conf import get_logger

logger = get_logger("config")

DEFAULT_PERSONA_NAME = "Jarvis"


def default_memory_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "ai_companion" / "memory"

DEFAULT_LIVE_MODEL = "gemini-3.1-flash-live-preview"
DEFAULT_WAKE_MODEL = "hey_jarvis"
DEFAULT_WAKE_THRESHOLD = 0.5
DEFAULT_VOICE = "Aoede"
DEFAULT_SILENCE_TIMEOUT = 45.0  # 秒
DEFAULT_MUTE_MIC_DURING_OUTPUT = True
DEFAULT_BARGE_IN_PREFIX_MS = 500
DEFAULT_MEMORY_RECENT_SESSIONS = 3
DEFAULT_MEMORY_MODEL = "gemini-2.0-flash"


def _load_dotenv() -> None:
    """CWD → プロジェクトソースツリーの順で .env を探す。

    macOS アプリとしてインストールした場合でも CWD の .env を読める。
    開発時（`uv run`）はソースツリー内の .env も探す。
    """
    from dotenv import load_dotenv

    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("loaded .env from %s", env_path)
            return


@dataclass
class Settings:
    """アプリ全体の設定。"""

    gemini_api_key: str = ""
    wake_model: str = DEFAULT_WAKE_MODEL
    wake_threshold: float = DEFAULT_WAKE_THRESHOLD
    live_model: str = DEFAULT_LIVE_MODEL
    voice: str = DEFAULT_VOICE
    silence_timeout: float = DEFAULT_SILENCE_TIMEOUT
    mute_mic_during_output: bool = DEFAULT_MUTE_MIC_DURING_OUTPUT
    barge_in_prefix_ms: int = DEFAULT_BARGE_IN_PREFIX_MS
    memory_dir: Path = field(default_factory=default_memory_dir)
    memory_recent_sessions: int = DEFAULT_MEMORY_RECENT_SESSIONS
    memory_model: str = DEFAULT_MEMORY_MODEL
    persona: Persona = field(default_factory=Persona)

    @classmethod
    def load(cls) -> "Settings":
        _load_dotenv()

        def _get(key: str, default: str = "") -> str:
            return os.environ.get(key, default).strip()

        def _float(key: str, default: float) -> float:
            value = _get(key)
            return float(value) if value else default

        def _bool(key: str, default: bool) -> bool:
            value = _get(key).lower()
            if not value:
                return default
            return value in ("1", "true", "yes", "on")

        def _int(key: str, default: int) -> int:
            value = _get(key)
            return int(value) if value else default

        settings = cls(
            gemini_api_key=_get("GEMINI_API_KEY") or _get("GOOGLE_API_KEY"),
            wake_model=_get("AICP_WAKE_MODEL") or DEFAULT_WAKE_MODEL,
            wake_threshold=_float("AICP_WAKE_THRESHOLD", DEFAULT_WAKE_THRESHOLD),
            live_model=_get("AICP_LIVE_MODEL") or DEFAULT_LIVE_MODEL,
            voice=_get("AICP_VOICE") or DEFAULT_VOICE,
            silence_timeout=_float("AICP_SILENCE_TIMEOUT", DEFAULT_SILENCE_TIMEOUT),
            mute_mic_during_output=_bool(
                "AICP_MUTE_MIC_DURING_OUTPUT", DEFAULT_MUTE_MIC_DURING_OUTPUT
            ),
            barge_in_prefix_ms=_int("AICP_BARGE_IN_PREFIX_MS", DEFAULT_BARGE_IN_PREFIX_MS),
            memory_dir=Path(_get("AICP_MEMORY_DIR") or str(default_memory_dir())),
            memory_recent_sessions=_int("AICP_MEMORY_RECENT_SESSIONS", DEFAULT_MEMORY_RECENT_SESSIONS),
            memory_model=_get("AICP_MEMORY_MODEL") or DEFAULT_MEMORY_MODEL,
        )
        settings.persona.name = _get("AICP_PERSONA_NAME") or DEFAULT_PERSONA_NAME
        if nick := _get("AICP_USER_NICKNAME"):
            settings.persona.user_nickname = nick
        return settings

    def validate(self) -> list[str]:
        """不足している必須設定の一覧を返す（空ならOK）。"""
        problems: list[str] = []
        if not self.gemini_api_key:
            problems.append("GEMINI_API_KEY が未設定です。")
        return problems
