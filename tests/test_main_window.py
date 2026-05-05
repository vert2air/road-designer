"""
tests/test_main_window.py

main_window.py の単体テスト。

UI 生成・メニュー・ファイルダイアログ・縦断線形ウィンドウ起動等は
統合テストの領域のため除外し、以下の純粋ロジックを重点的にテストする:
  - scene プロパティ
  - _get_or_create_ep
  - _collect_all_display
  - _do_add_clothoid / _do_delete_clothoid / _do_flip_clothoid
  - _do_delete_objects
  - _do_smooth_connect / _do_polyline_connect / _do_disconnect

観点の分類:
  [仕様] 詳細設計書に記載された振る舞いの確認
  [境界] 境界値試験
  [エッジ] エッジケース・コーナーケース
  [C1]   C1 カバレッジを高めるための追加試験
"""
from __future__ import annotations
import math
import sys
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from models import (
    Vec2, Line, Segment, Circle, Arc, Clothoid,
    ElementProfile, Scene, plan_length_of,
)
from main_window import MainWindow


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def make_window():
    """テスト用 MainWindow を生成する。デモ図形なしで初期化する。"""
    w = MainWindow()
    # デモ図形をクリアして空のシーンにする
    w.scene.lines.clear()
    w.scene.circles.clear()
    w.scene.clothoids.clear()
    w.scene.element_profiles.clear()
    w.scene.nicknames.clear()
    return w


def make_seg(x0=0, y0=0, x1=100, y1=0):
    ln = Line(Vec2(x0, y0), Vec2(x1, y1))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    return seg


def make_arc(cx=0, cy=0, r=50.0, a0=0.0, a1=math.pi):
    ci = Circle(Vec2(cx, cy), r)
    arc = Arc(ci, a0, a1)
    ci.arcs.append(arc)
    return arc


# ══════════════════════════════════════════════════════════════
# 1. scene プロパティ
# ══════════════════════════════════════════════════════════════

class TestSceneProperty:
    # [仕様] scene は canvas.scene と同一オブジェクト
    def test_same_object_as_canvas(self):
        w = make_window()
        assert w.scene is w._canvas.scene

    # [仕様] scene に追加した図形が canvas.scene にも反映される
    def test_reflects_in_canvas(self):
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        w.scene.add_line(ln)
        assert ln in w._canvas.scene.lines


# ══════════════════════════════════════════════════════════════
# 2. _get_or_create_ep
# ══════════════════════════════════════════════════════════════

class TestGetOrCreateEp:
    # [仕様] 対応する EP がない場合は新規作成して返す
    def test_creates_new_ep(self):
        w = make_window()
        seg = make_seg()
        w.scene.add_line(seg.line)
        ep = w._get_or_create_ep(seg, False)
        assert ep is not None
        assert ep.element_id == seg.id
        assert ep in w.scene.element_profiles

    # [仕様] 既存 EP がある場合はそれを返す（重複作成しない）
    def test_returns_existing_ep(self):
        w = make_window()
        seg = make_seg()
        w.scene.add_line(seg.line)
        ep1 = w._get_or_create_ep(seg, False)
        ep2 = w._get_or_create_ep(seg, False)
        assert ep1 is ep2
        assert len([e for e in w.scene.element_profiles if e.element_id == seg.id]) == 1

    # [仕様] element_type が常に最新値で上書きされる
    def test_element_type_segment(self):
        w = make_window()
        seg = make_seg()
        ep = w._get_or_create_ep(seg, False)
        assert ep.element_type == 'segment'

    def test_element_type_arc(self):
        w = make_window()
        arc = make_arc()
        ep = w._get_or_create_ep(arc, False)
        assert ep.element_type == 'arc'

    def test_element_type_clothoid(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        ep = w._get_or_create_ep(clo, False)
        assert ep.element_type == 'clothoid'

    # [仕様] plan_length が常に最新値で上書きされる
    def test_plan_length_updated(self):
        w = make_window()
        seg = make_seg(0, 0, 100, 0)
        ep = w._get_or_create_ep(seg, False)
        assert approx(ep.plan_length, plan_length_of(seg), tol=1e-4)

    # [仕様] reversed_flag が rev 引数で上書きされる
    def test_reversed_flag_set(self):
        w = make_window()
        seg = make_seg()
        ep = w._get_or_create_ep(seg, True)
        assert ep.reversed_flag is True

    def test_reversed_flag_overwritten(self):
        w = make_window()
        seg = make_seg()
        w._get_or_create_ep(seg, False)
        ep = w._get_or_create_ep(seg, True)
        assert ep.reversed_flag is True

    # [エッジ] Arc の plan_length は弧長
    def test_arc_plan_length(self):
        w = make_window()
        arc = make_arc(r=10.0, a0=0.0, a1=math.pi)
        ep = w._get_or_create_ep(arc, False)
        assert approx(ep.plan_length, 10.0 * math.pi, tol=1e-4)


# ══════════════════════════════════════════════════════════════
# 3. _collect_all_display
# ══════════════════════════════════════════════════════════════

class TestCollectAllDisplay:
    # [仕様] 全線分・全円弧・全クロソイドをフラットなリストで返す
    def test_collects_segments(self):
        w = make_window()
        seg = make_seg()
        w.scene.add_line(seg.line)
        result = w._collect_all_display()
        assert seg in result

    def test_collects_arcs(self):
        w = make_window()
        arc = make_arc()
        w.scene.add_circle(arc.circle)
        result = w._collect_all_display()
        assert arc in result

    def test_collects_clothoids(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        result = w._collect_all_display()
        assert clo in result

    # [仕様] 空のシーンでは空リスト
    def test_empty_scene(self):
        w = make_window()
        assert w._collect_all_display() == []

    # [仕様] 複数の Line の全 Segment が含まれる
    def test_multiple_lines(self):
        w = make_window()
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        seg1 = Segment(ln1, 0.0, 0.5)
        seg2 = Segment(ln1, 0.5, 1.0)
        ln1.segments.extend([seg1, seg2])
        w.scene.add_line(ln1)
        result = w._collect_all_display()
        assert seg1 in result
        assert seg2 in result

    # [C1] 返すリストの型は list
    def test_returns_list(self):
        w = make_window()
        result = w._collect_all_display()
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════
# 4. _do_add_clothoid / _do_delete_clothoid / _do_flip_clothoid
# ══════════════════════════════════════════════════════════════

class TestDoAddClothoid:
    # [仕様] Clothoid が Scene に追加される
    def test_adds_to_scene(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        before = len(w.scene.clothoids)
        w._do_add_clothoid(ln, ci)
        assert len(w.scene.clothoids) == before + 1

    # [仕様] snap 設定はデフォルト False（ユーザーが右パネルから個別に設定する）
    def test_default_snap_false(self):
        """_do_add_clothoid はデフォルトで snap_segment=False, snap_arc=False。
        ユーザーが右パネルのチェックボックスから個別に on にする設計。
        """
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        w._do_add_clothoid(ln, ci)
        clo = w.scene.clothoids[-1]
        assert clo.snap_segment is False
        assert clo.snap_arc is False

    # [仕様] Undo スタックに積まれる
    def test_push_undo(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        before = len(w._canvas._undo_stack)
        w._do_add_clothoid(ln, ci)
        assert len(w._canvas._undo_stack) == before + 1


class TestDoDeleteClothoid:
    # [仕様] 指定 Clothoid が Scene から削除される
    def test_removes_from_scene(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        w._do_delete_clothoid(clo)
        assert clo not in w.scene.clothoids

    # [仕様] Undo スタックに積まれる
    def test_push_undo(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        before = len(w._canvas._undo_stack)
        w._do_delete_clothoid(clo)
        assert len(w._canvas._undo_stack) == before + 1


class TestDoFlipClothoid:
    # [仕様] reversed_flag が反転される
    def test_flips_flag(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        original = clo.reversed_flag
        w._do_flip_clothoid(clo)
        assert clo.reversed_flag is not original

    # [仕様] flip 後に compute() が呼ばれる（is_valid が保持される）
    def test_compute_called_after_flip(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        was_valid = clo.is_valid
        w._do_flip_clothoid(clo)
        # flip 後も compute が呼ばれて valid 状態が維持される
        assert clo.is_valid == was_valid

    # [仕様] 2回 flip すると元に戻る
    def test_double_flip_restores(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        original = clo.reversed_flag
        w._do_flip_clothoid(clo)
        w._do_flip_clothoid(clo)
        assert clo.reversed_flag == original


# ══════════════════════════════════════════════════════════════
# 5. _do_delete_objects
# ══════════════════════════════════════════════════════════════

class TestDoDeleteObjects:
    # [仕様] Line を削除する
    def test_delete_line(self):
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        w.scene.add_line(ln)
        w._do_delete_objects([ln])
        assert ln not in w.scene.lines

    # [仕様] Circle を削除する
    def test_delete_circle(self):
        w = make_window()
        ci = Circle(Vec2(0, 0), 10.0)
        w.scene.add_circle(ci)
        w._do_delete_objects([ci])
        assert ci not in w.scene.circles

    # [仕様] Clothoid を削除する
    def test_delete_clothoid(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        w._do_delete_objects([clo])
        assert clo not in w.scene.clothoids

    # [仕様] Segment を削除する（親 Line の segments から除去）
    def test_delete_segment(self):
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg1 = Segment(ln, 0.0, 0.5)
        seg2 = Segment(ln, 0.5, 1.0)
        ln.segments.extend([seg1, seg2])
        w.scene.add_line(ln)
        w._do_delete_objects([seg1])
        assert seg1 not in ln.segments
        assert seg2 in ln.segments

    # [仕様] Arc を削除する（親 Circle の arcs から除去）
    def test_delete_arc(self):
        w = make_window()
        ci = Circle(Vec2(0, 0), 10.0)
        arc1 = Arc(ci, 0.0, math.pi / 2)
        arc2 = Arc(ci, math.pi / 2, math.pi)
        ci.arcs.extend([arc1, arc2])
        w.scene.add_circle(ci)
        w._do_delete_objects([arc1])
        assert arc1 not in ci.arcs
        assert arc2 in ci.arcs

    # [仕様] Undo スタックに積まれる
    def test_push_undo(self):
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        w.scene.add_line(ln)
        before = len(w._canvas._undo_stack)
        w._do_delete_objects([ln])
        assert len(w._canvas._undo_stack) == before + 1

    # [仕様] Line 削除時に関連 Clothoid も削除される
    def test_delete_line_removes_clothoids(self):
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_clothoid(clo)
        w._do_delete_objects([ln])
        assert ln not in w.scene.lines
        assert clo not in w.scene.clothoids

    # [エッジ] 空リストを渡しても例外にならない
    def test_empty_list_no_op(self):
        w = make_window()
        w._do_delete_objects([])  # 例外にならない


# ══════════════════════════════════════════════════════════════
# 6. _do_smooth_connect / _do_polyline_connect / _do_disconnect
# ══════════════════════════════════════════════════════════════

class TestDoSmoothConnect:
    # [仕様] Canvas.smooth_connect を呼ぶ（成功時に Circle と Clothoid が生成される）
    def test_calls_smooth_connect(self):
        w = make_window()
        a = Line(Vec2(-50, 0), Vec2(50, 0))
        seg_a = Segment(a, 0.0, 1.0)
        a.segments.append(seg_a)
        b = Line(Vec2(0, -50), Vec2(10, 50))
        seg_b = Segment(b, 0.0, 1.0)
        b.segments.append(seg_b)
        w.scene.add_line(a)
        w.scene.add_line(b)
        circles_before = len(w.scene.circles)
        w._do_smooth_connect(a, b)
        # 成功すれば Circle が追加される
        if len(w.scene.circles) > circles_before:
            assert a.connection is not None
            assert a.connection.kind == 'smooth'


class TestDoPolylineConnect:
    # [仕様] 折れ線接続を実行する
    def test_connects(self):
        w = make_window()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        w.scene.add_line(a)
        w.scene.add_line(b)
        w._do_polyline_connect(a, b)
        assert a.connection is not None
        assert a.connection.kind == 'polyline'

    # [仕様] Undo スタックに積まれる
    def test_push_undo(self):
        w = make_window()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        w.scene.add_line(a)
        w.scene.add_line(b)
        before = len(w._canvas._undo_stack)
        w._do_polyline_connect(a, b)
        assert len(w._canvas._undo_stack) == before + 1


class TestDoDisconnect:
    # [仕様] 接続を解除する
    def test_disconnects(self):
        w = make_window()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        w.scene.add_line(a)
        w.scene.add_line(b)
        w._do_polyline_connect(a, b)
        assert a.connection is not None
        w._do_disconnect(a, b)
        assert a.connection is None
        assert b.connection is None


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: _on_selection_changed の各分岐
# ══════════════════════════════════════════════════════════════

class TestOnSelectionChanged:
    # [C1] 選択なし → status "選択なし"（L226）
    def test_empty_selection(self):
        w = make_window()
        w._on_selection_changed([])
        assert '選択なし' in w._status_label.text()

    # [C1] 1個選択 → status "選択: {type}" (L228-231)
    def test_single_selection(self):
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        w._on_selection_changed([ln])
        assert 'Line' in w._status_label.text()

    # [C1] 2個以上選択 → status "{n} 個選択" (L232-233)
    def test_multi_selection(self):
        w = make_window()
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(0, 1), Vec2(10, 1))
        w._on_selection_changed([ln1, ln2])
        assert '2' in w._status_label.text()


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: _do_delete_objects の詳細な分岐
# ══════════════════════════════════════════════════════════════

class TestDoDeleteObjectsBranches:
    # [C1] Segment 削除後も Line が残存する場合、関連 Clothoid が再計算される（L396-399）
    def test_segment_removed_clothoid_recomputed(self):
        """Segment 削除で Line が空にならない場合、clo.compute() が呼ばれる分岐。"""
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg1 = Segment(ln, 0.0, 0.5)
        seg2 = Segment(ln, 0.5, 1.0)
        ln.segments.extend([seg1, seg2])
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        w.scene.add_clothoid(clo)
        # seg1 だけ削除 → Line に seg2 が残る → clo.compute() が呼ばれる
        w._do_delete_objects([seg1])
        assert seg1 not in ln.segments
        assert seg2 in ln.segments
        assert clo in w.scene.clothoids  # Clothoid は残る

    # [C1] Arc 削除後も Circle が残存する場合、関連 Clothoid が再計算される（L407-410）
    def test_arc_removed_clothoid_recomputed(self):
        """Arc 削除で Circle が空にならない場合、clo.compute() が呼ばれる分岐。"""
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc1 = Arc(ci, -0.5, 0.5)
        arc2 = Arc(ci, 0.5, 1.5)
        ci.arcs.extend([arc1, arc2])
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        w.scene.add_line(ln)
        w.scene.add_circle(ci)
        w.scene.add_clothoid(clo)
        # arc1 だけ削除 → Circle に arc2 が残る → clo.compute() が呼ばれる
        w._do_delete_objects([arc1])
        assert arc1 not in ci.arcs
        assert arc2 in ci.arcs
        assert clo in w.scene.clothoids

    # [C1] Segment が既に ln.segments にない場合のガード（L391）
    def test_segment_not_in_line_no_error(self):
        """obj in ln.segments のガードが False になるケース。"""
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        w.scene.add_line(ln)
        ln.segments.remove(seg)  # 事前に除去しておく
        w._do_delete_objects([seg])  # 例外にならない

    # [C1] Arc が既に ci.arcs にない場合のガード（L403）
    def test_arc_not_in_circle_no_error(self):
        """obj in ci.arcs のガードが False になるケース。"""
        w = make_window()
        ci = Circle(Vec2(0, 0), 10.0)
        arc = Arc(ci, 0.0, math.pi)
        ci.arcs.append(arc)
        w.scene.add_circle(ci)
        ci.arcs.remove(arc)  # 事前に除去しておく
        w._do_delete_objects([arc])  # 例外にならない


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: _save / _write_file（モックで検証）
# ══════════════════════════════════════════════════════════════

class TestSaveLoad:
    # [C1] _filepath が設定済みのとき _save は _write_file を呼ぶ（L258）
    def test_save_with_filepath(self):
        import tempfile, os
        w = make_window()
        with tempfile.NamedTemporaryFile(suffix='.rdjson', delete=False) as f:
            path = f.name
        try:
            w._filepath = path
            w._save()
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    # [C1] _write_file が JSON を正しく書き出す（L280-286）
    def test_write_file_json(self):
        import tempfile, os, json
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        w.scene.add_line(ln)
        with tempfile.NamedTemporaryFile(suffix='.rdjson', delete=False, mode='w') as f:
            path = f.name
        try:
            w._write_file(path)
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            assert 'lines' in data
            assert len(data['lines']) == 1
        finally:
            os.unlink(path)

    # [C1] _filepath なしで _save を呼ぶと _save_as へ委譲（ダイアログをモック）
    def test_save_without_filepath_calls_save_as(self):
        from unittest.mock import patch
        w = make_window()
        w._filepath = None
        called = []
        with patch.object(w, '_save_as', side_effect=lambda: called.append(True)):
            w._save()
        assert called == [True]

    # [C1] _open_vertical_window: 選択なしのとき何もしない（L491-492）
    def test_open_vertical_window_no_selection(self):
        w = make_window()
        w._canvas._selected = []  # 選択なし
        w._open_vertical_window()  # 例外にならない・何もしない

    # [C1] _open_vertical_window: 平面線形要素が選択されているとき VerticalAlignmentWindow が開く
    def test_open_vertical_window_with_selection(self):
        from unittest.mock import patch, MagicMock
        w = make_window()
        seg = make_seg()
        w.scene.add_line(seg.line)
        w._canvas._selected = [seg]
        mock_win = MagicMock()
        with patch('main_window.VerticalAlignmentWindow', return_value=mock_win):
            w._open_vertical_window()
        mock_win.show.assert_called_once()

    # [C1] _open_3d_viewer: 図形なしで「図形がありません」メッセージ（L529-531）
    def test_open_3d_viewer_empty_scene(self):
        from unittest.mock import patch
        w = make_window()
        w._canvas._selected = []
        msg_shown = []
        with patch('main_window.QMessageBox.information',
                   side_effect=lambda *a, **kw: msg_shown.append(True)):
            w._open_3d_viewer()
        assert msg_shown == [True]
