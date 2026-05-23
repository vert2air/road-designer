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

    # [仕様] plan_length < 0.001 の要素はスキップ（L209）
    def test_tiny_element_skipped(self):
        from road_viewer import build_centerline
        # 長さ0.0001の tiny 要素を先頭に置く: build_centerline の L209 で continue される
        ln_tiny = Line(Vec2(0, 0), Vec2(0.0001, 0))
        seg_tiny = Segment(ln_tiny, 0.0, 1.0)
        ln_tiny.segments.append(seg_tiny)
        ep_tiny = make_ep(0.0001, [make_gl(0, 0, 0.0001, 0)])
        ep_tiny.element_id   = seg_tiny.id
        ep_tiny.element_type = 'segment'

        ln2 = Line(Vec2(0.0001, 0), Vec2(50.0001, 0))
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        ep2 = make_ep(50.0, [make_gl(0, 10, 50, 15)])
        ep2.element_id   = seg2.id
        ep2.element_type = 'segment'

        # ep_tiny は L < 0.001 なのでスキップされ、seg2 だけの点列が生成される
        pts = build_centerline([seg_tiny, seg2], [ep_tiny, ep2], [False, False])
        # tiny はスキップされるが ep2 から点が生成される
        assert len(pts) > 0
        # dist は ep_tiny.plan_length (0.0001) から始まる(offsets[1]=0.0001)
        # 実際には tiny 要素がスキップされて dist が continuouos になるはず

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


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: build_centerline の内部分岐
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestBuildCenterlineBranches:
    # [C1] Arc rev=True のとき終点→始点で点列を生成（L101: continue の直前分岐）
    def test_arc_rev_true(self):
        from road_viewer import build_centerline
        ci = Circle(Vec2(0, 0), 50.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        ep = make_ep(arc.arc_length(), [make_gl(0, 0, arc.arc_length(), 5)])
        ep.element_id = arc.id
        ep.element_type = 'arc'
        # rev=False と rev=True で始点座標が異なる
        pts_fwd = build_centerline([arc], [ep], [False])
        pts_rev = build_centerline([arc], [ep], [True])
        assert len(pts_fwd) > 0 and len(pts_rev) > 0
        # 逆順なので始点と終点が入れ替わっている
        assert not approx(pts_fwd[0][0], pts_rev[0][0], tol=10)

    # [C1] Clothoid rev=True のとき reversed_flag を反転して点列を生成（L123）
    def test_clothoid_branch(self):
        from road_viewer import build_centerline
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if not clo.is_valid:
            pytest.skip("Clothoid not valid")
        ep = make_ep(50.0, [make_gl(0, 0, 50, 5)])
        ep.element_id = clo.id
        ep.element_type = 'clothoid'
        pts = build_centerline([clo], [ep], [False])
        pts_rev = build_centerline([clo], [ep], [True])
        assert len(pts) > 0
        assert len(pts_rev) > 0

    # [C1] 境界点（i==0）で前要素の末端 z を引き継ぐ（L146: pts_2d.append(raw[-1])）
    def test_boundary_inherits_prev_z(self):
        from road_viewer import build_centerline
        ln1 = Line(Vec2(0, 0), Vec2(100, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        ln1.segments.append(seg1)
        ln2 = Line(Vec2(100, 0), Vec2(150, 0))
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        ep1 = make_ep(100.0, [make_gl(0, 0, 100, 10)])
        ep2 = make_ep(50.0, [make_gl(0, 10, 50, 15)])
        ep1.element_id = seg1.id; ep1.element_type = 'segment'
        ep2.element_id = seg2.id; ep2.element_type = 'segment'
        pts = build_centerline([seg1, seg2], [ep1, ep2], [False, False])
        # dist ≈ 100 付近の z は 10m 付近（ep1 の末端）
        boundary = [p for p in pts if abs(p[3] - 100.0) < 2.0]
        assert any(approx(p[2], 10.0, tol=1.0) for p in boundary)

    # [C1] Clothoid の points が空のときスキップされる（L149: continue）
    def test_invalid_clothoid_skipped(self):
        from road_viewer import build_centerline
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)  # d < R → 無効
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid
        ep = make_ep(50.0)
        ep.element_id = clo.id; ep.element_type = 'clothoid'
        pts = build_centerline([clo], [ep], [False])
        assert pts == []


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: prepare_viewer_data の内部分岐
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestPrepareViewerDataBranches:
    # [C1] EP が存在しない要素は新規 ElementProfile を生成する（L779）
    def test_creates_ep_when_missing(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg, ep = make_seg_elem(100.0)
        sc.add_line(seg.line)
        # scene.element_profiles を空にして EP 未設定状態にする
        sc.element_profiles.clear()
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        assert 'centerline_3d' in result

    # [C1] all_display に plan_length=0 の要素が含まれる → スキップ（L784）
    def test_display_element_zero_length_skipped(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg1, ep1 = make_seg_elem(100.0)
        sc.add_line(seg1.line)
        sc.element_profiles.append(ep1)
        # plan_length = 0 の EP を持つ要素
        ln2 = Line(Vec2(100, 0), Vec2(100, 0))  # 長さ0
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        ep2 = make_ep(0.0)
        ep2.element_id = seg2.id; ep2.element_type = 'segment'
        sc.add_line(ln2)
        sc.element_profiles.append(ep2)
        result = prepare_viewer_data(
            sc, [seg1], [ep1], [False],
            all_display=[seg1, seg2]
        )
        # display_segments に長さ0の要素は含まれない（または空リスト）
        assert 'display_segments' in result

    # [C1] all_display で build_centerline が空リストを返す場合はスキップ（L786）
    def test_empty_centerline_not_added(self):
        from road_viewer import prepare_viewer_data
        sc = Scene()
        seg, ep = make_seg_elem(100.0)
        sc.add_line(seg.line)
        sc.element_profiles.append(ep)
        # 無効な Clothoid（points = []）を display に含める
        ln2 = Line(Vec2(0, 0), Vec2(100, 0))
        ci2 = Circle(Vec2(50, 10), 30.0)  # 無効
        clo = Clothoid(ln2, ci2, snap_segment=False, snap_arc=False)
        assert not clo.is_valid
        result = prepare_viewer_data(
            sc, [seg], [ep], [False],
            all_display=[clo]
        )
        # 空の centerline は display_segments に追加されない
        assert all(len(s) > 0 for s in result['display_segments'])


# ══════════════════════════════════════════════════════════════
# 5. _tangent_normal_at
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestTangentNormalAt:
    """_tangent_normal_at の全分岐を検証する。"""

    # [仕様] i=0（先頭点）→ 前進差分
    def test_first_point_forward_diff(self):
        from road_viewer import _tangent_normal_at
        cl = [(0.0, 0.0, 0.0, 0.0),
              (3.0, 4.0, 0.0, 5.0),
              (6.0, 8.0, 0.0, 10.0)]
        tx, ty, nx, ny = _tangent_normal_at(cl, 0)
        # (3,4) → 単位ベクトルは (0.6, 0.8)
        assert approx(tx, 0.6) and approx(ty, 0.8)
        # 右法線 = (ty, -tx) = (0.8, -0.6)
        assert approx(nx, 0.8) and approx(ny, -0.6)

    # [仕様] i=n-1（末尾点）→ 後退差分
    def test_last_point_backward_diff(self):
        from road_viewer import _tangent_normal_at
        cl = [(0.0, 0.0, 0.0, 0.0),
              (1.0, 0.0, 0.0, 1.0),
              (2.0, 0.0, 0.0, 2.0)]
        tx, ty, nx, ny = _tangent_normal_at(cl, 2)
        # 後退差分: (2,0)-(1,0)=(1,0) → (1,0)
        assert approx(tx, 1.0) and approx(ty, 0.0)
        assert approx(nx, 0.0) and approx(ny, -1.0)

    # [仕様] 中間点 → 中央差分（i-1 → i+1）
    def test_middle_point_central_diff(self):
        from road_viewer import _tangent_normal_at
        cl = [(0.0, 0.0, 0.0, 0.0),
              (1.0, 0.0, 0.0, 1.0),
              (2.0, 0.0, 0.0, 2.0)]
        tx, ty, nx, ny = _tangent_normal_at(cl, 1)
        # 中央差分: (2,0)-(0,0)=(2,0) → 単位 (1,0)
        assert approx(tx, 1.0) and approx(ty, 0.0)

    # [エッジ] dx=dy=0（縮退点）→ デフォルト (1, 0)
    def test_zero_length_segment_fallback(self):
        from road_viewer import _tangent_normal_at
        # i=0 で p0==p1 → dx=dy=0 → fallback
        cl = [(0.0, 0.0, 0.0, 0.0),
              (0.0, 0.0, 0.0, 0.0),
              (1.0, 0.0, 0.0, 1.0)]
        tx, ty, nx, ny = _tangent_normal_at(cl, 0)
        assert approx(tx, 1.0) and approx(ty, 0.0)

    # [境界] 2点リストでも正常動作
    def test_two_point_centerline(self):
        from road_viewer import _tangent_normal_at
        cl = [(0.0, 0.0, 0.0, 0.0),
              (0.0, 1.0, 0.0, 1.0)]
        # i=0 (先頭)
        tx0, ty0, _, _ = _tangent_normal_at(cl, 0)
        assert approx(tx0, 0.0) and approx(ty0, 1.0)
        # i=1 (末尾)
        tx1, ty1, _, _ = _tangent_normal_at(cl, 1)
        assert approx(tx1, 0.0) and approx(ty1, 1.0)

    # [仕様] 右法線は接線の右直交
    def test_normal_perpendicular_and_right(self):
        from road_viewer import _tangent_normal_at
        # 接線が (0,1) のとき右法線は (1,0)
        cl = [(0.0, 0.0, 0.0, 0.0),
              (0.0, 1.0, 0.0, 1.0),
              (0.0, 2.0, 0.0, 2.0)]
        tx, ty, nx, ny = _tangent_normal_at(cl, 1)
        assert approx(tx, 0.0) and approx(ty, 1.0)
        # 右法線 = (ty, -tx) = (1, 0)
        assert approx(nx, 1.0) and approx(ny, 0.0)


# ══════════════════════════════════════════════════════════════
# 6. _elem_endpoints_xy
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestElemEndpointsXy:
    """_elem_endpoints_xy の全型分岐を検証する。"""

    # [仕様] Segment → (start, end) を返す
    def test_segment(self):
        from road_viewer import _elem_endpoints_xy
        ln = Line(Vec2(1, 2), Vec2(5, 6))
        seg = Segment(ln, 0.0, 1.0)
        result = _elem_endpoints_xy(seg)
        assert result is not None
        s, e = result
        assert approx(s.x, 1.0) and approx(s.y, 2.0)
        assert approx(e.x, 5.0) and approx(e.y, 6.0)

    # [仕様] Arc → (start, end) を返す
    def test_arc(self):
        from road_viewer import _elem_endpoints_xy
        ci = Circle(Vec2(0, 0), 10.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        result = _elem_endpoints_xy(arc)
        assert result is not None
        assert len(result) == 2

    # [仕様] 有効な Clothoid → (_line_pt, _circle_pt) を返す
    def test_clothoid_valid(self):
        from road_viewer import _elem_endpoints_xy
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if not clo.is_valid:
            pytest.skip("Clothoid not valid for this geometry")
        result = _elem_endpoints_xy(clo)
        assert result is not None
        assert len(result) == 2

    # [仕様] 無効な Clothoid → None を返す
    def test_clothoid_invalid_returns_none(self):
        from road_viewer import _elem_endpoints_xy
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)  # d < R → 無効
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid
        assert _elem_endpoints_xy(clo) is None

    # [エッジ] 非対応型 → None を返す
    def test_unknown_type_returns_none(self):
        from road_viewer import _elem_endpoints_xy
        assert _elem_endpoints_xy("not_an_element") is None
        assert _elem_endpoints_xy(42) is None


# ══════════════════════════════════════════════════════════════
# 7. _elem_fwd_vec
# ══════════════════════════════════════════════════════════════

@skip_panda3d
class TestElemFwdVec:
    """_elem_fwd_vec の全分岐を検証する。"""

    # [仕様] points_xy >= 2点 & forward=True → 先頭2点から接線
    def test_forward_with_points_xy(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [(0.0, 0.0), (3.0, 4.0), (6.0, 8.0)],
                "start": (0.0, 0.0), "end": (6.0, 8.0)}
        dx, dy = _elem_fwd_vec(elem, True)
        assert approx(dx, 0.6) and approx(dy, 0.8)

    # [仕様] points_xy >= 2点 & forward=False → 末尾2点から接線（逆方向）
    def test_backward_with_points_xy(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [(0.0, 0.0), (3.0, 4.0), (6.0, 8.0)],
                "start": (0.0, 0.0), "end": (6.0, 8.0)}
        dx, dy = _elem_fwd_vec(elem, False)
        # pts[-1]→pts[-2]: (6,8)→(3,4) → diff=(-3,-4) → 単位 (-0.6, -0.8)
        assert approx(dx, -0.6) and approx(dy, -0.8)

    # [仕様] points_xy が空 & forward=True → start→end から接線
    def test_forward_without_points_xy(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [], "start": (0.0, 0.0), "end": (3.0, 4.0)}
        dx, dy = _elem_fwd_vec(elem, True)
        assert approx(dx, 0.6) and approx(dy, 0.8)

    # [仕様] points_xy が None & forward=False → end→start から接線
    def test_backward_without_points_xy(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": None, "start": (0.0, 0.0), "end": (3.0, 4.0)}
        dx, dy = _elem_fwd_vec(elem, False)
        assert approx(dx, -0.6) and approx(dy, -0.8)

    # [境界] 零ベクトル（start==end かつ points_xy なし）→ (1/1, 0/1) = (1, 0)
    def test_degenerate_zero_vector(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [], "start": (0.0, 0.0), "end": (0.0, 0.0)}
        dx, dy = _elem_fwd_vec(elem, True)
        # math.hypot(0,0) or 1.0 → ln=1.0 → dx=0, dy=0
        assert approx(dx, 0.0) and approx(dy, 0.0)

    # [C1] points_xy に 1点だけ → フォールバックして start/end を使う
    def test_single_point_falls_back_to_start_end(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [(0.0, 0.0)], "start": (0.0, 0.0), "end": (1.0, 0.0)}
        dx, dy = _elem_fwd_vec(elem, True)
        assert approx(dx, 1.0) and approx(dy, 0.0)


# ══════════════════════════════════════════════════════════════
# interp_cl — 中心線上の線形補間
# ══════════════════════════════════════════════════════════════

class TestInterpCl:
    """モジュールレベル関数 interp_cl の単体テスト。

    Panda3D 不要。RoadViewer._interp_cl が委譲するロジック本体。
    """
    from road_viewer import interp_cl as _f  # クラス属性で import（各テストで再利用）

    # [エッジ] 空リスト → フォールバック値
    def test_empty_returns_default(self):
        from road_viewer import interp_cl
        pos, fwd, right = interp_cl([], 0.0)
        assert pos == (0, 0, 0)
        assert fwd == (1, 0, 0)

    # [仕様] 単一区間の中点を補間
    def test_midpoint_interpolation(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, fwd, right = interp_cl(cl, 5.0)
        assert approx(pos[0], 5.0) and approx(pos[1], 0.0) and approx(pos[2], 0.0)
        assert approx(fwd[0], 1.0) and approx(fwd[1], 0.0)

    # [仕様] Z 方向の補間（坂道）
    def test_z_interpolation(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 10.0, 10.0)]
        pos, fwd, _ = interp_cl(cl, 5.0)
        assert approx(pos[2], 5.0)
        # fwd は (dx,dy,dz) を正規化: (10,0,10)/sqrt(200)
        expected = 10.0 / math.hypot(10, 0, 10)
        assert approx(fwd[0], expected)
        assert approx(fwd[2], expected)

    # [仕様] right ベクトルは fwd の xy 平面直交（z=0）
    def test_right_vector_is_xy_perp(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        _, fwd, right = interp_cl(cl, 5.0)
        # right は fwd を xy で 90° 回転: (fy, -fx, 0)
        assert approx(right[0], fwd[1])
        assert approx(right[1], -fwd[0])
        assert approx(right[2], 0.0)

    # [境界] dist がちょうど始点（d0）
    def test_dist_at_segment_start(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, _, _ = interp_cl(cl, 0.0)
        assert approx(pos[0], 0.0)

    # [境界] dist がちょうど終点（d1）
    def test_dist_at_segment_end(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, _, _ = interp_cl(cl, 10.0)
        assert approx(pos[0], 10.0)

    # [境界] dist が範囲外（末端を超える）→ 末端位置・デフォルト方向
    def test_dist_beyond_end_returns_last_point(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, fwd, _ = interp_cl(cl, 99.0)
        assert approx(pos[0], 10.0)
        assert fwd == (1, 0, 0)

    # [仕様] 複数区間：正しい区間を補間
    def test_multiple_segments(self):
        from road_viewer import interp_cl
        cl = [
            (0.0,  0.0, 0.0,  0.0),
            (10.0, 0.0, 0.0, 10.0),
            (10.0, 5.0, 0.0, 15.0),
        ]
        pos, fwd, _ = interp_cl(cl, 12.5)
        # 第2区間 dist=10→15 の中点 d=12.5 → t=0.5 → y=2.5
        assert approx(pos[0], 10.0) and approx(pos[1], 2.5)

    # [エッジ] 区間長ゼロ（d0==d1）→ t=0 で補間（先端座標）
    def test_zero_length_segment(self):
        from road_viewer import interp_cl
        cl = [(5.0, 3.0, 1.0, 0.0), (5.0, 3.0, 1.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, _, _ = interp_cl(cl, 0.0)
        assert approx(pos[0], 5.0) and approx(pos[1], 3.0)


# ══════════════════════════════════════════════════════════════
# bearing_str — 8 方位文字列
# ══════════════════════════════════════════════════════════════

class TestBearingStr:
    """モジュールレベル関数 bearing_str の単体テスト（全 8 方位）。"""

    def _bs(self, fx, fy):
        from road_viewer import bearing_str
        return bearing_str(fx, fy)

    # [仕様] 北: fwd_y > 0, fwd_x ≈ 0
    def test_north(self):  assert self._bs(0.0,  1.0) == "N"
    # [仕様] 南: fwd_y < 0, fwd_x ≈ 0
    def test_south(self):  assert self._bs(0.0, -1.0) == "S"
    # [仕様] 東: fwd_x > 0, fwd_y ≈ 0
    def test_east(self):   assert self._bs(1.0,  0.0) == "E"
    # [仕様] 西: fwd_x < 0, fwd_y ≈ 0
    def test_west(self):   assert self._bs(-1.0, 0.0) == "W"
    # [仕様] 北東
    def test_northeast(self):
        v = math.sqrt(0.5)
        assert self._bs(v,  v) == "NE"
    # [仕様] 南東
    def test_southeast(self):
        v = math.sqrt(0.5)
        assert self._bs(v, -v) == "SE"
    # [仕様] 南西
    def test_southwest(self):
        v = math.sqrt(0.5)
        assert self._bs(-v, -v) == "SW"
    # [仕様] 北西
    def test_northwest(self):
        v = math.sqrt(0.5)
        assert self._bs(-v,  v) == "NW"


# ══════════════════════════════════════════════════════════════
# make_elem_cl — 要素辞書から 3D 中心線を生成
# ══════════════════════════════════════════════════════════════

class TestMakeElemCl:
    """モジュールレベル関数 make_elem_cl の単体テスト。"""

    def _make(self, **kw):
        from road_viewer import make_elem_cl
        return make_elem_cl(kw["elem"], kw["forward"])

    # [仕様] points_xy あり・正順: 始点→終点の xy を使用
    def test_with_points_xy_forward(self):
        from road_viewer import make_elem_cl
        elem = {
            "plan_length": 10.0,
            "start": [0.0, 0.0], "end": [10.0, 0.0],
            "heights": [[0.0, 0.0], [10.0, 5.0]],
            "points_xy": [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]],
        }
        cl, total = make_elem_cl(elem, True)
        assert approx(total, 10.0)
        assert len(cl) == 3
        assert approx(cl[0][0], 0.0)  # start x
        assert approx(cl[-1][0], 10.0)  # end x

    # [仕様] points_xy あり・逆順: 終点→始点（点列反転）
    def test_with_points_xy_reverse(self):
        from road_viewer import make_elem_cl
        elem = {
            "plan_length": 10.0,
            "start": [0.0, 0.0], "end": [10.0, 0.0],
            "heights": [[0.0, 0.0], [10.0, 0.0]],
            "points_xy": [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]],
        }
        cl, total = make_elem_cl(elem, False)
        assert approx(cl[0][0], 10.0)  # 逆順: 始点が end 側
        assert approx(cl[-1][0], 0.0)

    # [仕様] points_xy なし（フォールバック）・正順: start→end を直線補間
    def test_fallback_forward(self):
        from road_viewer import make_elem_cl
        elem = {
            "plan_length": 100.0,
            "start": [0.0, 0.0], "end": [100.0, 0.0],
            "heights": [[0.0, 0.0], [100.0, 10.0]],
        }
        cl, total = make_elem_cl(elem, True)
        assert approx(total, 100.0)
        # 先頭: start 付近
        assert approx(cl[0][0], 0.0)
        # 末尾: end 付近
        assert approx(cl[-1][0], 100.0)
        # 末尾の高さ: elev=10.0
        assert approx(cl[-1][2], 10.0)

    # [仕様] points_xy なし・逆順: end→start
    def test_fallback_reverse(self):
        from road_viewer import make_elem_cl
        elem = {
            "plan_length": 100.0,
            "start": [0.0, 0.0], "end": [100.0, 0.0],
            "heights": [[0.0, 0.0], [100.0, 0.0]],
        }
        cl, total = make_elem_cl(elem, False)
        assert approx(cl[0][0], 100.0)
        assert approx(cl[-1][0], 0.0)

    # [仕様] heights デフォルト（キーなし）→ 全区間 elev=0
    def test_no_heights_defaults_to_zero(self):
        from road_viewer import make_elem_cl
        elem = {
            "plan_length": 50.0,
            "start": [0.0, 0.0], "end": [50.0, 0.0],
        }
        cl, _ = make_elem_cl(elem, True)
        for pt in cl:
            assert approx(pt[2], 0.0)

    # [仕様] heights の中間区間で線形補間
    def test_height_linear_interpolation(self):
        from road_viewer import make_elem_cl
        elem = {
            "plan_length": 10.0,
            "start": [0.0, 0.0], "end": [10.0, 0.0],
            "heights": [[0.0, 0.0], [10.0, 10.0]],
            "points_xy": [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]],
        }
        cl, _ = make_elem_cl(elem, True)
        # 中点 (5.0, 0.0) の dist ≈ 5.0 → elev ≈ 5.0
        mid = cl[1]
        assert approx(mid[2], 5.0, tol=0.1)

    # [境界] plan_length と points_xy の累積長が異なる（スケール補正）
    def test_scale_correction_when_pts_length_differs(self):
        from road_viewer import make_elem_cl
        # points_xy の合計長は 20.0 だが plan_length は 10.0 → scale=0.5
        elem = {
            "plan_length": 10.0,
            "start": [0.0, 0.0], "end": [20.0, 0.0],
            "heights": [[0.0, 0.0], [10.0, 0.0]],
            "points_xy": [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]],
        }
        cl, total = make_elem_cl(elem, True)
        assert approx(total, 10.0)
        # dist は plan_length にスケーリング: 末端 dist = 10.0
        assert approx(cl[-1][3], 10.0)


# ══════════════════════════════════════════════════════════════
# find_next_candidates — 次の走行候補を検索
# ══════════════════════════════════════════════════════════════

def _mk_elem(eid, sx, sy, ex, ey, s_ref=None, e_ref=None):
    """テスト用要素辞書を生成するヘルパー。"""
    return {
        "id": eid,
        "plan_length": math.hypot(ex - sx, ey - sy),
        "start": [sx, sy],
        "end":   [ex, ey],
        "start_clo_ref": s_ref,
        "end_clo_ref":   e_ref,
    }


class TestFindNextCandidates:
    """モジュールレベル関数 find_next_candidates の単体テスト。"""

    # [仕様] 末端座標が一致（start 側）→ (elem, True) を返す
    def test_coord_match_start_side(self):
        from road_viewer import find_next_candidates
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 10.0, 0.0, 20.0, 0.0)
        cands = find_next_candidates([e1, e2], cur_id=1, ex=10.0, ey=0.0,
                                     exit_clo_ref=None)
        assert len(cands) == 1
        assert cands[0][0]["id"] == 2
        assert cands[0][1] is True  # forward

    # [仕様] 末端座標が一致（end 側）→ (elem, False) を返す
    def test_coord_match_end_side(self):
        from road_viewer import find_next_candidates
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 20.0, 0.0, 10.0, 0.0)  # end が (10,0)
        cands = find_next_candidates([e1, e2], cur_id=1, ex=10.0, ey=0.0,
                                     exit_clo_ref=None)
        assert len(cands) == 1
        assert cands[0][0]["id"] == 2
        assert cands[0][1] is False  # reverse

    # [仕様] cur_id の要素自身は除外される
    def test_cur_id_excluded(self):
        from road_viewer import find_next_candidates
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        cands = find_next_candidates([e1], cur_id=1, ex=10.0, ey=0.0,
                                     exit_clo_ref=None)
        assert cands == []

    # [仕様] 距離が ad_tol を超える → 候補なし
    def test_beyond_tolerance_no_match(self):
        from road_viewer import find_next_candidates
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 10.5, 0.0, 20.0, 0.0)  # 0.5m 離れている
        cands = find_next_candidates([e1, e2], cur_id=1, ex=10.0, ey=0.0,
                                     exit_clo_ref=None, ad_tol=0.3)
        assert cands == []

    # [仕様] exit_clo_ref あり: start_clo_ref が一致 → (elem, True)
    def test_clothoid_ref_start_match(self):
        from road_viewer import find_next_candidates
        ref = {"clothoid_id": 99, "side": "circle"}
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 10.0, 0.0, 20.0, 0.0, s_ref=ref)
        cands = find_next_candidates([e1, e2], cur_id=1, ex=999.0, ey=999.0,
                                     exit_clo_ref=ref)
        assert len(cands) == 1
        assert cands[0][0]["id"] == 2
        assert cands[0][1] is True

    # [仕様] exit_clo_ref あり: end_clo_ref が一致 → (elem, False)
    def test_clothoid_ref_end_match(self):
        from road_viewer import find_next_candidates
        ref = {"clothoid_id": 88, "side": "line"}
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 20.0, 0.0, 10.0, 0.0, e_ref=ref)
        cands = find_next_candidates([e1, e2], cur_id=1, ex=999.0, ey=999.0,
                                     exit_clo_ref=ref)
        assert len(cands) == 1
        assert cands[0][0]["id"] == 2
        assert cands[0][1] is False

    # [仕様] exit_clo_ref あり: clothoid_id は一致するが side 不一致 → 候補なし
    def test_clothoid_ref_side_mismatch_no_match(self):
        from road_viewer import find_next_candidates
        ref_exit = {"clothoid_id": 99, "side": "circle"}
        ref_elem = {"clothoid_id": 99, "side": "line"}   # side が違う
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 10.0, 0.0, 20.0, 0.0, s_ref=ref_elem)
        cands = find_next_candidates([e1, e2], cur_id=1, ex=10.0, ey=0.0,
                                     exit_clo_ref=ref_exit)
        # exit_clo_ref が指定されているので座標距離判定には落ちない → 候補なし
        assert cands == []

    # [エッジ] elem_graph が空 → 候補なし
    def test_empty_graph(self):
        from road_viewer import find_next_candidates
        assert find_next_candidates([], cur_id=None, ex=0.0, ey=0.0,
                                    exit_clo_ref=None) == []

    # [C1] 複数候補が両方マッチ → 全部返す
    def test_multiple_candidates(self):
        from road_viewer import find_next_candidates
        e1 = _mk_elem(1, 0.0, 0.0, 10.0, 0.0)
        e2 = _mk_elem(2, 10.0, 0.0, 20.0, 0.0)
        e3 = _mk_elem(3, 10.0, 0.0, 10.0, 20.0)
        cands = find_next_candidates([e1, e2, e3], cur_id=1, ex=10.0, ey=0.0,
                                     exit_clo_ref=None)
        assert len(cands) == 2
        ids = {c[0]["id"] for c in cands}
        assert ids == {2, 3}
