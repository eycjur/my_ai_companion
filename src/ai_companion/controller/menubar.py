"""rumps メニューバー常駐アプリ — Composition Root。

ステータスアイコン: 待機中 / 会話中 / エラー
メニュー: 会話を終了 / ログを開く / 自動起動を解除して終了 / 終了
重い処理はすべて Orchestrator（別スレッド）に委譲し、AppKit メインスレッドを塞がない。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import rumps

from ..adapter.gemini_live import GeminiLiveSessionFactory
from ..adapter.memory_sqlite import SQLiteMemoryStore
from ..adapter.wake_word_oww import OpenWakeWordDetector, WakeWordLoop
from ..config import Settings
from ..domain.state import State
from ..logging_conf import get_logger, setup_logging
from ..usecase.conversation import ConversationUseCase
from ..usecase.memory_consolidation import MemoryConsolidationUseCase
from .orchestrator import Orchestrator

logger = get_logger("app")

# LaunchAgent のラベル（Makefile の LABEL と一致させること）。
# 「自動起動を解除」メニューから plist を削除＆アンロードするのに使う。
LAUNCH_AGENT_LABEL = "com.my-ai-companion"
LAUNCH_AGENT_PLIST = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)

# 常駐時のログ出力先。plist の StandardErrorPath と一致させること。
# （フォアグラウンド `make run` では stderr＝ターミナルに出るため、このファイルは無い）
LOG_FILE = Path.home() / "Library" / "Logs" / "ai-companion.err.log"

_STATUS_TITLE = {
    State.IDLE: "\U0001f916",
    State.LISTENING: "\U0001f916",
    State.CONVERSING: "\U0001f916\U0001f4ac",
    State.ERROR: "\U0001f916\u26a0\ufe0f",
}


def _build_orchestrator(settings: Settings, on_state: callable) -> Orchestrator:
    """adapter / usecase / orchestrator を組み立てる（Composition Root）。"""
    # Memory（常時有効）
    memory_store = SQLiteMemoryStore(settings.memory_dir)
    memory_store.ensure_initialized()
    from ..adapter.gemini_text import GeminiTextConsolidator
    consolidator = GeminiTextConsolidator(settings.gemini_api_key, settings.memory_model)
    consolidation = MemoryConsolidationUseCase(memory_store, consolidator)

    # Session factory
    session_factory = GeminiLiveSessionFactory(settings)

    # Use case
    conversation_uc = ConversationUseCase(
        persona=settings.persona,
        session_factory=session_factory,
        memory_store=memory_store,
        consolidation=consolidation,
        memory_recent_sessions=settings.memory_recent_sessions,
    )

    # Wake word
    detector = OpenWakeWordDetector(
        wake_model=settings.effective_wake_model,
        threshold=settings.wake_threshold,
    )

    # Orchestrator（on_detected は orchestrator 自身のメソッドを後から設定）
    orchestrator = Orchestrator(
        conversation=conversation_uc,
        wake_loop=WakeWordLoop(detector, on_detected=lambda: None),
        on_state_change=on_state,
    )
    # WakeWordLoop のコールバックを orchestrator に接続
    orchestrator._wake_loop._on_detected = orchestrator._on_wake

    return orchestrator


def run() -> int:
    setup_logging()
    settings = Settings.load()
    problems = settings.validate()
    if problems:
        for p in problems:
            logger.error("設定エラー: %s", p)
        print(
            "\n設定が不足しています。.env を確認してください:\n  - "
            + "\n  - ".join(problems),
            file=sys.stderr,
        )
        return 1

    class App(rumps.App):
        def __init__(self) -> None:
            super().__init__(_STATUS_TITLE[State.LISTENING], quit_button=None)
            self.orchestrator = _build_orchestrator(settings, on_state=self._on_state)
            self.menu = [
                rumps.MenuItem("会話を終了", callback=self._end_conversation),
                rumps.MenuItem("ログを開く", callback=self._open_log),
                None,
                rumps.MenuItem("自動起動を解除して終了", callback=self._disable_autostart),
                rumps.MenuItem("終了", callback=self._quit),
            ]
            self.orchestrator.start()

        def _on_state(self, state: State) -> None:
            self.title = _STATUS_TITLE.get(state, "\U0001f916")

        def _end_conversation(self, _sender) -> None:
            self.orchestrator.end_conversation()

        def _open_log(self, _sender) -> None:
            """ログファイルを既定アプリで開く。

            常駐時は plist が stderr をここへ転送する。フォアグラウンド起動では
            ファイルが無いので、その旨を知らせる（ログはターミナルに出ている）。
            """
            if LOG_FILE.exists():
                subprocess.run(["open", str(LOG_FILE)], check=False)
            else:
                rumps.alert(
                    title="ログファイルがありません",
                    message=(
                        f"{LOG_FILE} が見つかりません。\n"
                        "フォアグラウンド（make run）起動時はログはターミナルに出ます。"
                    ),
                )

        def _disable_autostart(self, _sender) -> None:
            """LaunchAgent を解除して終了（次回ログインから自動起動しない）。

            plist 実体を消してからラベル指定で bootout する。`make run` で直接
            起動した場合（plist 不在・未登録）でもエラーにせず、ふつうに終了する。
            """
            self.orchestrator.stop()
            try:
                LAUNCH_AGENT_PLIST.unlink(missing_ok=True)
                subprocess.run(
                    ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
                    check=False,
                    capture_output=True,
                )
            except OSError as e:
                logger.warning("自動起動の解除に失敗: %s", e)
            rumps.quit_application()

        def _quit(self, _sender) -> None:
            self.orchestrator.stop()
            rumps.quit_application()

    App().run()
    return 0
