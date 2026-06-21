# My AI Companion — 開発 & 常駐(launchd)管理
#
# 常駐まわりは macOS の LaunchAgent を使う。launchd は ~ や環境変数を展開しないため、
# packaging/*.plist.template のプレースホルダ(__PROJECT_DIR__ / __HOME__)を register 時に
# sed で絶対パスへ置換し、~/Library/LaunchAgents/ に実体を生成する。

LABEL          := com.my-ai-companion
PLIST_TEMPLATE := $(CURDIR)/packaging/$(LABEL).plist.template
PLIST_DST      := $(HOME)/Library/LaunchAgents/$(LABEL).plist
GUI_TARGET     := gui/$(shell id -u)/$(LABEL)

# テンプレートのプレースホルダを実パスへ置換して PLIST_DST を生成する（sed の区切りは | ）。
define GEN_PLIST
	mkdir -p "$(dir $(PLIST_DST))"
	sed -e 's|__PROJECT_DIR__|$(CURDIR)|g' -e 's|__HOME__|$(HOME)|g' \
		"$(PLIST_TEMPLATE)" > "$(PLIST_DST)"
endef

.DEFAULT_GOAL := help

# --- 開発 -------------------------------------------------------------------

.PHONY: install
install: ## 依存をインストールし、ウェイクワードのモデルを取得（初回セットアップ）
	uv sync
	uv run python -c "import openwakeword.utils as u; u.download_models()"

.PHONY: run
run: ## メニューバー常駐をフォアグラウンドで起動（開発用）
	uv run python -m ai_companion

.PHONY: dev
dev: ## コンソール版を起動（開発用・ウェイクワード不要で対話）
	uv run python -m ai_companion.controller.console

.PHONY: test
test: ## 単体テストを実行
	uv run pytest

# --- 常駐(launchd) ----------------------------------------------------------

.PHONY: register
register: ## LaunchAgent を生成・登録して常駐開始（ログイン時も自動起動）
	$(GEN_PLIST)
	launchctl load -w "$(PLIST_DST)"
	@echo "✅ 常駐を開始しました。メニューバーに 🤖 が出れば成功です。"

.PHONY: unregister
unregister: ## 常駐を停止して LaunchAgent を解除（自動起動も無効化）
	-launchctl unload -w "$(PLIST_DST)"
	-rm -f "$(PLIST_DST)"
	@echo "🗑  常駐を解除しました。"

.PHONY: restart
restart: ## 再起動（コード変更の反映や、メニューの「終了」後に動かし直すとき）
	launchctl kickstart -k "$(GUI_TARGET)"

.PHONY: status
status: ## 常駐状態を表示
	@launchctl print "$(GUI_TARGET)" 2>/dev/null | grep -E 'state|pid|last exit' \
		|| echo "未登録です。'make register' で登録してください。"

.PHONY: logs
logs: ## ログを追尾表示（Ctrl-C で抜ける）
	tail -f "$(HOME)/Library/Logs/ai-companion.err.log"

.PHONY: help
help: ## このヘルプを表示
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
