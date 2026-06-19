# 設計ドキュメント — My AI Companion（macOS 常駐 AI コンパニオン）

## 概要

macOS に常駐し、ウェイクワードで起動して **Gemini Live API** による自然な音声会話を行う
AI コンパニオン。会話中の文脈は Live API のセッションコンテキストが保持し、会話が終わると
要約とプロフィールをローカルに書き出して長期記憶へ積み重ねる（長期記憶は常時有効）。
音声・生の書き起こし全文はディスクに残さない。


---

## 技術スタック

| 役割 | 採用技術 |
|------|----------|
| 常駐 UI | `rumps`（macOS メニューバーアプリ） |
| ウェイクワード | **openWakeWord**（無料・APIキー不要・OSS） |
| 音声 I/O | `sounddevice` + `numpy`（入力 16kHz / 出力 24kHz / int16 / mono） |
| 会話 | **Gemini Live API** `google-genai`（`gemini-3.1-flash-live-preview`） |
| 設定 | `.env`（`python-dotenv`）→ `config.py` の `Settings` データクラス |
| ペルソナ | `domain/persona.py` の `Persona` データクラス。名前は `.env` から設定 |

> **方針: フォールバックを設けない。** 必要な依存は在る前提で、無ければ素直に例外を送出する。

---

## アーキテクチャ

4 層クリーンアーキテクチャを採用。依存方向は常に外側→内側。

```
controller/  ──→  usecase/  ──→  domain/
     │                              ↑
     └──→  adapter/  ───────────────┘
```

- **domain**: 純粋なエンティティ・値オブジェクト・ポート（Protocol）。外部依存ゼロ。
- **usecase**: アプリケーション固有のオーケストレーション。ポート経由で I/O。
- **adapter**: domain ポートの具象実装（Gemini SDK, sounddevice, openWakeWord, SQLite）。
- **controller**: エントリーポイント。adapter → usecase の DI 組み立て（Composition Root）。

```
controller/menubar(rumps) ── Orchestrator（状態機械）
                                  │
                     ConversationUseCase
                       ├─ build_system_instruction  (domain)
                       ├─ GeminiLiveSession          (adapter)
                       └─ MemoryConsolidationUseCase (usecase)
                                  │
                         ┌────────┴────────┐
                    WakeWordLoop      LiveSession
                  (openWakeWord)    (Gemini Live)
                                        │
                               MicrophoneStream (16kHz)
                               SpeakerStream   (24kHz)
```

### ディレクトリ構成

```
src/ai_companion/
├── __init__.py                      バージョン情報
├── __main__.py                      python -m ai_companion エントリポイント
├── config.py                        Settings データクラス、.env ロード
├── logging_conf.py                  ロギング設定
│
├── domain/                          純粋ドメイン（外部依存ゼロ）
│   ├── persona.py                   Persona データクラス + system instruction 合成
│   ├── transcript.py                Turn / Transcript / TranscriptCollector
│   ├── state.py                     State enum (IDLE/LISTENING/CONVERSING/ERROR)
│   └── ports.py                     Protocol インターフェース定義
│
├── usecase/                         アプリケーションロジック
│   ├── conversation.py              ConversationUseCase（会話実行・記憶統合）
│   └── memory_consolidation.py      MemoryConsolidationUseCase（要約・profile 更新）
│
├── adapter/                         外部依存の具象実装
│   ├── gemini_live.py               LiveSession + GeminiLiveSessionFactory
│   ├── gemini_text.py               GeminiTextConsolidator（Text API）
│   ├── audio_sounddevice.py         MicrophoneStream / SpeakerStream
│   ├── wake_word_oww.py             OpenWakeWordDetector / WakeWordLoop
│   └── memory_sqlite.py             SQLiteMemoryStore（profile.txt + episodic.db）
│
└── controller/                      エントリーポイント + DI 組み立て
    ├── orchestrator.py              状態機械（スリム版）
    ├── menubar.py                   rumps App + Composition Root
    └── console.py                   コンソールランナー（開発用）
```

---

## 状態機械

```
起動
 │
 ▼
LISTENING ──── ウェイクワード検出 ────▶ CONVERSING
    ▲                                       │
    └──────────── 会話終了 ─────────────────┘
                  （終了ワード / 無音タイムアウト / 手動停止）
```

- **LISTENING**: openWakeWord が 16kHz PCM を軽量ループで監視。検出で CONVERSING へ遷移し、マイクを Live セッションに譲る。
- **CONVERSING**: Live セッション実行中。終了条件成立で戻り、ウェイクワード検出を再開。

状態機械は `controller/orchestrator.py` の `Orchestrator` クラスが管理する。
会話ロジックは `usecase/conversation.py` の `ConversationUseCase` に委譲。

---

## system instruction の構成

会話開始時に `domain/persona.py` の `build_system_instruction()` が以下を合成して Live API に渡す:

```
キャラクター設定   ← Persona クラス（名前は .env、性格・話し方はデフォルト値）
倫理ガードレール  ← AIであることの誠実さ / 過度な依存を煽らない / 安全配慮
現在日時          ← 会話開始時刻を固定値で埋め込み（例: 2026年6月18日（木）21時30分）
呼び方            ← user_nickname または会話中に自然に尋ねる旨
記憶コンテキスト  ← profile + 直近 N 回の要約（常時注入）
話し方ガイドライン ← 短文・共感・深掘り 1 問など音声向けのコツ
対話のコツ        ← Persona.dialogue_patterns
```

---

## 音声パイプライン

- **入力**: `sounddevice.RawInputStream(16kHz, int16, mono, blocksize=640)` → 40ms チャンク → `session.send_realtime_input(audio/pcm;rate=16000)`
- **出力**: 受信 `inline_data.data`（24kHz int16）→ `sounddevice.RawOutputStream` 再生キュー
- **バージイン**: `content.interrupted` を検知したら再生キューをフラッシュ
- **ウェイク検出フェーズと会話フェーズはマイクを排他利用**（フェーズ遷移でデバイスをハンドオフ）

---

## Context Window Compression

音声は約 25 トークン/秒でコンテキストに蓄積するため、長時間会話向けに圧縮を設定している。

```python
COMPRESSION_TARGET_TOKENS  = 4_500  # 3分分を残す  (3 × 60 × 25)
COMPRESSION_TRIGGER_TOKENS = 9_000  # 6分分で圧縮発動 (target × 2)
```

6 分分溜まったら古い方を捨てて 3 分分に圧縮する。Session resumption と組み合わせることで
WebSocket リセット後も会話を継続できる。

---

## 終了条件

| 条件 | 説明 |
|------|------|
| 終了ワード | `Persona.farewell_keywords` に定義した語がユーザー発話に含まれる |
| 無音タイムアウト | ユーザー発話が `AICP_SILENCE_TIMEOUT`（既定 45 秒）ない |
| 手動停止 | メニューバー「会話を終了」 |

---

## 設定

| 環境変数 | 既定値 | 説明 |
|----------|--------|------|
| `GEMINI_API_KEY` | — | 必須 |
| `AICP_PERSONA_NAME` | `Jarvis` | コンパニオンの名前 |
| `AICP_USER_NICKNAME` | — | 相手の呼び方（未設定なら会話中に尋ねる） |
| `AICP_WAKE_MODEL` | `hey_jarvis` | openWakeWord モデル名 |
| `AICP_WAKE_THRESHOLD` | `0.5` | 検出スコアのしきい値 |
| `AICP_WAKE_MODEL_PATH` | — | カスタム `.onnx`/`.tflite` パス |
| `AICP_LIVE_MODEL` | `gemini-3.1-flash-live-preview` | Gemini Live モデル |
| `AICP_VOICE` | `Aoede` | 音声名 |
| `AICP_SILENCE_TIMEOUT` | `45` | 無音タイムアウト（秒） |
| `AICP_MUTE_MIC_DURING_OUTPUT` | `true` | AI 発話中のマイク送信抑止 |
| `AICP_BARGE_IN_PREFIX_MS` | `500` | 割り込みとみなす発話の最小長（ms） |
| `AICP_LOG_LEVEL` | `INFO` | ログレベル |
| `AICP_MEMORY_DIR` | `~/Library/Application Support/ai_companion/memory/` | 記憶保存先 |
| `AICP_MEMORY_RECENT_SESSIONS` | `3` | ウォームスタート注入件数 |
| `AICP_MEMORY_MODEL` | `gemini-2.0-flash` | consolidation モデル |

名前は `.env` の `AICP_PERSONA_NAME` で設定する。
性格・口調・終了ワード・対話パターンは `src/ai_companion/domain/persona.py` の `Persona` クラスのデフォルト値を編集する。

---

## 長期記憶（常時有効）

長期記憶は常時有効。

```
memory/
├── profile.txt     # semantic（ユーザーが編集可、プレーンテキスト）
└── episodic.db     # episodic（SQLite + FTS5）
```

| 系統 | タイミング | 仕組み |
|------|-----------|--------|
| A ウォームスタート | 会話開始前 | profile 全件 + 直近 N 要約 → system instruction |
| B recall | 会話中 | `search_memory` tool → summary の FTS5 検索 |
| Web 検索 | 会話中 | Google Search（常時、サーバー側で自動実行） |
| 書き込み | 会話終了後 | Gemini Text API で要約・fact 抽出（非同期） |

---

## プライバシー

- 音声・生の書き起こし全文はディスクに保存しない（揮発）。
- ローカル保存はテキスト要約・profile のみ。consolidation 時に Gemini Text API へ送信。
- 外部送信は Gemini API のみ。
