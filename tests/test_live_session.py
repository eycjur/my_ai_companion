"""LiveSession の終了条件ロジック（SDK 接続なし）。"""
from __future__ import annotations

from ai_companion.adapter.gemini_live import LiveSession
from ai_companion.config import Settings
from ai_companion.domain.persona import Persona


def _session(persona: Persona | None = None) -> LiveSession:
    settings = Settings(gemini_api_key="test-key", persona=persona or Persona())
    return LiveSession(settings, system_instruction="test")


def test_farewell_keyword_triggers_stop():
    session = _session()
    session._cur_user = "じゃあね、またね"
    session._check_farewell()
    assert session._stop.is_set()


def test_farewell_keyword_not_matched():
    session = _session()
    session._cur_user = "今日は暑いね"
    session._check_farewell()
    assert not session._stop.is_set()


def test_farewell_empty_user_text():
    session = _session()
    session._cur_user = ""
    session._check_farewell()
    assert not session._stop.is_set()


def test_custom_farewell_keywords():
    persona = Persona(farewell_keywords=["さようなら"])
    session = _session(persona)
    session._cur_user = "さようなら"
    session._check_farewell()
    assert session._stop.is_set()
