"""長期記憶モジュールの単体テスト。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ai_companion.adapter.memory_sqlite import (
    SQLiteMemoryStore,
    insert_session,
    load_profile,
    recent_summaries,
    save_profile,
    search_sessions,
)
from ai_companion.domain.persona import Persona, build_system_instruction
from ai_companion.domain.transcript import TranscriptCollector
from ai_companion.usecase.conversation import ConversationUseCase


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    d = tmp_path / "memory"
    d.mkdir()
    return d


def test_profile_load_save_roundtrip(memory_dir: Path):
    text = "呼び方: きみ\n好きな飲み物: コーヒー\n- 猫好き"
    save_profile(memory_dir, text)
    assert load_profile(memory_dir) == text


def test_profile_empty_when_missing(memory_dir: Path):
    assert load_profile(memory_dir) == ""


def test_episodic_recent_and_search(memory_dir: Path):
    insert_session(
        memory_dir,
        session_id="s1",
        started_at="2026-06-18T21:00:00Z",
        ended_at="2026-06-18T21:10:00Z",
        summary="京都旅行の計画。金閣寺に行く。",
    )
    insert_session(
        memory_dir,
        session_id="s2",
        started_at="2026-06-19T10:00:00Z",
        ended_at="2026-06-19T10:05:00Z",
        summary="転職の面接について話した。",
    )

    recent = recent_summaries(memory_dir, limit=2)
    assert recent[0].summary.startswith("転職")

    hits = search_sessions(memory_dir, "京都 旅行")
    assert any("京都" in h for h in hits)


def test_format_warm_start(memory_dir: Path):
    save_profile(memory_dir, "呼び方: きみ\n好み: コーヒー派")
    insert_session(
        memory_dir,
        session_id="s1",
        started_at="2026-06-18T21:00:00Z",
        ended_at="2026-06-18T21:10:00Z",
        summary="猫を飼い始めた。",
    )
    store = SQLiteMemoryStore(memory_dir)

    class FakeFactory:
        def create(self, system_instruction, *, memory_search=None):
            return None

    uc = ConversationUseCase(
        persona=Persona(),
        session_factory=FakeFactory(),
        memory_store=store,
    )
    text = uc._format_warm_start()
    assert "コーヒー派" in text
    assert "きみ" in text
    assert "猫を飼い始めた" in text


def test_memory_store_warm_start(memory_dir: Path):
    save_profile(memory_dir, "テスト profile")
    store = SQLiteMemoryStore(memory_dir)
    assert store.load_profile() == "テスト profile"


def test_memory_context_in_system_instruction():
    persona = Persona(name="Jarvis")
    instr = build_system_instruction(
        persona=persona,
        now=datetime(2026, 6, 19, 12, 0),
        memory_context="【最近の会話】\n- 6/18: テスト",
    )
    assert "【最近の会話】" in instr
    assert "テスト" in instr


def test_transcript_collector():
    tc = TranscriptCollector()
    tc.append_user("こんにちは")
    tc.on_turn_complete()
    tc.append_assistant("やあ")
    tc.on_turn_complete()
    t = tc.finalize()
    assert len(t.turns) == 2
    assert t.turns[0].role == "user"
    assert not t.is_empty()
