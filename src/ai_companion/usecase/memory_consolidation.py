"""記憶統合ユースケース — 会話後のプロフィール更新・要約保存。

会話終了後に Gemini Text API で書き起こしを要約・fact 抽出し、profile（semantic）と
episodic（SQLite）を更新する。
"""
from __future__ import annotations

import json
import re
import threading
from typing import TYPE_CHECKING

from ..domain.transcript import Transcript
from ..logging_conf import get_logger

if TYPE_CHECKING:
    from ..domain.ports import ConsolidationPort, MemoryStorePort

logger = get_logger("usecase.memory_consolidation")


def _format_transcript(transcript: Transcript) -> str:
    lines: list[str] = []
    for turn in transcript.turns:
        label = "ユーザー" if turn.role == "user" else "アシスタント"
        lines.append(f"{label}: {turn.text}")
    return "\n".join(lines)


def _build_consolidation_prompt(current_profile: str, transcript: str) -> str:
    profile_block = current_profile.strip() if current_profile.strip() else "（空）"
    return f"""\
以下の音声会話の書き起こしを分析し、JSON のみを出力してください。

## 現在の profile（ユーザーが編集しているプレーンテキスト）
{profile_block}

## ルール
- ユーザー発言に根拠がある事実だけ profile に反映する（推測禁止）
- profile は既存の書き方・体裁を可能な限り維持し、新情報だけ追加・更新する
- 変更がなければ profile は現在の内容をそのまま返す
- summary は 3〜5 文の日本語要約（固有名詞・話題名を含める）
- 医療・メンタルヘルス等のセンシティブ情報は profile に含めない

## 出力 JSON スキーマ
{{
  "summary": "string",
  "profile": "string"
}}

## 書き起こし
{transcript}
"""


def _parse_consolidation_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("consolidation 応答は JSON オブジェクトである必要があります")
    return data


def _session_id_from_started_at(started_at: str) -> str:
    """started_at からセッション ID を生成（ファイル名安全）。"""
    return started_at.replace(":", "").replace("+", "").replace(".", "")


class MemoryConsolidationUseCase:
    """会話終了後に要約を生成し、プロフィールを更新する。"""

    def __init__(
        self,
        memory_store: MemoryStorePort,
        consolidator: ConsolidationPort,
    ) -> None:
        self._store = memory_store
        self._consolidator = consolidator

    def consolidate(self, transcript: Transcript) -> None:
        """同期的に consolidation を実行する。"""
        if transcript.is_empty():
            logger.info("空のトランスクリプトのため consolidation をスキップ。")
            return

        current_profile = self._store.load_profile()
        prompt = _build_consolidation_prompt(
            current_profile,
            _format_transcript(transcript),
        )

        raw = self._consolidator.generate(prompt)
        data = _parse_consolidation_json(raw)

        summary = str(data["summary"]).strip()
        profile_raw = data["profile"]
        if not isinstance(profile_raw, str):
            raise ValueError("consolidation 応答の profile は文字列である必要があります")

        session_id = _session_id_from_started_at(transcript.started_at)
        self._store.insert_session(
            session_id=session_id,
            started_at=transcript.started_at,
            ended_at=transcript.ended_at,
            summary=summary,
        )

        if profile_raw != current_profile:
            self._store.save_profile(profile_raw)

        logger.info("consolidation 完了: session=%s", session_id)

    def run_in_background(self, transcript: Transcript) -> None:
        """バックグラウンドスレッドで consolidation を実行する。"""
        if transcript.is_empty():
            return

        def _run() -> None:
            try:
                self.consolidate(transcript)
            except Exception:
                logger.exception("バックグラウンド consolidation でエラー")

        threading.Thread(target=_run, daemon=True).start()
