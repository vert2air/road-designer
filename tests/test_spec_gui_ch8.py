"""
要求仕様書 第8章「メニュー・ショートカット一覧」適合確認テスト (GUI)。

実行方法:
    uv run pytest -m spec tests/test_spec_gui_ch8.py -v

CI では -m 'not spec' により除外されるため、開発者が手動で実行する。
各テストクラスの docstring に対応する仕様書の節番号と条文を引用する。
"""
import json
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.spec


def _add_line(scene, x0=0.0, y0=0.0, x1=100.0, y1=0.0):
    """シーンに直線と線分を1本追加して (line, seg) を返す。"""
    from models import Line, Segment, Vec2
    ln = Line(Vec2(x0, y0), Vec2(x1, y1))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    scene.add_line(ln)
    return ln, seg


def _menu_action(w, text_part):
    """メニューバーから表示テキストにマッチする QAction を探す。"""
    for menu_action in w.menuBar().actions():
        menu = menu_action.menu()
        if menu is None:
            continue
        for act in menu.actions():
            if text_part in act.text():
                return act
    return None


# ─── 8 子図形を初期化して保存（Ctrl+Shift+I） ────────────────────

class TestSpec8_SaveInitialized:
    """8 メインウィンドウ — Ctrl+Shift+I 子図形を初期化して保存

    仕様書より:
        直線の線分を1本化・円弧を全削除・クロソイドのsnap=off に
        してから別名保存。元シーンは変更しない。
    """

    @staticmethod
    def _scene_with_children(w):
        from models import Line, Segment, Circle, Arc, Vec2
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ln.segments.append(Segment(ln, 0.0, 0.4))
        ln.segments.append(Segment(ln, 0.6, 1.0))   # 線分 2 本
        w.scene.add_line(ln)
        ci = Circle(Vec2(50, 80), 20.0)
        ci.arcs.append(Arc(ci, 0.0, 1.0))           # 円弧あり
        w.scene.add_circle(ci)
        return ln, ci

    def test_saved_file_has_initialized_children(
            self, make_window_qt, tmp_path):
        """[8] 保存ファイルは線分1本（t=0..1）・円弧なしになる。"""
        w = make_window_qt()
        self._scene_with_children(w)
        path = tmp_path / "init.rdjson"
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',
                   return_value=(str(path), '')):
            w._save_initialized()
        data = json.loads(path.read_text(encoding='utf-8'))
        assert len(data["lines"][0]["segments"]) == 1
        assert data["lines"][0]["segments"][0]["t_start"] == 0.0
        assert data["lines"][0]["segments"][0]["t_end"] == 1.0
        assert data["circles"][0]["arcs"] == []

    def test_current_scene_not_modified(self, make_window_qt, tmp_path):
        """[8] 元のシーンは変更されない。"""
        w = make_window_qt()
        ln, ci = self._scene_with_children(w)
        path = tmp_path / "init.rdjson"
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',
                   return_value=(str(path), '')):
            w._save_initialized()
        assert len(ln.segments) == 2
        assert len(ci.arcs) == 1

    def test_shortcut_is_ctrl_shift_i(self, make_window_qt):
        """[8] メニュー項目のショートカットが Ctrl+Shift+I である。"""
        w = make_window_qt()
        act = _menu_action(w, "初期化して保存")
        assert act is not None
        assert act.shortcut().toString() == "Ctrl+Shift+I"


# ─── 8 追加で読み込む（Ctrl+Shift+O） ────────────────────────────

class TestSpec8_Merge:
    """8 メインウィンドウ — Ctrl+Shift+O 追加で読み込む

    仕様書より:
        現在のシーンに JSON データを追加読み込みする。追加時は既存の
        選択を解除し、追加した図形だけを選択状態にする。
    """

    def test_shortcut_is_ctrl_shift_o(self, make_window_qt):
        """[8] メニュー項目のショートカットが Ctrl+Shift+O である。"""
        w = make_window_qt()
        act = _menu_action(w, "追加で読み込む")
        assert act is not None
        assert act.shortcut().toString() == "Ctrl+Shift+O"

    def test_merge_selects_only_added(self, make_window_qt, tmp_path):
        """[8] 追加した図形だけが選択状態になる。"""
        from models import Scene, Line, Vec2
        w = make_window_qt()
        base, _ = _add_line(w.scene)
        w._canvas._selected = [base]
        src = Scene()
        src.add_line(Line(Vec2(0, 100), Vec2(100, 100)))
        path = tmp_path / "m.rdjson"
        path.write_text(json.dumps(src.to_dict()), encoding='utf-8')
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=(str(path), '')):
            w._merge()
        assert base not in w._canvas._selected
        assert len(w._canvas._selected) == 1


# ─── 8 全削除（メニューのみ） ────────────────────────────────────

class TestSpec8_ClearAll:
    """8 メインウィンドウ — 全削除

    仕様書より:
        確認ダイアログ表示後、シーン全データを削除。Undo 対応。
    """

    def test_yes_clears_scene(self, make_window_qt):
        """[8] 「はい」で全データが削除される。"""
        from PySide6.QtWidgets import QMessageBox
        w = make_window_qt()
        _add_line(w.scene)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Yes):
            w._clear_all()
        assert w.scene.lines == []

    def test_no_keeps_scene(self, make_window_qt):
        """[8] 「いいえ」では削除されない。"""
        from PySide6.QtWidgets import QMessageBox
        w = make_window_qt()
        _add_line(w.scene)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.No):
            w._clear_all()
        assert len(w.scene.lines) == 1

    def test_menu_item_exists(self, make_window_qt):
        """[8] メニューに「全削除」項目が存在する。"""
        w = make_window_qt()
        assert _menu_action(w, "全削除") is not None


# ─── 8 ID を振り直す（メニューのみ） ─────────────────────────────

class TestSpec8_RenumberIds:
    """8 メインウィンドウ — ID を振り直す

    仕様書より:
        全図形の ID を 1 から連番で付け直す。Undo 非対応のため
        実行前に確認ダイアログを表示。
    """

    def test_menu_item_exists(self, make_window_qt):
        """[8] メニューに「ID を振り直す」項目が存在する。"""
        w = make_window_qt()
        assert _menu_action(w, "振り直す") is not None

    def test_ok_renumbers_sequentially(self, make_window_qt):
        """[8] OK で ID が 1 からの連番になる。"""
        from PySide6.QtWidgets import QMessageBox
        from models import Line, Segment, Vec2
        w = make_window_qt()
        ln = Line(Vec2(0, 0), Vec2(10, 0), line_id=77)
        ln.segments.append(Segment(ln, 0.0, 1.0, seg_id=88))
        w.scene.add_line(ln)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Ok):
            w._renumber_ids()
        assert sorted([ln.id, ln.segments[0].id]) == [1, 2]


# ─── 8 右パネルを表示（ビューメニュー、チェック項目） ────────────

class TestSpec8_RightPanelToggle:
    """8 メインウィンドウ — 右パネルを表示

    仕様書より:
        右パネルを表示（デフォルト非表示。チェックで表示）。
    """

    def test_hidden_by_default(self, make_window_qt):
        """[8] 右パネルはデフォルト非表示。"""
        w = make_window_qt()
        assert w._right_panel.isHidden()
        assert w._act_right_panel.isChecked() is False

    def test_menu_toggle_shows_and_hides(self, make_window_qt):
        """[8] チェック項目のトグルで表示/非表示が切り替わる。"""
        w = make_window_qt()
        w.show()
        w._act_right_panel.trigger()   # チェック ON
        assert not w._right_panel.isHidden()
        assert w._act_right_panel.isChecked() is True
        w._act_right_panel.trigger()   # チェック OFF
        assert w._right_panel.isHidden()
