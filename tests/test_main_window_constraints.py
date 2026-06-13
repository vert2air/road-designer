"""MainWindow の拘束設定・ID 振り直し・マージのハンドラテスト。

仕様（仕様書 2.8・5.10 / 基本設計書 4.4）に基づく。
ダイアログは unittest.mock.patch でモックする。
"""
import json
from unittest.mock import patch

import pytest

from models import (
    Vec2,
    Line,
    Segment,
    Circle,
    Scene,
    OffsetConstraint,
    TwoLineOffsetConstraint,
)


def _add_xy_lines_circle(scene):
    la = Line(Vec2(0, 0), Vec2(10, 0))
    lb = Line(Vec2(0, 0), Vec2(0, 10))
    ci = Circle(Vec2(13, 12), 10.0)
    scene.add_line(la)
    scene.add_line(lb)
    scene.add_circle(ci)
    return la, lb, ci


class TestDoSetTwoLineOffsetConstraint:
    def test_creates_constraint_with_current_offsets(
            self, make_window_qt):
        w = make_window_qt()
        la, lb, ci = _add_xy_lines_circle(w.scene)
        w._do_set_two_line_offset_constraint(la, lb, ci)
        assert len(w.scene.two_line_offset_constraints) == 1
        oc = w.scene.two_line_offset_constraints[0]
        assert oc.off_a == pytest.approx(2.0)
        assert oc.off_b == pytest.approx(3.0)

    def test_duplicate_is_ignored(self, make_window_qt):
        w = make_window_qt()
        la, lb, ci = _add_xy_lines_circle(w.scene)
        w._do_set_two_line_offset_constraint(la, lb, ci)
        w._do_set_two_line_offset_constraint(lb, la, ci)   # 順序逆も同一
        assert len(w.scene.two_line_offset_constraints) == 1

    def test_cycle_rejected_with_warning(self, make_window_qt):
        """既存 OC: {A,B}→S があるとき TLOC: {S,T}→A は循環 →
        警告して登録しない（仕様 5.10 循環依存の検出）。"""
        w = make_window_qt()
        s = Line(Vec2(0, 0), Vec2(10, 0))
        t = Line(Vec2(0, 5), Vec2(10, 8))
        a = Circle(Vec2(5, 30), 10.0)
        b = Circle(Vec2(5, -30), 10.0)
        w.scene.add_line(s)
        w.scene.add_line(t)
        w.scene.add_circle(a)
        w.scene.add_circle(b)
        oc = OffsetConstraint()
        oc.line, oc.circle_a, oc.circle_b = s, a, b
        w.scene.offset_constraints.append(oc)

        with patch('PySide6.QtWidgets.QMessageBox.warning') as mock_warn:
            w._do_set_two_line_offset_constraint(s, t, a)
        mock_warn.assert_called_once()
        assert len(w.scene.two_line_offset_constraints) == 0


class TestDoClearTwoLineOffsetConstraint:
    def test_clears_only_matching_pair(self, make_window_qt):
        w = make_window_qt()
        la, lb, ci = _add_xy_lines_circle(w.scene)
        lc = Line(Vec2(5, 0), Vec2(5, 10))
        w.scene.add_line(lc)
        ci2 = Circle(Vec2(20, 20), 5.0)
        w.scene.add_circle(ci2)
        oc1 = TwoLineOffsetConstraint()
        oc1.line_a, oc1.line_b, oc1.circle = la, lb, ci
        oc2 = TwoLineOffsetConstraint()
        oc2.line_a, oc2.line_b, oc2.circle = la, lc, ci2
        w.scene.two_line_offset_constraints.extend([oc1, oc2])

        w._do_clear_two_line_offset_constraint(lb, la)   # 順序逆でも一致
        remaining = w.scene.two_line_offset_constraints
        assert remaining == [oc2]

    def test_clear_is_undoable(self, make_window_qt):
        w = make_window_qt()
        la, lb, ci = _add_xy_lines_circle(w.scene)
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = la, lb, ci
        w.scene.two_line_offset_constraints.append(oc)
        w._do_clear_two_line_offset_constraint(la, lb)
        assert len(w.scene.two_line_offset_constraints) == 0
        w._canvas.undo()
        assert len(w.scene.two_line_offset_constraints) == 1


class TestDoSetOffsetConstraintCycle:
    def test_cycle_rejected_with_warning(self, make_window_qt):
        """既存 TLOC: {L1,L2}→C があるとき OC: {C,D}→L1 は循環。"""
        w = make_window_qt()
        l1 = Line(Vec2(0, 0), Vec2(10, 0))
        l2 = Line(Vec2(0, 0), Vec2(0, 10))
        c = Circle(Vec2(13, 12), 10.0)
        d = Circle(Vec2(40, 40), 5.0)
        w.scene.add_line(l1)
        w.scene.add_line(l2)
        w.scene.add_circle(c)
        w.scene.add_circle(d)
        tl = TwoLineOffsetConstraint()
        tl.line_a, tl.line_b, tl.circle = l1, l2, c
        w.scene.two_line_offset_constraints.append(tl)

        with patch('PySide6.QtWidgets.QMessageBox.warning') as mock_warn:
            w._do_set_offset_constraint(l1, c, d)
        mock_warn.assert_called_once()
        assert len(w.scene.offset_constraints) == 0


class TestRenumberIdsMenu:
    @staticmethod
    def _scene_with_gapped_ids(w):
        ln = Line(Vec2(0, 0), Vec2(10, 0), line_id=100)
        seg = Segment(ln, 0.0, 1.0, seg_id=200)
        ln.segments.append(seg)
        w.scene.add_line(ln)
        w.scene.set_nickname(100, "named")
        return ln, seg

    def test_ok_renumbers_from_one(self, make_window_qt):
        from PySide6.QtWidgets import QMessageBox
        w = make_window_qt()
        ln, seg = self._scene_with_gapped_ids(w)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Ok):
            w._renumber_ids()
        assert sorted([ln.id, seg.id]) == [1, 2]
        assert w.scene.get_nickname(ln.id) == "named"

    def test_cancel_keeps_ids(self, make_window_qt):
        from PySide6.QtWidgets import QMessageBox
        w = make_window_qt()
        ln, seg = self._scene_with_gapped_ids(w)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Cancel):
            w._renumber_ids()
        assert ln.id == 100
        assert seg.id == 200


class TestMergeMenu:
    def test_merge_adds_and_selects_only_new(
            self, make_window_qt, tmp_path):
        w = make_window_qt()
        base = Line(Vec2(0, 0), Vec2(10, 0))
        w.scene.add_line(base)
        w._canvas._selected = [base]

        src = Scene()
        ln = Line(Vec2(0, 100), Vec2(100, 100))
        ln.segments.append(Segment(ln, 0.0, 1.0))
        src.add_line(ln)
        path = tmp_path / "merge_src.rdjson"
        path.write_text(json.dumps(src.to_dict()), encoding='utf-8')

        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=(str(path), '')):
            w._merge()
        assert len(w.scene.lines) == 2
        # 既存の選択は解除され、追加図形のみ選択される
        assert base not in w._canvas._selected
        assert len(w._canvas._selected) == 1

    def test_merge_is_undoable(self, make_window_qt, tmp_path):
        w = make_window_qt()
        src = Scene()
        src.add_line(Line(Vec2(0, 100), Vec2(100, 100)))
        path = tmp_path / "merge_src.rdjson"
        path.write_text(json.dumps(src.to_dict()), encoding='utf-8')

        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=(str(path), '')):
            w._merge()
        assert len(w.scene.lines) == 1
        w._canvas.undo()
        assert len(w.scene.lines) == 0

    def test_merge_cancel_dialog_is_noop(self, make_window_qt):
        w = make_window_qt()
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=('', '')):
            w._merge()
        assert len(w.scene.lines) == 0
