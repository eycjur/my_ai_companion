"""ポート（Protocol） — 外部依存のインターフェース定義。

adapter 層がこれらを実装し、usecase / controller 層が利用する。
domain 層は外部ライブラリに一切依存しない。
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Protocol

from .transcript import Transcript


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

class MicrophonePort(Protocol):
    """マイク入力ストリーム。"""

    def start(self) -> None: ...

    async def chunks(self) -> AsyncIterator[bytes]: ...

    def stop(self) -> None: ...


class SpeakerPort(Protocol):
    """スピーカー出力ストリーム。"""

    def start(self) -> None: ...

    def play(self, pcm: bytes) -> None: ...

    def flush(self) -> None: ...

    def has_pending(self) -> bool: ...

    def stop(self) -> None: ...


# ---------------------------------------------------------------------------
# Wake Word
# ---------------------------------------------------------------------------

class WakeWordDetectorPort(Protocol):
    """ウェイクワード検出器。"""

    def listen_once(self, should_stop: Callable[[], bool]) -> bool:
        """ウェイクワード検出までブロック。検出で True、停止要求で False。"""
        ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Live Session
# ---------------------------------------------------------------------------

class LiveSessionPort(Protocol):
    """1 回の会話セッション。"""

    async def run(self) -> Transcript: ...

    def request_stop(self) -> None: ...


class LiveSessionFactory(Protocol):
    """LiveSession の生成ファクトリ。"""

    def create(
        self,
        system_instruction: str,
        *,
        memory_search: Callable[[str], list[str]] | None = None,
    ) -> LiveSessionPort: ...


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class MemoryStorePort(Protocol):
    """長期記憶の永続化。"""

    def load_profile(self) -> str: ...

    def save_profile(self, text: str) -> None: ...

    def recent_summaries(self, limit: int) -> list[SessionSummaryRecord]: ...

    def search(self, query: str, limit: int) -> list[str]: ...

    def insert_session(
        self,
        session_id: str,
        started_at: str,
        ended_at: str,
        summary: str,
    ) -> None: ...


class SessionSummaryRecord(Protocol):
    """MemoryStorePort.recent_summaries が返すレコード。"""

    @property
    def started_at(self) -> str: ...

    @property
    def summary(self) -> str: ...


class ConsolidationPort(Protocol):
    """LLM を使った会話要約・プロフィール更新。"""

    def generate(self, prompt: str) -> str:
        """プロンプトを送り、応答テキストを返す。"""
        ...
