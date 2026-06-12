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


class TestTwoLineOffsetPanel:
    """_build_two_line_offset_constraint パネル（仕様 5.10.2）。"""

    @staticmethod
    def _scene_two_lines_circle():
        sc = Scene()
        la = Line(Vec2(0, 0), Vec2(10, 0))
        la.segments.append(Segment(la, 0.0, 1.0))
        lb = Line(Vec2(0, 0), Vec2(0, 10))
        lb.segments.append(Segment(lb, 0.0, 1.0))
        ci = Circle(Vec2(13, 12), 10.0)
        sc.add_line(la)
        sc.add_line(lb)
        sc.add_circle(ci)
        return sc, la, lb, ci

    @staticmethod
    def _find_button(panel, text):
        from PySide6.QtWidgets import QPushButton
        for b in panel.findChildren(QPushButton):
            if b.text() == text:
                return b
        return None

    def test_unset_panel_set_button_emits_request(
            self, make_panel_qt, qtbot):
        sc, la, lb, ci = self._scene_two_lines_circle()
        p, _ = make_panel_qt(sc)
        p.update_selection([la, lb, ci], sc)
        btn = self._find_button(p, "オフセット拘束を設定")
        assert btn is not None
        with qtbot.waitSignal(
                p.request_set_two_line_offset, timeout=1000) as blocker:
            btn.click()
        a, b, c = blocker.args
        assert {a, b} == {la, lb}
        assert c is ci

    def test_set_panel_clear_button_emits_request(
            self, make_panel_qt, qtbot):
        from models import TwoLineOffsetConstraint
        sc, la, lb, ci = self._scene_two_lines_circle()
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = la, lb, ci
        oc.calc_offsets_from_current()
        sc.two_line_offset_constraints.append(oc)
        p, _ = make_panel_qt(sc)
        p.update_selection([la, lb, ci], sc)
        btn = self._find_button(p, "オフセット拘束を解除")
        assert btn is not None
        with qtbot.waitSignal(
                p.request_clear_two_line_offset, timeout=1000) as blocker:
            btn.click()
        assert {blocker.args[0], blocker.args[1]} == {la, lb}

    def test_set_panel_spinbox_moves_circle(self, make_panel_qt):
        """設定済みパネルで off_a を変更すると円中心が即追従する。

        初期 off_a=2（A=x軸から縁まで 2m）。off_a を 7 に変更すると
        中心 y は 10+7=17 になるはず。
        """
        from PySide6.QtWidgets import QDoubleSpinBox
        from models import TwoLineOffsetConstraint
        sc, la, lb, ci = self._scene_two_lines_circle()
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = la, lb, ci
        oc.calc_offsets_from_current()
        sc.two_line_offset_constraints.append(oc)
        p, _ = make_panel_qt(sc)
        p.update_selection([la, lb, ci], sc)
        sbs = [sb for sb in p.findChildren(QDoubleSpinBox)
               if sb.isVisible() or True]
        # off_a スピンボックス（値 2.0）を特定して変更する
        sb_a = [sb for sb in sbs
                if abs(sb.value() - 2.0) < 1e-6]
        assert sb_a, "off_a スピンボックスが見つからない"
        sb_a[0].setValue(7.0)
        assert ci.center.y == pytest.approx(17.0)
        assert ci.center.x == pytest.approx(13.0)


class TestDoCopyWithClothoid:
    """クロソイドを含むコピー（詳細設計書 8.1b _do_copy）。"""

    @staticmethod
    def _scene_with_clothoid():
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ln.segments.append(Segment(ln, 0.0, 1.0))
        sc.add_line(ln)
        ci = Circle(Vec2(0, 30), 10.0)   # d=30 > r=10 → 有効クロソイド
        sc.add_circle(ci)
        from models import Clothoid
        clo = Clothoid(ln, ci)
        sc.add_clothoid(clo)
        assert clo.is_valid
        return sc, ln, ci, clo

    def test_clothoid_copy_references_copied_parents(self, make_panel_qt):
        """親 Line/Circle も同時コピーされた場合、複製クロソイドは
        複製された親を参照する。"""
        sc, ln, ci, clo = self._scene_with_clothoid()
        p, _ = make_panel_qt(sc)
        p._selected = [ln, ci, clo]
        p._do_copy()
        new_clo = [c for c in sc.clothoids if c is not clo][0]
        assert new_clo.line is not ln
        assert new_clo.circle is not ci
        assert new_clo.line in sc.lines
        assert new_clo.circle in sc.circles
        assert new_clo.is_valid

    def test_clothoid_only_copy_references_originals(self, make_panel_qt):
        """クロソイドのみ選択コピー → 元の Line/Circle を参照する。"""
        sc, ln, ci, clo = self._scene_with_clothoid()
        p, _ = make_panel_qt(sc)
        p._selected = [clo]
        p._do_copy()
        new_clo = [c for c in sc.clothoids if c is not clo][0]
        assert new_clo.line is ln
        assert new_clo.circle is ci
        assert len(sc.lines) == 1     # 親は複製されない
        assert len(sc.circles) == 1


class TestDoCopyElementProfileWithCurve:
    """縦断曲線・相互参照込みの ElementProfile 複製。"""

    def test_vertical_curve_copied_with_remapped_gl_ids(
            self, make_panel_qt):
        from vertical_profile import VerticalCurve
        sc, ln, seg, ci, _ = _scene_line_circle()
        ep = ElementProfile()
        ep.element_id = seg.id
        ep.element_type = "segment"
        ep.plan_length = 10.0
        gl1 = GradeLine()
        gl1.dist_start, gl1.elev_start = 0.0, 0.0
        gl1.dist_end, gl1.elev_end = 5.0, 1.0
        gl2 = GradeLine()
        gl2.dist_start, gl2.elev_start = 5.0, 1.0
        gl2.dist_end, gl2.elev_end = 10.0, 1.0
        ep.grade_lines.extend([gl1, gl2])
        vc = VerticalCurve()
        vc.pvi_dist, vc.pvi_elev = 5.0, 1.0
        vc.g1, vc.g2, vc.length = 20.0, 0.0, 2.0
        vc.prev_line_id, vc.next_line_id = gl1.id, gl2.id
        gl1.next_curve = vc
        gl2.prev_curve = vc
        ep.vertical_curves.append(vc)
        sc.element_profiles.append(ep)

        p, _ = make_panel_qt(sc)
        p._selected = [ln]
        p._do_copy()
        new_ep = [e for e in sc.element_profiles if e is not ep][0]
        assert len(new_ep.vertical_curves) == 1
        new_vc = new_ep.vertical_curves[0]
        new_gl_ids = {g.id for g in new_ep.grade_lines}
        # 相互参照が新しい ID 体系で再構築されている
        assert new_vc.prev_line_id in new_gl_ids
        assert new_vc.next_line_id in new_gl_ids
        assert new_vc.id != vc.id
        assert new_vc.length == pytest.approx(2.0)
        # 新 GradeLine の next/prev_curve は新 VC を指す
        assert new_ep.grade_lines[0].next_curve is new_vc
        assert new_ep.grade_lines[1].prev_curve is new_vc


class TestRelatedConstraintsPanel:
    """関連オフセット拘束の一覧表示と選択（仕様 5.5）。"""

    @staticmethod
    def _scene_with_both_constraints():
        from models import OffsetConstraint, TwoLineOffsetConstraint
        sc = Scene()
        s = Line(Vec2(-100, 0), Vec2(100, 0))
        s.segments.append(Segment(s, 0.0, 1.0))
        lb = Line(Vec2(0, -100), Vec2(0, 100))
        lb.segments.append(Segment(lb, 0.0, 1.0))
        ca = Circle(Vec2(0, 30), 10.0)
        cb = Circle(Vec2(0, -30), 10.0)
        sc.add_line(s)
        sc.add_line(lb)
        sc.add_circle(ca)
        sc.add_circle(cb)
        oc = OffsetConstraint()
        oc.line, oc.circle_a, oc.circle_b = s, ca, cb
        oc.calc_offsets_from_current()
        sc.offset_constraints.append(oc)
        tl = TwoLineOffsetConstraint()
        tl.line_a, tl.line_b, tl.circle = s, lb, ca
        tl.calc_offsets_from_current()
        sc.two_line_offset_constraints.append(tl)
        return sc, s, lb, ca, cb

    def test_group_lists_both_constraint_kinds(self, make_panel_qt):
        """直線 S は OC と TLOC の両方に関与 → 一覧に 2 行出る。"""
        from PySide6.QtWidgets import QGroupBox, QPushButton
        sc, s, *_ = self._scene_with_both_constraints()
        p, _ = make_panel_qt(sc)
        p.update_selection([s], sc)
        groups = [g for g in p.findChildren(QGroupBox)
                  if g.title() == "オフセット拘束"]
        assert len(groups) == 1
        btns = [b for b in groups[0].findChildren(QPushButton)
                if b.text() == "選択"]
        assert len(btns) == 2

    def test_select_button_selects_constraint_figures(
            self, make_panel_qt, qtbot):
        """「選択」で拘束の全構成図形が選択される。"""
        from PySide6.QtWidgets import QGroupBox, QPushButton
        sc, s, lb, ca, cb = self._scene_with_both_constraints()
        p, _ = make_panel_qt(sc)
        p.update_selection([ca], sc)   # 円 A 視点でも拘束が見える
        groups = [g for g in p.findChildren(QGroupBox)
                  if g.title() == "オフセット拘束"]
        assert groups
        btns = [b for b in groups[0].findChildren(QPushButton)
                if b.text() == "選択"]
        results = []
        p.request_select.connect(lambda objs: results.append(objs))
        for b in btns:
            b.click()
        # どの行の選択も 3 図形（拘束の構成要素）を含む
        assert results
        for objs in results:
            assert len(objs) == 3
        all_sets = [set(map(id, objs)) for objs in results]
        assert ({id(s), id(ca), id(cb)} in all_sets
                or {id(s), id(lb), id(ca)} in all_sets)

    def test_unrelated_figure_shows_no_group(self, make_panel_qt):
        from PySide6.QtWidgets import QGroupBox
        sc, *_ = self._scene_with_both_constraints()
        other = Line(Vec2(500, 500), Vec2(510, 500))
        sc.add_line(other)
        p, _ = make_panel_qt(sc)
        p.update_selection([other], sc)
        groups = [g for g in p.findChildren(QGroupBox)
                  if g.title() == "オフセット拘束"]
        assert groups == []


class TestSelectionBboxCenter:
    """_selection_bbox_center の図形タイプ別の寄与点。"""

    def test_line_without_segments_uses_refs(self, make_panel_qt):
        sc = Scene()
        ln = Line(Vec2(2, 4), Vec2(12, 8))   # 線分なし
        sc.add_line(ln)
        p, _ = make_panel_qt(sc)
        center = p._selection_bbox_center([ln])
        assert (center.x, center.y) == (7, 6)

    def test_circle_uses_extent(self, make_panel_qt):
        sc = Scene()
        ci = Circle(Vec2(10, 20), 5.0)
        sc.add_circle(ci)
        p, _ = make_panel_qt(sc)
        center = p._selection_bbox_center([ci])
        assert (center.x, center.y) == (10, 20)

    def test_clothoid_uses_points(self, make_panel_qt):
        from models import Clothoid
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ln.segments.append(Segment(ln, 0.0, 1.0))
        sc.add_line(ln)
        ci = Circle(Vec2(0, 30), 10.0)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci)
        assert clo.is_valid
        p, _ = make_panel_qt(sc)
        center = p._selection_bbox_center([clo])
        # クロソイド点列の AABB 中心は線（y=0）と円（y≦30）の間
        xs = [pt.x for pt in clo.points]
        ys = [pt.y for pt in clo.points]
        assert center.x == pytest.approx((min(xs) + max(xs)) / 2)
        assert center.y == pytest.approx((min(ys) + max(ys)) / 2)

    def test_empty_returns_origin(self, make_panel_qt):
        p, _ = make_panel_qt(Scene())
        center = p._selection_bbox_center([])
        assert (center.x, center.y) == (0, 0)
