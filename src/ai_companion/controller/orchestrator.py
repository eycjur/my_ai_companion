"""オーケストレータ — 状態機械で会話ライフサイクルを統括する。

状態遷移: LISTENING → (wake) → CONVERSING → LISTENING

責務:
- ウェイクワード検出ループの監督（会話中は pause しマイクを譲る）。
- 会話を別スレッドの asyncio ループで実行。
- 状態変更の通知。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Callable

from ..adapter.wake_word_oww import WakeWordLoop
from ..domain.state import State
from ..logging_conf import get_logger
from ..usecase.conversation import ConversationUseCase

logger = get_logger("controller")


class Orchestrator:
    """アプリの中枢。UI からは start/stop と状態購読のみ見えればよい。"""

    def __init__(
        self,
        conversation: ConversationUseCase,
        wake_loop: WakeWordLoop,
        on_state_change: Callable[[State], None] | None = None,
    ) -> None:
        self._conversation = conversation
        self._wake_loop = wake_loop
        self._on_state_change = on_state_change or (lambda s: None)
        self._state = State.IDLE
        self._conv_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        return self._state

    def _set_state(self, state: State) -> None:
        self._state = state
        logger.info("state -> %s", state.value)
        try:
            self._on_state_change(state)
        except Exception:  # pragma: no cover
            logger.exception("状態通知コールバックでエラー")

    def start(self) -> None:
        """ウェイクワード待機を開始する。"""
        self._wake_loop.start()
        self._set_state(State.LISTENING)

    def stop(self) -> None:
        """アプリ終了。会話中なら停止し、待機ループも止める。"""
        self._conversation.request_stop()
        self._wake_loop.stop()
        self._set_state(State.IDLE)

    def end_conversation(self) -> None:
        """UI から会話を手動終了。"""
        self._conversation.request_stop()

    def _on_wake(self) -> None:
        with self._lock:
            if self._state == State.CONVERSING:
                return
            self._wake_loop.pause()
            self._conv_thread = threading.Thread(target=self._run_conversation, daemon=True)
            self._conv_thread.start()

    def _run_conversation(self) -> None:
        try:
            self._set_state(State.CONVERSING)
            asyncio.run(self._conversation.execute())
        except Exception:
            logger.exception("会話スレッドで未捕捉の例外")
            self._set_state(State.ERROR)
        finally:
            self._wake_loop.resume()
            self._set_state(State.LISTENING)
