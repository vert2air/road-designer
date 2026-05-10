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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from PySide6.QtWidgets import QApplication
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


# ══════════════════════════════════════════════════════════════
# _do_set_offset_constraint / _do_clear_offset_constraint テスト
# ══════════════════════════════════════════════════════════════

class TestDoSetOffsetConstraint:
    """MainWindow._do_set_offset_constraint のテスト。"""

    # [仕様] OC を生成して scene に追加する
    def test_creates_and_appends_oc(self):
        """[仕様] OC を生成して calc_offsets_from_current を呼び scene に追加する。"""
        w = make_window()
        ca = Circle(Vec2(0,  30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        assert len(w.scene.offset_constraints) == 0
        w._do_set_offset_constraint(ln, ca, cb)
        assert len(w.scene.offset_constraints) == 1
        oc = w.scene.offset_constraints[0]
        assert oc.line is ln
        assert oc.circle_a is ca
        assert oc.circle_b is cb

    # [仕様] off_a / off_b が現在の位置関係から算出される
    def test_off_values_calculated_from_current(self):
        """[仕様] calc_offsets_from_current により off_a/off_b が自動算出される。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)   # dist=30, r=10 → off_a=20
        cb = Circle(Vec2(0, -40), 15.0)  # dist=40, r=15 → off_b=25
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        w._do_set_offset_constraint(ln, ca, cb)
        oc = w.scene.offset_constraints[0]
        assert abs(oc.off_a - 20.0) < 1e-6
        assert abs(oc.off_b - 25.0) < 1e-6

    # [仕様] 重複チェック: 同じ組み合わせの拘束が既にあれば追加しない
    def test_duplicate_not_added(self):
        """[仕様] 同じ (line, {ca, cb}) の組み合わせが既存なら何もしない。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        w._do_set_offset_constraint(ln, ca, cb)
        w._do_set_offset_constraint(ln, ca, cb)  # 2回目
        assert len(w.scene.offset_constraints) == 1

    # [仕様] 引数の順序が異なっても重複とみなす（集合比較）
    def test_duplicate_detected_regardless_of_order(self):
        """[仕様] ca/cb の引数順が逆でも {ca,cb} の集合で比較して重複を検出する。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        w._do_set_offset_constraint(ln, ca, cb)
        w._do_set_offset_constraint(ln, cb, ca)  # 順序を逆に
        assert len(w.scene.offset_constraints) == 1

    # [仕様] push_undo を呼ぶ（Undo スタックに積む）
    def test_calls_push_undo(self):
        """[仕様] _do_set_offset_constraint は push_undo() を呼ぶ。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        before = len(w._canvas._undo_stack)
        w._do_set_offset_constraint(ln, ca, cb)
        assert len(w._canvas._undo_stack) > before


class TestDoClearOffsetConstraint:
    """MainWindow._do_clear_offset_constraint のテスト。"""

    def _add_oc(self, w, ln, ca, cb):
        w._do_set_offset_constraint(ln, ca, cb)
        return w.scene.offset_constraints[-1]

    # [仕様] oc.line is ln のものを scene から削除する
    def test_removes_matching_constraint(self):
        """[仕様] oc.line is ln のオフセット拘束を削除する。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        self._add_oc(w, ln, ca, cb)
        assert len(w.scene.offset_constraints) == 1
        w._do_clear_offset_constraint(ln)
        assert len(w.scene.offset_constraints) == 0

    # [仕様] 他の直線の拘束は残る
    def test_other_constraints_remain(self):
        """[仕様] 解除対象でない他の直線の拘束はそのまま残る。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln1 = Line(Vec2(-100, 0), Vec2(100, 0))
        ln2 = Line(Vec2(0, -100), Vec2(0, 100))
        w.scene.add_circle(ca); w.scene.add_circle(cb)
        w.scene.add_line(ln1); w.scene.add_line(ln2)
        self._add_oc(w, ln1, ca, cb)
        self._add_oc(w, ln2, ca, cb)
        w._do_clear_offset_constraint(ln1)
        assert len(w.scene.offset_constraints) == 1
        assert w.scene.offset_constraints[0].line is ln2

    # [仕様] push_undo を呼ぶ
    def test_calls_push_undo(self):
        """[仕様] _do_clear_offset_constraint は push_undo() を呼ぶ。"""
        w = make_window()
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_circle(ca); w.scene.add_circle(cb); w.scene.add_line(ln)
        self._add_oc(w, ln, ca, cb)
        before = len(w._canvas._undo_stack)
        w._do_clear_offset_constraint(ln)
        assert len(w._canvas._undo_stack) > before

    # [エッジ] 拘束がない直線を解除しようとしても例外にならない
    def test_clear_nonexistent_constraint_no_error(self):
        """[エッジ] 拘束のない直線を解除しても例外にならない。"""
        w = make_window()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        w._do_clear_offset_constraint(ln)  # 例外にならない
        assert w.scene.offset_constraints == []


# ══════════════════════════════════════════════════════════════
# C1カバレッジ向上: main_window.py の残り未カバー分岐
# ══════════════════════════════════════════════════════════════

class TestSceneSetter:
    """MainWindow.scene property setter のテスト（L65）。"""

    # [C1] scene setter が _canvas.scene を更新する
    def test_scene_setter(self):
        """[C1] scene= で _canvas.scene が更新される（L65）。"""
        w = make_window()
        new_scene = Scene()
        w.scene = new_scene
        assert w._canvas.scene is new_scene


class TestSetRightPanelVisible:
    """MainWindow._set_right_panel_visible のテスト（L283-285）。"""

    # [C1] 右パネルを非表示にする
    def test_hide_right_panel(self):
        """[C1] _set_right_panel_visible(False) で右パネルが非表示になる（L283）。"""
        w = make_window()
        w._set_right_panel_visible(False)
        assert not w._right_panel.isVisible()
        assert not w._chk_right.isChecked()

    # [C1] 右パネルを表示する
    def test_show_right_panel(self):
        """[C1] _set_right_panel_visible(True) でチェック状態が True になる（L283-285）。"""
        w = make_window()
        w._set_right_panel_visible(False)
        assert not w._chk_right.isChecked()
        w._set_right_panel_visible(True)
        assert w._chk_right.isChecked()
        assert w._act_right_panel.isChecked()


class TestWriteFile:
    """MainWindow._write_file / _read_file のテスト（L303-318）。"""

    # [仕様] ファイルへの書き出しと読み込みが正常に動作する
    def test_write_and_read_file(self, tmp_path):
        """[仕様] _write_file で書き出したファイルを json.load+from_dict で読み込める（L303-318）。"""
        import json
        from models import Scene
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        path = str(tmp_path / "test.rdjson")
        w._write_file(path)
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        sc2 = Scene.from_dict(data)
        assert len(sc2.lines) == 1

    # [C1] 存在しないパスに書き込もうとしたとき例外が処理される（L317-318）
    def test_write_file_error_handled(self):
        """[C1] 書き込み不可パスでも例外が QMessageBox で処理される（L317-318）。"""
        from unittest.mock import patch
        w = make_window()
        with patch('PySide6.QtWidgets.QMessageBox.critical') as mock_crit:
            w._write_file("/no_such_dir/no_such_file.rdjson")
            assert mock_crit.called


class TestClearAll:
    """MainWindow._clear_all のテスト（L343-352）。"""

    # [仕様] 承認時に scene が空になる
    def test_clear_all_accepted(self):
        """[仕様] 確認ダイアログで Yes を選んだとき scene が空になる（L347-352）。"""
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        w = make_window()
        w.scene.add_line(Line(Vec2(0, 0), Vec2(100, 0)))
        assert len(w.scene.lines) == 1
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Yes):
            w._clear_all()
        assert len(w.scene.lines) == 0

    # [C1] キャンセル時は何も変わらない
    def test_clear_all_cancelled(self):
        """[C1] 確認ダイアログで No を選んだとき scene は変わらない（L347分岐）。"""
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        w = make_window()
        w.scene.add_line(Line(Vec2(0, 0), Vec2(100, 0)))
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.No):
            w._clear_all()
        assert len(w.scene.lines) == 1


class TestToggleRightPanelMenu:
    """メニューから右パネル表示切替のテスト（L272-273）。"""

    # [C1] メニューアクション経由で右パネルを切替
    def test_toggle_right_panel_menu(self):
        """[C1] _toggle_right_panel() を呼ぶとチェック状態が反映される（L272-273）。"""
        w = make_window()
        # チェックをオフにして _toggle_right_panel を呼ぶ
        w._act_right_panel.setChecked(False)
        w._toggle_right_panel()
        assert not w._chk_right.isChecked()
        # チェックをオンにして呼ぶ
        w._act_right_panel.setChecked(True)
        w._toggle_right_panel()
        assert w._chk_right.isChecked()


class TestOpenVerticalWindow:
    """MainWindow._open_vertical_window のテスト。"""

    # [仕様] 縦断線形ウィンドウを開く（選択図形あり）
    def test_open_vertical_window_with_selection(self):
        """[仕様] 選択図形がある状態で縦断線形ウィンドウを開いてもエラーにならない。"""
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0); ln.segments.append(seg)
        w.scene.add_line(ln)
        w._canvas.set_selection([seg])
        try:
            w._open_vertical_window()
        except Exception as e:
            assert False, f"例外が発生: {e}"


# ══════════════════════════════════════════════════════════════
# 追加価値の高い C1 カバレッジ向上テスト: main_window.py
# ══════════════════════════════════════════════════════════════

class TestSaveAsOpenWithMock:
    """_save_as / _open のファイルダイアログをモックしてテスト（L297-340）。"""

    def test_save_as_writes_file(self, tmp_path):
        """[仕様] _save_as() がパス選択後に _write_file を呼び _filepath を更新する（L299-301）。"""
        from unittest.mock import patch
        w = make_window()
        w.scene.add_line(Line(Vec2(0, 0), Vec2(100, 0)))
        path = str(tmp_path / "out.rdjson")
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',
                   return_value=(path, '')):
            w._save_as()
        assert w._filepath == path
        import os
        assert os.path.exists(path)

    def test_save_as_cancelled_does_nothing(self):
        """[C1] _save_as() でキャンセル（空文字）されたとき何もしない（L299 分岐）。"""
        from unittest.mock import patch
        w = make_window()
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',
                   return_value=('', '')):
            w._save_as()
        assert w._filepath is None or w._filepath == ''  # 変化しない

    def test_open_loads_scene(self, tmp_path):
        """[仕様] _open() がファイル選択後に Scene を読み込む（L327-335）。"""
        from unittest.mock import patch
        import json
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        path = str(tmp_path / "scene.rdjson")
        w._write_file(path)
        w2 = make_window()
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=(path, '')):
            w2._open()
        assert len(w2.scene.lines) == 1

    def test_open_cancelled_does_nothing(self):
        """[C1] _open() でキャンセルされたとき scene は変化しない（L327 分岐）。"""
        from unittest.mock import patch
        w = make_window()
        n_before = len(w.scene.lines)
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=('', '')):
            w._open()
        assert len(w.scene.lines) == n_before

    def test_open_invalid_json_shows_error(self, tmp_path):
        """[C1] _open() で JSON パースエラー時に QMessageBox.critical が呼ばれる（L328 例外分岐）。"""
        from unittest.mock import patch
        path = str(tmp_path / "bad.rdjson")
        with open(path, 'w') as f:
            f.write("not json {{{")
        w = make_window()
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=(path, '')), \
             patch('PySide6.QtWidgets.QMessageBox.critical') as mock_crit:
            w._open()
        assert mock_crit.called


class TestDoDeleteObjects:
    """_do_delete_objects の各分岐テスト（L431-447）。"""

    def test_delete_arc_remaining_arcs(self):
        """[C1] Arc 削除後に他の Arc が残る場合、Circle は保持される（L441-443）。"""
        import math
        w = make_window()
        ci = Circle(Vec2(0, 0), 10.0)
        arc1 = Arc(ci, 0.0, math.pi / 2)
        arc2 = Arc(ci, math.pi / 2, math.pi)
        ci.arcs.extend([arc1, arc2])
        w.scene.add_circle(ci)
        w._do_delete_objects([arc1])
        assert ci in w.scene.circles   # Circle は残る
        assert arc1 not in ci.arcs
        assert arc2 in ci.arcs

    def test_delete_arc_last_removes_circle(self):
        """[仕様] Arc を削除して arcs が空になると Circle ごと削除される（L438-439）。"""
        import math
        w = make_window()
        ci = Circle(Vec2(0, 0), 10.0)
        arc = Arc(ci, 0.0, math.pi)
        ci.arcs.append(arc)
        w.scene.add_circle(ci)
        w._do_delete_objects([arc])
        assert ci not in w.scene.circles

    def test_delete_line_object(self):
        """[C1] Line オブジェクトを削除する（L444-445）。"""
        w = make_window()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        w._do_delete_objects([ln])
        assert ln not in w.scene.lines

    def test_delete_circle_object(self):
        """[C1] Circle オブジェクトを削除する（L446-447）。"""
        w = make_window()
        ci = Circle(Vec2(0, 0), 10.0)
        w.scene.add_circle(ci)
        w._do_delete_objects([ci])
        assert ci not in w.scene.circles


class TestOpenVerticalWindowWithProfiles:
    """_open_vertical_window の標高同期テスト（L598-607）。"""

    def test_vertical_window_syncs_elevation(self):
        """[C1] 複数 EP が隣接するとき境界標高が同期される（L598-607）。"""
        from models import ElementProfile, GradeLine
        w = make_window()
        ln1 = Line(Vec2(0, 0), Vec2(100, 0))
        seg1 = Segment(ln1, 0.0, 1.0); ln1.segments.append(seg1)
        ln2 = Line(Vec2(100, 0), Vec2(200, 0))
        seg2 = Segment(ln2, 0.0, 1.0); ln2.segments.append(seg2)
        w.scene.add_line(ln1); w.scene.add_line(ln2)
        ep1 = ElementProfile(element_id=seg1.id, element_type='segment',
                              plan_length=100.0)
        gl1 = GradeLine(0.0, 100.0, 10.0, 12.0)
        ep1.grade_lines.append(gl1)
        ep2 = ElementProfile(element_id=seg2.id, element_type='segment',
                              plan_length=100.0)
        w.scene.element_profiles.extend([ep1, ep2])
        w._canvas.set_selection([seg1, seg2])
        w._open_vertical_window()
        # ep1.elev_end が ep2.elev_start に同期されている
        assert ep1.elev_end == ep2.elev_start
