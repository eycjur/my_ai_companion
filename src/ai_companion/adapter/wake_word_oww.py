"""ウェイクワード検出 — openWakeWord（無料・APIキー不要）。

設計は docs/DESIGN.md「状態機械 / 音声パイプライン」を参照。
- 軽量ループでウェイクワードを常時待機し、検出でコールバックを呼ぶ。
- 会話フェーズとはマイクを排他利用するため、検出後は入力ストリームを解放する。
"""
from __future__ import annotations

import threading
from typing import Callable, Protocol

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

from .audio_sounddevice import CHANNELS, DTYPE, INPUT_SAMPLE_RATE
from ..logging_conf import get_logger

logger = get_logger("wake_word")

# openWakeWord 推奨フレーム長（80ms @ 16kHz）
WAKE_FRAME_LENGTH = 1280

_DOWNLOAD_MODELS_CMD = (
    'uv run python -c "import openwakeword.utils as u; u.download_models()"'
)


class WakeWordDetector(Protocol):
    """ウェイクワード検出器の最小インターフェース。"""

    def listen_once(self, should_stop: Callable[[], bool]) -> bool:
        """ウェイクワード検出までブロックする。検出で True、停止要求で False。"""
        ...

    def close(self) -> None:
        ...


class OpenWakeWordDetector:
    """openWakeWord ベースの検出器。検出ごとに入力ストリームを開閉してマイクを譲る。"""

    def __init__(
        self,
        wake_model: str = "hey_jarvis",
        threshold: float = 0.5,
    ) -> None:
        self._wake_model = wake_model
        self._threshold = threshold
        self._model: Model | None = None

    def _ensure_model(self) -> Model:
        if self._model is None:
            inference_framework = (
                "tflite" if self._wake_model.endswith(".tflite") else "onnx"
            )
            try:
                self._model = Model(
                    wakeword_models=[self._wake_model],
                    inference_framework=inference_framework,
                )
            except ValueError as exc:
                msg = str(exc)
                if "tflite runtime" in msg.lower():
                    raise RuntimeError(
                        "ウェイクワードモデルを読み込めません。\n"
                        "  原因: モデルファイルが未ダウンロード、"
                        "または macOS では ONNX 版が必要です。\n"
                        f"  対処: 次を実行してください:\n"
                        f"    {_DOWNLOAD_MODELS_CMD}"
                    ) from exc
                if "Could not find pretrained model" in msg:
                    raise RuntimeError(
                        f"ウェイクワードモデル '{self._wake_model}' が見つかりません。\n"
                        "  対処: .env の AICP_WAKE_MODEL を確認するか、次を実行してください:\n"
                        f"    {_DOWNLOAD_MODELS_CMD}"
                    ) from exc
                if "onnxruntime" in msg.lower():
                    raise RuntimeError(
                        "onnxruntime が見つかりません。\n"
                        "  対処: uv sync を実行してください。"
                    ) from exc
                raise
            logger.info("openWakeWord モデルをロード: %s", self._wake_model)
        return self._model

    def listen_once(self, should_stop: Callable[[], bool]) -> bool:
        model = self._ensure_model()
        model.reset()
        stream = sd.RawInputStream(
            samplerate=INPUT_SAMPLE_RATE,
            blocksize=WAKE_FRAME_LENGTH,
            channels=CHANNELS,
            dtype=DTYPE,
        )
        stream.start()
        logger.info("ウェイクワード待機中…（'%s', しきい値=%.2f）", self._wake_model, self._threshold)
        try:
            while not should_stop():
                data, _overflowed = stream.read(WAKE_FRAME_LENGTH)
                frame = np.frombuffer(bytes(data), dtype=np.int16)
                scores = model.predict(frame)
                max_score = max(scores.values()) if scores else 0.0
                detected = max_score >= self._threshold
                score_text = ", ".join(f"{k}={v:.3f}" for k, v in scores.items())
                logger.debug(
                    "wake score: %s (max=%.3f, threshold=%.2f, detected=%s)",
                    score_text,
                    max_score,
                    self._threshold,
                    detected,
                )
                if detected:
                    logger.info(
                        "ウェイクワードを検出 (score=%.3f, threshold=%.2f).",
                        max_score,
                        self._threshold,
                    )
                    return True
            return False
        finally:
            stream.stop()
            stream.close()

    def close(self) -> None:
        self._model = None


class WakeWordLoop:
    """別スレッドで検出器を回し、検出時にコールバックを呼ぶ。"""

    def __init__(self, detector: WakeWordDetector, on_detected: Callable[[], None]) -> None:
        self._detector = detector
        self._on_detected = on_detected
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                self._stop.wait(0.2)
                continue
            detected = self._detector.listen_once(
                should_stop=lambda: self._stop.is_set() or self._paused.is_set()
            )
            if detected and not self._stop.is_set():
                self._on_detected()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """会話中は検出を止め、マイクを解放させる。"""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._detector.close()
