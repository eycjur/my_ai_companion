"""system instruction（ペルソナ）合成の単体テスト。"""
from __future__ import annotations

from datetime import datetime

from ai_companion.domain.persona import Persona, build_system_instruction


def test_persona_and_datetime_are_embedded():
    persona = Persona(
        name="Jarvis",
        pronoun="わたし",
        personality="明るい",
        speaking_style="やさしい話し方",
        farewell_keywords=["またね"],
        dialogue_patterns=["深掘りする"],
    )
    now = datetime(2026, 6, 18, 21, 30)  # 木曜
    instr = build_system_instruction(persona=persona, now=now)

    assert "Jarvis" in instr
    assert "わたし" in instr
    assert "明るい" in instr
    assert "深掘りする" in instr
    assert "2026年6月18日" in instr
    assert "（木）" in instr
    assert "21時30分" in instr


def test_nickname_injected():
    persona = Persona(name="Jarvis", user_nickname="きみ")
    instr = build_system_instruction(persona=persona, now=datetime(2026, 6, 18, 12, 0))
    assert "きみ" in instr


def test_empty_nickname_prompts_to_ask():
    persona = Persona(name="Jarvis", user_nickname="")
    instr = build_system_instruction(persona=persona, now=datetime(2026, 6, 18, 12, 0))
    assert "会話の中で自然に尋ねる" in instr


def test_no_tool_mentions():
    persona = Persona(name="Jarvis")
    instr = build_system_instruction(persona=persona, now=datetime(2026, 6, 18, 12, 0))
    assert "ツール" not in instr


def test_english_practice_instruction():
    persona = Persona(name="Jarvis")
    instr = build_system_instruction(persona=persona, now=datetime(2026, 6, 18, 12, 0))
    assert "英会話の練習" in instr
    assert "英語で返す" in instr


def test_ethics_and_guidelines_present():
    persona = Persona(name="Jarvis")
    instr = build_system_instruction(persona=persona, now=datetime(2026, 6, 18, 12, 0))
    assert "AI だが" in instr
    assert "話し方のガイドライン" in instr
    assert "対話のコツ" in instr
