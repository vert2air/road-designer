"""pytest 設定ファイル。

tests/ から実行するとき src/ をインポートパスに追加する。
また Qt のプラットフォームプラグインをクロスプラットフォームで設定する。

プラットフォーム別の動作:
  Linux/CI : QT_QPA_PLATFORM=offscreen（ディスプレイ不要）
  macOS    : QT_QPA_PLATFORM=offscreen（ヘッドレスCI対応）
  Windows  : 設定しない（Qt が自動的に "windows" プラグインを使う）
             実際のウィンドウが一瞬表示されるが、テスト自体は正常に動作する。
             タスクバーに表示が煩わしい場合は QT_QPA_PLATFORM=offscreen を
             手動で設定することも可能（PySide6 が offscreen DLL を含む場合のみ）。
"""
import sys
import os
import platform

# src/ をインポートパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Qt プラットフォームプラグインの設定
# Windows では offscreen プラグインが同梱されていないため設定しない
if platform.system() != 'Windows':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
