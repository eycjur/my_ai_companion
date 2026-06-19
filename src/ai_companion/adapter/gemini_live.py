"""Gemini Live セッション — リアルタイム音声会話の中核。

責務:
- Live API へ接続（system instruction / 音声出力 / 書き起こし /
  context window compression / session resumption / voice を設定）。
- マイク PCM を送信し、受信音声を再生。バージイン（interrupted）で再生をフラッシュ。
- 会話中のユーザー発話から終了ワードを検出する。
- 終了条件: 終了ワード / 無音タイムアウト / 外部停止イベント。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from google import genai
from google.genai import types

from ..config import Settings
from ..domain.transcript import Transcript, TranscriptCollector
from ..logging_conf import get_logger
from .audio_sounddevice import MicrophoneStream, SpeakerStream

logger = get_logger("live_session")

_AUDIO_TOKENS_PER_SEC = 25
_COMPRESSION_TARGET_SECS = 3 * 60
_COMPRESSION_TRIGGER_SECS = _COMPRESSION_TARGET_SECS * 2

COMPRESSION_TARGET_TOKENS = _COMPRESSION_TARGET_SECS * _AUDIO_TOKENS_PER_SEC
COMPRESSION_TRIGGER_TOKENS = _COMPRESSION_TRIGGER_SECS * _AUDIO_TOKENS_PER_SEC

_GOOGLE_SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())

_SEARCH_MEMORY_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_memory",
            description=(
                "ユーザーが過去の会話内容について尋ねたとき、"
                "キーワードで長期記憶を検索する。"
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "検索キーワード（例: 京都 旅行）",
                    },
                },
                "required": ["query"],
            },
        ),
    ]
)


def _build_tools(memory_search: Callable[[str], list[str]] | None) -> list[types.Tool]:
    tools: list[types.Tool] = [_GOOGLE_SEARCH_TOOL]
    if memory_search is not None:
        tools.append(_SEARCH_MEMORY_TOOL)
    return tools


class LiveSession:
    """1 回の会話セッションを管理する。終了条件成立まで会話を続ける。"""

    def __init__(
        self,
        settings: Settings,
        system_instruction: str,
        *,
        on_state: Callable[[str], None] | None = None,
        memory_search: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._settings = settings
        self._system_instruction = system_instruction
        self._on_state = on_state or (lambda s: None)
        self._memory_search = memory_search

        self._stop = asyncio.Event()
        self._last_user_activity = time.monotonic()
        self._cur_user = ""

        self._mic: MicrophoneStream | None = None
        self._speaker: SpeakerStream | None = None
        self._resumption_handle: str | None = None
        self._suppress_output = False
        self._model_output_active = False
        self._transcript = TranscriptCollector()

    def request_stop(self) -> None:
        self._stop.set()

    def _build_config(self) -> types.LiveConnectConfig:
        vad = types.AutomaticActivityDetection(
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
            prefix_padding_ms=self._settings.barge_in_prefix_ms,
            silence_duration_ms=500,
        )
        activity_handling = types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
        tools = _build_tools(self._memory_search)
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text=self._system_instruction)]),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._settings.voice)
                )
            ),
            tools=tools,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=COMPRESSION_TRIGGER_TOKENS,
                sliding_window=types.SlidingWindow(target_tokens=COMPRESSION_TARGET_TOKENS),
            ),
            session_resumption=types.SessionResumptionConfig(handle=self._resumption_handle),
            realtime_input_config=types.RealtimeInputConfig(
                activity_handling=activity_handling,
                automatic_activity_detection=vad,
            ),
        )

    async def run(self) -> Transcript:
        """会話を実行する。終了時にトランスクリプトを返す。"""
        client = genai.Client(api_key=self._settings.gemini_api_key)
        loop = asyncio.get_running_loop()

        self._speaker = SpeakerStream()
        self._speaker.start()
        self._mic = MicrophoneStream(loop)
        self._mic.start()
        self._on_state("conversing")
        if self._settings.mute_mic_during_output:
            logger.info(
                "AI 発話中はマイク入力を API に送りません（AICP_MUTE_MIC_DURING_OUTPUT=true）。"
            )

        try:
            while not self._stop.is_set():
                config = self._build_config()
                try:
                    async with client.aio.live.connect(
                        model=self._settings.live_model, config=config
                    ) as session:
                        await self._converse(session)
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    logger.warning("Live セッションが切断、再接続を試みます: %s", exc)
                    await asyncio.sleep(0.5)
                    continue
                break
        finally:
            if self._mic:
                self._mic.stop()
            if self._speaker:
                self._speaker.stop()

        return self._transcript.finalize()

    async def _converse(self, session) -> None:
        send_task = asyncio.create_task(self._send_audio(session))
        recv_task = asyncio.create_task(self._receive(session))
        idle_task = asyncio.create_task(self._watch_idle())
        try:
            await asyncio.wait(
                {send_task, recv_task, idle_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (send_task, recv_task, idle_task):
                t.cancel()
            await asyncio.gather(send_task, recv_task, idle_task, return_exceptions=True)

    async def _send_audio(self, session) -> None:
        assert self._mic is not None
        async for chunk in self._mic.chunks():
            if self._stop.is_set():
                return
            if self._should_suppress_mic():
                continue
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    def _should_suppress_mic(self) -> bool:
        if not self._settings.mute_mic_during_output:
            return False
        if self._model_output_active:
            return True
        if self._speaker is not None and self._speaker.has_pending():
            return True
        return False

    async def _receive(self, session) -> None:
        while not self._stop.is_set():
            async for response in session.receive():
                if self._stop.is_set():
                    return
                await self._handle_response(session, response)

    async def _handle_tool_call(self, session, tool_call) -> None:
        if not self._memory_search or not tool_call:
            return
        function_responses: list[types.FunctionResponse] = []
        for fc in tool_call.function_calls or []:
            if fc.name != "search_memory":
                continue
            query = str((fc.args or {}).get("query", "")).strip()
            results = self._memory_search(query) if query else []
            text = "\n".join(f"- {r}" for r in results) if results else "（該当する記憶は見つかりませんでした）"
            logger.info("search_memory: query=%r hits=%d", query, len(results))
            function_responses.append(
                types.FunctionResponse(
                    name=fc.name,
                    id=fc.id,
                    response={"memories": text},
                )
            )
        if function_responses:
            await session.send_tool_response(function_responses=function_responses)

    async def _handle_response(self, session, response) -> None:
        if getattr(response, "tool_call", None):
            await self._handle_tool_call(session, response.tool_call)
            return

        sru = getattr(response, "session_resumption_update", None)
        if sru is not None and getattr(sru, "new_handle", None):
            self._resumption_handle = sru.new_handle

        content = getattr(response, "server_content", None)
        if not content:
            return

        if getattr(content, "interrupted", None) is True:
            logger.info("割り込みを検出。再生キューをフラッシュします。")
            self._suppress_output = True
            self._model_output_active = False
            if self._speaker:
                self._speaker.flush()

        if not self._suppress_output:
            model_turn = getattr(content, "model_turn", None)
            if model_turn and getattr(model_turn, "parts", None):
                for part in model_turn.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None) and self._speaker:
                        self._model_output_active = True
                        self._speaker.play(inline.data)

        in_tr = getattr(content, "input_transcription", None)
        if in_tr and getattr(in_tr, "text", None):
            self._cur_user += in_tr.text
            self._transcript.append_user(in_tr.text)
            self._last_user_activity = time.monotonic()

        out_tr = getattr(content, "output_transcription", None)
        if out_tr and getattr(out_tr, "text", None):
            self._transcript.append_assistant(out_tr.text)

        if getattr(content, "turn_complete", None):
            if self._suppress_output:
                logger.debug("割り込みターン完了。モデル音声の再生を再開します。")
            self._suppress_output = False
            self._model_output_active = False
            self._check_farewell()
            self._transcript.on_turn_complete()
            self._cur_user = ""

    def _check_farewell(self) -> None:
        keywords = self._settings.persona.farewell_keywords
        if not keywords or not self._cur_user:
            return
        if any(kw in self._cur_user for kw in keywords):
            logger.info("終了ワードを検出。会話を終了します。")
            self._stop.set()

    async def _watch_idle(self) -> None:
        timeout = self._settings.silence_timeout
        while not self._stop.is_set():
            await asyncio.sleep(1.0)
            if time.monotonic() - self._last_user_activity > timeout:
                logger.info("無音タイムアウト（%.0fs）。会話を終了します。", timeout)
                self._stop.set()
                return


class GeminiLiveSessionFactory:
    """LiveSession の生成ファクトリ。controller 層が利用する。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(
        self,
        system_instruction: str,
        *,
        memory_search: Callable[[str], list[str]] | None = None,
    ) -> LiveSession:
        return LiveSession(
            self._settings,
            system_instruction=system_instruction,
            memory_search=memory_search,
        )
