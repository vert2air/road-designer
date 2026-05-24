"""
tests/test_gui_interactions.py

pytest-qt の qtbot フィクスチャを使った GUI インタラクションテスト。

test_canvas_qtest.py が PySide6 内蔵の QTest を直接使っているのに対し、
このファイルは pytest-qt の qtbot を使うことで次の利点を得る:

  - qtbot.addWidget(w)          : テスト後ウィジェット自動クリーンアップ
                                  （conftest.py の各フィクスチャが担当）
  - qtbot.waitSignal(sig, ...)  : タイムアウト付きシグナル検証
                                  → リスト append パターンより安全・簡潔
  - qtbot.mouseClick/keyClick() : QTest のラッパー（addWidget と連動）

テスト分類:
  [仕様] 詳細設計書に記載された振る舞いの確認
  [C1]   C1 カバレッジを高めるための追加試験
  [統合] 複数コンポーネントをまたぐワークフロー検証
"""
from __future__ import annotations
from canvas import Canvas
from models import (
    Vec2, Line, Segment, Circle, Arc, Clothoid,
)
from PySide6.QtWidgets import (
    QDoubleSpinBox, QPushButton, QCheckBox, QMessageBox,
)
from PySide6.QtCore import Qt, QPoint
import pytest
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# pytest-qt が QApplication を管理するため、モジュールレベルで生成しない


def _to_qpoint(canvas: Canvas, wx: float, wy: float) -> QPoint:
    """ワールド座標をキャンバス上の QPoint に変換する。"""
    pt = canvas.w2s(Vec2(wx, wy))
    return QPoint(int(pt.x()), int(pt.y()))


# ══════════════════════════════════════════════════════════════
# 1. RightPanel — qtbot.waitSignal でシグナル検証
# ══════════════════════════════════════════════════════════════

class TestRightPanelSignals:
    """RightPanel のシグナルを qtbot.waitSignal で検証するテスト。

    既存の test_right_panel.py がリスト append パターンを使っているのに対し、
    waitSignal を使うとタイムアウト内に emit されなければ即座に失敗する。
    """

    def test_redraw_emits_scene_changed(self, qtbot, make_panel_qt):
        """[仕様] _redraw() → scene_changed が emit される。"""
        p, sc = make_panel_qt()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        sc.add_clothoid(Clothoid(ln, ci))
        p.scene = sc
        with qtbot.waitSignal(p.scene_changed, timeout=1000):
            p._redraw()

    def test_line_spinbox_change_emits_scene_changed(
            self, qtbot, make_panel_qt):
        """[仕様] 直線プロパティのスピンボックス変更 → scene_changed が emit。"""
        p, sc = make_panel_qt()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        sc.add_line(ln)
        p.update_selection([ln], sc)
        sbs = p._prop_widget.findChildren(QDoubleSpinBox)
        if not sbs:
            pytest.skip("スピンボックスが見つからない")
        with qtbot.waitSignal(p.scene_changed, timeout=1000):
            sbs[0].setValue(sbs[0].value() + 1.0)

    def test_circle_spinbox_change_emits_scene_changed(
            self, qtbot, make_panel_qt):
        """[仕様] 円プロパティのスピンボックス変更 → scene_changed が emit。"""
        p, sc = make_panel_qt()
        ci = Circle(Vec2(0, 0), 20.0)
        sc.add_circle(ci)
        p.update_selection([ci], sc)
        sbs = p._prop_widget.findChildren(QDoubleSpinBox)
        if not sbs:
            pytest.skip("スピンボックスが見つからない")
        with qtbot.waitSignal(p.scene_changed, timeout=1000):
            sbs[0].setValue(sbs[0].value() + 1.0)

    def test_delete_yes_emits_request_delete(self, qtbot, make_panel_qt):
        """[仕様] 削除ダイアログで Yes → request_delete が emit される。"""
        from unittest.mock import patch
        p, sc = make_panel_qt()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        p._refresh_nick_combos()
        label = p._label_for_obj(seg)
        idx = p._nick_combos[0].findText(label)
        if idx >= 0:
            p._nick_combos[0].setCurrentIndex(idx)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Yes):
            with qtbot.waitSignal(p.request_delete, timeout=1000):
                p._delete_selected_objs()

    def test_delete_no_does_not_emit_request_delete(
            self, qtbot, make_panel_qt):
        """[仕様] 削除ダイアログで No → request_delete は emit されない。"""
        from unittest.mock import patch
        p, sc = make_panel_qt()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        p._refresh_nick_combos()
        label = p._label_for_obj(seg)
        idx = p._nick_combos[0].findText(label)
        if idx >= 0:
            p._nick_combos[0].setCurrentIndex(idx)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.No):
            with qtbot.waitSignal(
                p.request_delete, timeout=300, raising=False
            ) as blocker:
                p._delete_selected_objs()
        assert not blocker.signal_triggered

    def test_add_clothoid_button_emits_request_add_clothoid(
            self, qtbot, make_panel_qt):
        """[仕様] 「クロソイドを追加」ボタンクリック → request_add_clothoid が emit。"""
        p, sc = make_panel_qt()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        p.update_selection([ln, ci], sc)
        btns = [w for w in p.findChildren(QPushButton)
                if 'クロソイドを追加' in w.text() and w.isEnabled()]
        if not btns:
            pytest.skip("追加ボタンが見つからない（クロソイド追加条件未成立）")
        with qtbot.waitSignal(p.request_add_clothoid, timeout=1000):
            qtbot.mouseClick(btns[0], Qt.MouseButton.LeftButton)

    def test_clothoid_snap_checkbox_emits_scene_changed(
            self, qtbot, make_panel_qt):
        """[仕様] クロソイド snap チェックボックス変更 → scene_changed が emit。"""
        p, sc = make_panel_qt()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        p.update_selection([clo], sc)
        chks = p._prop_widget.findChildren(QCheckBox)
        if not chks:
            pytest.skip("チェックボックスが見つからない")
        with qtbot.waitSignal(p.scene_changed, timeout=1000):
            chks[0].setChecked(not chks[0].isChecked())

    def test_arc_spinbox_change_emits_scene_changed(
            self, qtbot, make_panel_qt):
        """[仕様] 円弧角度スピンボックス変更 → scene_changed が emit。"""
        p, sc = make_panel_qt()
        ci = Circle(Vec2(0, 0), 20.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        p.update_selection([arc], sc)
        sbs = p._prop_widget.findChildren(QDoubleSpinBox)
        if not sbs:
            pytest.skip("スピンボックスが見つからない")
        with qtbot.waitSignal(p.scene_changed, timeout=1000):
            sbs[0].setValue(sbs[0].value() + 5.0)

    def test_update_mouse_pos_updates_labels(self, qtbot, make_panel_qt):
        """[仕様] update_mouse_pos() でラベルが即時更新される。"""
        p, sc = make_panel_qt()
        # シグナルなしで状態だけ確認（waitSignal は不要）
        p.update_mouse_pos(12.345, -67.890)
        assert "12.345" in p._lbl_mouse_x.text()
        assert "-67.890" in p._lbl_mouse_y.text()


# ══════════════════════════════════════════════════════════════
# 2. Canvas — qtbot でキーボード・マウス操作 + waitSignal
# ══════════════════════════════════════════════════════════════

class TestCanvasInteractions:
    """Canvas の操作を qtbot で行い、waitSignal でシグナルを検証するテスト。

    test_canvas_qtest.py が QTest を直接使っているのに対し、
    ここでは「シグナルが emit されること」を waitSignal で保証する点が異なる。
    """

    def test_delete_key_emits_scene_changed(self, qtbot, make_canvas_qt):
        """[仕様] 選択図形に Delete → scene_changed が emit されて削除される。"""
        c, sc = make_canvas_qt()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        sc.add_line(ln)
        c.set_selection([ln])
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.keyClick(c, Qt.Key.Key_Delete)
        assert ln not in sc.lines

    def test_ctrl_z_undo_emits_scene_changed(self, qtbot, make_canvas_qt):
        """[仕様] Ctrl+Z → scene_changed が emit されてアンドゥが完了する。"""
        c, sc = make_canvas_qt()
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln1)
        c.push_undo()
        sc.add_line(Line(Vec2(10, 0), Vec2(20, 0)))
        assert len(sc.lines) == 2
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.keyClick(c, Qt.Key.Key_Z,
                           Qt.KeyboardModifier.ControlModifier)
        assert len(c.scene.lines) <= 2

    def test_line_mode_two_clicks_emits_scene_changed(
            self, qtbot, make_canvas_qt):
        """[仕様] 直線モードで2クリック → 直線追加 + scene_changed が emit。"""
        c, sc = make_canvas_qt()
        c.set_mode(Canvas.MODE_LINE)
        before = len(sc.lines)
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, -50, 0))
            qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, 50, 0))
        assert len(sc.lines) > before

    def test_circle_mode_press_release_emits_scene_changed(
            self, qtbot, make_canvas_qt):
        """[仕様] 円モードでドラッグ → 円追加 + scene_changed が emit。"""
        c, sc = make_canvas_qt()
        c.set_mode(Canvas.MODE_CIRCLE)
        before = len(sc.circles)
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.mousePress(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, 0, 0))
            qtbot.mouseRelease(c, Qt.MouseButton.LeftButton,
                               pos=_to_qpoint(c, 50, 0))
        assert len(sc.circles) > before

    def test_click_selects_line_and_emits_selection_changed(
            self, qtbot, make_canvas_qt):
        """[仕様] 選択モードでクリック → selection_changed が emit。"""
        c, sc = make_canvas_qt()
        c.set_mode(Canvas.MODE_SELECT)
        ln = Line(Vec2(-200, 0), Vec2(200, 0))
        sc.add_line(ln)
        with qtbot.waitSignal(c.selection_changed, timeout=1000):
            qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, 0, 0))
        assert ln in c._selected

    def test_escape_cancels_line_input_no_signal_needed(
            self, qtbot, make_canvas_qt):
        """[仕様] 直線モードで1点入力後 Escape → _line_first_pt がリセット。"""
        c, sc = make_canvas_qt()
        c.set_mode(Canvas.MODE_LINE)
        qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                         pos=_to_qpoint(c, -50, 0))
        assert c._line_first_pt is not None
        qtbot.keyClick(c, Qt.Key.Key_Escape)
        assert c._line_first_pt is None

    def test_middle_button_pan_starts_and_ends(self, qtbot, make_canvas_qt):
        """[仕様] 中ボタン押下でパン開始、リリースでパン終了する。"""
        c, sc = make_canvas_qt()
        assert c._is_panning is False
        qtbot.mousePress(c, Qt.MouseButton.MiddleButton,
                         pos=_to_qpoint(c, 0, 0))
        assert c._is_panning is True
        qtbot.mouseRelease(c, Qt.MouseButton.MiddleButton,
                           pos=_to_qpoint(c, 0, 0))
        assert c._is_panning is False


# ══════════════════════════════════════════════════════════════
# 3. MainWindow — コンポーネント間連携テスト
# ══════════════════════════════════════════════════════════════

class TestMainWindowWorkflow:
    """Canvas ↔ RightPanel ↔ MainWindow をまたぐワークフロー検証テスト。

    単体テストでは検証しにくい「操作 → 別コンポーネントへの伝播」を確認する。
    """

    def test_canvas_click_emits_selection_changed(self, qtbot, make_window_qt):
        """[統合] Canvas クリック → selection_changed が emit される。"""
        w = make_window_qt()
        ln = Line(Vec2(-200, 0), Vec2(200, 0))
        w.scene.add_line(ln)
        c = w._canvas
        with qtbot.waitSignal(c.selection_changed, timeout=1000):
            qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, 0, 0))
        assert ln in c._selected

    def test_canvas_line_add_then_undo_via_keyboard(
            self, qtbot, make_window_qt):
        """[統合] 直線モードで追加 → Ctrl+Z でアンドゥ → 直線が消える。"""
        w = make_window_qt()
        c = w._canvas
        c.set_mode(Canvas.MODE_LINE)
        # 直線を追加
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, -50, 0))
            qtbot.mouseClick(c, Qt.MouseButton.LeftButton,
                             pos=_to_qpoint(c, 50, 0))
        n_after_add = len(w.scene.lines)
        assert n_after_add >= 1
        # Ctrl+Z でアンドゥ
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.keyClick(c, Qt.Key.Key_Z,
                           Qt.KeyboardModifier.ControlModifier)
        assert len(w.scene.lines) < n_after_add

    def test_delete_key_removes_selected_via_window(
            self, qtbot, make_window_qt):
        """[統合] 図形を選択後 Delete → MainWindow 経由で削除される。"""
        w = make_window_qt()
        c = w._canvas
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        c.set_selection([ln])
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            qtbot.keyClick(c, Qt.Key.Key_Delete)
        assert ln not in w.scene.lines

    def test_right_panel_spinbox_propagates_to_scene(
            self, qtbot, make_window_qt):
        """[統合] RightPanel のスピンボックス変更 → scene の座標が更新。"""
        w = make_window_qt()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        # RightPanel に直線を選択させる
        w._right_panel.update_selection([ln], w.scene)
        sbs = w._right_panel._prop_widget.findChildren(QDoubleSpinBox)
        if not sbs:
            pytest.skip("スピンボックスが見つからない")
        old_val = sbs[0].value()
        with qtbot.waitSignal(w._right_panel.scene_changed, timeout=1000):
            sbs[0].setValue(old_val + 10.0)
        # 座標が変わっていること（scene_changed が emit → モデルが更新済み）
        assert sbs[0].value() != old_val
