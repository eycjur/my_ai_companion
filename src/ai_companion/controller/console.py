"""メニューバー無しのコンソール起動（開発・動作確認用）。

rumps（AppKit）を使わず、ターミナルで Orchestrator を直接動かす。Ctrl-C で終了。

使い方:
    python -m ai_companion.controller.console
"""
from __future__ import annotations

import sys
import time

from ..adapter.gemini_live import GeminiLiveSessionFactory
from ..adapter.memory_sqlite import SQLiteMemoryStore
from ..adapter.wake_word_oww import OpenWakeWordDetector, WakeWordLoop
from ..config import Settings
from ..logging_conf import setup_logging
from ..usecase.conversation import ConversationUseCase
from ..usecase.memory_consolidation import MemoryConsolidationUseCase
from .orchestrator import Orchestrator


def main() -> int:
    setup_logging()
    settings = Settings.load()
    problems = settings.validate()
    if problems:
        print("設定が不足しています:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 1

    # Memory（常時有効）
    memory_store = SQLiteMemoryStore(settings.memory_dir)
    memory_store.ensure_initialized()
    from ..adapter.gemini_text import GeminiTextConsolidator
    consolidator = GeminiTextConsolidator(settings.gemini_api_key, settings.memory_model)
    consolidation = MemoryConsolidationUseCase(memory_store, consolidator)

    session_factory = GeminiLiveSessionFactory(settings)
    conversation_uc = ConversationUseCase(
        persona=settings.persona,
        session_factory=session_factory,
        memory_store=memory_store,
        consolidation=consolidation,
        memory_recent_sessions=settings.memory_recent_sessions,
    )

    detector = OpenWakeWordDetector(
        wake_model=settings.effective_wake_model,
        threshold=settings.wake_threshold,
    )

    orchestrator = Orchestrator(
        conversation=conversation_uc,
        wake_loop=WakeWordLoop(detector, on_detected=lambda: None),
        on_state_change=lambda s: print(f"[状態] {s.value}"),
    )
    orchestrator._wake_loop._on_detected = orchestrator._on_wake

    print(f"{settings.persona.name} を起動します。ウェイクワード '{settings.effective_wake_model}' で話しかけてください。")
    print("（Ctrl-C で終了）")
    orchestrator.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n終了します…")
        orchestrator.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
