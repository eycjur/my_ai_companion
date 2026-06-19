"""Gemini Text API アダプタ — 会話要約・プロフィール更新用。"""
from __future__ import annotations

from google import genai

from ..logging_conf import get_logger

logger = get_logger("gemini_text")


class GeminiTextConsolidator:
    """ConsolidationPort の具象実装。Gemini Text API で要約を生成する。"""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, prompt: str) -> str:
        """プロンプトを送り、応答テキストを返す。"""
        response = self._client.models.generate_content(
            model=self._model, contents=prompt,
        )
        text = response.text
        if not text:
            raise ValueError("consolidation 応答が空です")
        return text
