# My AI Companion — macOS 常駐 AI コンパニオン 🤖

ウェイクワードで起動し、**Gemini Live API** によるリアルタイム音声会話を行う
macOS メニューバー常駐の AI コンパニオン。長期記憶は常時有効で、会話の要約と
プロフィールを積み重ねていく（音声・生の書き起こしはディスクに残さない）。

## 特長

- 🎙 **ウェイクワード常駐**: openWakeWord（無料・APIキー不要）で軽量に常時待機。
- 💬 **リアルタイム音声会話**: Gemini Live（`gemini-3.1-flash-live-preview`）。割り込み（バージイン）対応。
- 🕒 **現在日時を把握**: 会話開始時に日付・時刻・曜日をプロンプトに埋め込む。
- 🫶 **一貫した人格**: `Persona` データクラスでキャラクターを定義。名前は `.env` で設定。
- 🌐 **英会話練習**: ユーザーが英語で話したら英語で返す（日本語に戻れば自然に切り替え）。
- 🔒 **音声は揮発**: ディスクに残すのは会話の要約とプロフィールのみ。音声・生の書き起こし全文は保存しない。
- 🌐 **Google 検索（常時）**: Gemini Live の Grounding with Google Search で最新情報を取得。
- 🧠 **長期記憶（常時有効）**: `profile.txt`（ユーザー編集可）+ SQLite（要約のキーワード検索）。

## アーキテクチャ

```
controller/menubar(rumps) → Orchestrator(状態機械: LISTENING → CONVERSING → LISTENING)
   │                             │
   │  ConversationUseCase ◄──────┘
   │    ├─ Persona + build_system_instruction  (domain)
   │    ├─ GeminiLiveSession                   (adapter)
   │    └─ MemoryConsolidationUseCase          (usecase, 常時有効)
   │
   └─ WakeWordLoop(openWakeWord)               (adapter)
```

4 層クリーンアーキテクチャ（domain / usecase / adapter / controller）を採用。
詳細は [docs/DESIGN.md](docs/DESIGN.md) を参照。

## セットアップ（macOS）

### 前提
- macOS（Apple Silicon / Intel）、Python 3.13+
- [Gemini API キー](https://aistudio.google.com/apikey)

### インストール
```bash
make install   # 依存をインストールし、openWakeWord のモデルを取得（初回のみ）
```

`make` を使わない場合は直接:
```bash
uv sync
uv run python -c "import openwakeword.utils as u; u.download_models()"
```

### 設定
```bash
cp .env.example .env
# GEMINI_API_KEY を設定（必須）
```

### 起動
```bash
make run    # メニューバー常駐（フォアグラウンド）
make dev    # コンソール版（開発用・ウェイクワード不要で対話）
```

🤖 が出たら待機中。**"Hey Jarvis"**（`hey_jarvis` モデル）と話しかけると 🤖💬 になり会話開始。
「またね」「おやすみ」などで終了すると 🤖 に戻る。

### バックグラウンド常駐（launchd）

ターミナルを閉じても動き続け、ログイン時に自動起動させたい場合は macOS の
LaunchAgent に登録する。リポジトリには[テンプレート](packaging/com.my-ai-companion.plist.template)
だけを置き、`make register` がパスを埋めて `~/Library/LaunchAgents/` に実体を生成する
（launchd は `~` を展開しないため絶対パスが必要）。管理は `Makefile` 経由で行う。

```bash
make register     # LaunchAgent を登録して常駐開始（以降ログイン時も自動起動）
make status       # 常駐状態を確認
make logs         # ログを追尾（うまく動かないとき）
make unregister   # 常駐を解除（自動起動も無効化）
```

| コマンド | 説明 |
|----------|------|
| `make register` | `~/Library/LaunchAgents/` に登録し即起動。クラッシュ時のみ自動再起動 |
| `make unregister` | 停止して登録を解除 |
| `make restart` | 再起動（コード変更の反映や、メニューの「終了」後に動かし直すとき） |
| `make status` | 稼働状態・PID・最終終了コードを表示 |
| `make logs` | `~/Library/Logs/ai-companion.err.log` を追尾 |

メニューバーの 🤖 をクリックすると次が選べる:

- **会話を終了** — 進行中の会話だけ打ち切り、待機に戻す（常駐は継続）
- **ログを開く** — `~/Library/Logs/ai-companion.err.log` を既定アプリで開く（常駐時のログ）
- **自動起動を解除して終了** — plist を削除＆アンロードしてアプリ終了（`make unregister` 相当。次回ログインから出ない）
- **終了** — アプリを終了するだけ（登録は残るので次回ログインで自動復活）

「終了」したあと再び動かすには `make restart`。

> **メモ**: 生成される plist は venv の Python（`.venv/bin/python`）と作業ディレクトリを
> 絶対パスで持つ。別の場所に clone・移動した場合は、その場所で `make unregister && make register`
> すればパスが更新される。初回のマイクアクセス時に許可ダイアログが出る（出ない場合は
> システム設定 → プライバシーとセキュリティ → マイク で Python を許可）。

## カスタマイズ

### 環境変数（`.env`）

| 環境変数 | 既定値 | 説明 |
|----------|--------|------|
| `GEMINI_API_KEY` | — | 必須。`GOOGLE_API_KEY` でも可 |
| `AICP_PERSONA_NAME` | `Jarvis` | コンパニオンの名前 |
| `AICP_USER_NICKNAME` | — | 相手の呼び方（未設定なら会話中に尋ねる） |
| `AICP_WAKE_MODEL` | `hey_jarvis` | openWakeWord モデル名 |
| `AICP_WAKE_THRESHOLD` | `0.5` | 検出スコアのしきい値（低いほど反応しやすい） |
| `AICP_WAKE_MODEL_PATH` | — | カスタム `.onnx`/`.tflite` パス（設定時は `AICP_WAKE_MODEL` より優先。相対パスは CWD 基準） |
| `AICP_LIVE_MODEL` | `gemini-3.1-flash-live-preview` | Gemini Live モデル |
| `AICP_VOICE` | `Aoede` | 音声名 |
| `AICP_SILENCE_TIMEOUT` | `45` | 無音タイムアウト（秒） |
| `AICP_MUTE_MIC_DURING_OUTPUT` | `true` | AI 発話中にマイク送信を抑止（`false` で割り込みしやすく） |
| `AICP_BARGE_IN_PREFIX_MS` | `500` | 割り込みとみなす発話の最小長（ms） |
| `AICP_LOG_LEVEL` | `INFO` | ログレベル |
| `AICP_MEMORY_DIR` | `~/Library/Application Support/ai_companion/memory/` | 記憶ファイルの保存先 |
| `AICP_MEMORY_RECENT_SESSIONS` | `3` | 会話開始時に注入する直近セッション数 |
| `AICP_MEMORY_MODEL` | `gemini-2.0-flash` | 会話終了後の要約・fact 抽出モデル |

### 長期記憶

```
~/Library/Application Support/ai_companion/memory/
├── profile.txt     # プレーンテキスト（内容はそのままプロンプトに注入）
└── episodic.db     # セッション要約 + summary の FTS5 検索
```

- **会話開始前**: profile + 直近 N 回の要約を system instruction に注入
- **会話中（記憶）**: 「覚えてる？」等で `search_memory` tool → summary を FTS5 検索
- **会話中（Web）**: モデルが必要と判断したとき Google 検索（常時有効）
- **会話終了後**: Gemini Text API で要約・fact 抽出（非同期）

### カスタムウェイクワード

`hey_jarvis` などの事前学習済みモデル以外に、好きな呼びかけ（例: ペルソナの名前）を
自分で学習させて使える。openWakeWord の[自動学習 Colab ノートブック](https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb)
にウェイクワードを文字で入力すると、TTS で合成した学習データからモデルを生成してくれる。

1. Colab でウェイクワードを学習し、**`.onnx` 形式**で書き出す（macOS は基本 ONNX 版が必要）。
2. 生成された `.onnx` を `model/` などに配置する。
3. `.env` で参照する:

   ```bash
   AICP_WAKE_MODEL_PATH=model/haru.onnx   # AICP_WAKE_MODEL より優先。相対パスは CWD 基準
   # 反応が渋ければしきい値を下げる
   AICP_WAKE_THRESHOLD=0.3
   ```

検出されにくい・誤検出が多い場合は `AICP_WAKE_THRESHOLD` を調整する（低いほど反応しやすい）。

### ペルソナ詳細

名前は `.env` の `AICP_PERSONA_NAME` で設定する（既定: `Jarvis`）。
性格・口調・終了ワード・対話パターンは `src/ai_companion/domain/persona.py` の `Persona` クラスのデフォルト値を編集する。

## テスト

外部 SDK（Gemini / マイク）不要の単体テスト:

```bash
uv sync --extra dev
uv run pytest
```

## 注意

- Live API は Preview。モデル名は `.env` で差し替え可能。
- マイク・メニューバー・各 SDK の結合動作は macOS 実機での確認が必要。

## ライセンス
MIT
