"""会話トランスクリプト収集。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Turn:
    role: str  # user / assistant
    text: str
    at: str  # ISO8601


@dataclass
class Transcript:
    started_at: str
    ended_at: str = ""
    turns: list[Turn] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(t.text.strip() for t in self.turns)


class TranscriptCollector:
    """LiveSession の書き起こしをターン単位で蓄積する。"""

    def __init__(self, started_at: datetime | None = None) -> None:
        start = started_at or datetime.now(timezone.utc)
        self._started_at = start.isoformat()
        self._turns: list[Turn] = []
        self._cur_user = ""
        self._cur_assistant = ""

    @property
    def started_at(self) -> str:
        return self._started_at

    def append_user(self, text: str) -> None:
        self._cur_user += text

    def append_assistant(self, text: str) -> None:
        self._cur_assistant += text

    def on_turn_complete(self) -> None:
        """ユーザーターン確定（turn_complete 時）。"""
        if text := self._cur_user.strip():
            self._turns.append(
                Turn(role="user", text=text, at=datetime.now(timezone.utc).isoformat())
            )
        self._cur_user = ""
        if text := self._cur_assistant.strip():
            self._turns.append(
                Turn(role="assistant", text=text, at=datetime.now(timezone.utc).isoformat())
            )
            self._cur_assistant = ""

    def finalize(self) -> Transcript:
        """会話終了時。未確定バッファをフラッシュする。"""
        if self._cur_user.strip() or self._cur_assistant.strip():
            self.on_turn_complete()
        return Transcript(
            started_at=self._started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            turns=list(self._turns),
        )
