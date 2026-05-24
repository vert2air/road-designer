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

import pytest

# src/ をインポートパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Qt プラットフォームプラグインの設定
# Windows では offscreen プラグインが同梱されていないため設定しない
if platform.system() != 'Windows':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


# ──────────────────────────────────────────────────────────────
# pytest-qt フィクスチャ
#
# qtbot.addWidget(w) でテスト後に自動クリーンアップされる。
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def make_panel_qt(qtbot):
    """qtbot 対応の RightPanel を生成するファクトリフィクスチャ。

    使い方::

        def test_something(qtbot, make_panel_qt):
            p, sc = make_panel_qt()
            with qtbot.waitSignal(p.scene_changed, timeout=1000):
                p._redraw()
    """
    from models import Scene
    from right_panel import RightPanel

    def _factory(scene=None):
        sc = scene if scene is not None else Scene()
        p = RightPanel(sc)
        qtbot.addWidget(p)   # テスト後に自動 close/destroy
        return p, sc

    return _factory


@pytest.fixture
def make_canvas_qt(qtbot):
    """qtbot 対応の Canvas を生成するファクトリフィクスチャ。

    使い方::

        def test_something(qtbot, make_canvas_qt):
            c, sc = make_canvas_qt()
            with qtbot.waitSignal(c.scene_changed, timeout=1000):
                qtbot.keyClick(c, Qt.Key.Key_Delete)
    """
    from models import Vec2, Scene
    from canvas import Canvas

    def _factory(w=1000, h=1000, scene=None):
        sc = scene if scene is not None else Scene()
        c = Canvas(sc)
        c._scale = 1.0
        c._offset = Vec2(w / 2, h / 2)
        c.resize(w, h)
        qtbot.addWidget(c)   # テスト後に自動 close/destroy
        c.show()
        return c, sc

    return _factory


@pytest.fixture
def make_window_qt(qtbot):
    """qtbot 対応の MainWindow を生成するファクトリフィクスチャ。

    使い方::

        def test_something(qtbot, make_window_qt):
            w = make_window_qt()
            with qtbot.waitSignal(w._canvas.selection_changed, timeout=1000):
                qtbot.mouseClick(w._canvas, Qt.MouseButton.LeftButton, pos=...)
    """
    from main_window import MainWindow
    from models import Vec2

    def _factory():
        w = MainWindow()
        # デモ図形をクリアして空のシーンにする
        w.scene.lines.clear()
        w.scene.circles.clear()
        w.scene.clothoids.clear()
        w.scene.element_profiles.clear()
        w.scene.nicknames.clear()
        qtbot.addWidget(w)   # テスト後に自動 close/destroy
        # Canvas をテスト可能なサイズに初期化
        c = w._canvas
        c._scale = 1.0
        c._offset = Vec2(500, 500)
        c.resize(1000, 1000)
        return w

    return _factory
