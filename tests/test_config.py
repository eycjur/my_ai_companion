"""Settings / Persona の設定ロードテスト。"""
from __future__ import annotations

import os

import pytest

from ai_companion.config import (
    DEFAULT_BARGE_IN_PREFIX_MS,
    DEFAULT_LIVE_MODEL,
    DEFAULT_MUTE_MIC_DURING_OUTPUT,
    DEFAULT_SILENCE_TIMEOUT,
    DEFAULT_VOICE,
    DEFAULT_WAKE_MODEL,
    DEFAULT_WAKE_THRESHOLD,
    Settings,
)
from ai_companion.domain.persona import Persona


@pytest.fixture(autouse=True)
def skip_dotenv(monkeypatch: pytest.MonkeyPatch):
    """実際の .env を読まない（CI / ローカル環境に依存しない）。"""
    monkeypatch.setattr("ai_companion.config._load_dotenv", lambda: None)
def test_persona_defaults():
    persona = Persona()
    assert persona.name == ""  # name は .env から設定される
    assert persona.pronoun == "わたし"
    assert persona.user_nickname == ""
    assert "明るく親しみやすい" in persona.personality
    assert "またね" in persona.farewell_keywords
    assert len(persona.dialogue_patterns) >= 1


def test_settings_load_sets_default_persona_name(monkeypatch: pytest.MonkeyPatch):
    for key in list(os.environ):
        if key.startswith("AICP_") or key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    settings = Settings.load()
    assert settings.persona.name == "Jarvis"


def test_settings_validate_requires_api_key():
    settings = Settings()
    problems = settings.validate()
    assert any("GEMINI_API_KEY" in p for p in problems)


def test_settings_validate_ok_with_key():
    settings = Settings(gemini_api_key="test-key")
    assert settings.validate() == []


def test_effective_wake_model_defaults_to_pretrained():
    settings = Settings(gemini_api_key="key")
    assert settings.effective_wake_model == DEFAULT_WAKE_MODEL


def test_effective_wake_model_prefers_path(tmp_path):
    model_file = tmp_path / "haru.onnx"
    model_file.write_bytes(b"")
    settings = Settings(
        gemini_api_key="key",
        wake_model="hey_jarvis",
        wake_model_path=str(model_file),
    )
    assert settings.effective_wake_model == str(model_file)


def test_settings_load_reads_wake_model_path(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("AICP_") or key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(key, raising=False)
    model_file = tmp_path / "haru.onnx"
    model_file.write_bytes(b"")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("AICP_WAKE_MODEL_PATH", str(model_file))

    settings = Settings.load()
    assert settings.wake_model_path == str(model_file)
    assert settings.effective_wake_model == str(model_file)


def test_settings_validate_flags_missing_wake_model_path():
    settings = Settings(gemini_api_key="key", wake_model_path="/no/such/haru.onnx")
    problems = settings.validate()
    assert any("AICP_WAKE_MODEL_PATH" in p for p in problems)


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch):
    for key in list(os.environ):
        if key.startswith("AICP_") or key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("AICP_PERSONA_NAME", "Jarvis")
    monkeypatch.setenv("AICP_USER_NICKNAME", "boss")
    monkeypatch.setenv("AICP_WAKE_MODEL", "alexa")
    monkeypatch.setenv("AICP_WAKE_THRESHOLD", "0.3")
    monkeypatch.setenv("AICP_LIVE_MODEL", "custom-live")
    monkeypatch.setenv("AICP_VOICE", "Zephyr")
    monkeypatch.setenv("AICP_SILENCE_TIMEOUT", "30")
    monkeypatch.setenv("AICP_MUTE_MIC_DURING_OUTPUT", "false")
    monkeypatch.setenv("AICP_BARGE_IN_PREFIX_MS", "800")

    settings = Settings.load()

    assert settings.gemini_api_key == "env-key"
    assert settings.persona.name == "Jarvis"
    assert settings.persona.user_nickname == "boss"
    assert settings.wake_model == "alexa"
    assert settings.wake_threshold == 0.3
    assert settings.live_model == "custom-live"
    assert settings.voice == "Zephyr"
    assert settings.silence_timeout == 30.0
    assert settings.mute_mic_during_output is False
    assert settings.barge_in_prefix_ms == 800


def test_settings_load_google_api_key_fallback(monkeypatch: pytest.MonkeyPatch):
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    settings = Settings.load()
    assert settings.gemini_api_key == "google-key"


def test_settings_defaults():
    settings = Settings(gemini_api_key="key")
    assert settings.wake_model == DEFAULT_WAKE_MODEL
    assert settings.wake_threshold == DEFAULT_WAKE_THRESHOLD
    assert settings.live_model == DEFAULT_LIVE_MODEL
    assert settings.voice == DEFAULT_VOICE
    assert settings.silence_timeout == DEFAULT_SILENCE_TIMEOUT
    assert settings.mute_mic_during_output == DEFAULT_MUTE_MIC_DURING_OUTPUT
    assert settings.barge_in_prefix_ms == DEFAULT_BARGE_IN_PREFIX_MS
