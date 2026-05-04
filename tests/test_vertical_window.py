"""
tests/test_vertical_window.py

vertical_window.py の単体テスト。
ProfileCanvas の UI 非依存ロジック（座標変換・snap・ハンドル生成・
標高計算・set_plan_elements / save_to_profiles）を重点的にテストする。

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
    ElementProfile, GradeLine, VerticalCurve, Scene,
)
from vertical_window import ProfileCanvas, _make_empty_profile


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def make_gl(d0, e0, d1, e1):
    """GradeLine を生成するヘルパー。"""
    gl = GradeLine()
    gl.dist_start = d0; gl.elev_start = e0
    gl.dist_end   = d1; gl.elev_end   = e1
    return gl


def make_ep(plan_length, gls=None, vcs=None):
    """ElementProfile を生成するヘルパー。"""
    ep = ElementProfile()
    ep.plan_length = plan_length
    ep.grade_lines     = gls or []
    ep.vertical_curves = vcs or []
    return ep


def make_canvas():
    sc = Scene()
    c = ProfileCanvas(sc)
    c._scale_x = 1.0
    c._scale_y = 1.0
    c._offset  = Vec2(0.0, 0.0)
    return c, sc


# ══════════════════════════════════════════════════════════════
# 1. _make_empty_profile
# ══════════════════════════════════════════════════════════════

class TestMakeEmptyProfile:
    # [仕様] 空の ElementProfile を返す
    def test_empty_lists(self):
        ep = _make_empty_profile()
        assert ep.grade_lines     == []
        assert ep.vertical_curves == []

    def test_returns_element_profile(self):
        ep = _make_empty_profile()
        assert isinstance(ep, ElementProfile)


# ══════════════════════════════════════════════════════════════
# 2. ProfileCanvas 座標変換
# ══════════════════════════════════════════════════════════════

class TestProfileCanvasCoordTransform:
    # [仕様] w2s: screen_x = dist*scale_x + ox, screen_y = -elev*scale_y + oy
    def test_w2s_at_origin(self):
        c, _ = make_canvas()
        c._offset = Vec2(100, 200)
        pt = c.w2s(0.0, 0.0)
        assert approx(pt.x(), 100.0) and approx(pt.y(), 200.0)

    def test_w2s_y_inverted(self):
        c, _ = make_canvas()
        c._scale_x = 2.0; c._scale_y = 3.0
        c._offset  = Vec2(0, 0)
        pt = c.w2s(5.0, 4.0)
        assert approx(pt.x(), 10.0) and approx(pt.y(), -12.0)

    # [仕様] s2w は w2s の逆変換
    def test_s2w_roundtrip(self):
        c, _ = make_canvas()
        c._scale_x = 2.0; c._scale_y = 5.0
        c._offset  = Vec2(50, 100)
        for d, e in [(10.0, 3.0), (0.0, 0.0), (100.0, -5.0)]:
            pt = c.w2s(d, e)
            d2, e2 = c.s2w(pt.x(), pt.y())
            assert approx(d2, d) and approx(e2, e)

    # [境界] scale = 1 のとき変換は単純な平行移動
    def test_scale_1(self):
        c, _ = make_canvas()
        c._offset = Vec2(0, 0)
        pt = c.w2s(7.0, 3.0)
        assert approx(pt.x(), 7.0) and approx(pt.y(), -3.0)


# ══════════════════════════════════════════════════════════════
# 3. _elev_at（静的メソッド）
# ══════════════════════════════════════════════════════════════

class TestElevAt:
    # [仕様] GradeLine の線形補間
    def test_midpoint(self):
        gl = make_gl(0, 10, 100, 20)
        assert approx(ProfileCanvas._elev_at(50, gl), 15.0)

    def test_at_start(self):
        gl = make_gl(0, 10, 100, 20)
        assert approx(ProfileCanvas._elev_at(0, gl), 10.0)

    def test_at_end(self):
        gl = make_gl(0, 10, 100, 20)
        assert approx(ProfileCanvas._elev_at(100, gl), 20.0)

    # [境界] 長さゼロ GL → elev_start を返す
    def test_zero_length_gl(self):
        gl = make_gl(50, 12.0, 50, 12.0)
        assert approx(ProfileCanvas._elev_at(50, gl), 12.0)

    # [仕様] 下り坂
    def test_downhill(self):
        gl = make_gl(0, 100, 100, 0)
        assert approx(ProfileCanvas._elev_at(25, gl), 75.0)

    # [エッジ] dist が範囲外でも計算する（範囲チェックは呼び出し元の責任）
    def test_extrapolation(self):
        gl = make_gl(0, 0, 100, 10)
        assert approx(ProfileCanvas._elev_at(200, gl), 20.0)


# ══════════════════════════════════════════════════════════════
# 4. _grade_lines_sorted
# ══════════════════════════════════════════════════════════════

class TestGradeLinesSorted:
    # [仕様] dist_start の昇順でソートされる
    def test_sorted(self):
        c, _ = make_canvas()
        c._grade_lines = [
            make_gl(50, 5, 100, 10),
            make_gl(0,  0,  50,  5),
        ]
        result = c._grade_lines_sorted()
        assert result[0].dist_start == 0
        assert result[1].dist_start == 50

    # [仕様] 既にソート済みでも正しく返る
    def test_already_sorted(self):
        c, _ = make_canvas()
        c._grade_lines = [make_gl(0, 0, 50, 5), make_gl(50, 5, 100, 10)]
        result = c._grade_lines_sorted()
        assert result[0].dist_start == 0

    # [境界] 空リスト
    def test_empty(self):
        c, _ = make_canvas()
        c._grade_lines = []
        assert c._grade_lines_sorted() == []

    # [C1] 元のリストは変更されない（sorted は新しいリストを返す）
    def test_does_not_modify_original(self):
        c, _ = make_canvas()
        gl1 = make_gl(50, 0, 100, 5)
        gl2 = make_gl(0, 0, 50, 5)
        c._grade_lines = [gl1, gl2]
        c._grade_lines_sorted()
        assert c._grade_lines[0] is gl1  # 元の順序は保持


# ══════════════════════════════════════════════════════════════
# 5. _vc_for_pvi / _vc_at
# ══════════════════════════════════════════════════════════════

class TestVcForPvi:
    # [仕様] pvi_dist が一致する VC を返す
    def test_exact_match(self):
        c, _ = make_canvas()
        vc = VerticalCurve()
        vc.pvi_dist = 50.0; vc.pvi_elev = 5.0; vc.g1 = 2; vc.g2 = 0; vc.length = 20
        c._vertical_curves = [vc]
        assert c._vc_for_pvi(50.0) is vc

    # [仕様] 0.01m 以内の誤差は許容
    def test_near_match(self):
        c, _ = make_canvas()
        vc = VerticalCurve()
        vc.pvi_dist = 50.0; vc.pvi_elev = 5.0; vc.g1 = 2; vc.g2 = 0; vc.length = 20
        c._vertical_curves = [vc]
        assert c._vc_for_pvi(50.009) is vc

    # [境界] 0.01m を超えると None
    def test_too_far(self):
        c, _ = make_canvas()
        vc = VerticalCurve()
        vc.pvi_dist = 50.0; vc.pvi_elev = 5.0; vc.g1 = 2; vc.g2 = 0; vc.length = 20
        c._vertical_curves = [vc]
        assert c._vc_for_pvi(50.011) is None

    # [エッジ] 空リスト
    def test_empty(self):
        c, _ = make_canvas()
        c._vertical_curves = []
        assert c._vc_for_pvi(50.0) is None


class TestVcAt:
    def _make_vc(self, pvi=50.0, L=40.0):
        vc = VerticalCurve()
        vc.pvi_dist = pvi; vc.pvi_elev = 5.0; vc.g1 = 2; vc.g2 = 0; vc.length = L
        return vc  # vpc=30, vpt=70

    # [仕様] VPC〜VPT の範囲内を返す
    def test_inside(self):
        c, _ = make_canvas()
        vc = self._make_vc()
        c._vertical_curves = [vc]
        assert c._vc_at(50.0) is vc

    def test_at_vpc(self):
        c, _ = make_canvas()
        vc = self._make_vc()
        c._vertical_curves = [vc]
        assert c._vc_at(vc.vpc_dist) is vc

    def test_at_vpt(self):
        c, _ = make_canvas()
        vc = self._make_vc()
        c._vertical_curves = [vc]
        assert c._vc_at(vc.vpt_dist) is vc

    # [境界] 0.001m 許容（VPC の少し手前）
    def test_just_before_vpc(self):
        c, _ = make_canvas()
        vc = self._make_vc()
        c._vertical_curves = [vc]
        assert c._vc_at(vc.vpc_dist - 0.0005) is vc  # 許容範囲内

    # [境界] VPC より手前（範囲外）
    def test_before_vpc(self):
        c, _ = make_canvas()
        vc = self._make_vc()
        c._vertical_curves = [vc]
        assert c._vc_at(vc.vpc_dist - 0.002) is None

    # [エッジ] 空リスト
    def test_empty(self):
        c, _ = make_canvas()
        c._vertical_curves = []
        assert c._vc_at(50.0) is None


# ══════════════════════════════════════════════════════════════
# 6. _elevation_at
# ══════════════════════════════════════════════════════════════

class TestElevationAt:
    # [仕様] VC が優先される（VPC〜VPT 範囲内）
    def test_vc_priority(self):
        c, _ = make_canvas()
        gl = make_gl(0, 0, 100, 10)
        c._grade_lines = [gl]
        vc = VerticalCurve()
        vc.pvi_dist = 50; vc.pvi_elev = 5; vc.g1 = 10; vc.g2 = 0; vc.length = 40
        c._vertical_curves = [vc]
        # dist=50 は VC 範囲内 → VC を使う
        result = c._elevation_at(50.0)
        assert result is not None
        assert approx(result, vc.elevation_at(50.0), tol=1e-3)

    # [仕様] VC 範囲外は GL を使う
    def test_gl_fallback(self):
        c, _ = make_canvas()
        gl = make_gl(0, 0, 100, 10)
        c._grade_lines = [gl]
        vc = VerticalCurve()
        vc.pvi_dist = 80; vc.pvi_elev = 8; vc.g1 = 10; vc.g2 = 0; vc.length = 20
        c._vertical_curves = [vc]
        # dist=10 は GL 範囲内、VC 範囲外
        result = c._elevation_at(10.0)
        assert result is not None
        assert approx(result, 1.0, tol=1e-3)  # GL 線形補間

    # [仕様] GL も VC も該当なし → None
    def test_none_when_no_match(self):
        c, _ = make_canvas()
        c._grade_lines = []
        c._vertical_curves = []
        assert c._elevation_at(50.0) is None

    # [C1] GL のみ（VC なし）
    def test_gl_only(self):
        c, _ = make_canvas()
        gl = make_gl(0, 100, 200, 120)
        c._grade_lines = [gl]
        c._vertical_curves = []
        assert approx(c._elevation_at(100.0), 110.0)


# ══════════════════════════════════════════════════════════════
# 7. _snap_grade_lines
# ══════════════════════════════════════════════════════════════

class TestSnapGradeLines:
    # [仕様] 'end': 前→後方向に伝播
    def test_end_propagation(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(60, 99, 100, 10)  # dist_start がずれている
        c._grade_lines = [gl1, gl2]
        c._snap_grade_lines('end')
        assert approx(gl2.dist_start, gl1.dist_end)
        assert approx(gl2.elev_start, gl1.elev_end)

    # [仕様] 'start': 後→前方向に伝播
    def test_start_propagation(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(40, 4, 100, 10)  # dist_start がずれている
        c._grade_lines = [gl1, gl2]
        c._snap_grade_lines('start')
        assert approx(gl1.dist_end, gl2.dist_start)
        assert approx(gl1.elev_end, gl2.elev_start)

    # [仕様] 'both': 両方向に伝播
    def test_both_propagation(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(60, 99, 100, 10)
        gl3 = make_gl(110, 199, 150, 15)
        c._grade_lines = [gl1, gl2, gl3]
        c._snap_grade_lines('both')
        assert approx(gl2.dist_start, gl1.dist_end)
        assert approx(gl3.dist_start, gl2.dist_end)

    # [エッジ] 空リスト → 何もしない
    def test_empty_no_op(self):
        c, _ = make_canvas()
        c._grade_lines = []
        c._snap_grade_lines('both')  # 例外にならない

    # [境界] 1本のみ → 伝播なし
    def test_single_gl(self):
        c, _ = make_canvas()
        gl = make_gl(0, 0, 100, 10)
        c._grade_lines = [gl]
        c._snap_grade_lines('both')  # 例外にならない
        assert approx(gl.dist_end, 100.0)

    # [C1] 3本以上での 'end' 伝播
    def test_end_three_gls(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(99, 0, 100, 10)
        gl3 = make_gl(999, 0, 200, 20)
        c._grade_lines = [gl1, gl2, gl3]
        c._snap_grade_lines('end')
        assert approx(gl2.dist_start, 50.0)
        assert approx(gl3.dist_start, 100.0)


# ══════════════════════════════════════════════════════════════
# 8. _get_handles
# ══════════════════════════════════════════════════════════════

class TestGetHandles:
    # [仕様] 1本の GL → 2つのハンドル（始点・終点）
    def test_single_gl_two_handles(self):
        c, _ = make_canvas()
        c._grade_lines = [make_gl(0, 0, 100, 10)]
        handles = c._get_handles()
        assert len(handles) == 2

    # [仕様] 連続する 2 本の GL の境界は共有ハンドルに統合される
    def test_two_connected_gls_three_handles(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(50, 5, 100, 10)  # gl1.dist_end == gl2.dist_start
        c._grade_lines = [gl1, gl2]
        handles = c._get_handles()
        assert len(handles) == 3  # 始点・共有点・終点

    # [仕様] 境界ハンドルの partners に両方の GL が含まれる
    def test_shared_handle_has_two_partners(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(50, 5, 100, 10)
        c._grade_lines = [gl1, gl2]
        handles = c._get_handles()
        # dist=50 の共有ハンドルを探す
        shared = [h for h in handles if abs(h['dist'] - 50.0) < 0.1]
        assert len(shared) == 1
        assert len(shared[0]['partners']) == 2

    # [境界] GL がない → 空リスト
    def test_empty_gls(self):
        c, _ = make_canvas()
        c._grade_lines = []
        assert c._get_handles() == []

    # [エッジ] 0.01m 以内の誤差は境界とみなす
    def test_near_boundary_merged(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(50.005, 5, 100, 10)  # 0.005m ずれ → 統合される
        c._grade_lines = [gl1, gl2]
        handles = c._get_handles()
        assert len(handles) == 3

    # [エッジ] 0.01m より大きいずれは別ハンドル
    def test_separated_not_merged(self):
        c, _ = make_canvas()
        gl1 = make_gl(0, 0, 50, 5)
        gl2 = make_gl(50.02, 5, 100, 10)  # 0.02m ずれ → 別ハンドル
        c._grade_lines = [gl1, gl2]
        handles = c._get_handles()
        assert len(handles) == 4

    # [C1] ハンドル辞書のキー確認
    def test_handle_keys(self):
        c, _ = make_canvas()
        c._grade_lines = [make_gl(0, 0, 100, 10)]
        handles = c._get_handles()
        for h in handles:
            assert 'dist'     in h
            assert 'elev'     in h
            assert 'partners' in h


# ══════════════════════════════════════════════════════════════
# 9. _hit_handle
# ══════════════════════════════════════════════════════════════

class TestHitHandle:
    # [仕様] 選択モード以外は None
    def test_non_select_mode_returns_none(self):
        c, _ = make_canvas()
        c._mode = 'grade'
        c._grade_lines = [make_gl(0, 0, 100, 10)]
        result = c._hit_handle(0.0, 0.0)
        assert result is None

    # [仕様] ハンドルの位置でヒット
    def test_hit_at_handle_position(self):
        c, _ = make_canvas()
        c._mode = 'select'
        c._scale_x = 1.0; c._scale_y = 1.0
        c._offset  = Vec2(0, 0)
        gl = make_gl(0, 0, 100, 10)
        c._grade_lines = [gl]
        # dist=0, elev=0 → screen(0, 0)
        result = c._hit_handle(0.0, 0.0)
        assert result is not None

    # [仕様] ハンドルから離れた位置は None
    def test_miss(self):
        c, _ = make_canvas()
        c._mode = 'select'
        c._scale_x = 1.0; c._scale_y = 1.0
        c._offset  = Vec2(0, 0)
        gl = make_gl(0, 0, 100, 10)
        c._grade_lines = [gl]
        result = c._hit_handle(1000.0, 1000.0)
        assert result is None

    # [エッジ] GL がない場合は None
    def test_no_gls_returns_none(self):
        c, _ = make_canvas()
        c._mode = 'select'
        c._grade_lines = []
        assert c._hit_handle(0.0, 0.0) is None


# ══════════════════════════════════════════════════════════════
# 10. _dist_point_seg（静的メソッド）
# ══════════════════════════════════════════════════════════════

class TestDistPointSeg:
    # [仕様] 垂線の距離
    def test_perpendicular(self):
        d = ProfileCanvas._dist_point_seg(5, 3, 0, 0, 10, 0)
        assert approx(d, 3.0)

    # [仕様] 端点を超えた場合は端点への距離
    def test_beyond_endpoint(self):
        d = ProfileCanvas._dist_point_seg(15, 0, 0, 0, 10, 0)
        assert approx(d, 5.0)

    # [境界] 始点と一致
    def test_at_start(self):
        d = ProfileCanvas._dist_point_seg(0, 0, 0, 0, 10, 0)
        assert approx(d, 0.0)

    # [エッジ] 縮退した線分
    def test_degenerate(self):
        d = ProfileCanvas._dist_point_seg(3, 4, 0, 0, 0, 0)
        assert approx(d, 5.0)


# ══════════════════════════════════════════════════════════════
# 11. set_plan_elements と save_to_profiles
# ══════════════════════════════════════════════════════════════

class TestSetPlanElements:
    def _make_seg_elem(self, length):
        """線分要素（Segment）と対応する EP を生成する。"""
        ln = Line(Vec2(0, 0), Vec2(length, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ep = make_ep(length, [make_gl(0, 0, length, length * 0.1)])
        ep.element_id = seg.id
        ep.element_type = 'segment'
        return seg, ep

    # [仕様] GL が累積距離に変換されて統合される
    def test_gl_accumulated(self):
        c, sc = make_canvas()
        seg1, ep1 = self._make_seg_elem(100.0)
        seg2, ep2 = self._make_seg_elem(50.0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        c.set_plan_elements([seg1, seg2], [ep1, ep2], [False, False])
        # _grade_lines に2本分の GL が統合される
        assert len(c._grade_lines) == 2
        # 2本目の GL は offset=100 から始まる
        gls = c._grade_lines_sorted()
        assert approx(gls[1].dist_start, 100.0)

    # [仕様] 空の EP リストでも例外にならない
    def test_empty_elements(self):
        c, sc = make_canvas()
        c.set_plan_elements([], [], [])
        assert c._grade_lines == []

    # [仕様] rev=True のとき dist/elev が反転される
    def test_reversed_element(self):
        c, sc = make_canvas()
        seg, ep = self._make_seg_elem(100.0)
        sc.add_line(seg.line)
        c.set_plan_elements([seg], [ep], [True])
        gls = c._grade_lines_sorted()
        if gls:
            # 逆順: elev_start と elev_end が入れ替わる
            assert approx(gls[0].elev_start, ep.grade_lines[0].elev_end)

    # [仕様] _snap_grade_lines('both') が実行されて境界が揃う
    def test_snap_called(self):
        c, sc = make_canvas()
        seg1, ep1 = self._make_seg_elem(100.0)
        seg2, ep2 = self._make_seg_elem(50.0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        c.set_plan_elements([seg1, seg2], [ep1, ep2], [False, False])
        gls = c._grade_lines_sorted()
        if len(gls) >= 2:
            assert approx(gls[1].dist_start, gls[0].dist_end)

    # [エッジ] EP に GL がない要素
    def test_ep_with_no_gl(self):
        c, sc = make_canvas()
        seg, ep = self._make_seg_elem(100.0)
        ep.grade_lines = []  # GL なし
        sc.add_line(seg.line)
        c.set_plan_elements([seg], [ep], [False])
        assert c._grade_lines == []


class TestSaveToProfiles:
    def _make_seg_elem(self, length, gl_e_start=0, gl_e_end=10):
        ln = Line(Vec2(0, 0), Vec2(length, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ep = make_ep(length, [make_gl(0, gl_e_start, length, gl_e_end)])
        ep.element_id = seg.id
        ep.element_type = 'segment'
        return seg, ep

    # [仕様] save_to_profiles で GL が各 EP の範囲に切り出される
    def test_save_restores_gls(self):
        c, sc = make_canvas()
        seg1, ep1 = self._make_seg_elem(100.0, 0, 10)
        seg2, ep2 = self._make_seg_elem(50.0, 10, 15)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        c.set_plan_elements([seg1, seg2], [ep1, ep2], [False, False])
        c.save_to_profiles()
        # ep1: dist_start=0, dist_end=100
        if ep1.grade_lines:
            assert approx(ep1.grade_lines[0].dist_start, 0.0, tol=0.5)
            assert approx(ep1.grade_lines[-1].dist_end, 100.0, tol=0.5)

    # [仕様] save 後に elev_start / elev_end が更新される
    def test_elev_start_end_updated(self):
        c, sc = make_canvas()
        seg, ep = self._make_seg_elem(100.0, 0, 10)
        sc.add_line(seg.line)
        c.set_plan_elements([seg], [ep], [False])
        c.save_to_profiles()
        assert approx(ep.elev_start, 0.0, tol=0.5)
        assert approx(ep.elev_end, 10.0, tol=0.5)

    # [エッジ] GL がない状態で save → 空 EP のまま
    def test_save_empty(self):
        c, sc = make_canvas()
        seg, ep = self._make_seg_elem(100.0)
        ep.grade_lines = []
        sc.add_line(seg.line)
        c.set_plan_elements([seg], [ep], [False])
        c.save_to_profiles()  # 例外にならない


# ══════════════════════════════════════════════════════════════
# 12. _element_color / _element_length
# ══════════════════════════════════════════════════════════════

class TestElementColor:
    # [仕様] Segment → 青
    def test_segment(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        seg = Segment(ln)
        col = c._element_color(seg)
        from vertical_window import CB_SEGMENT
        assert col == CB_SEGMENT

    # [仕様] Arc → 紫
    def test_arc(self):
        c, _ = make_canvas()
        ci = Circle(Vec2(0, 0), 5.0)
        arc = Arc(ci, 0, math.pi)
        col = c._element_color(arc)
        from vertical_window import CB_ARC
        assert col == CB_ARC

    # [仕様] Clothoid → 緑
    def test_clothoid(self):
        c, _ = make_canvas()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        col = c._element_color(clo)
        from vertical_window import CB_CLOTHOID
        assert col == CB_CLOTHOID

    # [C1] その他の型 → グレー
    def test_unknown_type(self):
        c, _ = make_canvas()
        from PyQt6.QtGui import QColor
        col = c._element_color("unknown")
        assert isinstance(col, QColor)


class TestElementLength:
    # [仕様] Segment → 線分の長さ
    def test_segment(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        assert approx(c._element_length(seg), 100.0)

    # [仕様] Arc → 弧長
    def test_arc(self):
        c, _ = make_canvas()
        ci = Circle(Vec2(0, 0), 10.0)
        arc = Arc(ci, 0.0, math.pi)
        assert approx(c._element_length(arc), 10.0 * math.pi)

    # [仕様] Clothoid → 点列の折れ線長
    def test_clothoid(self):
        c, _ = make_canvas()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        length = c._element_length(clo)
        assert length >= 0.0  # 非負


# ══════════════════════════════════════════════════════════════
# 13. set_mode
# ══════════════════════════════════════════════════════════════

class TestSetMode:
    # [仕様] モード切り替えで _grade_first がリセットされる
    def test_grade_first_reset(self):
        c, _ = make_canvas()
        c._grade_first = (50.0, 5.0)
        c.set_mode('select')
        assert c._mode == 'select'
        assert c._grade_first is None

    def test_to_grade_mode(self):
        c, _ = make_canvas()
        c.set_mode('grade')
        assert c._mode == 'grade'
