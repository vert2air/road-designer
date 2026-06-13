"""TwoLineOffsetConstraint と detect_constraint_cycle の単体テスト。

仕様（仕様書 2.5.2 / 基本設計書 4.4.2）に基づき、期待値は幾何学的に
手計算した値を使う。実装の式をなぞらない。

座標系: x 右・y 上、signed_dist は直線の左側が正。
"""
import math

import pytest

from models import (
    Vec2,
    Line,
    Circle,
    Scene,
    OffsetConstraint,
    TwoLineOffsetConstraint,
    detect_constraint_cycle,
)


def _make_xy_lines_and_circle():
    """x 軸・y 軸の 2 直線と中心 (13, 12)・半径 10 の円を作る。

    手計算による初期状態:
      - 直線A = x軸（方向 +x）: 円中心は左側（y=12 > 0）
        距離 12 = 半径 10 + off_a → off_a = 2
      - 直線B = y軸（方向 +y）: 円中心は右側（x=13、左=−x 側）
        距離 13 = 半径 10 + off_b → off_b = 3
    """
    line_a = Line(Vec2(0, 0), Vec2(10, 0))
    line_b = Line(Vec2(0, 0), Vec2(0, 10))
    circle = Circle(Vec2(13, 12), 10.0)
    oc = TwoLineOffsetConstraint()
    oc.line_a = line_a
    oc.line_b = line_b
    oc.circle = circle
    return line_a, line_b, circle, oc


class TestCalcOffsetsFromCurrent:
    """仕様: 設定時点の位置関係から off_a/off_b を算出する。"""

    def test_offsets_are_edge_distances(self):
        _, _, _, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        # 円の縁から直線までの距離（中心距離 − 半径）
        assert oc.off_a == pytest.approx(2.0)
        assert oc.off_b == pytest.approx(3.0)

    def test_negative_offset_when_line_crosses_circle(self):
        """直線が円に食い込む位置関係では負のオフセットになる。"""
        line_a = Line(Vec2(0, 0), Vec2(10, 0))
        line_b = Line(Vec2(0, 0), Vec2(0, 10))
        ci = Circle(Vec2(20, 4), 10.0)   # x 軸まで 4 < 半径 10
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = line_a, line_b, ci
        oc.calc_offsets_from_current()
        assert oc.off_a == pytest.approx(4.0 - 10.0)    # -6
        assert oc.off_b == pytest.approx(20.0 - 10.0)   # 10

    def test_missing_reference_is_noop(self):
        oc = TwoLineOffsetConstraint()
        oc.calc_offsets_from_current()   # 例外を投げない
        assert oc.off_a == 0.0
        assert oc.off_b == 0.0


class TestSolve:
    """仕様: 直線移動・半径変更時に円中心が距離拘束を満たす点へ動く。"""

    def test_line_translation_moves_center(self):
        """直線 A を y=5 へ平行移動 → 中心は (13, 17) になるはず。

        手計算: A からの距離 12（左側）→ y = 5 + 12 = 17。
        B からの距離 13（右側 = +x）→ x = 13（不変）。
        """
        line_a, _, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()

        line_a.ref_start = Vec2(0, 5)
        line_a.ref_end = Vec2(10, 5)
        assert oc.solve() is True
        assert oc.feasible is True
        assert circle.center.x == pytest.approx(13.0)
        assert circle.center.y == pytest.approx(17.0)

    def test_radius_change_keeps_edge_offsets(self):
        """半径 10→5 に縮小 → 縁までの距離 off を維持して中心が動く。

        手計算: A から 5+2=7 → y=7。B から 5+3=8 → x=8。
        """
        _, _, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()

        circle.radius = 5.0
        assert oc.solve() is True
        assert circle.center.x == pytest.approx(8.0)
        assert circle.center.y == pytest.approx(7.0)

    def test_oblique_line_distance_constraint(self):
        """斜め 45° の直線でも距離拘束を満たすことを距離で検証する。"""
        line_a = Line(Vec2(0, 0), Vec2(10, 10))   # 45°
        line_b = Line(Vec2(0, 0), Vec2(0, 10))    # y 軸
        circle = Circle(Vec2(20, 5), 6.0)
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = line_a, line_b, circle
        oc.calc_offsets_from_current()
        exp_da = line_a.distance_to(circle.center)
        exp_db = line_b.distance_to(circle.center)

        # 直線 B を x=−3 へ移動 → B からの中心距離は維持される
        line_b.ref_start = Vec2(-3, 0)
        line_b.ref_end = Vec2(-3, 10)
        assert oc.solve() is True
        assert line_a.distance_to(circle.center) == pytest.approx(exp_da)
        assert line_b.distance_to(circle.center) == pytest.approx(exp_db)

    def test_side_is_preserved(self):
        """法線方向の維持: 解は設定時と同じ側に選ばれる。"""
        line_a, line_b, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        line_a.ref_start = Vec2(0, -2)
        line_a.ref_end = Vec2(10, -2)
        assert oc.solve() is True
        # 円中心は依然として A の左側（上）・B の右側（+x）
        assert line_a.signed_dist(circle.center) > 0
        assert line_b.signed_dist(circle.center) < 0

    def test_parallel_lines_infeasible(self):
        """2 直線が平行 → feasible=False、円中心は変更しない。"""
        line_a, line_b, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        before = Vec2(circle.center.x, circle.center.y)

        line_b.ref_start = Vec2(0, 20)
        line_b.ref_end = Vec2(10, 20)   # A と平行に
        assert oc.solve() is False
        assert oc.feasible is False
        assert circle.center.x == before.x
        assert circle.center.y == before.y

    def test_recovers_after_parallel(self):
        """平行解消後に solve すると追従を再開する（仕様 2.5.2）。"""
        line_a, line_b, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        orig_b_start = Vec2(line_b.ref_start.x, line_b.ref_start.y)
        orig_b_end = Vec2(line_b.ref_end.x, line_b.ref_end.y)

        line_b.ref_start = Vec2(0, 20)
        line_b.ref_end = Vec2(10, 20)
        oc.solve()
        line_b.ref_start = orig_b_start
        line_b.ref_end = orig_b_end
        assert oc.solve() is True
        assert oc.feasible is True
        assert circle.center.x == pytest.approx(13.0)
        assert circle.center.y == pytest.approx(12.0)

    def test_missing_reference_infeasible(self):
        oc = TwoLineOffsetConstraint()
        assert oc.solve() is False
        assert oc.feasible is False


class TestSerialization:
    """to_dict / from_dict と Scene 経由の往復。"""

    def test_to_dict_keys(self):
        _, _, _, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        d = oc.to_dict()
        assert d["la_id"] == oc.line_a.id
        assert d["lb_id"] == oc.line_b.id
        assert d["circle_id"] == oc.circle.id
        assert d["off_a"] == pytest.approx(2.0)
        assert d["off_b"] == pytest.approx(3.0)

    def test_scene_roundtrip_restores_references(self):
        line_a, line_b, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        sc = Scene()
        sc.add_line(line_a)
        sc.add_line(line_b)
        sc.add_circle(circle)
        sc.two_line_offset_constraints.append(oc)

        sc2 = Scene.from_dict(sc.to_dict())
        assert len(sc2.two_line_offset_constraints) == 1
        oc2 = sc2.two_line_offset_constraints[0]
        # 復元された Scene 内のオブジェクトを参照していること
        assert oc2.line_a in sc2.lines
        assert oc2.line_b in sc2.lines
        assert oc2.circle in sc2.circles
        assert oc2.off_a == pytest.approx(2.0)
        assert oc2.off_b == pytest.approx(3.0)

    def test_roundtrip_then_solve_behaves_identically(self):
        """ロード後（_eps 未設定）でも直線移動への追従が正しい。"""
        line_a, line_b, circle, oc = _make_xy_lines_and_circle()
        oc.calc_offsets_from_current()
        sc = Scene()
        sc.add_line(line_a)
        sc.add_line(line_b)
        sc.add_circle(circle)
        sc.two_line_offset_constraints.append(oc)

        sc2 = Scene.from_dict(sc.to_dict())
        oc2 = sc2.two_line_offset_constraints[0]
        oc2.line_a.ref_start = Vec2(0, 5)
        oc2.line_a.ref_end = Vec2(10, 5)
        assert oc2.solve() is True
        assert oc2.circle.center.y == pytest.approx(17.0)
        assert oc2.circle.center.x == pytest.approx(13.0)


class TestDetectConstraintCycle:
    """detect_constraint_cycle（基本設計書 4.4 / 詳細設計書 1.14d）。"""

    @staticmethod
    def _scene_with_oc(line, ca, cb):
        sc = Scene()
        oc = OffsetConstraint()
        oc.line, oc.circle_a, oc.circle_b = line, ca, cb
        sc.offset_constraints.append(oc)
        return sc

    def test_empty_scene_no_cycle(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(1, 0))
        ci = Circle(Vec2(5, 5), 1)
        assert detect_constraint_cycle(
            sc, inputs={ln}, outputs={ci}) is False

    def test_simple_two_constraint_cycle(self):
        """既存 OC: {A,B}→S に対し、新 TLOC: {S,T}→A はループ。"""
        s = Line(Vec2(0, 0), Vec2(1, 0))
        t = Line(Vec2(0, 0), Vec2(0, 1))
        a = Circle(Vec2(5, 5), 1)
        b = Circle(Vec2(9, 9), 1)
        sc = self._scene_with_oc(s, a, b)
        assert detect_constraint_cycle(
            sc, inputs={s, t}, outputs={a}) is True

    def test_reverse_direction_cycle(self):
        """既存 TLOC: {A,B}→C に対し、新 OC: {C,D}→A はループ。"""
        a = Line(Vec2(0, 0), Vec2(1, 0))
        b = Line(Vec2(0, 0), Vec2(0, 1))
        c = Circle(Vec2(5, 5), 1)
        d = Circle(Vec2(9, 9), 1)
        sc = Scene()
        tl = TwoLineOffsetConstraint()
        tl.line_a, tl.line_b, tl.circle = a, b, c
        sc.two_line_offset_constraints.append(tl)
        assert detect_constraint_cycle(
            sc, inputs={c, d}, outputs={a}) is True

    def test_multi_stage_cycle(self):
        """OC: {C1,C2}→L1、TLOC: {L1,L2}→C3 のとき
        新 OC: {C3,C4}→L2 は 3 段ループになる…ではなく、
        outputs={L2} から TLOC 経由で C3 → inputs に到達するので True。
        """
        l1 = Line(Vec2(0, 0), Vec2(1, 0))
        l2 = Line(Vec2(0, 0), Vec2(0, 1))
        c1 = Circle(Vec2(1, 1), 1)
        c2 = Circle(Vec2(2, 2), 1)
        c3 = Circle(Vec2(3, 3), 1)
        c4 = Circle(Vec2(4, 4), 1)
        sc = self._scene_with_oc(l1, c1, c2)
        tl = TwoLineOffsetConstraint()
        tl.line_a, tl.line_b, tl.circle = l1, l2, c3
        sc.two_line_offset_constraints.append(tl)
        assert detect_constraint_cycle(
            sc, inputs={c3, c4}, outputs={l2}) is True

    def test_chain_without_cycle(self):
        """一方向の連鎖（C1,C2→L1、L1,L2→C3）に、無関係な
        新拘束 {C4,C5}→L3 を足してもループではない。"""
        l1 = Line(Vec2(0, 0), Vec2(1, 0))
        l2 = Line(Vec2(0, 0), Vec2(0, 1))
        l3 = Line(Vec2(5, 0), Vec2(5, 1))
        c1 = Circle(Vec2(1, 1), 1)
        c2 = Circle(Vec2(2, 2), 1)
        c3 = Circle(Vec2(3, 3), 1)
        c4 = Circle(Vec2(4, 4), 1)
        c5 = Circle(Vec2(5, 5), 1)
        sc = self._scene_with_oc(l1, c1, c2)
        tl = TwoLineOffsetConstraint()
        tl.line_a, tl.line_b, tl.circle = l1, l2, c3
        sc.two_line_offset_constraints.append(tl)
        assert detect_constraint_cycle(
            sc, inputs={c4, c5}, outputs={l3}) is False

    def test_downstream_extension_is_not_cycle(self):
        """既存 OC: {A,B}→S の下流に新 TLOC: {S,T}→C を足すのは
        ループではない（C は A・B に戻らない）。"""
        s = Line(Vec2(0, 0), Vec2(1, 0))
        t = Line(Vec2(0, 0), Vec2(0, 1))
        a = Circle(Vec2(5, 5), 1)
        b = Circle(Vec2(9, 9), 1)
        c = Circle(Vec2(7, 7), 1)
        sc = self._scene_with_oc(s, a, b)
        assert detect_constraint_cycle(
            sc, inputs={s, t}, outputs={c}) is False


class TestSolveDistanceInvariant:
    """ランダムでない多数ケースで「拘束条件そのもの」を検証する。"""

    @pytest.mark.parametrize("cx,cy,r", [
        (13, 12, 10), (30, 4, 2), (5, 40, 8), (100, 50, 25),
    ])
    def test_distance_equals_radius_plus_offset(self, cx, cy, r):
        line_a = Line(Vec2(0, 0), Vec2(10, 0))
        line_b = Line(Vec2(0, 0), Vec2(0, 10))
        circle = Circle(Vec2(cx, cy), float(r))
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = line_a, line_b, circle
        oc.calc_offsets_from_current()

        # 直線 A を傾ける（30°）
        ang = math.radians(30)
        line_a.ref_end = Vec2(10 * math.cos(ang), 10 * math.sin(ang))
        assert oc.solve() is True
        # 拘束条件: dist = radius + off（仕様 2.5.2）
        assert line_a.distance_to(circle.center) == pytest.approx(
            circle.radius + oc.off_a)
        assert line_b.distance_to(circle.center) == pytest.approx(
            circle.radius + oc.off_b)
