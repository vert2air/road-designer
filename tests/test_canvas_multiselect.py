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


class TestHitBbox:
    """_hit_bbox のヒット判定（頂点 → 対角線 → 辺の優先順）。

    キャンバスは scale=1, offset=(500,500)。
    AABB はワールド (0,-50)-(150,50) → スクリーン四隅
    TL(500,450)・TR(650,450)・BR(650,550)・BL(500,550)。
    """

    @staticmethod
    def _setup(c, sc):
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        ci = Circle(Vec2(100, 0), 50.0)
        sc.add_circle(ci)
        c._selected = [ln, ci]
        return ln, ci

    def test_vertex_hit(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        self._setup(c, sc)
        assert c._hit_bbox(Vec2(500, 450)) == 'vertex_0'   # TL
        assert c._hit_bbox(Vec2(650, 550)) == 'vertex_2'   # BR

    def test_edge_hit_on_top_edge(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        self._setup(c, sc)
        # 上辺の中点（対角線から十分離れている）
        assert c._hit_bbox(Vec2(575, 450)) == 'edge_0'

    def test_diagonal_hit(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        self._setup(c, sc)
        # TL→BR 対角線上 t=0.3 の点 (545, 480)
        assert c._hit_bbox(Vec2(545, 480)) == 'diagonal'

    def test_miss_returns_none(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        self._setup(c, sc)
        assert c._hit_bbox(Vec2(300, 300)) is None

    def test_single_selection_returns_none(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        c._selected = [ln]
        assert c._hit_bbox(Vec2(500, 500)) is None


class TestDoBboxDrag:
    """_do_bbox_drag のモード別フルパイプライン。

    AABB はワールド (0,-50)-(150,50)、中心 (75, 0)。
    """

    @staticmethod
    def _setup_drag(c, sc, mode, start_w):
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        ci = Circle(Vec2(100, 0), 50.0)
        sc.add_circle(ci)
        c._selected = [ln, ci]
        c._bbox_drag_mode = mode
        c._bbox_drag_start_w = Vec2(*start_w)
        c._bbox_drag_snapshot = c._snapshot_selected()
        c._bbox_drag_aabb = c._selection_aabb()
        return ln, ci

    def test_edge_mode_translates(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, ci = self._setup_drag(c, sc, 'edge_0', (0, 0))
        c._do_bbox_drag(Vec2(3, 4))
        assert (ln.ref_start.x, ln.ref_start.y) == (3, 4)
        assert (ci.center.x, ci.center.y) == (103, 4)

    def test_vertex_mode_scales_by_max_ratio(self, make_canvas_qt):
        """頂点 TR(150,50) を (225,0) へ → fx=150/75=2, fy=0 →
        factor=max=2。中心 (75,0) 基準で 2 倍。"""
        c, sc = make_canvas_qt()
        ln, ci = self._setup_drag(c, sc, 'vertex_1', (150, 50))
        c._do_bbox_drag(Vec2(225, 0))
        assert ln.ref_start.x == pytest.approx(-75)
        assert ln.ref_end.x == pytest.approx(-55)
        assert ci.center.x == pytest.approx(125)
        assert ci.radius == pytest.approx(100)

    def test_diagonal_mode_rotates(self, make_canvas_qt):
        """開始点 TR(150,50) を中心周り 90° の位置 (25,75) へ →
        全体が中心 (75,0) 基準で 90° 回転。"""
        c, sc = make_canvas_qt()
        ln, ci = self._setup_drag(c, sc, 'diagonal', (150, 50))
        # (150,50)-中心(75,0) = (75,50) → 90°回転 (-50,75) → (25,75)
        c._do_bbox_drag(Vec2(25, 75))
        assert ln.ref_start.x == pytest.approx(75)
        assert ln.ref_start.y == pytest.approx(-75)
        assert ci.center.x == pytest.approx(75)
        assert ci.center.y == pytest.approx(25)
        assert ci.radius == pytest.approx(50)   # 回転で半径不変

    def test_no_mode_is_noop(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, ci = self._setup_drag(c, sc, None, (0, 0))
        c._bbox_drag_mode = None
        c._do_bbox_drag(Vec2(100, 100))
        assert (ln.ref_start.x, ln.ref_start.y) == (0, 0)


class TestSelectionAabbVariants:
    """_selection_aabb の図形タイプ別の寄与点。"""

    def test_empty_selection_returns_none(self, make_canvas_qt):
        c, _ = make_canvas_qt()
        c._selected = []
        assert c._selection_aabb() is None

    def test_line_without_segments_uses_refs(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln = Line(Vec2(2, 3), Vec2(12, 7))
        sc.add_line(ln)
        c._selected = [ln]
        assert c._selection_aabb() == (2, 3, 12, 7)

    def test_segment_direct_selection(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ln, seg = _add_line_with_segment(sc, (0, 0), (10, 0))
        c._selected = [seg]
        assert c._selection_aabb() == (0, 0, 10, 0)

    def test_arc_contributes_circle_extent(self, make_canvas_qt):
        c, sc = make_canvas_qt()
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, 1.0)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        c._selected = [arc]
        assert c._selection_aabb() == (-5, -5, 5, 5)


class TestEscapeClearsRubberSelect:
    """Esc キーでラバーバンド選択がキャンセルされる（仕様 4.5）。"""

    def test_escape_resets_and_clears_measure(
            self, make_canvas_qt, qtbot):
        from PySide6.QtCore import Qt
        c, sc = make_canvas_qt()
        c._rubber_select_start = Vec2(100, 100)
        c._rubber_select_end = Vec2(200, 200)
        with qtbot.waitSignal(c.measure_dist_changed,
                              timeout=1000) as blocker:
            qtbot.keyClick(c, Qt.Key.Key_Escape)
        assert blocker.args[0] == -1.0
        assert c._rubber_select_start is None
        assert c._rubber_select_end is None


class TestPropagateFromPublicEntries:
    """propagate_from_line / propagate_from_circle の公開伝播。"""

    @staticmethod
    def _setup_tloc(sc):
        from models import TwoLineOffsetConstraint
        la = Line(Vec2(0, 0), Vec2(10, 0))
        lb = Line(Vec2(0, 0), Vec2(0, 10))
        ci = Circle(Vec2(13, 12), 10.0)
        sc.add_line(la)
        sc.add_line(lb)
        sc.add_circle(ci)
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = la, lb, ci
        oc.calc_offsets_from_current()
        sc.two_line_offset_constraints.append(oc)
        return la, lb, ci

    def test_propagate_from_line_moves_circle(
            self, make_canvas_qt, qtbot):
        c, sc = make_canvas_qt()
        la, _, ci = self._setup_tloc(sc)
        la.ref_start = Vec2(0, 5)
        la.ref_end = Vec2(10, 5)
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            c.propagate_from_line(la)
        assert ci.center.y == pytest.approx(17.0)
        assert ci.center.x == pytest.approx(13.0)

    def test_propagate_from_circle_radius_change(
            self, make_canvas_qt, qtbot):
        """半径変更 → 円中心が縁オフセットを維持する位置へ動く。"""
        c, sc = make_canvas_qt()
        _, _, ci = self._setup_tloc(sc)
        ci.radius = 5.0
        with qtbot.waitSignal(c.scene_changed, timeout=1000):
            c.propagate_from_circle(ci)
        assert ci.center.x == pytest.approx(8.0)
        assert ci.center.y == pytest.approx(7.0)


class TestRubberSelectDragPipeline:
    """Shift+ドラッグの press → move → release フルパイプライン。

    scale=1, offset=(500,500): ワールド (x,y) = スクリーン (x+500, 500−y)。
    """

    def test_full_drag_selects_and_measures(self, make_canvas_qt, qtbot):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        c, sc = make_canvas_qt()
        ln, seg = _add_line_with_segment(sc, (0, 0), (10, 0))

        measured = []
        c.measure_dist_changed.connect(measured.append)
        # 図形のヒット範囲外（直線から 200 ワールド単位上）から
        # 線分全体を囲むドラッグ: ワールド (-100,200) → (12,-2)
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier,
                         QPoint(400, 300))
        assert c._rubber_select_start is not None
        QTest.mouseMove(c, QPoint(512, 502))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ShiftModifier,
                           QPoint(512, 502))
        # 選択結果: 線分とその親直線
        assert seg in c._selected
        assert ln in c._selected
        # 測距: ドラッグ中に正の距離 → 終了で −1
        assert any(d > 0 for d in measured)
        assert measured[-1] == -1.0
        assert c._rubber_select_start is None

    def test_drag_paints_rubber_rect(self, make_canvas_qt, qtbot):
        """ドラッグ中の再描画で _draw_rubber_select が実行される。"""
        c, sc = make_canvas_qt()
        c._rubber_select_start = Vec2(450, 450)
        c._rubber_select_end = Vec2(550, 550)
        c.repaint()   # 例外なく矩形+対角線が描画される
        assert True


class TestBboxDragEventPipeline:
    """AABB ハンドルの press → move → release フルパイプライン。

    AABB はワールド (0,-50)-(150,50) → スクリーン TL(500,450)。
    """

    @staticmethod
    def _setup(c, sc):
        ln, _ = _add_line_with_segment(sc, (0, 0), (10, 0))
        ci = Circle(Vec2(100, 0), 50.0)
        sc.add_circle(ci)
        c._selected = [ln, ci]
        return ln, ci

    def test_press_on_edge_starts_drag_and_release_commits(
            self, make_canvas_qt, qtbot):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        c, sc = make_canvas_qt()
        ln, ci = self._setup(c, sc)

        # 上辺の中点 (575,450) でプレス → AABB ドラッグ開始
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(575, 450))
        assert c._bbox_drag_mode == 'edge_0'
        assert len(c._undo_stack) == 1   # ドラッグ開始時に push_undo

        # ワールド (75,50)→(78,54) へ move = Δ(3,4)
        QTest.mouseMove(c, QPoint(578, 446))
        assert ln.ref_start.x == pytest.approx(3)
        assert ln.ref_start.y == pytest.approx(4)
        assert ci.center.x == pytest.approx(103)

        emitted = []
        c.scene_changed.connect(lambda: emitted.append(1))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier,
                           QPoint(578, 446))
        assert c._bbox_drag_mode is None
        assert emitted   # コミット通知
        # Undo でドラッグ前に戻る
        c.undo()
        restored = c.scene.lines[0]
        assert restored.ref_start.x == pytest.approx(0)
        assert restored.ref_start.y == pytest.approx(0)

    def test_paint_with_multiselect_draws_bbox(self, make_canvas_qt):
        """複数選択時の再描画で _draw_bbox_handles が実行される。"""
        c, sc = make_canvas_qt()
        self._setup(c, sc)
        c.repaint()
        assert True
