"""ロギング設定。

会話の中身（プライバシー情報）はデフォルトでは INFO 以下に出さない。
DEBUG 時のみ transcript の断片が出る可能性があるため、本番では INFO 推奨。
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def _load_dotenv_for_logging() -> None:
    """setup_logging より前に .env を読み、AICP_LOG_LEVEL 等を os.environ に載せる。"""
    from pathlib import Path

    from dotenv import load_dotenv

    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path)
            return


def setup_logging(level: str | None = None) -> None:
    """ルートロガーを一度だけ設定する。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    _load_dotenv_for_logging()

    level_name = (level or os.environ.get("AICP_LOG_LEVEL") or "INFO").upper()
    log_level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """`ai_companion.<name>` 名前空間のロガーを返す。"""
    return logging.getLogger(f"ai_companion.{name}")
