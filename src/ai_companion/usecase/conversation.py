"""会話ユースケース — system instruction 構築・セッション実行・記憶統合。

1 回の会話のオーケストレーション（記憶の warm-start 注入 → Live セッション実行 →
終了後の記憶統合）を担う。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ..domain.persona import Persona, build_system_instruction
from ..logging_conf import get_logger

if TYPE_CHECKING:
    from ..domain.ports import LiveSessionFactory, MemoryStorePort
    from ..usecase.memory_consolidation import MemoryConsolidationUseCase

logger = get_logger("usecase.conversation")


class ConversationUseCase:
    """1 回の会話を実行する。

    system instruction を組み立て、セッションを実行し、
    終了後に記憶を統合する。
    """

    def __init__(
        self,
        persona: Persona,
        session_factory: LiveSessionFactory,
        *,
        memory_store: MemoryStorePort | None = None,
        consolidation: MemoryConsolidationUseCase | None = None,
        memory_recent_sessions: int = 3,
    ) -> None:
        self._persona = persona
        self._session_factory = session_factory
        self._memory_store = memory_store
        self._consolidation = consolidation
        self._memory_recent_sessions = memory_recent_sessions
        self._active_session = None

    @property
    def active_session(self):
        return self._active_session

    def request_stop(self) -> None:
        """外部から会話を停止する。"""
        if self._active_session is not None:
            self._active_session.request_stop()

    async def execute(self) -> None:
        """会話を実行する。"""
        memory_ctx = ""
        memory_search = None

        if self._memory_store is not None:
            memory_ctx = self._format_warm_start()
            def _search(query: str) -> list[str]:
                assert self._memory_store is not None
                return self._memory_store.search(query, limit=5)

            memory_search = _search

        instruction = build_system_instruction(
            persona=self._persona,
            now=datetime.now(),
            memory_context=memory_ctx,
        )

        session = self._session_factory.create(
            system_instruction=instruction,
            memory_search=memory_search,
        )
        self._active_session = session
        try:
            transcript = await session.run()
            logger.info("会話終了。")

            if self._consolidation is not None:
                self._consolidation.run_in_background(transcript)
        finally:
            self._active_session = None

    def _format_warm_start(self) -> str:
        """メモリストアから warm-start コンテキストを構築する。"""
        assert self._memory_store is not None
        profile = self._memory_store.load_profile().strip()
        recent = [
            f"{s.started_at[:10]}: {s.summary}"
            for s in self._memory_store.recent_summaries(limit=self._memory_recent_sessions)
        ]

        sections: list[str] = []
        if profile:
            sections.append(f"【このユーザーについて覚えていること】\n{profile}")
        if recent:
            lines = "\n".join(f"- {s}" for s in recent)
            sections.append(f"【最近の会話】\n{lines}")
        if not sections:
            return ""
        sections.append(
            "上記は過去の記憶です。今回の話題に合わせて自然に参照し、"
            "無関係なら無理に引きずらないでください。"
            "ユーザーが過去の特定の話題について聞いたら search_memory ツールを使ってください。"
        )
        return "\n\n".join(sections)
