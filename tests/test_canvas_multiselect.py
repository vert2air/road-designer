"""Canvas のラバーバンド選択・AABB 変換・折れ線追従の単体テスト。

仕様（仕様書 4.5 / 基本設計書 4.3.1・6.1.2・6.1.2b）に基づき、
期待座標は手計算した値を使う。
"""
import math

import pytest

from models import Vec2, Line, Segment, Circle, Arc


def _add_line_with_segment(scene, p0, p1):
    ln = Line(Vec2(*p0), Vec2(*p1))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    scene.add_line(ln)
    return ln, seg


class TestObjectsInWorldRect:
    """ラバーバンド選択の包含判定（仕様 4.5: 完全包含のみ選択）。"""

    def test_segment_fully_inside_selects_segment_and_parent(
            self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, seg = _add_line_with_segment(sc, (0, 0), (10, 0))
        result = c._objects_in_world_rect(-1, -1, 11, 1)
        assert seg in result
        assert ln in result

    def test_segment_partially_inside_not_selected(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, seg = _add_line_with_segment(sc, (0, 0), (10, 0))
        # 始点 (0,0) が矩形の外（x>5 のみ覆う）
        result = c._objects_in_world_rect(5, -1, 11, 1)
        assert result == []

    def test_circle_without_arcs_inside(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ci = Circle(Vec2(0, 0), 5.0)
        sc.add_circle(ci)
        assert c._objects_in_world_rect(-6, -6, 6, 6) == [ci]

    def test_circle_without_arcs_partially_inside(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ci = Circle(Vec2(0, 0), 5.0)
        sc.add_circle(ci)
        # 左端 (-5, 0) が矩形の外
        assert c._objects_in_world_rect(-4, -6, 6, 6) == []

    def test_arc_inside_selects_arc_and_parent_circle(
            self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi / 2)   # 第1象限の弧
        ci.arcs.append(arc)
        sc.add_circle(ci)
        result = c._objects_in_world_rect(-0.5, -0.5, 5.5, 5.5)
        assert arc in result
        assert ci in result

    def test_arc_bulge_outside_rect_not_selected(self, make_canvas_qt):
        """弧の膨らみ部分が矩形からはみ出す場合は選択しない。

        端点 (5,0)・(0,5) は対角線上の矩形に入るが、弧の中間点
        (5/√2, 5/√2)≈(3.54, 3.54) は端点を結ぶ対角線の外側にある。
        x 上限 3 の矩形では弧全体が入らない。
        """
        c, sc = make_canvas_qt()
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        result = c._objects_in_world_rect(-0.5, -0.5, 3.0, 5.5)
        assert result == []

    def test_multiple_objects_no_duplicates(self, make_canvas_qt):
        """同一円の複数円弧が入っても親円は 1 回だけ追加される。"""
        c, sc = make_canvas_qt()
        ci = Circle(Vec2(0, 0), 5.0)
        ci.arcs.append(Arc(ci, 0.0, 0.5))
        ci.arcs.append(Arc(ci, 1.0, 1.5))
        sc.add_circle(ci)
        result = c._objects_in_world_rect(-6, -6, 6, 6)
        assert result.count(ci) == 1
        assert len(result) == 3   # arc×2 + circle×1


class TestCompleteRubberSelect:
    """_complete_rubber_select（スクリーン矩形 → 選択）。"""

    def test_tiny_rect_is_click(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        _add_line_with_segment(sc, (0, 0), (10, 0))
        c._rubber_select_start = Vec2(500, 500)
        c._rubber_select_end = Vec2(502, 502)   # 4px 未満
        assert c._complete_rubber_select() == []

    def test_screen_rect_maps_to_world(self, make_canvas_qt):
        """スクリーン y 反転を跨いだ変換が正しいこと。

        scale=1, offset=(500,500) → ワールド (0,0)=スクリーン (500,500)。
        線分 (0,0)-(10,0) を囲むスクリーン矩形は
        (499,499)-(511,501)（y はワールド ±1 に対応）。
        """
        c, sc = make_canvas_qt()
        ln, seg = _add_line_with_segment(sc, (0, 0), (10, 0))
        c._rubber_select_start = Vec2(489, 489)
        c._rubber_select_end = Vec2(511, 511)
        result = c._complete_rubber_select()
        assert seg in result and ln in result


class TestBboxTransforms:
    """AABB 変換（仕様 4.5: 頂点=等率拡縮 / 辺=移動 / 対角線=回転）。"""

    @staticmethod
    def _setup(c, sc):
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        ci = Circle(Vec2(20, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        c._selected = [ln, ci]
        c._bbox_drag_snapshot = c._snapshot_selected()
        return ln, ci, arc

    def test_translate(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, ci, _ = self._setup(c, sc)
        c._bbox_apply_translate(3, 4)
        assert (ln.ref_start.x, ln.ref_start.y) == (3, 4)
        assert (ln.ref_end.x, ln.ref_end.y) == (13, 4)
        assert (ci.center.x, ci.center.y) == (23, 4)
        assert ci.radius == 5.0   # 平行移動で半径は不変

    def test_translate_is_not_cumulative(self, make_canvas_qt):
        """同じ移動量で 2 回呼んでも結果は 1 回分（スナップショット基準）。"""
        c, sc = make_canvas_qt()
        ln, ci, _ = self._setup(c, sc)
        c._bbox_apply_translate(3, 4)
        c._bbox_apply_translate(3, 4)
        assert (ln.ref_start.x, ln.ref_start.y) == (3, 4)
        assert (ci.center.x, ci.center.y) == (23, 4)

    def test_scale_about_origin(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, ci, _ = self._setup(c, sc)
        c._bbox_apply_scale(2.0, Vec2(0, 0))
        assert (ln.ref_start.x, ln.ref_start.y) == (0, 0)
        assert (ln.ref_end.x, ln.ref_end.y) == (20, 0)
        assert (ci.center.x, ci.center.y) == (40, 0)
        assert ci.radius == 10.0

    def test_scale_about_arbitrary_center(self, make_canvas_qt):
        """中心 (10,0)・倍率 0.5: 点 P → center + (P-center)*0.5。"""
        c, sc = make_canvas_qt()
        ln, ci, _ = self._setup(c, sc)
        c._bbox_apply_scale(0.5, Vec2(10, 0))
        assert (ln.ref_start.x, ln.ref_start.y) == (5, 0)
        assert (ln.ref_end.x, ln.ref_end.y) == (10, 0)
        assert (ci.center.x, ci.center.y) == (15, 0)
        assert ci.radius == 2.5

    def test_rotate_90_about_origin(self, make_canvas_qt):
        """90° 回転: (x,y) → (−y,x)。円弧角度も 90° シフト。"""
        c, sc = make_canvas_qt()
        ln, ci, arc = self._setup(c, sc)
        c._bbox_apply_rotate(math.pi / 2, Vec2(0, 0))
        assert ln.ref_end.x == pytest.approx(0)
        assert ln.ref_end.y == pytest.approx(10)
        assert ci.center.x == pytest.approx(0)
        assert ci.center.y == pytest.approx(20)
        assert arc.angle_start == pytest.approx(math.pi / 2)
        assert arc.angle_end == pytest.approx(math.pi)
        assert ci.radius == 5.0   # 回転で半径は不変

    def test_rotate_preserves_arc_endpoint_position(self, make_canvas_qt):
        """円弧の端点は剛体回転として正しい位置に来ること。

        回転前の弧始点 (25, 0)（=中心(20,0)+r5・角0）は
        原点 90° 回転で (0, 25) に移るはず。
        """
        c, sc = make_canvas_qt()
        _, ci, arc = self._setup(c, sc)
        c._bbox_apply_rotate(math.pi / 2, Vec2(0, 0))
        assert arc.start.x == pytest.approx(0)
        assert arc.start.y == pytest.approx(25)


class TestSelectionAabb:
    """_selection_aabb と _is_multi_select。"""

    def test_aabb_of_line_and_circle(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        ci = Circle(Vec2(20, 0), 5.0)
        sc.add_circle(ci)
        c._selected = [ln, ci]
        aabb = c._selection_aabb()
        # 線分 (0,0)-(10,0) と円の外接 (15,-5)-(25,5)
        assert aabb == (0, -5, 25, 5)

    def test_single_object_is_not_multi(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        c._selected = [ln]
        assert c._is_multi_select() is False

    def test_seg_and_parent_line_is_not_multi(self, make_canvas_qt):
        """線分と親直線の 2 個選択は実効 1 図形 → 複数選択ではない。"""
        c, sc = make_canvas_qt()
        ln, seg = _add_line_with_segment(sc, (0, 0), (10, 0))
        c._selected = [seg, ln]
        assert c._is_multi_select() is False


class TestFollowPolylineConnection:
    """折れ線接続の追従（基本設計書 4.3.1 追従動作）。"""

    @staticmethod
    def _connected_pair(c, sc):
        la, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        lb, _ = _add_line_with_segment(sc, (10, 0), (10, 10))
        c._connect_polyline(la, lb)
        assert la.connection is lb.connection
        return la, lb

    def test_partner_translates_to_follow_shared_point(
            self, make_canvas_qt):
        """直線 A を +y に 5 移動 → B は平行移動して共有点を追従。"""
        c, sc = make_canvas_qt()
        la, lb = self._connected_pair(c, sc)
        la.ref_start = Vec2(0, 5)
        la.ref_end = Vec2(10, 5)
        c._propagate_line(la)
        # B は (0,5) 平行移動: (10,5)-(10,15)
        assert (lb.ref_start.x, lb.ref_start.y) == (10, 5)
        assert (lb.ref_end.x, lb.ref_end.y) == (10, 15)
        # 共有点も更新される
        conn = la.connection
        assert (conn.shared_point.x, conn.shared_point.y) == (10, 5)

    def test_partner_direction_unchanged(self, make_canvas_qt):
        """追従は平行移動であり、相手の方向は変わらない。"""
        c, sc = make_canvas_qt()
        la, lb = self._connected_pair(c, sc)
        before = lb.direction
        la.ref_start = Vec2(3, 7)
        la.ref_end = Vec2(13, 7)
        c._propagate_line(la)
        after = lb.direction
        assert after.x == pytest.approx(before.x)
        assert after.y == pytest.approx(before.y)

    def test_no_move_is_noop(self, make_canvas_qt):
        """共有点が動いていなければ相手は動かない（再帰終端）。"""
        c, sc = make_canvas_qt()
        la, lb = self._connected_pair(c, sc)
        b_start = (lb.ref_start.x, lb.ref_start.y)
        c._propagate_line(la)
        assert (lb.ref_start.x, lb.ref_start.y) == b_start

    def test_moving_b_follows_back_to_a(self, make_canvas_qt):
        """逆方向（B を動かす）でも A が追従する。"""
        c, sc = make_canvas_qt()
        la, lb = self._connected_pair(c, sc)
        lb.ref_start = Vec2(15, 0)
        lb.ref_end = Vec2(15, 10)
        c._propagate_line(lb)
        # A は (5,0) 平行移動: (5,0)-(15,0)
        assert (la.ref_start.x, la.ref_start.y) == (5, 0)
        assert (la.ref_end.x, la.ref_end.y) == (15, 0)
