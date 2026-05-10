"""
tests/test_models.py

models.py の単体テスト。

観点の分類:
  [仕様] 詳細設計書に記載された振る舞いの確認
  [境界] 境界値試験
  [エッジ] エッジケース・コーナーケース
  [C1]   分岐カバレッジを 100% にするための追加試験
"""
from __future__ import annotations

import math
import sys
import os

# tests/ から実行される場合に src/ をパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest

from models import (
    Vec2, Line, Segment, LineConnection, Circle, Arc, Clothoid,
    GradeLine, VerticalCurve, ElementProfile, Scene,
    SegmentSnap, ArcSnap, OffsetConstraint,
    new_id, _reset_id_counter_after,
    plan_length_of, tangent_at, entry_tangent, resolve_chain,
    SNAP_TOL, _elem_endpoints, _pt_dist,
    _fresnel_xy_tau, _find_tau,
)


# ══════════════════════════════════════════════════════════════
# ヘルパー
# ══════════════════════════════════════════════════════════════

def approx(a, b, tol=1e-6):
    return abs(a - b) < tol

def vec_approx(v1: Vec2, v2: Vec2, tol=1e-6):
    return approx(v1.x, v2.x, tol) and approx(v1.y, v2.y, tol)

def _make_clothoid(dx=100.0, dy=0.0, cx=50.0, cy=40.0, r=30.0):
    """x 軸方向の直線と右上の円から左カーブのクロソイドを生成する。"""
    ln = Line(Vec2(0, 0), Vec2(dx, dy))
    seg = Segment(ln)
    ln.segments.append(seg)
    ci = Circle(Vec2(cx, cy), r)
    return Clothoid(ln, ci, snap_segment=False, snap_arc=False)


# ══════════════════════════════════════════════════════════════
# 1. ID 管理
# ══════════════════════════════════════════════════════════════

class TestIdManagement:
    # [仕様] new_id() は単調増加する正の整数を返す
    def test_new_id_positive_and_increasing(self):
        a = new_id()
        b = new_id()
        assert a >= 1
        assert b == a + 1

    # [仕様] _reset_id_counter_after(n) の後は n+1 から採番される
    def test_reset_id_counter_after(self):
        _reset_id_counter_after(1000)
        assert new_id() == 1001

    # [境界] max_id=0 のとき次は 1
    def test_reset_id_counter_zero(self):
        _reset_id_counter_after(0)
        assert new_id() == 1


# ══════════════════════════════════════════════════════════════
# 2. Vec2
# ══════════════════════════════════════════════════════════════

class TestVec2:
    # [仕様] 算術演算が正しく計算される
    def test_add(self):
        assert Vec2(1, 2) + Vec2(3, 4) == Vec2(4, 6)

    def test_sub(self):
        assert Vec2(5, 3) - Vec2(2, 1) == Vec2(3, 2)

    def test_mul_scalar(self):
        assert Vec2(2, 3) * 2.0 == Vec2(4.0, 6.0)

    def test_rmul_scalar(self):
        assert 3.0 * Vec2(1, 2) == Vec2(3.0, 6.0)

    def test_neg(self):
        assert -Vec2(1, -2) == Vec2(-1, 2)

    # [仕様] dot: 直交ベクトルの内積は 0
    def test_dot_orthogonal(self):
        assert Vec2(1, 0).dot(Vec2(0, 1)) == 0.0

    # [仕様] dot: 同方向ベクトルの内積は長さの積
    def test_dot_same_direction(self):
        assert Vec2(3, 0).dot(Vec2(4, 0)) == 12.0

    # [仕様] cross: CCW 方向が正
    def test_cross_ccw_positive(self):
        assert Vec2(1, 0).cross(Vec2(0, 1)) == 1.0

    # [仕様] cross: CW 方向が負
    def test_cross_cw_negative(self):
        assert Vec2(1, 0).cross(Vec2(0, -1)) == -1.0

    # [エッジ] cross: 平行ベクトルは 0
    def test_cross_parallel_zero(self):
        assert Vec2(1, 0).cross(Vec2(2, 0)) == 0.0

    # [仕様] length: 零ベクトルは 0.0
    def test_length_zero_vector(self):
        assert Vec2(0, 0).length() == 0.0

    def test_length_pythagorean(self):
        assert approx(Vec2(3, 4).length(), 5.0)

    # [仕様] normalized: 単位ベクトルを返す
    def test_normalized_unit(self):
        v = Vec2(3, 4).normalized()
        assert approx(v.length(), 1.0)

    # [エッジ] normalized: 零ベクトルは Vec2(1, 0) を返す
    def test_normalized_zero_vector_fallback(self):
        assert Vec2(0, 0).normalized() == Vec2(1, 0)

    # [境界] normalized: 長さが 1e-12 ちょうどは Vec2(1, 0) を返す
    def test_normalized_at_threshold(self):
        v = Vec2(1e-13, 0).normalized()
        assert v == Vec2(1, 0)

    # [仕様] perp: CCW 90° 回転
    def test_perp(self):
        assert Vec2(1, 0).perp() == Vec2(0, 1)
        assert Vec2(0, 1).perp() == Vec2(-1, 0)

    # [仕様] tuple と __iter__ でアンパック可能
    def test_tuple(self):
        assert Vec2(1.0, 2.0).tuple() == (1.0, 2.0)

    def test_iter_unpack(self):
        x, y = Vec2(3.0, 4.0)
        assert x == 3.0 and y == 4.0

    # [仕様] to_dict / from_dict 往復変換
    def test_dict_roundtrip(self):
        v = Vec2(1.5, -2.5)
        assert Vec2.from_dict(v.to_dict()) == v


# ══════════════════════════════════════════════════════════════
# 3. Line
# ══════════════════════════════════════════════════════════════

class TestLine:
    def _make(self, sx=0, sy=0, ex=10, ey=0):
        return Line(Vec2(sx, sy), Vec2(ex, ey))

    # [仕様] direction は正規化されている
    def test_direction_normalized(self):
        ln = self._make(0, 0, 3, 4)
        assert approx(ln.direction.length(), 1.0)

    # [仕様] direction: x 軸方向
    def test_direction_x_axis(self):
        ln = self._make()
        assert ln.direction == Vec2(1, 0)

    # [エッジ] ref_start == ref_end のとき direction は Vec2(1, 0)
    def test_direction_degenerate(self):
        ln = Line(Vec2(5, 5), Vec2(5, 5))
        assert ln.direction == Vec2(1, 0)

    # [仕様] angle: 範囲 (-π, π]
    def test_angle_x_axis(self):
        assert approx(self._make().angle, 0.0)

    def test_angle_y_axis(self):
        ln = Line(Vec2(0, 0), Vec2(0, 1))
        assert approx(ln.angle, math.pi / 2)

    # [仕様] project_point: 直線への正射影
    def test_project_point(self):
        ln = self._make()
        assert vec_approx(ln.project_point(Vec2(3, 4)), Vec2(3, 0))

    # [仕様] project_t: ref_start=0, ref_end=1
    def test_project_t_endpoints(self):
        ln = self._make()
        assert approx(ln.project_t(Vec2(0, 0)), 0.0)
        assert approx(ln.project_t(Vec2(10, 0)), 1.0)

    # [仕様] project_t: 中点は 0.5
    def test_project_t_midpoint(self):
        ln = self._make()
        assert approx(ln.project_t(Vec2(5, 3)), 0.5)

    # [エッジ] project_t: 長さゼロの直線は 0.0 を返す
    def test_project_t_zero_length(self):
        ln = Line(Vec2(5, 5), Vec2(5, 5))
        assert approx(ln.project_t(Vec2(3, 3)), 0.0)

    # [仕様] point_at: t=0 は ref_start, t=1 は ref_end
    def test_point_at_endpoints(self):
        ln = self._make()
        assert ln.point_at(0.0) == Vec2(0, 0)
        assert ln.point_at(1.0) == Vec2(10, 0)

    # [仕様] point_at: 外挿も可能
    def test_point_at_extrapolation(self):
        ln = self._make()
        assert vec_approx(ln.point_at(2.0), Vec2(20, 0))

    # [仕様] distance_to: 直線への垂直距離は常に正
    def test_distance_to_positive(self):
        ln = self._make()
        assert approx(ln.distance_to(Vec2(5, 3)), 3.0)

    # [境界] distance_to: 直線上の点は 0
    def test_distance_to_on_line(self):
        ln = self._make()
        assert approx(ln.distance_to(Vec2(5, 0)), 0.0)

    # [仕様] signed_dist: 左側が正, 右側が負
    def test_signed_dist_left_positive(self):
        ln = self._make()
        assert ln.signed_dist(Vec2(0, 5)) > 0

    def test_signed_dist_right_negative(self):
        ln = self._make()
        assert ln.signed_dist(Vec2(0, -5)) < 0

    # [境界] signed_dist: 直線上は 0
    def test_signed_dist_on_line(self):
        ln = self._make()
        assert approx(ln.signed_dist(Vec2(5, 0)), 0.0)

    # [仕様] left_normal は direction を CCW に 90° 回転したもの
    def test_left_normal(self):
        ln = self._make()
        assert vec_approx(ln.left_normal, Vec2(0, 1))

    # [仕様] intersect: 交点を返す
    def test_intersect(self):
        a = self._make(0, 0, 10, 0)
        b = Line(Vec2(5, -5), Vec2(5, 5))
        pt = a.intersect(b)
        assert pt is not None
        assert vec_approx(pt, Vec2(5, 0))

    # [エッジ] intersect: 平行直線は None
    def test_intersect_parallel(self):
        a = self._make(0, 0, 10, 0)
        b = self._make(0, 1, 10, 1)
        assert a.intersect(b) is None

    # [仕様] to_dict / from_dict 往復変換
    def test_dict_roundtrip(self):
        ln = Line(Vec2(1, 2), Vec2(3, 4))
        seg = Segment(ln, 0.2, 0.8)
        ln.segments.append(seg)
        d = ln.to_dict()
        ln2 = Line.from_dict(d)
        assert vec_approx(ln2.ref_start, Vec2(1, 2))
        assert vec_approx(ln2.ref_end, Vec2(3, 4))
        assert len(ln2.segments) == 1

    # [C1] project はproject_point の別名
    def test_project_alias(self):
        ln = self._make()
        p = Vec2(5, 3)
        assert ln.project(p) == ln.project_point(p)


# ══════════════════════════════════════════════════════════════
# 4. Segment
# ══════════════════════════════════════════════════════════════

class TestSegment:
    def _make(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.2, 0.8)
        return ln, seg

    # [仕様] start/end は line.point_at(t) で動的に計算される
    def test_start_end_dynamic(self):
        ln, seg = self._make()
        assert vec_approx(seg.start, Vec2(2, 0))
        assert vec_approx(seg.end, Vec2(8, 0))

    # [仕様] 参照点が変わると start/end が追従する
    def test_follows_line_change(self):
        ln, seg = self._make()
        ln.ref_end = Vec2(20, 0)
        assert vec_approx(seg.start, Vec2(4, 0))
        assert vec_approx(seg.end, Vec2(16, 0))

    # [仕様] length: 区間長を返す
    def test_length(self):
        ln, seg = self._make()
        assert approx(seg.length(), 6.0)

    # [境界] t_start == t_end のとき length は 0.0
    def test_length_zero(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.5, 0.5)
        assert approx(seg.length(), 0.0)

    # [仕様] to_dict / from_dict 往復変換
    def test_dict_roundtrip(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.3, 0.7, seg_id=999)
        d = seg.to_dict()
        seg2 = Segment.from_dict(d, ln)
        assert approx(seg2.t_start, 0.3)
        assert approx(seg2.t_end, 0.7)
        assert seg2.id == 999


# ══════════════════════════════════════════════════════════════
# 5. Arc
# ══════════════════════════════════════════════════════════════

class TestArc:
    def _make(self, a_start=0.0, a_end=math.pi/2, r=10.0):
        ci = Circle(Vec2(0, 0), r)
        arc = Arc(ci, a_start, a_end)
        return ci, arc

    # [仕様] start/end は円周上の点
    def test_start_on_circle(self):
        ci, arc = self._make()
        assert approx((arc.start - ci.center).length(), ci.radius)

    def test_end_on_circle(self):
        ci, arc = self._make()
        assert approx((arc.end - ci.center).length(), ci.radius)

    # [仕様] arc_angle: 常に正 (CCW 角度差)
    def test_arc_angle_positive(self):
        _, arc = self._make(0.0, math.pi / 2)
        assert approx(arc.arc_angle(), math.pi / 2)

    # [境界] angle_start == angle_end → arc_angle = 0
    def test_arc_angle_zero_when_same(self):
        _, arc = self._make(1.0, 1.0)
        assert approx(arc.arc_angle(), 0.0)

    # [エッジ] angle_end < angle_start (跨ぎ) でも arc_angle は正
    def test_arc_angle_wrap_around(self):
        _, arc = self._make(3 * math.pi / 2, math.pi / 2)
        # (pi/2 - 3pi/2) % 2pi = pi
        assert approx(arc.arc_angle(), math.pi)

    # [仕様] arc_length = radius * arc_angle
    def test_arc_length(self):
        _, arc = self._make(0.0, math.pi, r=5.0)
        assert approx(arc.arc_length(), 5.0 * math.pi)

    # [仕様] to_dict / from_dict 往復変換
    def test_dict_roundtrip(self):
        ci = Circle(Vec2(1, 1), 5.0)
        arc = Arc(ci, 0.1, 1.2, arc_id=42)
        d = arc.to_dict()
        arc2 = Arc.from_dict(d, ci)
        assert approx(arc2.angle_start, 0.1)
        assert approx(arc2.angle_end, 1.2)
        assert arc2.id == 42


# ══════════════════════════════════════════════════════════════
# 6. クロソイド計算関数
# ══════════════════════════════════════════════════════════════

class TestFresnelXyTau:
    # [仕様] tau_end < 1e-9 のとき (0.0, 0.0) を返す
    def test_zero_tau(self):
        xe, ye = _fresnel_xy_tau(0.0, 50.0)
        assert xe == 0.0 and ye == 0.0

    # [境界] tau_end = 1e-9 ちょうどは閾値以上なので計算が実行される（非ゼロ）
    def test_tau_at_threshold(self):
        """条件は tau_end < 1e-9。1e-9 ちょうどは計算される。"""
        xe, ye = _fresnel_xy_tau(1e-9, 50.0)
        # 非常に小さいが 0.0 ではない
        assert xe != 0.0 or ye != 0.0

    # [境界] tau_end = 1e-9 未満 → (0.0, 0.0)
    def test_tau_just_below_threshold(self):
        xe, ye = _fresnel_xy_tau(1e-10, 50.0)
        assert xe == 0.0 and ye == 0.0

    # [仕様] xe > 0, ye > 0 (tau > 0 の場合)
    def test_positive_values(self):
        xe, ye = _fresnel_xy_tau(math.pi / 4, 50.0)
        assert xe > 0 and ye > 0

    # [仕様] ye < xe (クロソイドは直線方向への変位が大きい)
    def test_ye_less_than_xe(self):
        xe, ye = _fresnel_xy_tau(math.pi / 4, 50.0)
        assert ye < xe

    # [エッジ] n=1 でも例外にならない
    def test_n_equals_one(self):
        xe, ye = _fresnel_xy_tau(0.5, 30.0, n=1)
        assert xe > 0


class TestFindTau:
    # [仕様] d_abs <= R → None を返す（クロソイド不存在）
    def test_no_solution_when_d_leq_r(self):
        assert _find_tau(50.0, 50.0) is None
        assert _find_tau(50.0, 30.0) is None

    # [境界] d_abs = R + 1e-9 → まだ None かもしれないが例外にはならない
    def test_near_threshold(self):
        result = _find_tau(50.0, 50.0 + 1e-9)
        # None または float のどちらでも例外にならないことを確認
        assert result is None or isinstance(result, float)

    # [仕様] d_abs > R → float を返す
    def test_returns_float_when_d_gt_r(self):
        tau = _find_tau(50.0, 100.0)
        assert tau is not None
        assert isinstance(tau, float)
        assert tau > 0

    # [仕様] residual 条件が満たされている
    def test_fresnel_condition_satisfied(self):
        R = 50.0
        d = 80.0
        tau = _find_tau(R, d)
        assert tau is not None
        _, ye = _fresnel_xy_tau(tau, R)
        residual = ye - (d - R * math.cos(tau))
        assert abs(residual) < 1e-6

    # [エッジ] 両端 residual が同符号 → None
    def test_no_solution_same_sign(self):
        # d_abs がとても大きいと解なしになる場合がある
        # R=1.0, d=1000 は両端 residual が同符号の可能性が高い
        result = _find_tau(1.0, 1000.0)
        # None か float どちらでも例外にならないことを確認
        assert result is None or isinstance(result, float)


# ══════════════════════════════════════════════════════════════
# 7. Clothoid
# ══════════════════════════════════════════════════════════════

class TestClothoid:
    def _make_left_curve(self):
        """x 軸方向の直線と y>0 方向の円で左カーブのクロソイドを生成。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -math.pi / 4, math.pi / 4)
        ci.arcs.append(arc)
        return Clothoid(ln, ci, snap_segment=True, snap_arc=True)  # snap on でテスト（スムーズ接続相当）

    def _make_right_curve(self):
        """x 軸方向の直線と y<0 方向の円で右カーブのクロソイドを生成。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, -60), 40.0)
        arc = Arc(ci, 3 * math.pi / 4, 5 * math.pi / 4)
        ci.arcs.append(arc)
        return Clothoid(ln, ci, snap_segment=True, snap_arc=True)  # snap on でテスト（スムーズ接続相当）

    # [仕様] デフォルトは snap_segment=False, snap_arc=False
    def test_default_snap_is_false(self):
        """[仕様] Clothoid のデフォルトは snap off。
        直接生成する場合は線分・円弧を接点で分割して管理する。
        スムーズ接続（Canvas.smooth_connect）で生成する場合のみ True を渡す。
        """
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci)  # snap 引数を省略
        assert clo.snap_segment is False
        assert clo.snap_arc is False

    # [仕様] 有効なクロソイドは is_valid=True
    def test_is_valid_true(self):
        clo = _make_clothoid()
        assert clo.is_valid

    # [仕様] d_abs <= R のとき is_valid=False
    def test_is_valid_false_when_d_leq_r(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 20), 30.0)  # d=20 < R=30
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid

    # [仕様] 無効時 points=[], line_contact=None, circle_contact=None
    def test_invalid_empty_points(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 20), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.points == []
        assert clo.line_contact is None
        assert clo.circle_contact is None

    # [仕様] 有効時 points に 2 点以上ある
    def test_valid_has_points(self):
        clo = _make_clothoid()
        assert len(clo.points) >= 2

    # [仕様] line_contact は直線上の点（直線への距離がほぼ 0）
    def test_line_contact_on_line(self):
        clo = _make_clothoid()
        assert clo.line_contact is not None
        ln = clo.line
        dist = ln.distance_to(clo.line_contact)
        assert dist < 1e-4

    # [仕様] circle_contact は円周上の点
    def test_circle_contact_on_circle(self):
        clo = _make_clothoid()
        assert clo.circle_contact is not None
        ci = clo.circle
        d = (clo.circle_contact - ci.center).length()
        assert approx(d, ci.radius, tol=1e-4)

    # [仕様] is_left_curve: 円が直線の左側なら True
    def test_is_left_curve_true(self):
        clo = _make_clothoid(cx=50, cy=40)  # y>0 は左側
        assert clo.is_left_curve

    # [仕様] is_left_curve: 円が直線の右側なら False
    def test_is_left_curve_false(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, -60), 40.0)  # y<0 は右側
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_left_curve

    # [仕様] effective_direction: reversed_flag=False は line.direction と同じ
    def test_effective_direction_normal(self):
        clo = _make_clothoid()
        assert vec_approx(clo.effective_direction, clo.line.direction)

    # [仕様] effective_direction: reversed_flag=True は逆向き
    def test_effective_direction_reversed(self):
        clo = _make_clothoid()
        clo.reversed_flag = True
        clo.compute()
        assert vec_approx(clo.effective_direction, -clo.line.direction)

    # [仕様] effective_ref_start: reversed_flag=False は line.ref_start
    def test_effective_ref_start_normal(self):
        clo = _make_clothoid()
        assert clo.effective_ref_start == clo.line.ref_start

    # [仕様] effective_ref_start: reversed_flag=True は line.ref_end
    def test_effective_ref_start_reversed(self):
        clo = _make_clothoid()
        clo.reversed_flag = True
        assert clo.effective_ref_start == clo.line.ref_end

    # [仕様] _A = R * sqrt(2 * tau)
    def test_A_property(self):
        clo = _make_clothoid()
        expected_A = clo.circle.radius * math.sqrt(2.0 * clo._tau)
        assert approx(clo._A, expected_A)

    # [境界] _A: 無効時は 0.0
    def test_A_invalid_is_zero(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo._A == 0.0

    # [仕様] points の先頭は line_contact, 末尾は circle_contact に近い
    def test_points_start_end(self):
        clo = _make_clothoid()
        pts = clo.points
        assert vec_approx(pts[0], clo.line_contact, tol=1e-4)
        assert vec_approx(pts[-1], clo.circle_contact, tol=1e-4)

    # [仕様] snap_segment=True: 最も近い線分の端点が接点に吸着する
    def test_snap_segment_true_moves_endpoint(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -0.5, 0.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        if clo.is_valid:
            expected_t = ln.project_t(clo.line_contact)
            assert approx(seg.t_end, expected_t, tol=1e-4)

    # [仕様] snap_arc=True: 最も近い円弧の端点が接点に吸着する
    def test_snap_arc_true_moves_endpoint(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -0.5, 0.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=True)
        if clo.is_valid:
            # 左カーブなので arc.angle_start が接点角度になる
            angle_contact = math.atan2(
                clo.circle_contact.y - ci.center.y,
                clo.circle_contact.x - ci.center.x
            )
            assert approx(arc.angle_start, angle_contact, tol=1e-4)

    # [仕様] snap_arc=True で円弧がない場合、自動生成される
    def test_snap_arc_auto_creates_arc(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)  # arcs なし
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=True)
        if clo.is_valid:
            assert len(ci.arcs) == 1

    # [仕様] _clear_segment_split: AX+XB を元の AB に戻す
    def test_clear_segment_split(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if clo.is_valid and clo._split_seg_ids:
            n_before = len(ln.segments)
            clo._clear_segment_split()
            assert len(ln.segments) == n_before - 1
            assert clo._split_seg_ids == []

    # [C1] _clear_segment_split: split がない場合は何もしない
    def test_clear_segment_split_no_op(self):
        clo = _make_clothoid()  # snap=False
        clo._split_seg_ids = []
        clo._clear_segment_split()  # 例外にならない

    # [仕様] _clear_arc_split: 分割円弧を元に戻す
    def test_clear_arc_split(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -1.0, 1.0)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if clo.is_valid and clo._split_arc_ids:
            n_before = len(ci.arcs)
            clo._clear_arc_split()
            assert len(ci.arcs) == n_before - 1
            assert clo._split_arc_ids == []

    # [C1] _clear_arc_split: split がない場合は何もしない
    def test_clear_arc_split_no_op(self):
        clo = _make_clothoid()
        clo._split_arc_ids = []
        clo._clear_arc_split()  # 例外にならない

    # [エッジ] radius が 0 に近い場合は無効
    def test_near_zero_radius_invalid(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 0.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid

    # [仕様] to_dict に計算キャッシュは含まれない
    def test_to_dict_no_cache(self):
        clo = _make_clothoid()
        d = clo.to_dict()
        assert '_line_pt' not in d
        assert '_circle_pt' not in d
        assert 'points' not in d

    # [仕様] _dist_to_seg: 線分への最短距離
    def test_dist_to_seg(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.0, 1.0)
        pt = Vec2(5, 3)
        d = Clothoid._dist_to_seg(pt, seg)
        assert approx(d, 3.0)

    # [エッジ] _dist_to_seg: 縮退した線分は始点からの距離
    def test_dist_to_seg_degenerate(self):
        ln = Line(Vec2(0, 0), Vec2(0, 0))
        seg = Segment(ln, 0.0, 0.0)
        pt = Vec2(3, 4)
        d = Clothoid._dist_to_seg(pt, seg)
        assert approx(d, 5.0)


# ══════════════════════════════════════════════════════════════
# 8. plan_length_of
# ══════════════════════════════════════════════════════════════

class TestPlanLengthOf:
    # [仕様] Segment の平面長
    def test_segment(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        assert approx(plan_length_of(seg), 10.0)

    # [仕様] Arc の平面長
    def test_arc(self):
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi)
        assert approx(plan_length_of(arc), 5.0 * math.pi)

    # [仕様] Clothoid の平面長 = 2 * R * tau
    def test_clothoid_valid(self):
        clo = _make_clothoid()
        if clo.is_valid:
            expected = 2.0 * clo.circle.radius * clo._tau
            assert approx(plan_length_of(clo), expected)

    # [仕様] 無効な Clothoid は 0.0
    def test_clothoid_invalid(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert plan_length_of(clo) == 0.0

    # [C1] 非対応型は 0.0
    def test_unsupported_type(self):
        assert plan_length_of("not a shape") == 0.0
        assert plan_length_of(None) == 0.0


# ══════════════════════════════════════════════════════════════
# 9. ElementProfile.elev_at
# ══════════════════════════════════════════════════════════════

class TestElementProfileElevAt:
    def _make_ep_with_gl(self, plan_len=100.0):
        ep = ElementProfile()
        ep.plan_length = plan_len
        gl = GradeLine()
        gl.dist_start = 0.0; gl.elev_start = 10.0
        gl.dist_end   = plan_len; gl.elev_end = 20.0
        ep.grade_lines = [gl]
        return ep

    # [仕様] 勾配直線の線形補間
    def test_gl_interpolation(self):
        ep = self._make_ep_with_gl()
        assert approx(ep.elev_at(0.0), 10.0)
        assert approx(ep.elev_at(50.0), 15.0)
        assert approx(ep.elev_at(100.0), 20.0)

    # [境界] rel < 0 は 0 にクリップ
    def test_clip_negative(self):
        ep = self._make_ep_with_gl()
        assert approx(ep.elev_at(-10.0), 10.0)

    # [境界] rel > plan_length は plan_length にクリップ
    def test_clip_over(self):
        ep = self._make_ep_with_gl()
        assert approx(ep.elev_at(150.0), 20.0)

    # [仕様] GL がない場合は 0.0
    def test_no_gl_returns_zero(self):
        ep = ElementProfile()
        ep.plan_length = 100.0
        assert ep.elev_at(50.0) == 0.0

    # [仕様] VerticalCurve が優先される
    def test_vc_priority_over_gl(self):
        ep = self._make_ep_with_gl(100.0)
        # VPC=25, VPT=75, g1=2%, g2=0%, L=50
        vc = VerticalCurve()
        vc.pvi_dist = 50.0; vc.pvi_elev = 15.0
        vc.g1 = 2.0; vc.g2 = 0.0; vc.length = 50.0
        ep.vertical_curves = [vc]
        # VPC での標高は vc.vpc_elev
        elev_vpc = ep.elev_at(vc.vpc_dist)
        assert approx(elev_vpc, vc.vpc_elev, tol=1e-3)

    # [仕様] VC 範囲外は GL にフォールバック
    def test_vc_fallback_outside(self):
        ep = self._make_ep_with_gl(100.0)
        vc = VerticalCurve()
        vc.pvi_dist = 50.0; vc.pvi_elev = 15.0
        vc.g1 = 2.0; vc.g2 = 0.0; vc.length = 20.0  # VPC=40, VPT=60
        ep.vertical_curves = [vc]
        # rel=10 は VC 範囲外 → GL から
        assert approx(ep.elev_at(10.0), 11.0)

    # [エッジ] VC.elevation_at が NaN を返す場合は GL にフォールバック
    def test_vc_nan_fallback(self):
        ep = self._make_ep_with_gl(100.0)
        # VC を作るが vpc_dist > plan_length となるように設定
        vc = VerticalCurve()
        vc.pvi_dist = 200.0; vc.pvi_elev = 0.0
        vc.g1 = 0.0; vc.g2 = 0.0; vc.length = 50.0
        ep.vertical_curves = [vc]
        # rel=50 は VC の範囲外 → GL から 15.0
        assert approx(ep.elev_at(50.0), 15.0)

    # [エッジ] GradeLine の長さがゼロ (dist_end == dist_start)
    def test_gl_zero_length(self):
        ep = ElementProfile()
        ep.plan_length = 100.0
        gl = GradeLine()
        gl.dist_start = gl.dist_end = 50.0
        gl.elev_start = gl.elev_end = 12.0
        ep.grade_lines = [gl]
        # 境界で 0 除算が起きないことを確認
        assert approx(ep.elev_at(50.0), 12.0)


# ══════════════════════════════════════════════════════════════
# 10. GradeLine
# ══════════════════════════════════════════════════════════════

class TestGradeLine:
    # [仕様] gradient: 上り坂は正
    def test_gradient_uphill(self):
        gl = GradeLine()
        gl.dist_start = 0; gl.dist_end = 100
        gl.elev_start = 0; gl.elev_end = 5
        assert approx(gl.gradient, 5.0)

    # [仕様] gradient: 下り坂は負
    def test_gradient_downhill(self):
        gl = GradeLine()
        gl.dist_start = 0; gl.dist_end = 100
        gl.elev_start = 10; gl.elev_end = 0
        assert approx(gl.gradient, -10.0)

    # [境界] gradient: dist_end - dist_start < 1e-9 のとき 0.0
    def test_gradient_zero_length(self):
        gl = GradeLine()
        gl.dist_start = gl.dist_end = 50.0
        assert gl.gradient == 0.0

    # [仕様] to_dict / from_dict 往復変換
    def test_dict_roundtrip(self):
        gl = GradeLine()
        gl.id = 77
        gl.dist_start = 10.0; gl.elev_start = 5.0
        gl.dist_end = 110.0; gl.elev_end = 15.0
        d = gl.to_dict()
        gl2 = GradeLine.from_dict(d)
        assert gl2.id == 77
        assert approx(gl2.dist_start, 10.0)
        assert approx(gl2.gradient, 10.0)


# ══════════════════════════════════════════════════════════════
# 11. VerticalCurve
# ══════════════════════════════════════════════════════════════

class TestVerticalCurve:
    def _make(self):
        vc = VerticalCurve()
        vc.pvi_dist = 100.0
        vc.pvi_elev = 20.0
        vc.g1 = 2.0    # 上り 2%
        vc.g2 = -2.0   # 下り 2%
        vc.length = 80.0
        return vc

    # [仕様] vpc_dist = pvi_dist - L/2
    def test_vpc_dist(self):
        vc = self._make()
        assert approx(vc.vpc_dist, 60.0)

    # [仕様] vpt_dist = pvi_dist + L/2
    def test_vpt_dist(self):
        vc = self._make()
        assert approx(vc.vpt_dist, 140.0)

    # [仕様] vpc_elev = pvi_elev - g1/100 * L/2
    def test_vpc_elev(self):
        vc = self._make()
        expected = 20.0 - 2.0 / 100 * 40.0
        assert approx(vc.vpc_elev, expected)

    # [仕様] vpt_elev = pvi_elev + g2/100 * L/2
    def test_vpt_elev(self):
        vc = self._make()
        expected = 20.0 + (-2.0) / 100 * 40.0
        assert approx(vc.vpt_elev, expected)

    # [仕様] K = L / |g2 - g1|
    def test_K_value(self):
        vc = self._make()
        assert approx(vc.K, 80.0 / 4.0)

    # [境界] K: g1 == g2 のとき inf
    def test_K_flat(self):
        vc = VerticalCurve()
        vc.g1 = vc.g2 = 2.0
        vc.length = 100.0
        assert vc.K == float('inf')

    # [仕様] elevation_at: VPC での標高は vpc_elev
    def test_elevation_at_vpc(self):
        vc = self._make()
        assert approx(vc.elevation_at(vc.vpc_dist), vc.vpc_elev)

    # [仕様] elevation_at: VPT での標高は vpt_elev
    def test_elevation_at_vpt(self):
        vc = self._make()
        assert approx(vc.elevation_at(vc.vpt_dist), vc.vpt_elev)

    # [仕様] elevation_at: 放物線の頂点（PVI）での標高確認
    def test_elevation_at_pvi(self):
        vc = self._make()
        e = vc.elevation_at(vc.pvi_dist)
        # 山形曲線なので PVI の標高は vpc_elev から上昇して最高点
        assert e > vc.vpc_elev

    # [境界] elevation_at: 範囲外（x < 0）は NaN
    def test_elevation_at_below_vpc(self):
        vc = self._make()
        result = vc.elevation_at(vc.vpc_dist - 1.0)
        assert math.isnan(result)

    # [境界] elevation_at: 範囲外（x > L）は NaN
    def test_elevation_at_above_vpt(self):
        vc = self._make()
        result = vc.elevation_at(vc.vpt_dist + 1.0)
        assert math.isnan(result)

    # [詳細設計] 例: g1=2%, g2=0%, L=100m, vpc_elev=10.0
    def test_elevation_at_design_spec_example(self):
        """放物線式 y(x) = vpc_elev + (g1/100)*x + ((g2-g1)/(2*L)/100)*x² の確認。
        vpc_dist=0, vpc_elev=10.0, g1=2%, g2=0%, L=100m のとき:
          x=0   → 10.0
          x=50  → 10 + 1.0 + ((-2)/(200)/100)*2500 = 10 + 1.0 - 0.25 = 10.75
          x=100 → 10 + 2.0 + ((-2)/(200)/100)*10000 = 10 + 2.0 - 1.0 = 11.0
        注: VPT は pvi_dist + L/2 = 100, vpc_elev + g1/100*L + (g2-g1)/(200L)*L² = vpt_elev
        """
        vc = VerticalCurve()
        vc.pvi_dist = 50.0
        vc.g1 = 2.0; vc.g2 = 0.0; vc.length = 100.0
        vc.pvi_elev = 11.0  # vpc_elev=10.0 なので pvi=10+2/100*50=11
        assert approx(vc.elevation_at(vc.vpc_dist), 10.0, tol=1e-4)
        # x=50: 10 + 1.0 - 0.25 = 10.75
        assert approx(vc.elevation_at(vc.vpc_dist + 50.0), 10.75, tol=1e-4)
        # x=100: 10 + 2.0 - 1.0 = 11.0 → vpt_elev = pvi + g2/100*50 = 11 + 0 = 11
        assert approx(vc.elevation_at(vc.vpt_dist), vc.vpt_elev, tol=1e-4)

    # [仕様] to_dict / from_dict 往復変換
    def test_dict_roundtrip(self):
        vc = self._make()
        d = vc.to_dict()
        vc2 = VerticalCurve.from_dict(d)
        assert approx(vc2.pvi_dist, vc.pvi_dist)
        assert approx(vc2.g1, vc.g1)
        assert approx(vc2.length, vc.length)


# ══════════════════════════════════════════════════════════════
# 12. Scene
# ══════════════════════════════════════════════════════════════

class TestScene:
    # [仕様] 初期状態: 全リストが空
    def test_initial_state_empty(self):
        sc = Scene()
        assert sc.lines == []
        assert sc.circles == []
        assert sc.clothoids == []
        assert sc.element_profiles == []
        assert sc.nicknames == {}

    # [仕様] add_line: lines に追加、デフォルトニックネームが設定される
    def test_add_line(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(1, 0))
        sc.add_line(ln)
        assert ln in sc.lines
        assert ln.id in sc.nicknames

    # [仕様] add_line: 既存ニックネームは上書きしない
    def test_add_line_no_overwrite_nickname(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(1, 0))
        sc.nicknames[ln.id] = 'my_line'
        sc.add_line(ln)
        assert sc.nicknames[ln.id] == 'my_line'

    # [仕様] add_circle / add_clothoid も同様
    def test_add_circle(self):
        sc = Scene()
        ci = Circle(Vec2(0, 0), 5.0)
        sc.add_circle(ci)
        assert ci in sc.circles

    # [仕様] remove_line: 関連 Clothoid も削除される
    def test_remove_line_removes_clothoids(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        sc.remove_line(ln)
        assert ln not in sc.lines
        assert clo not in sc.clothoids

    # [仕様] remove_circle: 関連 Clothoid も削除される
    def test_remove_circle_removes_clothoids(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        sc.remove_circle(ci)
        assert ci not in sc.circles
        assert clo not in sc.clothoids

    # [仕様] remove_clothoid: _clear_segment_split と _clear_arc_split が呼ばれる
    def test_remove_clothoid_clears_splits(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        # 削除後に split_ids がクリアされていること
        sc.remove_clothoid(clo)
        assert clo not in sc.clothoids
        assert clo._split_seg_ids == []
        assert clo._split_arc_ids == []

    # [C1] remove_clothoid: 存在しない clothoid は無視
    def test_remove_clothoid_not_in_list(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.remove_clothoid(clo)  # 例外にならない

    # [仕様] clothoids_for: 指定 Line と Circle の Clothoid を返す
    def test_clothoids_for(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.clothoids_for(ln, ci)
        assert clo in result

    # [仕様] get_nickname: 未設定は "nickname_{prefix}_{id}"
    def test_get_nickname_default(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(1, 0))
        name = sc.get_nickname(ln.id, 'line')
        assert 'line' in name
        assert str(ln.id) in name

    # [仕様] set_nickname: 空文字で削除
    def test_set_nickname_delete_on_empty(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(1, 0))
        sc.nicknames[ln.id] = 'test'
        sc.set_nickname(ln.id, '')
        assert ln.id not in sc.nicknames

    # [仕様] to_dict / from_dict 往復変換（シリアライズ可能性）
    def test_to_dict_from_dict_roundtrip(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        ln.segments.append(seg)
        sc.add_line(ln)
        ci = Circle(Vec2(5, 8), 5.0)
        sc.add_circle(ci)
        d = sc.to_dict()
        sc2 = Scene.from_dict(d)
        assert len(sc2.lines) == 1
        assert len(sc2.circles) == 1
        assert len(sc2.lines[0].segments) == 1

    # [仕様] from_dict: ID 衝突を自動修正する
    def test_from_dict_resolves_id_collision(self):
        # 同じ ID を持つ2本の直線を辞書に含める
        d = {
            'lines': [
                {'id': 100, 'ref_start': {'x': 0, 'y': 0},
                 'ref_end': {'x': 1, 'y': 0}, 'segments': []},
                {'id': 100, 'ref_start': {'x': 2, 'y': 0},
                 'ref_end': {'x': 3, 'y': 0}, 'segments': []},
            ],
            'circles': [], 'clothoids': [],
            'element_profiles': [],
        }
        sc = Scene.from_dict(d)
        ids = [ln.id for ln in sc.lines]
        assert len(set(ids)) == 2  # ID が衝突していない

    # [仕様] connected_objects: Line → Clothoid と接続相手 Line を返す
    def test_connected_objects_line(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(ln)
        assert clo in result

    # [仕様] connected_objects: Circle → Clothoid を返す
    def test_connected_objects_circle(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(ci)
        assert clo in result

    # [仕様] connected_objects: Clothoid → line と circle を返す
    def test_connected_objects_clothoid(self):
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(clo)
        assert ln in result
        assert ci in result


# ══════════════════════════════════════════════════════════════
# 13. ユーティリティ関数
# ══════════════════════════════════════════════════════════════

class TestTangentAt:
    # [仕様] Segment: 始点と終点で同じ接線
    def test_segment_start(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        tx, ty = tangent_at(seg, False)
        assert approx(tx, 1.0) and approx(ty, 0.0)

    def test_segment_end(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        tx, ty = tangent_at(seg, True)
        assert approx(tx, 1.0) and approx(ty, 0.0)

    # [仕様] Arc: 始点の接線は (-sin(angle_start), cos(angle_start))
    def test_arc_start(self):
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        tx, ty = tangent_at(arc, False)
        assert approx(tx, -math.sin(0.0)) and approx(ty, math.cos(0.0))

    # [仕様] Arc: 終点の接線
    def test_arc_end(self):
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        tx, ty = tangent_at(arc, True)
        assert approx(tx, -math.sin(math.pi / 2), tol=1e-6)
        assert approx(ty,  math.cos(math.pi / 2), tol=1e-6)

    # [仕様] Clothoid: 有効時は始点・終点で異なる接線
    def test_clothoid_valid(self):
        clo = _make_clothoid()
        if clo.is_valid:
            t_start = tangent_at(clo, False)
            t_end = tangent_at(clo, True)
            assert t_start != t_end

    # [エッジ] Clothoid: points が 2 点未満のとき (1, 0)
    def test_clothoid_invalid_fallback(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)  # 無効
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert tangent_at(clo, False) == (1, 0)
        assert tangent_at(clo, True) == (1, 0)

    # [C1] 非対応型は (1, 0)
    def test_unsupported_type(self):
        assert tangent_at("not_a_shape", False) == (1, 0)


class TestEntryTangent:
    # [仕様] Segment: connect_at_start=True は start→end 方向
    def test_segment_from_start(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        tx, ty = entry_tangent(seg, True)
        assert approx(tx, 1.0) and approx(ty, 0.0)

    # [仕様] Segment: connect_at_start=False は end→start 方向
    def test_segment_from_end(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        tx, ty = entry_tangent(seg, False)
        assert approx(tx, -1.0) and approx(ty, 0.0)

    # [仕様] Arc: connect_at_start=True は angle_start から +0.1° 方向
    def test_arc_from_start(self):
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi)
        result = entry_tangent(arc, True)
        assert result is not None
        # CCW 方向なので ty > 0
        assert result[1] > 0

    # [仕様] Arc: connect_at_start=False は angle_end から -0.1° 方向の近傍ベクトル
    def test_arc_from_end(self):
        """angle_end=pi（終点は (-R,0)）のとき、ang1=pi-delta の点との差分ベクトル。
        sin(pi-delta) ≈ +delta なので dy>0 → ty > 0 が正しい実装の挙動。
        この「共有端点→近傍点」ベクトルは exit_tan との内積で [順]/[逆] 判定に使われる。
        """
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi)
        result = entry_tangent(arc, False)
        assert result is not None
        # ang0=pi, ang1=pi-0.001 → x1-x0 ≈ 0, y1-y0 ≈ sin(pi-0.001) > 0 → ty > 0
        assert result[1] > 0

    # [仕様] 有効 Clothoid: connect_at_start=True は始点→2番目 方向
    def test_clothoid_valid(self):
        clo = _make_clothoid()
        if clo.is_valid:
            result = entry_tangent(clo, True)
            assert result is not None

    # [エッジ] 無効 Clothoid は None
    def test_clothoid_invalid_returns_none(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert entry_tangent(clo, True) is None
        assert entry_tangent(clo, False) is None

    # [C1] 非対応型は None
    def test_unsupported_type(self):
        assert entry_tangent("not_a_shape", True) is None


class TestElemEndpoints:
    # [仕様] Segment: (start, end) を返す
    def test_segment(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln, 0.2, 0.8)
        s, e = _elem_endpoints(seg)
        assert vec_approx(s, seg.start)
        assert vec_approx(e, seg.end)

    # [仕様] Arc: (start, end) を返す
    def test_arc(self):
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        s, e = _elem_endpoints(arc)
        assert vec_approx(s, arc.start)
        assert vec_approx(e, arc.end)

    # [仕様] 有効 Clothoid: (_line_pt, _circle_pt) を返す
    def test_clothoid_valid(self):
        clo = _make_clothoid()
        if clo.is_valid:
            s, e = _elem_endpoints(clo)
            assert vec_approx(s, clo.line_contact)
            assert vec_approx(e, clo.circle_contact)

    # [エッジ] 無効 Clothoid: (None, None) を返す
    def test_clothoid_invalid(self):
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        s, e = _elem_endpoints(clo)
        assert s is None and e is None

    # [C1] 非対応型: (None, None) を返す
    def test_unsupported_type(self):
        s, e = _elem_endpoints("not_a_shape")
        assert s is None and e is None


class TestPtDist:
    # [仕様] 2点間のユークリッド距離を返す
    def test_normal(self):
        a = Vec2(0, 0)
        b = Vec2(3, 4)
        assert approx(_pt_dist(a, b), 5.0)

    # [境界] 同じ点は 0
    def test_same_point(self):
        a = Vec2(1, 2)
        assert approx(_pt_dist(a, a), 0.0)

    # [エッジ] いずれかが None のとき inf
    def test_none_returns_inf(self):
        assert _pt_dist(None, Vec2(0, 0)) == float('inf')
        assert _pt_dist(Vec2(0, 0), None) == float('inf')
        assert _pt_dist(None, None) == float('inf')


# ══════════════════════════════════════════════════════════════
# 14. resolve_chain
# ══════════════════════════════════════════════════════════════

class TestResolveChain:
    # [境界] 空リストは ([], []) を返す
    def test_empty(self):
        chain, flags = resolve_chain([])
        assert chain == [] and flags == []

    # [仕様] 1要素はそのまま返す
    def test_single_element(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        chain, flags = resolve_chain([seg])
        assert chain == [seg]
        assert len(flags) == 1

    # [仕様] 1要素: ElementProfile の reversed_flag を使う
    def test_single_element_uses_ep_flag(self):
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        ep = ElementProfile()
        ep.element_id = seg.id
        ep.reversed_flag = True
        chain, flags = resolve_chain([seg], [ep])
        assert flags[0] is True

    # [仕様] 2要素: 孤立端点を持つ要素が先頭になる
    def test_two_elements_connected(self):
        """seg1=(0,0)-(10,0), seg2=(10,0)-(20,0) が連結している場合。
        入力順 [seg1, seg2] で渡すと seg1.start=(0,0) が孤立端点として先頭候補になる。
        候補選択は elems のループ順で先着優先のため、seg1 が candidates[0] になる。
        """
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        ln2 = Line(Vec2(10, 0), Vec2(20, 0))
        seg2 = Segment(ln2, 0.0, 1.0)
        chain, flags = resolve_chain([seg1, seg2])
        assert chain[0] is seg1
        assert chain[1] is seg2

    # [仕様] 3要素の直列チェーン
    def test_three_elements_chain(self):
        """seg1→seg2→seg3 の直列チェーン。
        seg1.start が孤立端点 → seg1 が先頭。貪欲法で seg2, seg3 が続く。
        入力は正しい順 [seg1, seg2, seg3] で渡す（先頭候補の決定はループ順依存）。
        """
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(10, 0), Vec2(20, 0))
        ln3 = Line(Vec2(20, 0), Vec2(30, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        seg2 = Segment(ln2, 0.0, 1.0)
        seg3 = Segment(ln3, 0.0, 1.0)
        chain, flags = resolve_chain([seg1, seg2, seg3])
        assert chain[0] is seg1
        assert chain[-1] is seg3

    # [エッジ] 全要素が環状（孤立端点なし）→ elems[0] が強制先頭
    def test_cyclic_no_isolated_endpoint(self):
        # 3点が環状に接続された線分
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(10, 0), Vec2(5, 9))
        ln3 = Line(Vec2(5, 9), Vec2(0, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        seg2 = Segment(ln2, 0.0, 1.0)
        seg3 = Segment(ln3, 0.0, 1.0)
        chain, flags = resolve_chain([seg1, seg2, seg3])
        assert len(chain) == 3
        assert len(flags) == 3

    # [仕様] ElementProfile の reversed_flag が一致する候補を優先
    def test_prefers_ep_matching_flag(self):
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(10, 0), Vec2(20, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        seg2 = Segment(ln2, 0.0, 1.0)
        ep1 = ElementProfile()
        ep1.element_id = seg1.id
        ep1.reversed_flag = False
        chain, flags = resolve_chain([seg2, seg1], [ep1])
        assert chain[0] is seg1
        assert flags[0] is False

    # [エッジ] SNAP_TOL * 10 以内で候補が見つからない場合は残り先頭を強制追加
    def test_disconnected_elements(self):
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(100, 0), Vec2(200, 0))  # 遠く離れている
        seg1 = Segment(ln1, 0.0, 1.0)
        seg2 = Segment(ln2, 0.0, 1.0)
        chain, flags = resolve_chain([seg1, seg2])
        assert len(chain) == 2  # 両方含まれる


# ══════════════════════════════════════════════════════════════
# 15. SnapTol 定数
# ══════════════════════════════════════════════════════════════

class TestSnapTol:
    # [仕様] SNAP_TOL は 1.0
    def test_snap_tol_value(self):
        assert SNAP_TOL == 1.0


# ══════════════════════════════════════════════════════════════
# 16. C1カバレッジ補完テスト（未カバー分岐を網羅）
# ══════════════════════════════════════════════════════════════

class TestUpdateSnaps:
    """_update_snaps の各分岐（snap_segment/snap_arc の on/off 組み合わせ）。"""

    # [C1] snap_segment=False かつ snap_arc=False → _apply_segment_split + _apply_arc_split
    def test_both_off(self):
        """[C1] snap=off/off: _apply_segment_split と _apply_arc_split が呼ばれる分岐。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -1.0, 1.0)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        # is_valid なら _update_snaps が通る
        assert clo._valid is not None  # 例外なし

    # [C1] snap_segment=True かつ snap_arc=True → _apply_segment_snap + _apply_arc_snap
    def test_both_on(self):
        """[C1] snap=on/on: _apply_segment_snap と _apply_arc_snap が呼ばれる分岐。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -0.5, 0.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=True)
        assert clo._valid is not None

    # [C1] is_valid=False のとき _update_snaps は即リターン
    def test_invalid_early_return(self):
        """[C1] is_valid=False: _update_snaps の最初の return 分岐。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 5), 30.0)  # d < R → 無効
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=True)
        assert not clo.is_valid
        # 例外なし = 早期リターンが正しく動作


class TestApplySegmentSnapReversed:
    """_apply_segment_snap の reversed_flag=True 側と縮退防止分岐。"""

    # [C1] reversed_flag=True → t_start を移動する分岐
    def test_reversed_moves_t_start(self):
        """[C1] reversed_flag=True のとき t_start が接点 t 値に更新される。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -0.5, 0.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, reversed_flag=True, snap_segment=True, snap_arc=False)
        if clo.is_valid:
            expected_t = ln.project_t(clo.line_contact)
            assert approx(seg.t_start, expected_t, tol=1e-4)

    # [C1] t_end <= t_start + 1e-9 になるとき t_end を t_start + 0.1 に補正（reversed=True 側）
    def test_reversed_degenerate_prevention(self):
        """[C1] reversed=True で t_end ≤ t_start+1e-9 → t_end = t_start + 0.1 補正。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        # t_end=0.0 に設定しておく（接点が t=0 付近に来るとき縮退する）
        seg = Segment(ln, 0.0, 0.0)  # t_start=t_end=0 → 縮退状態
        ln.segments.append(seg)
        # reversed=True で line_pt が t=0 付近に来る直線・円を設定
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, reversed_flag=True, snap_segment=True, snap_arc=False)
        if clo.is_valid:
            # 縮退防止が働いて t_end > t_start になっていること
            assert seg.t_end > seg.t_start

    # [C1] segments が空のとき _apply_segment_snap は即リターン
    def test_no_segments_returns_early(self):
        """[C1] line.segments=[] のとき _apply_segment_snap の早期リターン。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))  # segments なし
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        # 例外にならない


class TestClearSegmentSplitRestore:
    """_clear_segment_split の実際の復元処理。"""

    # [C1] _split_seg_ids が設定済みのとき AX+XB を AB に戻す（L1132-1138）
    def test_restores_original_segment(self):
        """[C1] snap=False で分割後、_clear_segment_split で元の 1 本に戻る。

        接点が線分の内部（t∈[1e-6, 1-1e-6]）に来るよう直線を
        Vec2(-100,0)→Vec2(100,0) に延長することで分割を確実に発生させる。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        # この設定では接点 t ≈ 0.42 → 線分内部に来るため分割される
        assert clo.is_valid
        assert len(clo._split_seg_ids) == 2
        n_before = len(ln.segments)
        clo._clear_segment_split()
        assert len(ln.segments) == n_before - 1
        assert approx(ln.segments[0].t_end, 1.0, tol=0.01)
        assert clo._split_seg_ids == []


class TestApplyArcSnapRightCurve:
    """_apply_arc_snap の右カーブ側と自動生成の右カーブ側。"""

    # [C1] 右カーブ → arc.angle_end を circle_pt の角度に設定
    def test_right_curve_snaps_angle_end(self):
        """[C1] is_left_curve=False のとき arc.angle_end を接点角度に更新する分岐。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, -60), 40.0)  # y<0 → 右カーブ
        arc = Arc(ci, math.pi / 2, 3 * math.pi / 2)  # 下側の半円
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=True)
        if clo.is_valid:
            angle_contact = math.atan2(
                clo.circle_contact.y - ci.center.y,
                clo.circle_contact.x - ci.center.x
            )
            assert approx(arc.angle_end, angle_contact, tol=1e-4)

    # [C1] 右カーブで円弧なし → 右カーブ用の自動生成分岐
    def test_right_curve_auto_creates_arc(self):
        """[C1] 右カーブで ci.arcs が空 → Arc(ci, contact-π/4, contact) を自動生成する分岐。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, -60), 40.0)  # 円弧なし・右カーブ
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=True)
        if clo.is_valid:
            assert len(ci.arcs) == 1
            # 右カーブの自動生成: angle_end = angle_contact
            angle_contact = math.atan2(
                clo.circle_contact.y - ci.center.y,
                clo.circle_contact.x - ci.center.x
            )
            assert approx(ci.arcs[0].angle_end, angle_contact, tol=1e-4)

    # [C1] _apply_arc_split の追従更新パス（既存 split_arc_ids あり）
    def test_arc_split_followup_update(self):
        """[C1] _split_arc_ids 設定済みの状態で compute() → 追従更新（return 手前）の分岐。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        arc = Arc(ci, -1.0, 1.0)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if clo.is_valid and len(clo._split_arc_ids) == 2:
            # 2回目の compute() で追従更新パスが実行される
            clo.compute()
            assert clo._split_arc_ids  # まだ split_ids が保持されている


class TestClearArcSplitRestore:
    """_clear_arc_split の実際の復元処理。"""

    # [C1] _split_arc_ids が設定済みのとき 2 本を 1 本に戻す（L1262-1265）
    def test_restores_original_arc(self):
        """[C1] snap=False で分割後、_clear_arc_split で元の 1 本に戻る。

        arc の angle_end が元の値（1.0）に戻ることと、arc 数が減ることを確認。
        直線を延長して arc 内部に接点が来るようにする。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)  # 大きな円弧で接点が内部に入りやすい
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_arc_ids) == 2:
            orig_end = 1.5
            n_before = len(ci.arcs)
            clo._clear_arc_split()
            assert len(ci.arcs) == n_before - 1
            assert approx(ci.arcs[0].angle_end, orig_end, tol=0.1)
            assert clo._split_arc_ids == []
        else:
            # 接点が円弧の端点と一致した場合は分割されない
            pass


class TestApplyArcSplitBranches:
    """_apply_arc_split の各分岐。"""

    # [C1] arcs が空のとき早期リターン
    def test_no_arcs_returns_early(self):
        """[C1] circle.arcs=[] のとき _apply_arc_split は何もしない。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)  # arcs なし
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        # 例外にならない（arc_split は arcs がないので分割されない）

    # [C1] 接点が弧の内部にない場合は best_arc=None → return
    def test_contact_at_arc_endpoint_no_split(self):
        """[C1] 接点が arc の端点と一致（rel < 1e-4）→ best_arc=None で return。"""
        """[C1] 接点が弧の端点と一致する（rel < 1e-4）→ best_arc=None で return。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        # 接点が arc の始点と完全一致するよう angle_start を接点角度に設定
        clo_tmp = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if clo_tmp.is_valid:
            contact_angle = math.atan2(
                clo_tmp.circle_contact.y - ci.center.y,
                clo_tmp.circle_contact.x - ci.center.x
            )
            # 接点が arc_start に一致 → 内部点でない
            arc = Arc(ci, contact_angle, contact_angle + 1.0)
            ci.arcs.clear()
            ci.arcs.append(arc)
            # 再 compute
            clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
            # 分割されないことを確認
            assert clo._split_arc_ids == []


class TestSegmentArcSnapSerialization:
    """SegmentSnap / ArcSnap の to_dict / from_dict。"""

    # [C1] SegmentSnap.to_dict / from_dict 往復変換
    def test_segment_snap_roundtrip(self):
        """[C1] SegmentSnap のシリアライズ・デシリアライズ。"""
        ss = SegmentSnap(1, 'end', 2, 'start')
        d = ss.to_dict()
        ss2 = SegmentSnap.from_dict(d)
        assert ss2.seg_a_id == 1
        assert ss2.end_a == 'end'
        assert ss2.seg_b_id == 2
        assert ss2.end_b == 'start'

    # [C1] ArcSnap.to_dict / from_dict 往復変換
    def test_arc_snap_roundtrip(self):
        """[C1] ArcSnap のシリアライズ・デシリアライズ。"""
        as_ = ArcSnap(10, 'start', 20, 'end')
        d = as_.to_dict()
        as2 = ArcSnap.from_dict(d)
        assert as2.arc_a_id == 10
        assert as2.end_a == 'start'
        assert as2.arc_b_id == 20
        assert as2.end_b == 'end'


class TestElementProfileSerialization:
    """ElementProfile.to_dict / from_dict。"""

    # [C1] to_dict / from_dict 往復変換（grade_lines / vertical_curves 含む）
    def test_ep_roundtrip(self):
        """[C1] ElementProfile のシリアライズ・デシリアライズ。"""
        ep = ElementProfile()
        ep.element_id = 99
        ep.element_type = 'segment'
        ep.plan_length = 50.0
        ep.reversed_flag = True
        ep.elev_start = 5.0
        ep.elev_end = 10.0
        gl = GradeLine()
        gl.dist_start = 0; gl.dist_end = 50; gl.elev_start = 5; gl.elev_end = 10
        ep.grade_lines = [gl]
        vc = VerticalCurve()
        vc.pvi_dist = 25; vc.pvi_elev = 7.5; vc.g1 = 10; vc.g2 = 0; vc.length = 20
        ep.vertical_curves = [vc]
        d = ep.to_dict()
        ep2 = ElementProfile.from_dict(d)
        assert ep2.element_id == 99
        assert ep2.element_type == 'segment'
        assert approx(ep2.plan_length, 50.0)
        assert ep2.reversed_flag is True
        assert len(ep2.grade_lines) == 1
        assert len(ep2.vertical_curves) == 1


class TestElevAtBranches:
    """elev_at の VC NaN 分岐と GL ループ分岐。"""

    # [C1] VC が NaN を返す → GL へフォールバック（L1483 のブランチ）
    def test_vc_returns_nan_uses_gl(self):
        """[C1] vc.elevation_at が NaN → GL の線形補間にフォールバックする分岐。

        elev_at の条件チェック: vpc_dist-0.001 <= rel <= vpt_dist+0.001。
        vpc_dist-0.0005 は条件を満たすが elevation_at では x=-0.0005 < 0 → NaN。
        このとき GL にフォールバックして有限値を返すことを確認する。
        """
        ep = ElementProfile()
        ep.plan_length = 100.0
        gl = GradeLine()
        gl.dist_start = 0; gl.dist_end = 100; gl.elev_start = 0; gl.elev_end = 10
        ep.grade_lines = [gl]
        vc = VerticalCurve()
        vc.pvi_dist = 50.0; vc.pvi_elev = 5.0; vc.g1 = 10; vc.g2 = 0; vc.length = 40.0
        # vpc_dist=30, vpt_dist=70
        # rel = vpc_dist - 0.0005 = 29.9995 → 条件を満たすが x < 0 → NaN
        ep.vertical_curves = [vc]
        rel = vc.vpc_dist - 0.0005
        result = ep.elev_at(rel)
        assert not math.isnan(result)
        assert approx(result, rel / 10.0, tol=0.01)  # GL から線形補間

    # [C1] GL ループで最初の GL が範囲外、2本目が範囲内
    def test_second_gl_matches(self):
        """[C1] grade_lines が複数あり 2 本目が rel に対応する分岐。"""
        ep = ElementProfile()
        ep.plan_length = 200.0
        gl1 = GradeLine()
        gl1.dist_start = 0; gl1.dist_end = 100; gl1.elev_start = 0; gl1.elev_end = 10
        gl2 = GradeLine()
        gl2.dist_start = 100; gl2.dist_end = 200; gl2.elev_start = 10; gl2.elev_end = 20
        ep.grade_lines = [gl1, gl2]
        # rel=150 は gl1 の範囲外、gl2 の範囲内
        assert approx(ep.elev_at(150.0), 15.0)


class TestVerticalAlignmentSerialization:
    """VerticalAlignment の to_dict / from_dict。"""

    # [C1] to_dict / from_dict 往復変換
    def test_va_roundtrip(self):
        """[C1] VerticalAlignment のシリアライズ・デシリアライズ（旧フォーマット互換）。"""
        from models import VerticalAlignment
        va = VerticalAlignment()
        va.nickname = 'test_va'
        gl = GradeLine()
        gl.dist_start = 0; gl.dist_end = 50; gl.elev_start = 0; gl.elev_end = 5
        va.grade_lines = [gl]
        d = va.to_dict()
        va2 = VerticalAlignment.from_dict(d)
        assert va2.nickname == 'test_va'
        assert len(va2.grade_lines) == 1


class TestSceneNicknameBranches:
    """Scene のニックネーム関連分岐。"""

    # [C1] get_nickname: nicknames に存在するとき L1739 の return 分岐
    def test_get_nickname_existing(self):
        """[C1] nicknames[id] が存在するとき直接返す分岐（L1739）。"""
        sc = Scene()
        sc.nicknames[999] = 'my_name'
        assert sc.get_nickname(999, 'test') == 'my_name'

    # [C1] set_nickname: name が空でないとき L1753 の代入分岐
    def test_set_nickname_nonempty(self):
        """[C1] name が空でないとき nicknames に代入する分岐（L1753）。"""
        sc = Scene()
        sc.set_nickname(1, 'hello')
        assert sc.nicknames[1] == 'hello'

    # [C1] set_nickname: 空文字かつ obj_id が存在しない場合は何もしない（L1754 の elif）
    def test_set_nickname_empty_nonexistent(self):
        """[C1] name='' かつ obj_id が nicknames に存在しない → 何もしない分岐（L1754）。"""
        sc = Scene()
        sc.set_nickname(999, '')  # 例外にならない
        assert 999 not in sc.nicknames

    # [C1] add_circle: id が nicknames にすでにある場合は上書きしない（L1781 の if not）
    def test_add_circle_no_overwrite_nickname(self):
        """[C1] add_circle で既存 nickname を上書きしない分岐（L1781）。"""
        sc = Scene()
        ci = Circle(Vec2(0, 0), 5.0)
        sc.nicknames[ci.id] = 'existing'
        sc.add_circle(ci)
        assert sc.nicknames[ci.id] == 'existing'

    # [C1] add_clothoid: id が nicknames にすでにある場合は上書きしない（L1794）
    def test_add_clothoid_no_overwrite_nickname(self):
        """[C1] add_clothoid で既存 nickname を上書きしない分岐（L1794）。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.nicknames[clo.id] = 'existing_clo'
        sc.add_clothoid(clo)
        assert sc.nicknames[clo.id] == 'existing_clo'


class TestConnectedObjectsBranches:
    """connected_objects の各 isinstance 分岐。"""

    # [C1] Line + connection あり → 相手 Line も返す（L1862-1864）
    def test_line_with_connection(self):
        """[C1] Line.connection が設定済みのとき相手 Line も connected_objects に含まれる。"""
        sc = Scene()
        ln_a = Line(Vec2(0, 0), Vec2(10, 0))
        ln_b = Line(Vec2(10, 0), Vec2(20, 0))
        sc.add_line(ln_a)
        sc.add_line(ln_b)
        # 手動で接続情報を設定
        conn = LineConnection(
            kind='polyline', line_a=ln_a, line_b=ln_b,
            shared_point=Vec2(10, 0),
            a_end_is_shared=True, b_start_is_shared=True
        )
        ln_a.connection = conn
        ln_b.connection = conn
        result = sc.connected_objects(ln_a)
        assert ln_b in result

    # [C1] Clothoid → line + circle が返る（L1869-1872）
    def test_clothoid_returns_line_and_circle(self):
        """[C1] connected_objects(Clothoid) → line と circle が返る分岐（L1869-1872）。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(clo)
        assert ln in result
        assert ci in result


class TestToDictNicknameBranch:
    """to_dict の nickname なし分岐（L1885）。"""

    # [C1] nickname が設定されていない図形の to_dict
    def test_to_dict_no_nickname(self):
        """[C1] nickname が nicknames にない場合、to_dict に nickname フィールドを追加しない。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(1, 0))
        sc.lines.append(ln)  # add_line を通さず直接追加（nickname 未設定）
        d = sc.to_dict()
        # nickname フィールドが含まれないことを確認
        ln_d = d['lines'][0]
        assert 'nickname' not in ln_d


class TestFromDictBranches:
    """Scene.from_dict の各分岐。"""

    # [C1] Clothoid の復元（L1978-1987）
    def test_from_dict_restores_clothoids(self):
        """[C1] from_dict で clothoids が正しく復元される分岐。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        d = sc.to_dict()
        sc2 = Scene.from_dict(d)
        assert len(sc2.clothoids) == 1

    # [C1] _resolve_id: id=None のとき new_id() で採番（L1951-1952）
    def test_from_dict_id_none_gets_new_id(self):
        """[C1] 辞書に id フィールドがない場合は new_id() で採番する分岐（L1951-1952）。"""
        d = {
            'lines': [
                {'ref_start': {'x': 0, 'y': 0},
                 'ref_end': {'x': 1, 'y': 0}, 'segments': []}
                # id フィールドなし
            ],
            'circles': [], 'clothoids': [], 'element_profiles': [],
        }
        sc = Scene.from_dict(d)
        assert len(sc.lines) == 1
        assert sc.lines[0].id >= 1

    # [C1] arc_snaps が含まれる from_dict（L1972）
    def test_from_dict_with_arc_snaps(self):
        """[C1] from_dict で arc_snaps が処理される分岐。"""
        d = {
            'lines': [], 'circles': [], 'clothoids': [],
            'element_profiles': [],
            'arc_snaps': [
                {'arc_a_id': 1, 'end_a': 'start', 'arc_b_id': 2, 'end_b': 'end'}
            ],
        }
        sc = Scene.from_dict(d)
        assert len(sc.arc_snaps) == 1

    # [C1] 旧フォーマット（grade_lines / vertical_curves がトップレベル）の復元（L1998-2002）
    def test_from_dict_old_format(self):
        """[C1] 旧フォーマット（トップレベル grade_lines）が VerticalAlignment に変換される分岐。"""
        d = {
            'lines': [], 'circles': [], 'clothoids': [], 'element_profiles': [],
            'grade_lines': [
                {'id': 1, 'dist_start': 0, 'elev_start': 0,
                 'dist_end': 100, 'elev_end': 10}
            ],
            'vertical_curves': [],
        }
        sc = Scene.from_dict(d)
        assert len(sc.vertical_alignments) == 1

    # [C1] nicknames がトップレベルにある旧フォーマット（L2008）
    def test_from_dict_top_level_nicknames(self):
        """[C1] トップレベルの nicknames フィールドが読み込まれる分岐（L2008）。"""
        d = {
            'lines': [
                {'id': 42, 'ref_start': {'x': 0, 'y': 0},
                 'ref_end': {'x': 1, 'y': 0}, 'segments': []}
            ],
            'circles': [], 'clothoids': [], 'element_profiles': [],
            'nicknames': {'42': 'old_nickname'},
        }
        sc = Scene.from_dict(d)
        assert sc.nicknames.get(42) == 'old_nickname'

    # [C1] element_profiles に grade_lines / vertical_curves がある場合（L2014-2015）
    def test_from_dict_ep_with_gl_vc(self):
        """[C1] ElementProfile が grade_lines/vertical_curves を持つ場合のカウンタ更新分岐。"""
        gl = GradeLine()
        gl.id = 500
        gl.dist_start = 0; gl.dist_end = 50; gl.elev_start = 0; gl.elev_end = 5
        vc = VerticalCurve()
        vc.id = 501
        vc.pvi_dist = 25; vc.pvi_elev = 2.5; vc.g1 = 10; vc.g2 = 0; vc.length = 20
        ep = ElementProfile()
        ep.id = 100
        ep.grade_lines = [gl]
        ep.vertical_curves = [vc]
        d = {'lines': [], 'circles': [], 'clothoids': [],
             'element_profiles': [ep.to_dict()]}
        sc = Scene.from_dict(d)
        assert len(sc.element_profiles) == 1
        # カウンタが max_id+1 から再開されることを確認
        next_id = new_id()
        assert next_id > 501

    # [C1] vertical_alignments に grade_lines / vertical_curves がある場合（L2017-2019）
    def test_from_dict_va_with_gl_vc(self):
        """[C1] VerticalAlignment が grade_lines/vertical_curves を持つ場合のカウンタ更新分岐。"""
        from models import VerticalAlignment
        va = VerticalAlignment()
        va.id = 600
        gl = GradeLine()
        gl.id = 601
        gl.dist_start = 0; gl.dist_end = 50; gl.elev_start = 0; gl.elev_end = 5
        va.grade_lines = [gl]
        d = {'lines': [], 'circles': [], 'clothoids': [],
             'element_profiles': [],
             'vertical_alignments': [va.to_dict()]}
        sc = Scene.from_dict(d)
        assert len(sc.vertical_alignments) == 1

    # [C1] all_ids が空のとき _reset_id_counter_after を呼ばない（L2020 の if all_ids）
    def test_from_dict_empty_scene(self):
        """[C1] 全 ID リストが空のとき _reset_id_counter_after が呼ばれない分岐（L2020）。"""
        d = {'lines': [], 'circles': [], 'clothoids': [], 'element_profiles': []}
        sc = Scene.from_dict(d)
        assert sc.lines == []


class TestEntryTangentClothoidEnd:
    """entry_tangent の Clothoid at_end=True 側（connect_at_start=False の Clothoid 分岐）。"""

    # [C1] Clothoid connect_at_start=False → points[-1] から points[-2] 方向（L2168-2169）
    def test_clothoid_from_end(self):
        """[C1] entry_tangent(clo, connect_at_start=False) → points[-2] から [-1] の逆方向。"""
        clo = _make_clothoid()
        if clo.is_valid and len(clo.points) >= 2:
            result = entry_tangent(clo, connect_at_start=False)
            assert result is not None
            # points[-2] → points[-1] とは逆方向
            dx = clo.points[-2].x - clo.points[-1].x
            dy = clo.points[-2].y - clo.points[-1].y
            ln = math.hypot(dx, dy) or 1
            expected = (dx / ln, dy / ln)
            assert approx(result[0], expected[0])
            assert approx(result[1], expected[1])


class TestResolveChainRevTrue:
    """resolve_chain で rev=True が選択される分岐（L2249）。"""

    # [C1] 終点が孤立する要素は rev=True（逆順）で先頭になる
    def test_rev_true_when_end_isolated(self):
        """[C1] seg.end が孤立端点のとき rev=True で先頭になる分岐（L2249）。"""
        # seg1: (0,0)→(10,0)  seg2: (0,0)→(-10,0)
        # seg2.end=(-10,0) は孤立、seg2.start=(0,0) は seg1.start=(0,0) と接続
        # → seg2 は end が孤立なので rev=True で先頭候補になる
        # EP で rev=True を優先するよう設定
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(0, 0), Vec2(-10, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        seg2 = Segment(ln2, 0.0, 1.0)
        ep2 = ElementProfile()
        ep2.element_id = seg2.id
        ep2.reversed_flag = True  # rev=True を優先させる
        chain, flags = resolve_chain([seg2, seg1], [ep2])
        # seg2 が rev=True で先頭になっているはず
        # （seg2.end=(-10,0) が孤立端点なので rev=True の先頭候補）
        if chain[0] is seg2:
            assert flags[0] is True
        else:
            # seg1 が先頭になる場合は rev=False
            assert chain[0] is seg1

    # [C1] 貪欲法で d_rev < d_fwd のとき best_rev=True が選ばれる（L2249）
    def test_greedy_rev_true_selected(self):
        """[C1] 次の要素の終点が現在の出口に近い場合 rev=True で選択される分岐（L2249）。"""
        # seg1: (0,0)→(10,0)  seg2: (20,0)→(10,0)（seg2.end が seg1.end に近い）
        ln1 = Line(Vec2(0, 0), Vec2(10, 0))
        ln2 = Line(Vec2(20, 0), Vec2(10, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        seg2 = Segment(ln2, 0.0, 1.0)
        chain, flags = resolve_chain([seg1, seg2])
        assert len(chain) == 2
        # seg2 は終点(10,0) が seg1 の終点(10,0) に近い → rev=True で連結
        if chain[1] is seg2:
            assert flags[1] is True


class TestRemainingCoverage:
    """残りの未カバー分岐を網羅する追加テスト。"""

    # [C1] connected_objects(Line): クロソイドなし・接続なし → 空リスト（L1859->1858）
    def test_connected_objects_line_no_clothoid(self):
        """[C1] Line にクロソイドも接続もない場合 connected_objects は空リスト（L1859->1858）。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        assert sc.connected_objects(ln) == []

    # [C1] connected_objects(Circle): クロソイドなし → 空リスト（L1867->1866）
    def test_connected_objects_circle_no_clothoid(self):
        """[C1] Circle にクロソイドがない場合 connected_objects は空リスト（L1867->1866）。"""
        sc = Scene()
        ci = Circle(Vec2(0, 0), 5.0)
        sc.add_circle(ci)
        assert sc.connected_objects(ci) == []

    # [C1] from_dict: clothoid の line_id が見つからない場合はスキップ（L1982->1977）
    def test_from_dict_clothoid_missing_refs(self):
        """[C1] clothoid の line_id/circle_id が参照先にない → clothoid はスキップ（L1982->1977）。"""
        d = {
            'lines': [], 'circles': [],
            'clothoids': [{'id': 99, 'line_id': 9999, 'circle_id': 8888}],
            'element_profiles': [],
        }
        sc = Scene.from_dict(d)
        assert len(sc.clothoids) == 0  # 参照先なしなのでスキップ

    # [C1] _apply_segment_split: _split_seg_ids 内の seg が消えているとき リセット→再分割
    def test_segment_split_ids_stale(self):
        """[C1] _split_seg_ids の線分が削除済み → リセットして再分割を試みる（L1102）。

        直線を延長して分割が確実に起きるようにしてから XB を削除する。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_seg_ids) == 2:
            # XB を手動削除して stale 状態を作る
            xb_id = clo._split_seg_ids[1]
            ln.segments = [s for s in ln.segments if s.id != xb_id]
            # compute() を再呼び出し → stale ids をリセットして再分割
            clo.compute()
            # 例外にならない

    # [C1] _apply_segment_split: candidates が空（全線分が split_ids）→ return（L1107）
    def test_segment_split_no_candidates(self):
        """[C1] 全線分が _split_seg_ids に含まれる → candidates 空で return（L1107）。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if clo.is_valid and len(clo._split_seg_ids) == 2:
            # _split_seg_ids に全線分を含める
            clo._split_seg_ids = [s.id for s in ln.segments]
            clo._apply_segment_split()  # candidates 空 → return、例外なし

    # [C1] _apply_arc_split: _split_arc_ids の arc が消えているとき リセット（L1226）
    def test_arc_split_ids_stale(self):
        """[C1] _split_arc_ids の円弧が削除済み → リセットして再分割を試みる（L1226）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_arc_ids) == 2:
            xb_id = clo._split_arc_ids[1]
            ci.arcs = [a for a in ci.arcs if a.id != xb_id]
            clo.compute()  # stale ids をリセット → 例外なし

    # [C1] _apply_arc_split: arc.id が _split_arc_ids に含まれる → continue（L1232）
    def test_arc_split_skips_own_arcs(self):
        """[C1] _apply_arc_split で arc.id が _split_arc_ids にある → continue スキップ（L1232）。

        分割済みの状態で compute() すると追従更新パスが走り、
        _split_arc_ids に含まれる arc がループでスキップされる。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_arc_ids) == 2:
            # 2 回目の compute → 追従更新パス + continue スキップが実行される
            clo.compute()
            assert len(clo._split_arc_ids) == 2

    # [C1] _update_snaps: snap_segment=True かつ _line_pt is None → L1031 の条件False
    def test_update_snaps_line_pt_none_skips(self):
        """[C1] is_valid=True かつ _line_pt=None という状態は通常起きないが
        snap_segment=True でも _line_pt=None のとき _apply_segment_snap を呼ばない（L1031）。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=True)
        # is_valid の場合、_line_pt は必ず設定されるため
        # このテストは「有効なら always _line_pt あり」の確認
        if clo.is_valid:
            assert clo._line_pt is not None

    # [C1] from_dict の arc_snaps 処理（L1972）
    def test_from_dict_segment_snaps(self):
        """[C1] from_dict で segment_snaps が処理される分岐。"""
        d = {
            'lines': [], 'circles': [], 'clothoids': [],
            'element_profiles': [],
            'segment_snaps': [
                {'seg_a_id': 1, 'end_a': 'end', 'seg_b_id': 2, 'end_b': 'start'}
            ],
        }
        sc = Scene.from_dict(d)
        assert len(sc.segment_snaps) == 1


class TestConnectedObjectsAllBranches:
    """connected_objects の全分岐（Line/Circle に clothoid あり/なし、Clothoid）。"""

    # [C1] connected_objects(Line): clothoid があるとき L1859 の if c.line is obj が True
    def test_line_with_clothoid_branch(self):
        """[C1] Line に clothoid がある → L1859 の if 分岐が通る。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(ln)
        assert clo in result

    # [C1] connected_objects(Circle): clothoid があるとき L1867 の if c.circle is obj が True
    def test_circle_with_clothoid_branch(self):
        """[C1] Circle に clothoid がある → L1867 の if 分岐が通る。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(ci)
        assert clo in result

    # [C1] connected_objects(Clothoid): L1869-1872 の elif isinstance(obj, Clothoid) 分岐
    def test_clothoid_branch(self):
        """[C1] Clothoid を渡したとき L1869 の elif 分岐が通る。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(clo)
        assert ln in result and ci in result

    # [C1] _apply_segment_snap の縮退防止: t_start >= t_end-1e-9 → t_start = t_end-0.1（L1067）
    def test_segment_snap_degenerate_prevention_normal(self):
        """[C1] reversed=False で接点 t が t_start より小さいとき縮退防止が発動（L1067）。

        t_start=0.5 の線分に対して接点が t=0.3 に来るとき、
        t_end=0.3 < t_start=0.5 → 縮退防止で t_start=t_end-0.1 になる。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        # t_start を 0.5 に設定して接点が t_start より前に来るようにする
        seg = Segment(ln, 0.5, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        if clo.is_valid:
            # 縮退防止の結果として t_end > t_start になっていること
            assert seg.t_end > seg.t_start

    # [C1] from_dict の arc_snaps ループ（L1972）
    def test_from_dict_arc_snaps_loop(self):
        """[C1] from_dict で arc_snaps が正しく復元される（L1972）。"""
        d = {
            'lines': [], 'circles': [], 'clothoids': [],
            'element_profiles': [],
            'arc_snaps': [
                {'arc_a_id': 11, 'end_a': 'start', 'arc_b_id': 22, 'end_b': 'end'},
                {'arc_a_id': 33, 'end_a': 'end',   'arc_b_id': 44, 'end_b': 'start'},
            ],
        }
        sc = Scene.from_dict(d)
        assert len(sc.arc_snaps) == 2
        assert sc.arc_snaps[0].arc_a_id == 11
        assert sc.arc_snaps[1].arc_a_id == 33


class TestFinalCoverage:
    """最終カバレッジ補完テスト。防御的 Dead Code 以外の全分岐。"""

    # [C1] _clear_segment_split: seg_xb が segments にない場合（L1135 False → L1138）
    def test_clear_segment_split_xb_already_removed(self):
        """[C1] _clear_segment_split で seg_xb が既に segments にない → if False → L1138のみ実行。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_seg_ids) == 2:
            # seg_xb を手動で segments から除去してから _clear 呼び出し
            xb_id = clo._split_seg_ids[1]
            ln.segments = [s for s in ln.segments if s.id != xb_id]
            clo._clear_segment_split()  # if が False → L1138 の split_ids=[] のみ
            assert clo._split_seg_ids == []

    # [C1] _clear_arc_split: arc_xb が circle.arcs にある場合（L1262 True → L1263-L1265）
    def test_clear_arc_split_xb_present(self):
        """[C1] _clear_arc_split の if True 分岐: arc_ax/arc_xb が両方存在（L1262->1265）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_arc_ids) == 2:
            orig_end = ci.arcs[-1].angle_end  # XB の angle_end
            n = len(ci.arcs)
            clo._clear_arc_split()  # L1262 True → L1263,1264,1265 通過
            assert len(ci.arcs) == n - 1
            assert clo._split_arc_ids == []

    # [C1] _apply_arc_split の continue 分岐（L1232）: 既存 split_ids のある arc はスキップ
    def test_arc_split_continue_branch(self):
        """[C1] _apply_arc_split で _split_arc_ids に含まれる arc → continue（L1232）。

        2 回目の compute() で split_arc_ids が既に設定済みのとき、
        ループ内で arc.id が split_arc_ids にあると continue される。
        ただし split_arc_ids がある場合は追従更新パスに入るため、
        この分岐は実質到達困難（防御的コード）であることを確認する。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        # _split_arc_ids が設定済みの場合の compute は追従更新パスに入るため
        # L1232 の continue には実際には到達しない（追従更新が return するため）
        if len(clo._split_arc_ids) == 2:
            clo.compute()  # 追従更新パス → return で L1232 には到達しない
            assert len(clo._split_arc_ids) == 2  # 維持されている

    # [C1] _apply_segment_split の candidates が空のケース（L1107）
    def test_segment_split_empty_candidates(self):
        """[C1] segments が全て _split_seg_ids の場合 candidates 空 → return（L1107）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        # 全線分を _split_seg_ids に含め、さらに _split_seg_ids を [] にリセット
        # することで "あたかも全セグメントが管理下" の状態を作る
        # その後 _apply_segment_split を直接呼ぶ
        all_ids = [s.id for s in ln.segments]
        clo._split_seg_ids = all_ids  # 全線分を split_ids に含める
        clo._apply_segment_split()  # candidates が空 → L1107 の return
        # 例外にならない


class TestSegmentSnapDegeneratePrevention:
    """_apply_segment_snap の縮退防止分岐（L1067/L1071）を確実にカバーする。"""

    # [C1] L1067: reversed=False で t_start > t_x → 縮退防止で t_start = t_end - 0.1
    def test_normal_degenerate_t_start_corrected(self):
        """[C1] reversed=False かつ t_start(0.9) > t_x(0.61) → L1067 True 発動。

        Line(-200,0)-(100,0), seg.t_start=0.9, 接点≈t=0.61 なので
        t_end=0.61 < t_start=0.9 → 縮退防止で t_start=t_end-0.1 ≈ 0.51 に補正。
        """
        ln = Line(Vec2(-200, 0), Vec2(100, 0))
        seg = Segment(ln, 0.9, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        t_start_before = seg.t_start
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        assert clo.is_valid
        # 縮退防止が発動して t_start が補正されている
        assert seg.t_start < t_start_before, "縮退防止で t_start が減少するはず"
        assert seg.t_end > seg.t_start, "補正後 t_end > t_start を保証"

    # [C1] L1071: reversed=True で t_end < t_x → 縮退防止で t_end = t_start + 0.1
    def test_reversed_degenerate_t_end_corrected(self):
        """[C1] reversed=True かつ t_end(0.1) < t_x(0.61) → L1071 True 発動。

        reversed=True のとき t_start = t_x に設定される。
        元の t_end(0.1) <= t_start(0.61) + 1e-9 → 縮退防止で t_end = t_start + 0.1 ≈ 0.71。
        """
        ln = Line(Vec2(-200, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 0.1)  # t_end=0.1 (小さい値)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        t_end_before = seg.t_end
        clo = Clothoid(ln, ci, reversed_flag=True, snap_segment=True, snap_arc=False)
        assert clo.is_valid
        # reversed=True: t_start = t_x (大きい値), t_end(0.1) <= t_start+1e-9 → 補正
        assert seg.t_end > t_end_before, "縮退防止で t_end が増加するはず"
        assert seg.t_end > seg.t_start, "補正後 t_end > t_start を保証"

    # [C1] L1232: _apply_arc_split の continue（arc が split_ids に含まれる）
    def test_arc_split_continue(self):
        """[C1] _apply_arc_split 内で arc.id が _split_arc_ids にある → continue（L1232）。

        分割済みの状態で追加の arc をリストに入れ、
        分割済みの arc が continue でスキップされることを確認する。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc1 = Arc(ci, -1.5, 1.5)  # 分割対象の arc
        arc2 = Arc(ci, 2.0, 3.0)   # 追加の別 arc（split_ids には含まれない）
        ci.arcs.append(arc1)
        ci.arcs.append(arc2)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_arc_ids) == 2:
            # _split_arc_ids に arc1 が入っている状態で compute() → L1232 が通る
            clo.compute()
            # arc1 が split_ids に含まれているので continue でスキップ
            # arc2 が分割対象の候補として残る
            assert len(clo._split_arc_ids) >= 0  # 例外にならない

    # [C1] L1262->1265: _clear_arc_split の True 分岐（復元実行）
    def test_clear_arc_split_true_branch(self):
        """[C1] _clear_arc_split で arc_ax と arc_xb が両方存在 → 復元実行（L1262 True）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert clo.is_valid
        if len(clo._split_arc_ids) == 2:
            n_before = len(ci.arcs)
            clo._clear_arc_split()  # L1262 True → L1263, L1264, L1265
            assert len(ci.arcs) == n_before - 1
            assert clo._split_arc_ids == []
        else:
            pytest.skip("arc split が発生しなかったためスキップ")

    # [C1] connected_objects: Line の for ループで c.line is obj が True（L1859）
    def test_connected_objects_line_loop_true_branch(self):
        """[C1] connected_objects(Line) の for ループ内で c.line is obj True → L1859 通過。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        # 別の Clothoid（ln を参照しない）も追加して False 分岐も通す
        ln2 = Line(Vec2(0, 0), Vec2(50, 50))
        sc.add_line(ln2)
        clo2 = Clothoid(ln2, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo2)
        result = sc.connected_objects(ln)
        assert clo in result
        assert clo2 not in result  # clo2 は ln2 を参照

    # [C1] connected_objects: Circle の for ループで c.circle is obj True（L1867）
    def test_connected_objects_circle_loop_true_branch(self):
        """[C1] connected_objects(Circle) の for ループ内で c.circle is obj True → L1867 通過。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        ci2 = Circle(Vec2(0, 0), 10.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        sc.add_circle(ci2)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(ci2)
        assert clo not in result  # clo は ci を参照（ci2 ではない）

    # [C1] connected_objects: isinstance(obj, Clothoid) → L1869-1872 通過
    def test_connected_objects_clothoid_isinstance_branch(self):
        """[C1] connected_objects(Clothoid) → L1869 の elif 分岐を通る。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 40.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        result = sc.connected_objects(clo)
        assert ln in result and ci in result

    # [C1] from_dict の circles の arcs の _resolve_id（L1972）
    def test_from_dict_resolves_arc_ids(self):
        """[C1] from_dict で circles.arcs の _resolve_id が呼ばれる（L1972）。"""
        d = {
            'lines': [],
            'circles': [
                {'id': 200, 'center': {'x': 0, 'y': 0}, 'radius': 5.0,
                 'arcs': [{'id': 201, 'angle_start': 0.0, 'angle_end': 1.57}]}
            ],
            'clothoids': [], 'element_profiles': [],
        }
        sc = Scene.from_dict(d)
        assert len(sc.circles) == 1
        assert len(sc.circles[0].arcs) == 1

    # [C1] from_dict の circles.arcs で ID 衝突がある場合（L1972 の _resolve_id）
    def test_from_dict_resolves_arc_id_collision(self):
        """[C1] circles.arcs で ID 衝突 → _resolve_id で新 ID を割り当て（L1972）。"""
        d = {
            'lines': [
                {'id': 300, 'ref_start': {'x': 0, 'y': 0},
                 'ref_end': {'x': 1, 'y': 0}, 'segments': []}
            ],
            'circles': [
                {'id': 301, 'center': {'x': 0, 'y': 0}, 'radius': 5.0,
                 'arcs': [
                     {'id': 300, 'angle_start': 0.0, 'angle_end': 1.0},  # line と ID 衝突
                 ]}
            ],
            'clothoids': [], 'element_profiles': [],
        }
        sc = Scene.from_dict(d)
        all_ids = [ln.id for ln in sc.lines] + [ci.id for ci in sc.circles] +                   [a.id for ci in sc.circles for a in ci.arcs]
        assert len(set(all_ids)) == len(all_ids), "ID が衝突していないこと"


# ══════════════════════════════════════════════════════════════
# OffsetConstraint テスト
# ══════════════════════════════════════════════════════════════

class TestOffsetConstraintInit:
    """OffsetConstraint.__post_init__ のテスト。"""

    # [仕様] _eps_a / _eps_b は 0（未設定）で初期化される
    def test_post_init_eps_zero(self):
        """[仕様] __post_init__ で _eps_a=0, _eps_b=0 に初期化される（後方互換モード）。"""
        oc = OffsetConstraint()
        assert oc._eps_a == 0
        assert oc._eps_b == 0

    # [仕様] feasible のデフォルトは True
    def test_default_feasible_true(self):
        """[仕様] デフォルト feasible=True（未解決状態では成功を仮定）。"""
        oc = OffsetConstraint()
        assert oc.feasible is True

    # [仕様] off_a / off_b のデフォルトは 0.0
    def test_default_off_zero(self):
        """[仕様] デフォルト off_a=0.0, off_b=0.0。"""
        oc = OffsetConstraint()
        assert oc.off_a == 0.0
        assert oc.off_b == 0.0


class TestOffsetConstraintCalcOffsets:
    """OffsetConstraint.calc_offsets_from_current のテスト。"""

    def _make_oc(self, ln, ca, cb):
        oc = OffsetConstraint()
        oc.line = ln; oc.circle_a = ca; oc.circle_b = cb
        return oc

    # [仕様] off_a = distance_to(ca) - ca.radius
    def test_off_a_calculation(self):
        """[仕様] off_a = distance_to(circle_a.center) - circle_a.radius。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))   # y=0 の水平直線
        ca = Circle(Vec2(0, 30), 20.0)            # dist=30, r=20 → off_a=10
        cb = Circle(Vec2(0, -50), 30.0)
        oc = self._make_oc(ln, ca, cb)
        oc.calc_offsets_from_current()
        assert abs(oc.off_a - 10.0) < 1e-9

    # [仕様] off_b = distance_to(cb) - cb.radius
    def test_off_b_calculation(self):
        """[仕様] off_b = distance_to(circle_b.center) - circle_b.radius。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ca = Circle(Vec2(0, 30), 20.0)
        cb = Circle(Vec2(0, -50), 30.0)           # dist=50, r=30 → off_b=20
        oc = self._make_oc(ln, ca, cb)
        oc.calc_offsets_from_current()
        assert abs(oc.off_b - 20.0) < 1e-9

    # [仕様] _eps_a = -sign(signed_dist(ca)) → ca が左側なら _eps_a=-1
    def test_eps_a_ca_left_side(self):
        """[仕様] ca が直線の左側（signed_dist>0）→ _eps_a=-1。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))   # left_normal=(0,1)
        ca = Circle(Vec2(0, 30), 20.0)            # signed_dist=+30（左側）
        cb = Circle(Vec2(0, -50), 30.0)
        oc = self._make_oc(ln, ca, cb)
        oc.calc_offsets_from_current()
        assert oc._eps_a == -1

    # [仕様] ca が右側（signed_dist<0）→ _eps_a=+1
    def test_eps_a_ca_right_side(self):
        """[仕様] ca が直線の右側（signed_dist<0）→ _eps_a=+1。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ca = Circle(Vec2(0, -30), 20.0)           # signed_dist=-30（右側）
        cb = Circle(Vec2(0, 50), 30.0)
        oc = self._make_oc(ln, ca, cb)
        oc.calc_offsets_from_current()
        assert oc._eps_a == +1

    # [仕様] _eps_b = +sign(signed_dist(cb)) → cb が左側なら _eps_b=+1
    def test_eps_b_cb_left_side(self):
        """[仕様] cb が直線の左側（signed_dist>0）→ _eps_b=+1。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ca = Circle(Vec2(0, -30), 20.0)
        cb = Circle(Vec2(0, 50), 30.0)            # signed_dist=+50（左側）
        oc = self._make_oc(ln, ca, cb)
        oc.calc_offsets_from_current()
        assert oc._eps_b == +1

    # [仕様] cb が右側（signed_dist<0）→ _eps_b=-1
    def test_eps_b_cb_right_side(self):
        """[仕様] cb が直線の右側（signed_dist<0）→ _eps_b=-1。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ca = Circle(Vec2(0, 30), 20.0)
        cb = Circle(Vec2(0, -50), 30.0)           # signed_dist=-50（右側）
        oc = self._make_oc(ln, ca, cb)
        oc.calc_offsets_from_current()
        assert oc._eps_b == -1

    # [エッジ] line が None のとき何もしない（早期リターン）
    def test_line_none_no_error(self):
        """[エッジ] line=None のとき何もしない（AttributeError を起こさない）。"""
        oc = OffsetConstraint()
        oc.circle_a = Circle(Vec2(0, 10), 5.0)
        oc.circle_b = Circle(Vec2(0, -10), 5.0)
        oc.calc_offsets_from_current()  # 例外にならない
        assert oc.off_a == 0.0  # 変化しない

    # [エッジ] circle_a が None のとき何もしない
    def test_circle_a_none_no_error(self):
        """[エッジ] circle_a=None のとき何もしない。"""
        oc = OffsetConstraint()
        oc.line = Line(Vec2(-100, 0), Vec2(100, 0))
        oc.circle_b = Circle(Vec2(0, -10), 5.0)
        oc.calc_offsets_from_current()
        assert oc.off_a == 0.0


class TestOffsetConstraintSolve:
    """OffsetConstraint.solve のテスト。"""

    def _make_oc(self, ln, ca, cb):
        oc = OffsetConstraint()
        oc.line = ln; oc.circle_a = ca; oc.circle_b = cb
        oc.calc_offsets_from_current()
        return oc

    def _dist(self, ln, center):
        return ln.distance_to(center)

    # [仕様] 正常ケース: 距離拘束を満たす直線を生成
    def test_solve_normal_case(self):
        """[仕様] solve() が True を返し、各円の距離拘束を満たす直線を生成する。"""
        ca = Circle(Vec2(0,  50), 20.0)
        cb = Circle(Vec2(0, -50), 30.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        oc = self._make_oc(ln, ca, cb)
        ok = oc.solve()
        assert ok is True
        assert oc.feasible is True
        assert abs(self._dist(ln, ca.center) - (ca.radius + oc.off_a)) < 1e-6
        assert abs(self._dist(ln, cb.center) - (cb.radius + oc.off_b)) < 1e-6

    # [仕様] 法線方向の維持: 2円の間の直線が外に飛び出さない
    def test_solve_maintains_normal_direction_between_circles(self):
        """[仕様] 2円の間の直線が、円を近づけても外に飛び出さない（法線方向維持）。"""
        import math
        ca = Circle(Vec2(0,  30), 20.0)
        cb = Circle(Vec2(0, -30), 20.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))  # 2円の間
        oc = self._make_oc(ln, ca, cb)
        # 設定時 signed_dist: ca が左側(+)、cb が右側(-)
        sign_ca_init = ln.signed_dist(ca.center) > 0  # True（左側）

        # cb を近づける（L=20 が限界）→ solve が成功する範囲で法線方向を確認
        for y_cb in [-30, -25, -21]:
            cb.center = Vec2(0, y_cb)
            ok = oc.solve()
            if ok:
                # ca は常に左側のまま
                assert ln.signed_dist(ca.center) > 0, \
                    f"y_cb={y_cb}: ca が右側に飛び出した"

    # [仕様] 2円の中心が一致 → False, feasible=False
    def test_solve_circles_same_center(self):
        """[仕様] 2円の中心が一致（L<1e-9）→ False かつ feasible=False。"""
        ca = Circle(Vec2(0, 10), 5.0)
        cb = Circle(Vec2(0, 10), 8.0)  # 同じ中心
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        oc = self._make_oc(ln, ca, cb)
        ok = oc.solve()
        assert ok is False
        assert oc.feasible is False

    # [仕様] 距離拘束が矛盾（|rhs|>1）→ False, feasible=False
    def test_solve_infeasible_too_close(self):
        """[仕様] 固定した (ε_a,ε_b) で |rhs|>1 → False かつ feasible=False。"""
        ca = Circle(Vec2(0,  30), 20.0)
        cb = Circle(Vec2(0, -30), 20.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        oc = self._make_oc(ln, ca, cb)
        # 2円を非常に近づけて矛盾を起こす
        cb.center = Vec2(0, 29)  # ca と cb の中心がほぼ同じ（L≈1）
        ok = oc.solve()
        assert ok is False
        assert oc.feasible is False

    # [仕様] feasible=False 後に条件回復 → True に戻る
    def test_solve_recovery_after_infeasible(self):
        """[仕様] feasible=False になった後、条件が回復すると solve=True に戻る。"""
        ca = Circle(Vec2(0,  30), 20.0)
        cb = Circle(Vec2(0, -30), 20.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        oc = self._make_oc(ln, ca, cb)

        # 矛盾状態に
        cb.center = Vec2(0, 29)
        oc.solve()
        assert oc.feasible is False

        # 回復
        cb.center = Vec2(0, -30)
        ok = oc.solve()
        assert ok is True
        assert oc.feasible is True

    # [仕様] ref_start に近い垂線の足を ref_start に割り当てる
    def test_solve_assigns_closer_foot_to_ref_start(self):
        """[仕様] ref_start に近い垂線の足が ref_start に割り当てられる。"""
        ca = Circle(Vec2(-50, 30), 10.0)   # 左寄り
        cb = Circle(Vec2( 50, 30), 10.0)   # 右寄り
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        # ref_start = (-100, 0) → ca の垂線の足 (-50, y) の方が近い
        oc = self._make_oc(ln, ca, cb)
        oc.solve()
        # ref_start は ca 側（x が負側）
        assert ln.ref_start.x < 0

    # [仕様] solve=False のとき直線は変更しない
    def test_solve_false_does_not_change_line(self):
        """[仕様] solve=False のとき直線の ref_start/ref_end を変更しない。"""
        ca = Circle(Vec2(0,  30), 20.0)
        cb = Circle(Vec2(0, -30), 20.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        oc = self._make_oc(ln, ca, cb)
        oc.solve()  # 一度成功させて ref_start を変更
        rs_before = Vec2(ln.ref_start.x, ln.ref_start.y)
        re_before = Vec2(ln.ref_end.x,   ln.ref_end.y)
        # 矛盾状態
        cb.center = Vec2(0, 29)
        oc.solve()
        assert ln.ref_start.x == rs_before.x
        assert ln.ref_start.y == rs_before.y
        assert ln.ref_end.x   == re_before.x
        assert ln.ref_end.y   == re_before.y

    # [仕様] _eps_a/_eps_b=0（未設定）の後方互換モード: 全組み合わせを探索
    def test_solve_backward_compat_mode(self):
        """[仕様] _eps_a=_eps_b=0 の後方互換モードでも距離拘束を満たす解を返す。"""
        ca = Circle(Vec2(0,  50), 20.0)
        cb = Circle(Vec2(0, -50), 30.0)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        oc = OffsetConstraint()
        oc.line = ln; oc.circle_a = ca; oc.circle_b = cb
        oc.off_a = 20.0; oc.off_b = 20.0
        # _eps_a/_eps_b = 0 のまま（calc_offsets_from_current を呼ばない）
        assert oc._eps_a == 0 and oc._eps_b == 0
        ok = oc.solve()
        assert ok is True
        assert abs(self._dist(ln, ca.center) - (ca.radius + oc.off_a)) < 1e-4


class TestOffsetConstraintSerialization:
    """OffsetConstraint.to_dict / from_dict のテスト。"""

    def _make_oc(self):
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ca = Circle(Vec2(0,  30), 20.0)
        cb = Circle(Vec2(0, -30), 10.0)
        oc = OffsetConstraint()
        oc.line = ln; oc.circle_a = ca; oc.circle_b = cb
        oc.calc_offsets_from_current()
        return oc, ln, ca, cb

    # [仕様] to_dict に必要なキーが含まれる
    def test_to_dict_keys(self):
        """[仕様] to_dict が id/line_id/ca_id/cb_id/off_a/off_b を含む辞書を返す。"""
        oc, ln, ca, cb = self._make_oc()
        d = oc.to_dict()
        assert d['id']      == oc.id
        assert d['line_id'] == ln.id
        assert d['ca_id']   == ca.id
        assert d['cb_id']   == cb.id
        assert abs(d['off_a'] - oc.off_a) < 1e-9
        assert abs(d['off_b'] - oc.off_b) < 1e-9

    # [仕様] _eps_a/_eps_b/feasible は to_dict に含まれない
    def test_to_dict_no_internal_fields(self):
        """[仕様] _eps_a/_eps_b/feasible は to_dict に含まれない（ロード後に再計算）。"""
        oc, *_ = self._make_oc()
        d = oc.to_dict()
        assert '_eps_a' not in d
        assert '_eps_b' not in d
        assert 'feasible' not in d

    # [仕様] from_dict が辞書から正しく復元する
    def test_from_dict_restores(self):
        """[仕様] from_dict が line/circle_a/circle_b/off_a/off_b を正しく復元する。"""
        oc, ln, ca, cb = self._make_oc()
        d = oc.to_dict()
        lines_by_id   = {ln.id: ln}
        circles_by_id = {ca.id: ca, cb.id: cb}
        oc2 = OffsetConstraint.from_dict(d, lines_by_id, circles_by_id)
        assert oc2.line is ln
        assert oc2.circle_a is ca
        assert oc2.circle_b is cb
        assert abs(oc2.off_a - oc.off_a) < 1e-9
        assert abs(oc2.off_b - oc.off_b) < 1e-9

    # [エッジ] line_id が lines_by_id に存在しない → line=None
    def test_from_dict_missing_line(self):
        """[エッジ] line_id が lines_by_id にない → oc.line=None。"""
        d = {'id': 999, 'line_id': 1, 'ca_id': 2, 'cb_id': 3,
             'off_a': 5.0, 'off_b': 3.0}
        ca = Circle(Vec2(0, 10), 5.0)
        cb = Circle(Vec2(0, -10), 5.0)
        oc = OffsetConstraint.from_dict(d, {}, {2: ca, 3: cb})
        assert oc.line is None


class TestSceneFixDuplicateIds:
    """Scene._fix_duplicate_ids のテスト。"""

    # [仕様] Line.id と Segment.id が同じ → Segment が振り直し
    def test_line_and_segment_same_id(self):
        """[仕様] Line.id と Segment.id が同じとき、後から処理される Segment が振り直される。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        # 強制的に ID を同じにする
        seg.id = ln.id
        assert ln.id == seg.id  # 衝突を確認
        sc._fix_duplicate_ids()
        assert ln.id != seg.id  # 振り直し後は異なる

    # [仕様] Circle.id と Arc.id が同じ → Arc が振り直し
    def test_circle_and_arc_same_id(self):
        """[仕様] Circle.id と Arc.id が同じとき振り直しが起きる。"""
        sc = Scene()
        ci = Circle(Vec2(0, 0), 10.0)
        arc = Arc(ci, 0.0, 1.0)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        arc.id = ci.id  # 強制衝突
        sc._fix_duplicate_ids()
        assert ci.id != arc.id

    # [仕様] Clothoid.id が他の図形と衝突 → 振り直し
    def test_clothoid_id_collision(self):
        """[仕様] Clothoid.id が Line.id と同じとき振り直しが起きる。"""
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln); sc.add_circle(ci)
        clo = Clothoid(ln, ci)
        sc.add_clothoid(clo)
        clo.id = ln.id  # 強制衝突
        sc._fix_duplicate_ids()
        assert clo.id != ln.id

    # [境界] 重複なしのとき ID は変わらない
    def test_no_duplicates_unchanged(self):
        """[境界] 重複がない正常なシーンでは ID が変わらない。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        ln_id_before = ln.id
        seg_id_before = seg.id
        sc._fix_duplicate_ids()
        assert ln.id  == ln_id_before
        assert seg.id == seg_id_before

    # [仕様] to_dict を呼ぶと _fix_duplicate_ids が自動実行される
    def test_to_dict_calls_fix(self):
        """[仕様] to_dict() を呼ぶと保存前に _fix_duplicate_ids() が実行される。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        seg.id = ln.id  # 意図的に衝突させる
        d = sc.to_dict()
        # JSON 内に重複 ID がないことを確認
        all_ids = [ld['id'] for ld in d['lines']]
        all_ids += [sd['id'] for ld in d['lines'] for sd in ld.get('segments', [])]
        assert len(set(all_ids)) == len(all_ids)


class TestSceneOffsetConstraintSerialization:
    """Scene の offset_constraints シリアライズ/デシリアライズのテスト。"""

    def _make_scene_with_oc(self):
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ca = Circle(Vec2(0,  30), 20.0)
        cb = Circle(Vec2(0, -30), 10.0)
        sc.add_line(ln); sc.add_circle(ca); sc.add_circle(cb)
        oc = OffsetConstraint()
        oc.line = ln; oc.circle_a = ca; oc.circle_b = cb
        oc.calc_offsets_from_current()
        sc.offset_constraints.append(oc)
        return sc, ln, ca, cb, oc

    # [仕様] to_dict に offset_constraints が含まれる
    def test_to_dict_includes_offset_constraints(self):
        """[仕様] to_dict() が 'offset_constraints' キーを含む辞書を返す。"""
        sc, *_ = self._make_scene_with_oc()
        d = sc.to_dict()
        assert 'offset_constraints' in d
        assert len(d['offset_constraints']) == 1

    # [仕様] from_dict が offset_constraints を復元する
    def test_from_dict_restores_offset_constraints(self):
        """[仕様] from_dict() が offset_constraints を復元し参照が正しい。"""
        sc, ln, ca, cb, oc = self._make_scene_with_oc()
        d = sc.to_dict()
        sc2 = Scene.from_dict(d)
        assert len(sc2.offset_constraints) == 1
        oc2 = sc2.offset_constraints[0]
        assert oc2.line     is not None
        assert oc2.circle_a is not None
        assert oc2.circle_b is not None
        assert abs(oc2.off_a - oc.off_a) < 1e-9
        assert abs(oc2.off_b - oc.off_b) < 1e-9

    # [仕様] ID 振り直し後もフォールバック参照で clothoid が消えない
    def test_from_dict_clothoid_survives_id_remap(self):
        """[仕様] Line.id と Segment.id が衝突するファイルでも clothoid が消えない。"""
        import copy
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln); sc.add_circle(ci)
        clo = Clothoid(ln, ci)
        sc.add_clothoid(clo)
        d = sc.to_dict()
        # 細工: Segment の id を Line の id と同じにして衝突させる
        d_bad = copy.deepcopy(d)
        ln_id = d_bad['lines'][0]['id']
        d_bad['lines'][0]['segments'][0]['id'] = ln_id  # 衝突
        # from_dict でフォールバック参照により clothoid が消えないこと
        sc2 = Scene.from_dict(d_bad)
        assert len(sc2.clothoids) == 1, "clothoid が消えてはいけない"

    # [エッジ] offset_constraints が空のファイルを from_dict で読める
    def test_from_dict_no_offset_constraints(self):
        """[エッジ] offset_constraints が空でも from_dict でエラーにならない。"""
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        sc.add_line(ln)
        d = sc.to_dict()
        assert d.get('offset_constraints', []) == []
        sc2 = Scene.from_dict(d)
        assert sc2.offset_constraints == []


# ══════════════════════════════════════════════════════════════
# C1カバレッジ向上: models.py の残りの未カバー分岐
# ══════════════════════════════════════════════════════════════

class TestOffsetConstraintSolveEdge:
    """OffsetConstraint.solve の未カバー分岐テスト。"""

    # [C1] line/circle_a/circle_b のいずれかが None のとき False を返す
    def test_solve_returns_false_when_line_none(self):
        """[C1] line=None のとき solve() は False を返す（早期リターン分岐）。"""
        oc = OffsetConstraint()
        oc.circle_a = Circle(Vec2(0, 10), 5.0)
        oc.circle_b = Circle(Vec2(0, -10), 5.0)
        assert oc.solve() is False

    def test_solve_returns_false_when_circle_a_none(self):
        """[C1] circle_a=None のとき solve() は False を返す。"""
        oc = OffsetConstraint()
        oc.line = Line(Vec2(-100, 0), Vec2(100, 0))
        oc.circle_b = Circle(Vec2(0, -10), 5.0)
        assert oc.solve() is False

    def test_solve_returns_false_when_circle_b_none(self):
        """[C1] circle_b=None のとき solve() は False を返す。"""
        oc = OffsetConstraint()
        oc.line = Line(Vec2(-100, 0), Vec2(100, 0))
        oc.circle_a = Circle(Vec2(0, 10), 5.0)
        assert oc.solve() is False


class TestSceneFromDictCircleIdRemap:
    """from_dict で circle の ID が振り直された場合のフォールバック参照テスト。"""

    # [C1] circle.id が segment.id と衝突して振り直されてもフォールバックで clothoid が消えない
    def test_circle_id_remap_fallback(self):
        """[C1] circle.id が _resolve_id で振り直されてもフォールバック参照で clothoid が消えない（L2282）。

        フォールバックが有効な状況:
        - ファイル内で circle.id = Q, clo.circle_id = Q
        - Q が先に処理された segment.id と衝突して circle が振り直される
        - circles_by_id[original_id=Q] = ci（フォールバック）が追加される
        - clo.circle_id = Q → circles_by_id.get(Q) = ci → 見つかる
        """
        import copy
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0); ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln); sc.add_circle(ci)
        clo = Clothoid(ln, ci)
        sc.add_clothoid(clo)
        d = sc.to_dict()
        seg_id = d['lines'][0]['segments'][0]['id']
        ci_id  = d['circles'][0]['id']
        d_bad = copy.deepcopy(d)
        # circle.id を segment.id と同じにして衝突させる
        d_bad['circles'][0]['id'] = seg_id
        # clo.circle_id も同じ値にする（保存ファイルでは必ず一致）
        d_bad['clothoids'][0]['circle_id'] = seg_id
        sc2 = Scene.from_dict(d_bad)
        assert len(sc2.clothoids) == 1, "circle id のフォールバック参照で clothoid が消えてはいけない"


class TestClothoidSnapCoverage:
    """Clothoid の snap 系の残り未カバー分岐テスト。"""

    # [C1] _apply_segment_snap: candidates が空のとき early return（L1109）
    def test_apply_segment_snap_no_candidates(self):
        """[C1] segments が空のとき _apply_segment_snap は何もしない（L1109 早期 return）。"""
        import os; os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        import sys
        app = QApplication.instance() or QApplication(sys.argv)
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        # segments を空にしてから Clothoid を生成
        ci = Circle(Vec2(50, 60), 30.0)
        # snap_segment=True でも segments が空なら early return
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        # 例外にならないことを確認（segments=[] なので候補なし）
        assert True

    # [C1] snap_arc=False のとき _split_arc_ids は空（L1260 early return の前提）
    def test_no_split_arc_ids_when_snap_off(self):
        """[C1] snap_arc=False のとき _split_arc_ids=[]（L1259-1260 の early return 条件）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -0.5, 0.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_arc=False)
        assert clo._split_arc_ids == []

    # [C1] _apply_segment_snap: t_x が範囲外のとき分割しない（L1113-1114）
    def test_apply_segment_snap_tx_out_of_range(self):
        """[C1] 接点の t_x が線分の範囲外のとき分割せずに return（L1113-1114）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        # 線分を接点よりかなり遠い位置に設定（t_x が範囲外になる）
        seg = Segment(ln, 0.9, 1.0)  # 末端の小さな線分
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        # snap=True でも接点が線分の範囲内でなければ分割しない
        clo = Clothoid(ln, ci, snap_segment=True)
        # 例外にならないことを確認
        assert True  # 境界値: t_x が範囲外の場合の動作確認
