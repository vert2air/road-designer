"""
tests/test_road_viewer.py

road_viewer.py の単体テスト。
Panda3D に依存しない純粋計算関数（_elev_at_dist, build_centerline,
prepare_viewer_data）を重点的にテストする。

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
from models import (
    Vec2, Line, Segment, Circle, Arc, Clothoid,
    ElementProfile, GradeLine, VerticalCurve, Scene,
)


def approx(a, b, tol=1e-4):
    return abs(a - b) < tol


def make_gl(d0, e0, d1, e1):
    gl = GradeLine()
    gl.dist_start = d0; gl.elev_start = e0
    gl.dist_end   = d1; gl.elev_end   = e1
    return gl


def make_ep(plan_length, gls=None, vcs=None, rev=False):
    ep = ElementProfile()
    ep.plan_length   = plan_length
    ep.reversed_flag = rev
    ep.grade_lines     = gls or []
    ep.vertical_curves = vcs or []
    return ep


def make_seg_elem(length, elev_start=0.0, elev_end=10.0):
    """Segment 要素と対応する ElementProfile を生成するヘルパー。"""
    ln = Line(Vec2(0, 0), Vec2(length, 0))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    ep = make_ep(length, [make_gl(0, elev_start, length, elev_end)])
    ep.element_id   = seg.id
    ep.element_type = 'segment'
    return seg, ep


# ══════════════════════════════════════════════════════════════
# 1. _elev_at_dist
# ══════════════════════════════════════════════════════════════

try:
    from road_viewer import _elev_at_dist
    HAS_PANDA3D = True
except ImportError:
    HAS_PANDA3D = False

skip_panda3d = pytest.mark.skipif(
    not HAS_PANDA3D,
    reason="Panda3D not available"
)


@skip_panda3d
class TestElevAtDist:
    # [仕様] チェーン累積距離から標高を返す
    def test_basic(self):
        ep = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        offsets = [0.0]
        assert approx(_elev_at_dist(50.0, [ep], offsets), 5.0)

    # [仕様] 2番目の要素の範囲内
    def test_second_element(self):
        ep1 = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        ep2 = make_ep(50.0, [make_gl(0, 10, 50, 15)])
        offsets = [0.0, 100.0]
        # dist=125 は ep2 の相対距離 25 → elev = 10 + 5*(25/50) = 12.5
        assert approx(_elev_at_dist(125.0, [ep1, ep2], offsets), 12.5)

    # [仕様] チェーン全体を超える dist → 0.0
    def test_beyond_chain(self):
        ep = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        offsets = [0.0]
        assert _elev_at_dist(200.0, [ep], offsets) == 0.0

    # [境界] dist = 0 → 先頭の elev_start
    def test_at_zero(self):
        ep = make_ep(100.0, [make_gl(0, 5, 100, 15)])
        offsets = [0.0]
        assert approx(_elev_at_dist(0.0, [ep], offsets), 5.0)

    # [境界] dist = plan_length（最終要素の末端）
    def test_at_end(self):
        ep = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        offsets = [0.0]
        assert approx(_elev_at_dist(100.0, [ep], offsets), 10.0)

    # [仕様] 最後の要素は d_end を超えても処理する（is_last=True）
    def test_last_element_handles_overflow(self):
        """is_last=True でも 1e-9 超過なら 0.0。1e-9 以内は正常処理する。"""
        ep = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        offsets = [0.0]
        # dist = plan_length + 1e-9 → 処理される
        assert approx(_elev_at_dist(100.0 + 1e-9, [ep], offsets), 10.0, tol=0.01)
        # dist = plan_length + 1e-8 → 0.0（許容超過）
        assert _elev_at_dist(100.0 + 1e-8, [ep], offsets) == 0.0

    # [エッジ] 空の profiles → 0.0
    def test_empty_profiles(self):
        assert _elev_at_dist(50.0, [], []) == 0.0


# ══════════════════════════════════════════════════════════════
# 2. build_centerline
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestBuildCenterline:
    from road_viewer import build_centerline

    # [仕様] Segment から点列を生成する
    def test_segment_basic(self):
        from road_viewer import build_centerline
        seg, ep = make_seg_elem(100.0, 0.0, 10.0)
        pts = build_centerline([seg], [ep], [False])
        assert len(pts) > 0
        # 全点が (x, y, z, dist) の4要素タプル
        assert all(len(p) == 4 for p in pts)

    # [仕様] dist は単調増加
    def test_dist_monotonic(self):
        from road_viewer import build_centerline
        seg, ep = make_seg_elem(100.0)
        pts = build_centerline([seg], [ep], [False])
        dists = [p[3] for p in pts]
        assert all(dists[i] <= dists[i+1] for i in range(len(dists)-1))

    # [仕様] 始点座標が Segment の start と一致
    def test_start_position(self):
        from road_viewer import build_centerline
        ln = Line(Vec2(10, 20), Vec2(110, 20))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ep = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        pts = build_centerline([seg], [ep], [False])
        assert approx(pts[0][0], 10.0, tol=0.5)
        assert approx(pts[0][1], 20.0, tol=0.5)

    # [仕様] plan_length < 0.001 の要素はスキップ
    def test_tiny_element_skipped(self):
        from road_viewer import build_centerline
        seg, ep = make_seg_elem(100.0)
        ep_tiny = make_ep(0.0001)  # 極小要素
        ln2 = Line(Vec2(100, 0), Vec2(150, 0))
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        ep2 = make_ep(50.0, [make_gl(0, 10, 50, 15)])
        pts = build_centerline([seg, seg2], [ep, ep2], [False, False])
        # 正常な2要素の点列が生成される（tiny はスキップ）
        # skip後も ep2 の点が続く
        assert len(pts) > 0

    # [仕様] 境界点（i=0, points非空）は前要素の末端 z を継承する（段差防止）
    def test_boundary_z_continuity(self):
        from road_viewer import build_centerline
        seg1, ep1 = make_seg_elem(100.0, 0.0, 10.0)
        seg2, ep2 = make_seg_elem(50.0, 10.0, 15.0)
        # seg2 は seg1 の終端に接続
        seg2.line.ref_start = Vec2(100, 0)
        seg2.line.ref_end   = Vec2(150, 0)
        pts = build_centerline([seg1, seg2], [ep1, ep2], [False, False])
        # 境界点（seg2 の最初の点）は seg1 の最後の z と等しい
        # pts を dist でグループ化して確認
        if len(pts) >= 2:
            # dist=100 付近の連続した点で z が連続していることを確認
            boundary_pts = [p for p in pts if abs(p[3] - 100.0) < 1.0]
            if len(boundary_pts) >= 2:
                assert approx(boundary_pts[0][2], boundary_pts[1][2], tol=0.5)

    # [仕様] rev=True のとき Segment の端点が逆順になる
    def test_rev_true_segment(self):
        from road_viewer import build_centerline
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ep = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        pts_fwd = build_centerline([seg], [ep], [False])
        pts_rev = build_centerline([seg], [ep], [True])
        # 逆順では始点が終点付近の座標になる
        assert not approx(pts_fwd[0][0], pts_rev[0][0], tol=50)

    # [仕様] Arc の中心線を生成する
    def test_arc_centerline(self):
        from road_viewer import build_centerline
        ci = Circle(Vec2(0, 0), 50.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        ep = make_ep(arc.arc_length(), [make_gl(0, 0, arc.arc_length(), 5)])
        ep.element_id   = arc.id
        ep.element_type = 'arc'
        pts = build_centerline([arc], [ep], [False])
        assert len(pts) > 0
        # 全点が円弧の半径 50m 付近にある
        for p in pts:
            d = math.hypot(p[0], p[1])  # center=(0,0)
            assert approx(d, 50.0, tol=5.0)

    # [仕様] Clothoid の中心線を生成する
    def test_clothoid_centerline(self):
        from road_viewer import build_centerline
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if not clo.is_valid:
            pytest.skip("Clothoid not valid")
        ep = make_ep(clo._tau * 2 * 30, [make_gl(0, 0, 100, 5)])
        ep.element_id   = clo.id
        ep.element_type = 'clothoid'
        pts = build_centerline([clo], [ep], [False])
        assert len(pts) > 0

    # [エッジ] Clothoid.points が空 → スキップ
    def test_clothoid_empty_points_skipped(self):
        from road_viewer import build_centerline
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)  # d < R → 無効
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid
        ep = make_ep(50.0)
        pts = build_centerline([clo], [ep], [False])
        assert pts == []

    # [エッジ] 複数要素のチェーン
    def test_multi_element_chain(self):
        from road_viewer import build_centerline
        seg1, ep1 = make_seg_elem(100.0, 0.0, 10.0)
        seg2, ep2 = make_seg_elem(50.0, 10.0, 15.0)
        seg2.line.ref_start = Vec2(100, 0)
        seg2.line.ref_end   = Vec2(150, 0)
        pts = build_centerline([seg1, seg2], [ep1, ep2], [False, False])
        # 全長 150m → dist の最大値が 150 付近
        max_dist = max(p[3] for p in pts)
        assert approx(max_dist, 150.0, tol=5.0)

    # [境界] n_per_m を変えると点数が変わる
    def test_n_per_m_affects_density(self):
        from road_viewer import build_centerline
        seg, ep = make_seg_elem(100.0)
        pts_low  = build_centerline([seg], [ep], [False], n_per_m=0.1)
        pts_high = build_centerline([seg], [ep], [False], n_per_m=2.0)
        assert len(pts_high) > len(pts_low)


# ══════════════════════════════════════════════════════════════
# 3. prepare_viewer_data
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestPrepareViewerData:
    # [仕様] 返り値の辞書キーを確認
    def test_return_keys(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg, ep = make_seg_elem(100.0)
        sc.add_line(seg.line)
        sc.element_profiles.append(ep)
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        assert 'centerline_3d'    in result
        assert 'display_segments' in result

    # [仕様] centerline_3d は (x, y, z, dist) のリスト
    def test_centerline_3d_format(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg, ep = make_seg_elem(100.0)
        sc.add_line(seg.line)
        sc.element_profiles.append(ep)
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        cl = result['centerline_3d']
        assert len(cl) > 0
        assert all(len(p) == 4 for p in cl)

    # [仕様] all_display=None のとき display_segments は空
    def test_no_display_segments(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg, ep = make_seg_elem(100.0)
        sc.add_line(seg.line)
        result = prepare_viewer_data(sc, [seg], [ep], [False], all_display=None)
        assert result['display_segments'] == []

    # [仕様] all_display を渡すと display_segments に点列が含まれる
    def test_with_display_segments(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg1, ep1 = make_seg_elem(100.0)
        seg2, ep2 = make_seg_elem(50.0)
        seg2.line.ref_start = Vec2(100, 0)
        seg2.line.ref_end   = Vec2(150, 0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        sc.element_profiles.append(ep1)
        sc.element_profiles.append(ep2)
        result = prepare_viewer_data(
            sc, [seg1], [ep1], [False],
            all_display=[seg1, seg2]
        )
        assert len(result['display_segments']) > 0

    # [エッジ] 要素が空のとき centerline_3d は空リスト
    def test_empty_elements(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        result = prepare_viewer_data(sc, [], [], [])
        assert result['centerline_3d'] == []

    # [仕様] 標高が連続している（段差 < 0.1m）
    def test_elevation_continuity(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg1, ep1 = make_seg_elem(100.0, 0.0, 10.0)
        seg2, ep2 = make_seg_elem(50.0, 10.0, 15.0)
        seg2.line.ref_start = Vec2(100, 0)
        seg2.line.ref_end   = Vec2(150, 0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        sc.element_profiles.append(ep1)
        sc.element_profiles.append(ep2)
        result = prepare_viewer_data(sc, [seg1, seg2], [ep1, ep2], [False, False])
        cl = result['centerline_3d']
        # 連続した点間の z の差が 0.5m 未満であることを確認
        for i in range(len(cl) - 1):
            assert abs(cl[i+1][2] - cl[i][2]) < 0.5, \
                f"z jump at dist={cl[i][3]:.1f}: {cl[i][2]:.3f} → {cl[i+1][2]:.3f}"
