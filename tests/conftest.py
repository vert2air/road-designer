"""pytest 設定ファイル。

tests/ から実行するとき src/ をインポートパスに追加する。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
