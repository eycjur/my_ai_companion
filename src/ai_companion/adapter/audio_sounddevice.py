"""音声 I/O — マイク入力（16kHz）とスピーカー出力（24kHz）。

設計は docs/DESIGN.md「音声パイプライン」を参照。
- 入力: sounddevice.RawInputStream で 16kHz/mono/int16 を取得し asyncio.Queue へ。
- 出力: 受信した 24kHz/mono/int16 PCM を OutputStream で再生。バージイン時はフラッシュ。
"""
from __future__ import annotations

import asyncio
import queue
import threading

import sounddevice as sd

from ..logging_conf import get_logger

logger = get_logger("audio")

INPUT_SAMPLE_RATE = 16000   # Gemini Live 入力（必須）
OUTPUT_SAMPLE_RATE = 24000  # Gemini Live 出力（必須）
CHANNELS = 1
DTYPE = "int16"
INPUT_BLOCKSIZE = 640       # 40ms 分（16000 * 0.04）— Live API 推奨レンジ


class MicrophoneStream:
    """マイクから 16kHz/int16 PCM を読み、asyncio キューに供給する。

    sounddevice のコールバックは別スレッドで動くため、スレッドセーフな
    queue.Queue を介し、`chunks()` 側で asyncio に橋渡しする。
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._stream = None
        self._closed = False

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            logger.debug("input status: %s", status)
        data = bytes(indata)
        # コールバックスレッド → イベントループへ安全に渡す
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, data)
        except RuntimeError:
            pass  # ループ終了済み
        except asyncio.QueueFull:
            logger.debug("mic queue full, dropping frame")

    def start(self) -> None:
        self._stream = sd.RawInputStream(
            samplerate=INPUT_SAMPLE_RATE,
            blocksize=INPUT_BLOCKSIZE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()
        logger.info("マイク入力を開始（%dHz）。", INPUT_SAMPLE_RATE)

    async def chunks(self):
        """PCM チャンクを非同期に yield する。"""
        while not self._closed:
            chunk = await self._queue.get()
            yield chunk

    def stop(self) -> None:
        self._closed = True
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # pragma: no cover
                pass
            self._stream = None
        logger.info("マイク入力を停止。")


class SpeakerStream:
    """24kHz/int16 PCM を再生する。バージイン時にキューをフラッシュ。

    出力は専用スレッドで queue.Queue から取り出して書き込む。
    flush 時は世代カウンタを進め、キュー内と書き込み待ちの古いチャンクを無効化する。
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[tuple[int, bytes] | None]" = queue.Queue()
        self._stream = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._generation = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stream = sd.RawOutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
        )
        self._stream.start()
        self._running = True
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()
        logger.info("スピーカー出力を開始（%dHz）。", OUTPUT_SAMPLE_RATE)

    def _writer(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                continue
            generation, data = item
            with self._lock:
                if generation != self._generation:
                    continue
            try:
                self._stream.write(data)  # type: ignore[union-attr]
            except Exception as exc:  # pragma: no cover
                logger.debug("output write error: %s", exc)

    def play(self, pcm: bytes) -> None:
        if self._running and pcm:
            with self._lock:
                generation = self._generation
            self._queue.put((generation, pcm))

    def flush(self) -> None:
        """再生待ちをすべて破棄（バージイン対応）。"""
        with self._lock:
            self._generation += 1
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        logger.debug("再生キューをフラッシュ（割り込み, generation=%d）。", self._generation)

    def has_pending(self) -> bool:
        """再生待ちキューにデータがあるか。"""
        return not self._queue.empty()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # pragma: no cover
                pass
            self._stream = None
        logger.info("スピーカー出力を停止。")
