"""RightPanel の複数選択操作（コピー・移動・回転・拡縮）の単体テスト。

仕様（仕様書 5.6 / 詳細設計書 8.1b）に基づき、期待座標は手計算する。
"""
import math

import pytest

from models import Vec2, Line, Segment, Circle, Arc, Scene
from vertical_profile import ElementProfile, GradeLine


def _scene_line_circle():
    """直線 (0,0)-(10,0)（線分付き）と円 (20,0) r=5（弧付き）。"""
    sc = Scene()
    ln = Line(Vec2(0, 0), Vec2(10, 0))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    sc.add_line(ln)
    ci = Circle(Vec2(20, 0), 5.0)
    arc = Arc(ci, 0.0, math.pi / 2)
    ci.arcs.append(arc)
    sc.add_circle(ci)
    return sc, ln, seg, ci, arc


class TestDoTranslate:
    def test_moves_all_selected(self, make_panel_qt):
        sc, ln, _, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_translate(1, 2)
        assert (ln.ref_start.x, ln.ref_start.y) == (1, 2)
        assert (ln.ref_end.x, ln.ref_end.y) == (11, 2)
        assert (ci.center.x, ci.center.y) == (21, 2)
        assert ci.radius == 5.0

    def test_child_selection_moves_parent(self, make_panel_qt):
        """線分・円弧を選択していても親図形全体が動く（effective_set）。"""
        sc, ln, seg, ci, arc = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [seg, arc]
        p._do_translate(0, 10)
        assert ln.ref_start.y == 10
        assert ci.center.y == 10

    def test_unselected_untouched(self, make_panel_qt):
        sc, ln, _, ci, _ = _scene_line_circle()
        other = Line(Vec2(100, 100), Vec2(110, 100))
        sc.add_line(other)
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_translate(5, 5)
        assert (other.ref_start.x, other.ref_start.y) == (100, 100)


class TestDoRotate:
    def test_rotate_90_about_origin(self, make_panel_qt):
        sc, ln, _, ci, arc = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_rotate(90.0, use_bbox_center=False)
        # (x,y) → (−y,x)
        assert ln.ref_end.x == pytest.approx(0)
        assert ln.ref_end.y == pytest.approx(10)
        assert ci.center.x == pytest.approx(0)
        assert ci.center.y == pytest.approx(20)
        # 円弧角度も +90°
        assert arc.angle_start == pytest.approx(math.pi / 2)

    def test_rotate_180_about_bbox_center(self, make_panel_qt):
        """直線のみ選択・AABB 中心 (5,0) 基準の 180° 回転で
        参照点が入れ替わった位置に来る。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        ln.segments.append(Segment(ln, 0.0, 1.0))
        sc.add_line(ln)
        p, _ = make_panel_qt(sc)
        p._selected = [ln]
        p._do_rotate(180.0, use_bbox_center=True)
        assert ln.ref_start.x == pytest.approx(10)
        assert ln.ref_start.y == pytest.approx(0)
        assert ln.ref_end.x == pytest.approx(0)
        assert ln.ref_end.y == pytest.approx(0)

    def test_rotation_is_rigid_for_arc_endpoint(self, make_panel_qt):
        """弧の始点 (25,0) が原点 90° 回転で (0,25) に来る（剛体性）。"""
        sc, ln, _, ci, arc = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_rotate(90.0, use_bbox_center=False)
        assert arc.start.x == pytest.approx(0)
        assert arc.start.y == pytest.approx(25)


class TestDoScale:
    def test_scale_about_origin(self, make_panel_qt):
        sc, ln, _, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_scale(2.0, use_bbox_center=False)
        assert (ln.ref_end.x, ln.ref_end.y) == (20, 0)
        assert (ci.center.x, ci.center.y) == (40, 0)
        assert ci.radius == 10.0

    def test_scale_keeps_segment_world_length_ratio(self, make_panel_qt):
        """線分は t で親直線に従属するため、線分長も倍率に従う。"""
        sc, ln, seg, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        before = seg.length()
        p._do_scale(3.0, use_bbox_center=False)
        assert seg.length() == pytest.approx(before * 3.0)

    def test_zero_factor_is_noop(self, make_panel_qt):
        sc, ln, _, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_scale(0.0, use_bbox_center=False)
        assert (ln.ref_end.x, ln.ref_end.y) == (10, 0)
        assert ci.radius == 5.0


class TestDoCopy:
    def test_copies_appended_and_originals_untouched(self, make_panel_qt):
        sc, ln, _, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_copy()
        assert len(sc.lines) == 2
        assert len(sc.circles) == 2
        # 元図形は不変
        assert (ln.ref_start.x, ln.ref_start.y) == (0, 0)
        # 複製はジオメトリが等しく ID が異なる
        copy_ln = [x for x in sc.lines if x is not ln][0]
        assert copy_ln.id != ln.id
        assert (copy_ln.ref_start.x, copy_ln.ref_start.y) == (0, 0)
        assert (copy_ln.ref_end.x, copy_ln.ref_end.y) == (10, 0)

    def test_copy_emits_request_select_with_copies_only(
            self, make_panel_qt, qtbot):
        sc, ln, _, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        with qtbot.waitSignal(p.request_select, timeout=1000) as blocker:
            p._do_copy()
        selected = blocker.args[0]
        assert ln not in selected
        assert ci not in selected
        assert len(selected) == 2

    def test_copy_duplicates_children(self, make_panel_qt):
        """線分・円弧も複製され、複製側の子は複製親に属する。"""
        sc, ln, seg, ci, arc = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_copy()
        copy_ln = [x for x in sc.lines if x is not ln][0]
        copy_ci = [x for x in sc.circles if x is not ci][0]
        assert len(copy_ln.segments) == 1
        assert copy_ln.segments[0] is not seg
        assert copy_ln.segments[0].line is copy_ln
        assert len(copy_ci.arcs) == 1
        assert copy_ci.arcs[0].circle is copy_ci
        assert copy_ci.arcs[0].angle_end == pytest.approx(math.pi / 2)

    def test_copy_all_ids_unique(self, make_panel_qt):
        sc, ln, _, ci, _ = _scene_line_circle()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci]
        p._do_copy()
        ids = []
        for x in sc.lines:
            ids.append(x.id)
            ids.extend(s.id for s in x.segments)
        for x in sc.circles:
            ids.append(x.id)
            ids.extend(a.id for a in x.arcs)
        assert len(ids) == len(set(ids))

    def test_copy_duplicates_element_profile(self, make_panel_qt):
        """仕様 5.6: 対応する縦断線形データも複製される。"""
        sc, ln, seg, ci, _ = _scene_line_circle()
        ep = ElementProfile()
        ep.element_id = seg.id
        ep.element_type = "segment"
        ep.plan_length = 10.0
        gl = GradeLine()
        gl.dist_start, gl.elev_start = 0.0, 5.0
        gl.dist_end, gl.elev_end = 10.0, 8.0
        ep.grade_lines.append(gl)
        sc.element_profiles.append(ep)

        p, _ = make_panel_qt(sc)
        p._selected = [ln]
        p._do_copy()
        assert len(sc.element_profiles) == 2
        copy_ln = [x for x in sc.lines if x is not ln][0]
        copy_seg = copy_ln.segments[0]
        new_ep = [e for e in sc.element_profiles if e is not ep][0]
        # 複製 EP は複製線分を指し、縦断データの中身が等しい
        assert new_ep.element_id == copy_seg.id
        assert len(new_ep.grade_lines) == 1
        assert new_ep.grade_lines[0].elev_end == pytest.approx(8.0)
        assert new_ep.grade_lines[0] is not gl
