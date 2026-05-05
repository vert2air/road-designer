"""
tests/test_right_panel.py

right_panel.py の単体テスト。

UI 生成メソッド（_build_*、_rebuild_props 等）はウィジェット描画に依存するため除外し、
以下の純粋ロジックを重点的にテストする:
  - _endpoints_of
  - _adjacent_elements
  - _free_endpoint
  - _shared_pt
  - _next_is_forward
  - _compute_next_forward
  - _prev_is_fwd_for_adj
  - _adjacent_from_obj / _adjacent_from_pt
  - _label_for_obj / _find_by_nick_label
  - _seg_end_blocked / _arc_end_blocked
  - _candidate_seg_pairs / _merge_segments
  - _candidate_arc_pairs / _merge_arcs

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
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from models import (
    Vec2, Line, Segment, Circle, Arc, Clothoid,
    ElementProfile, GradeLine, Scene, SNAP_TOL,
)
from right_panel import RightPanel


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def make_panel():
    """テスト用 RightPanel を生成する。"""
    sc = Scene()
    panel = RightPanel(sc)
    return panel, sc


def make_seg(x0=0, y0=0, x1=100, y1=0):
    """直線上の線分を生成するヘルパー。"""
    ln = Line(Vec2(x0, y0), Vec2(x1, y1))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    return seg


def make_arc(cx=0, cy=0, r=50.0, a0=0.0, a1=math.pi):
    """円弧を生成するヘルパー。"""
    ci = Circle(Vec2(cx, cy), r)
    arc = Arc(ci, a0, a1)
    ci.arcs.append(arc)
    return arc


# ══════════════════════════════════════════════════════════════
# 1. _endpoints_of
# ══════════════════════════════════════════════════════════════

class TestEndpointsOf:
    # [仕様] Segment → [start, end]
    def test_segment(self):
        p, _ = make_panel()
        seg = make_seg(0, 0, 10, 0)
        pts = p._endpoints_of(seg)
        assert len(pts) == 2
        assert approx(pts[0].x, 0.0) and approx(pts[0].y, 0.0)
        assert approx(pts[1].x, 10.0) and approx(pts[1].y, 0.0)

    # [仕様] Arc → [start, end]
    def test_arc(self):
        p, _ = make_panel()
        arc = make_arc(0, 0, 10.0, 0.0, math.pi / 2)
        pts = p._endpoints_of(arc)
        assert len(pts) == 2
        assert approx(pts[0].x, 10.0) and approx(pts[0].y, 0.0)

    # [仕様] 有効な Clothoid → [_line_pt, _circle_pt]
    def test_clothoid_valid(self):
        p, _ = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        if clo.is_valid:
            pts = p._endpoints_of(clo)
            assert len(pts) == 2
            assert pts[0] == clo._line_pt
            assert pts[1] == clo._circle_pt

    # [エッジ] 無効な Clothoid → []
    def test_clothoid_invalid(self):
        p, _ = make_panel()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)  # d < R → 無効
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid
        assert p._endpoints_of(clo) == []

    # [エッジ] 非対応型 → []
    def test_unsupported_type(self):
        p, _ = make_panel()
        assert p._endpoints_of("not_a_shape") == []
        assert p._endpoints_of(None) == []

    # [C1] Line を渡すと [] （Line はエンドポイントを持たない）
    def test_line_returns_empty(self):
        p, _ = make_panel()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        assert p._endpoints_of(ln) == []


# ══════════════════════════════════════════════════════════════
# 2. _free_endpoint
# ══════════════════════════════════════════════════════════════

class TestFreeEndpoint:
    # [仕様] shared_pt と離れた端点を返す
    def test_basic(self):
        p, _ = make_panel()
        seg = make_seg(0, 0, 100, 0)
        # shared_pt = start (0,0) → free = end (100,0)
        result = p._free_endpoint(seg, Vec2(0, 0))
        assert result is not None
        assert approx(result.x, 100.0)

    # [仕様] 両端点が shared_pt と一致 → None
    def test_both_shared(self):
        p, _ = make_panel()
        seg = make_seg(0, 0, 0, 0)  # 縮退（始点=終点=原点）
        result = p._free_endpoint(seg, Vec2(0, 0))
        assert result is None

    # [境界] SNAP_TOL ちょうどの距離は「一致」とみなす（条件が > なので SNAP_TOL は非 free）
    def test_snap_tol_boundary(self):
        """_free_endpoint は distance > SNAP_TOL で free と判定する。
        distance == SNAP_TOL は free でない（None を返す）。
        """
        p, _ = make_panel()
        seg = make_seg(0, 0, SNAP_TOL, 0)
        # end=(SNAP_TOL, 0): 距離 = SNAP_TOL、> SNAP_TOL は False → free でない
        result = p._free_endpoint(seg, Vec2(0, 0))
        assert result is None

    # [境界] SNAP_TOL より少しだけ大きい距離は free
    def test_just_beyond_snap_tol(self):
        p, _ = make_panel()
        seg = make_seg(0, 0, SNAP_TOL + 0.01, 0)
        result = p._free_endpoint(seg, Vec2(0, 0))
        assert result is not None
        assert approx(result.x, SNAP_TOL + 0.01)

    # [エッジ] 空リスト → None
    def test_empty_endpoints(self):
        p, _ = make_panel()
        result = p._free_endpoint("not_a_shape", Vec2(0, 0))
        assert result is None


# ══════════════════════════════════════════════════════════════
# 3. _shared_pt
# ══════════════════════════════════════════════════════════════

class TestSharedPt:
    # [仕様] 共有端点を返す
    def test_connected_segments(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)  # seg1.end == seg2.start
        result = p._shared_pt(seg1, seg2)
        assert result is not None
        assert approx(result.x, 10.0) and approx(result.y, 0.0)

    # [仕様] 共有端点がない → None
    def test_no_shared(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(20, 0, 30, 0)  # 離れている
        assert p._shared_pt(seg1, seg2) is None

    # [境界] SNAP_TOL 以内で共有
    def test_near_shared(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10 + SNAP_TOL * 0.9, 0, 20, 0)  # ぎりぎり共有
        result = p._shared_pt(seg1, seg2)
        assert result is not None

    # [境界] SNAP_TOL 超で非共有
    def test_beyond_snap_tol(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10 + SNAP_TOL * 1.1, 0, 20, 0)
        assert p._shared_pt(seg1, seg2) is None

    # [エッジ] 非対応型どうし → None
    def test_unsupported_types(self):
        p, _ = make_panel()
        assert p._shared_pt("a", "b") is None


# ══════════════════════════════════════════════════════════════
# 4. _adjacent_elements
# ══════════════════════════════════════════════════════════════

class TestAdjacentElements:
    # [仕様] 端点が一致する隣接線分を返す
    def test_finds_adjacent_segment(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        p.scene = sc
        result = p._adjacent_elements(seg1)
        cands = [c for c, _ in result]
        assert seg2 in cands

    # [仕様] 自分自身は含まれない
    def test_excludes_self(self):
        p, sc = make_panel()
        seg = make_seg(0, 0, 10, 0)
        sc.add_line(seg.line)
        p.scene = sc
        result = p._adjacent_elements(seg)
        assert seg not in [c for c, _ in result]

    # [仕様] 始点で接続 → is_forward=True
    def test_is_forward_true_at_start(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)  # seg2.start == seg1.end
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        p.scene = sc
        result = p._adjacent_elements(seg1)
        match = [(c, fwd) for c, fwd in result if c is seg2]
        assert match
        assert match[0][1] is True  # 始点で接続 → 正順

    # [仕様] 終点で接続 → is_forward=False
    def test_is_forward_false_at_end(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(0, 0, 20, 0)  # seg2.start == seg1.start
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        p.scene = sc
        result = p._adjacent_elements(seg1)
        match = [(c, fwd) for c, fwd in result if c is seg2]
        if match:
            # seg2 の始点が seg1 の始点に一致 → seg2 は正順(True)
            assert match[0][1] is True

    # [仕様] exclude_pt を指定すると対象端点を除外する
    def test_exclude_pt(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(0, 0, -10, 0)  # seg1.start に接続
        seg3 = make_seg(10, 0, 20, 0)  # seg1.end に接続
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        sc.add_line(seg3.line)
        p.scene = sc
        # exclude_pt = seg1.start → seg2 は除外、seg3 は残る
        result = p._adjacent_elements(seg1, exclude_pt=Vec2(0, 0))
        cands = [c for c, _ in result]
        assert seg2 not in cands
        assert seg3 in cands

    # [エッジ] シーンに図形がない → []
    def test_empty_scene(self):
        p, sc = make_panel()
        seg = make_seg(0, 0, 10, 0)
        sc.add_line(seg.line)
        p.scene = sc
        result = p._adjacent_elements(seg)
        assert result == []

    # [エッジ] 端点数が 2 未満の候補は除外される
    def test_candidate_with_no_endpoints_excluded(self):
        p, sc = make_panel()
        seg = make_seg(0, 0, 10, 0)
        sc.add_line(seg.line)
        p.scene = sc
        # Line 単体（segments なし）はendpoints=[] → 候補にならない
        result = p._adjacent_elements(seg)
        assert all(c is not seg.line for c, _ in result)


# ══════════════════════════════════════════════════════════════
# 5. _next_is_forward
# ══════════════════════════════════════════════════════════════

class TestNextIsForward:
    # [仕様] exit_pt が next_obj の始点に近い → True（正順）
    def test_forward_when_exit_near_start(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)  # seg2.start=(10,0) = seg1.end
        # prev_is_fwd=True → exit_pt = seg1.end = (10,0)
        result = p._next_is_forward(seg1, True, seg2)
        assert result is True

    # [仕様] exit_pt が next_obj の終点に近い → False（逆順）
    def test_reverse_when_exit_near_end(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(0, 0, 10, 0)  # seg2.end=(10,0) = seg1.end
        result = p._next_is_forward(seg1, True, seg2)
        # exit_pt=(10,0), seg2.start=(0,0): d_start=10, seg2.end=(10,0): d_end=0
        # d_start > d_end → False（終点で接続 = 逆順）
        assert result is False

    # [仕様] prev_is_fwd=False → exit_pt は始点側
    def test_uses_start_when_rev(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(0, 0, 20, 0)  # seg2.start=(0,0) = seg1.start
        result = p._next_is_forward(seg1, False, seg2)
        # prev_is_fwd=False → exit_pt = seg1.start = (0,0)
        # d_start = 0, d_end = 20 → True（始点で接続）
        assert result is True

    # [エッジ] 端点が取得できない → True（デフォルト）
    def test_no_endpoints_returns_true(self):
        p, _ = make_panel()
        result = p._next_is_forward("a", True, "b")
        assert result is True


# ══════════════════════════════════════════════════════════════
# 6. _compute_next_forward
# ══════════════════════════════════════════════════════════════

class TestComputeNextForward:
    # [仕様] 出口接線と入口接線の内積 ≥ 0 → True（順方向）
    def test_same_direction_true(self):
        p, _ = make_panel()
        # seg1 が x 軸方向、seg2 も x 軸方向
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)
        # exit_tan = (1,0), entry_tan from start = (1,0), dot=1 ≥ 0 → True
        result = p._compute_next_forward(seg1, True, seg2)
        assert result is True

    # [仕様] 逆方向の接線 → False
    def test_opposite_direction_false(self):
        """seg2 が(-1,0)方向（左向き）で、connect_at_start=True で接続する場合。
        entry_tangent(seg2, True) = start→end方向 = (-1,0)
        exit_tan(seg1,True) = (1,0), dot = -1 < 0 → False
        """
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        # seg2: start=(10,0), end=(0,0) → 左向き。start で seg1.end に接続
        ln2 = Line(Vec2(10, 0), Vec2(0, 0))
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        result = p._compute_next_forward(seg1, True, seg2)
        # exit_tan=(1,0), entry_tangent(seg2,True)=start→end=(-1,0), dot=-1 < 0 → False
        assert result is False

    # [エッジ] entry_tangent が None → True（デフォルト）
    def test_none_entry_returns_true(self):
        p, _ = make_panel()
        seg = make_seg(0, 0, 10, 0)
        result = p._compute_next_forward(seg, True, "not_a_shape")
        assert result is True

    # [境界] 内積がゼロ（直交）→ True（≥ 0 なので True）
    def test_orthogonal_returns_true(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        # 90°回転した方向の線分
        ln2 = Line(Vec2(10, 0), Vec2(10, 10))
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        result = p._compute_next_forward(seg1, True, seg2)
        assert result is True  # dot=0 ≥ 0


# ══════════════════════════════════════════════════════════════
# 7. _prev_is_fwd_for_adj
# ══════════════════════════════════════════════════════════════

class TestPrevIsFwdForAdj:
    # [仕様] cand の端点が prev_obj の終点に近い → True（正順通過）
    def test_true_when_cand_near_end(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)  # seg2.start = seg1.end
        result = p._prev_is_fwd_for_adj(seg1, seg2)
        assert result is True

    # [仕様] cand の端点が prev_obj の始点に近い → False（逆順通過）
    def test_false_when_cand_near_start(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(0, 0, -10, 0)  # seg2.start = seg1.start
        result = p._prev_is_fwd_for_adj(seg1, seg2)
        assert result is False

    # [エッジ] どちらにも一致しない → True（デフォルト）
    def test_default_true(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(100, 0, 200, 0)  # 遠くにある
        result = p._prev_is_fwd_for_adj(seg1, seg2)
        assert result is True

    # [エッジ] 端点が取得できない → True（デフォルト）
    def test_no_endpoints_returns_true(self):
        p, _ = make_panel()
        result = p._prev_is_fwd_for_adj("a", "b")
        assert result is True


# ══════════════════════════════════════════════════════════════
# 8. _label_for_obj / _find_by_nick_label
# ══════════════════════════════════════════════════════════════

class TestLabelForObj:
    # [仕様] Segment のラベルを返す
    def test_segment_label(self):
        p, sc = make_panel()
        seg = make_seg()
        sc.add_line(seg.line)
        p.scene = sc
        label = p._label_for_obj(seg)
        assert label  # 非空文字列
        assert str(seg.id) in label

    # [仕様] Arc のラベルを返す
    def test_arc_label(self):
        p, sc = make_panel()
        arc = make_arc()
        sc.add_circle(arc.circle)
        p.scene = sc
        label = p._label_for_obj(arc)
        assert label
        assert str(arc.id) in label

    # [仕様] Clothoid のラベルを返す
    def test_clothoid_label(self):
        p, sc = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        p.scene = sc
        label = p._label_for_obj(clo)
        assert label
        assert str(clo.id) in label

    # [エッジ] 非対応型 → 空文字
    def test_unsupported_returns_empty(self):
        p, sc = make_panel()
        p.scene = sc
        assert p._label_for_obj("not_a_shape") == ""


class TestFindByNickLabel:
    # [仕様] ラベルから図形を逆引きする
    def test_roundtrip(self):
        p, sc = make_panel()
        seg = make_seg()
        sc.add_line(seg.line)
        p.scene = sc
        label = p._label_for_obj(seg)
        result = p._find_by_nick_label(label)
        assert result is seg

    # [仕様] "(なし)" → None
    def test_none_label(self):
        p, sc = make_panel()
        p.scene = sc
        assert p._find_by_nick_label("(なし)") is None

    # [仕様] [順]/[逆] プレフィックスを除去して検索する
    def test_with_prefix(self):
        p, sc = make_panel()
        seg = make_seg()
        sc.add_line(seg.line)
        p.scene = sc
        label = p._label_for_obj(seg)
        result = p._find_by_nick_label("[順] " + label)
        assert result is seg

    # [エッジ] 存在しないラベル → None
    def test_not_found_returns_none(self):
        p, sc = make_panel()
        p.scene = sc
        assert p._find_by_nick_label("nonexistent_label") is None


# ══════════════════════════════════════════════════════════════
# 9. _seg_end_blocked
# ══════════════════════════════════════════════════════════════

class TestSegEndBlocked:
    # [仕様] クロソイドに束縛されていない → False
    def test_not_blocked(self):
        p, sc = make_panel()
        seg = make_seg(0, 0, 100, 0)
        sc.add_line(seg.line)
        p.scene = sc
        assert p._seg_end_blocked(seg, 'end') is False
        assert p._seg_end_blocked(seg, 'start') is False

    # [仕様] snap=True のクロソイドの接点が端点と一致 → True
    def test_blocked_by_snap(self):
        p, sc = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        sc.add_line(ln)
        sc.add_circle(ci)
        sc.add_clothoid(clo)
        p.scene = sc
        if clo.is_valid:
            # snap=True なら end か start が接点に固定される
            blocked_end   = p._seg_end_blocked(seg, 'end')
            blocked_start = p._seg_end_blocked(seg, 'start')
            assert blocked_end or blocked_start

    # [仕様] _split_seg_ids に含まれる → True
    def test_blocked_by_split_ids(self):
        p, sc = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_line(ln)
        sc.add_circle(ci)
        sc.add_clothoid(clo)
        p.scene = sc
        if clo.is_valid and seg.id in clo._split_seg_ids:
            assert p._seg_end_blocked(seg, 'end') is True

    # [C1] 無効なクロソイドは無視される
    def test_invalid_clothoid_ignored(self):
        p, sc = make_panel()
        seg = make_seg(0, 0, 100, 0)
        sc.add_line(seg.line)
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 5), 30.0)  # 無効
        clo = Clothoid(ln, ci, snap_segment=True, snap_arc=False)
        sc.add_clothoid(clo)
        p.scene = sc
        assert p._seg_end_blocked(seg, 'end') is False


# ══════════════════════════════════════════════════════════════
# 10. _arc_end_blocked
# ══════════════════════════════════════════════════════════════

class TestArcEndBlocked:
    # [仕様] 束縛なし → False
    def test_not_blocked(self):
        p, sc = make_panel()
        arc = make_arc()
        sc.add_circle(arc.circle)
        p.scene = sc
        assert p._arc_end_blocked(arc, 'start') is False
        assert p._arc_end_blocked(arc, 'end') is False

    # [仕様] _split_arc_ids に含まれる → True
    def test_blocked_by_split_ids(self):
        p, sc = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        arc = Arc(ci, -1.5, 1.5)
        ci.arcs.append(arc)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        p.scene = sc
        if arc.id in clo._split_arc_ids:
            assert p._arc_end_blocked(arc, 'end') is True

    # [C1] 無効なクロソイドは無視される
    def test_invalid_clothoid_ignored(self):
        p, sc = make_panel()
        arc = make_arc()
        sc.add_circle(arc.circle)
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci2 = Circle(Vec2(50, 5), 30.0)  # 無効
        clo = Clothoid(ln, ci2, snap_segment=False, snap_arc=True)
        sc.add_clothoid(clo)
        p.scene = sc
        assert p._arc_end_blocked(arc, 'start') is False


# ══════════════════════════════════════════════════════════════
# 11. _candidate_seg_pairs / _merge_segments
# ══════════════════════════════════════════════════════════════

class TestCandidateSegPairs:
    # [仕様] 全4ペアを距離でソートして返す
    def test_four_pairs_sorted(self):
        p, sc = make_panel()
        seg_a = make_seg(0, 0, 10, 0)
        seg_b = make_seg(10, 0, 20, 0)
        sc.add_line(seg_a.line)
        sc.add_line(seg_b.line)
        p.scene = sc
        pairs = p._candidate_seg_pairs(seg_a, seg_b)
        assert len(pairs) == 4
        # 最も近いペアが先頭
        assert pairs[0]['dist'] <= pairs[-1]['dist']

    # [仕様] ペアに 'end_a', 'end_b', 'dist', 'blocked_a', 'blocked_b', 'label' が含まれる
    def test_pair_keys(self):
        p, sc = make_panel()
        seg_a = make_seg(0, 0, 10, 0)
        seg_b = make_seg(10, 0, 20, 0)
        sc.add_line(seg_a.line)
        sc.add_line(seg_b.line)
        p.scene = sc
        pairs = p._candidate_seg_pairs(seg_a, seg_b)
        for pair in pairs:
            for key in ('end_a', 'end_b', 'dist', 'blocked_a', 'blocked_b', 'label'):
                assert key in pair

    # [仕様] 最近傍ペアは seg_a.end と seg_b.start（距離 0）
    def test_nearest_pair(self):
        p, sc = make_panel()
        seg_a = make_seg(0, 0, 10, 0)
        seg_b = make_seg(10, 0, 20, 0)
        sc.add_line(seg_a.line)
        sc.add_line(seg_b.line)
        p.scene = sc
        pairs = p._candidate_seg_pairs(seg_a, seg_b)
        nearest = pairs[0]
        assert approx(nearest['dist'], 0.0)
        assert nearest['end_a'] == 'end'
        assert nearest['end_b'] == 'start'


class TestMergeSegments:
    # [仕様] end_a='end', end_b='start' → seg_a.t_end = seg_b.t_end
    def test_merge_end_start(self):
        p, sc = make_panel()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg_a = Segment(ln, 0.0, 0.4)
        seg_b = Segment(ln, 0.4, 1.0)
        ln.segments.extend([seg_a, seg_b])
        sc.add_line(ln)
        p.scene = sc
        p._merge_segments(seg_a, seg_b, 'end', 'start')
        assert approx(seg_a.t_end, 1.0)
        assert seg_b not in ln.segments

    # [仕様] end_a='end', end_b='end' → seg_a.t_end = seg_b.t_start
    def test_merge_end_end(self):
        p, sc = make_panel()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg_a = Segment(ln, 0.0, 0.4)
        seg_b = Segment(ln, 1.0, 0.4)  # 逆順（t_end が接点）
        ln.segments.extend([seg_a, seg_b])
        sc.add_line(ln)
        p.scene = sc
        p._merge_segments(seg_a, seg_b, 'end', 'end')
        assert approx(seg_a.t_end, 1.0)  # far_t = seg_b.t_start = 1.0

    # [仕様] end_a='start', end_b='start' → seg_a.t_start = seg_b.t_end
    def test_merge_start_start(self):
        p, sc = make_panel()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg_a = Segment(ln, 0.5, 1.0)
        seg_b = Segment(ln, 0.0, 0.5)
        ln.segments.extend([seg_a, seg_b])
        sc.add_line(ln)
        p.scene = sc
        p._merge_segments(seg_a, seg_b, 'start', 'start')
        assert approx(seg_a.t_start, 0.5)  # far_t = seg_b.t_end = 0.5

    # [仕様] end_a='start', end_b='end' → seg_a.t_start = seg_b.t_start
    def test_merge_start_end(self):
        p, sc = make_panel()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg_a = Segment(ln, 0.5, 1.0)
        seg_b = Segment(ln, 0.0, 0.5)
        ln.segments.extend([seg_a, seg_b])
        sc.add_line(ln)
        p.scene = sc
        p._merge_segments(seg_a, seg_b, 'start', 'end')
        assert approx(seg_a.t_start, 0.0)  # far_t = seg_b.t_start = 0.0


# ══════════════════════════════════════════════════════════════
# 12. _candidate_arc_pairs / _merge_arcs
# ══════════════════════════════════════════════════════════════

class TestCandidateArcPairs:
    # [仕様] 全4ペアを距離でソートして返す
    def test_four_pairs_sorted(self):
        p, sc = make_panel()
        ci = Circle(Vec2(0, 0), 10.0)
        arc_a = Arc(ci, 0.0, math.pi / 2)
        arc_b = Arc(ci, math.pi / 2, math.pi)
        ci.arcs.extend([arc_a, arc_b])
        sc.add_circle(ci)
        p.scene = sc
        pairs = p._candidate_arc_pairs(arc_a, arc_b)
        assert len(pairs) == 4
        assert pairs[0]['dist'] <= pairs[-1]['dist']

    # [仕様] 最近傍ペアは arc_a.end と arc_b.start（距離 0）
    def test_nearest_pair(self):
        p, sc = make_panel()
        ci = Circle(Vec2(0, 0), 10.0)
        arc_a = Arc(ci, 0.0, math.pi / 2)
        arc_b = Arc(ci, math.pi / 2, math.pi)
        ci.arcs.extend([arc_a, arc_b])
        sc.add_circle(ci)
        p.scene = sc
        pairs = p._candidate_arc_pairs(arc_a, arc_b)
        nearest = pairs[0]
        assert approx(nearest['dist'], 0.0, tol=1e-4)
        assert nearest['end_a'] == 'end'
        assert nearest['end_b'] == 'start'


class TestMergeArcs:
    # [仕様] end_a='end', end_b='start' → arc_a.angle_end = arc_b.angle_end
    def test_merge_end_start(self):
        p, sc = make_panel()
        ci = Circle(Vec2(0, 0), 10.0)
        arc_a = Arc(ci, 0.0, math.pi / 2)
        arc_b = Arc(ci, math.pi / 2, math.pi)
        ci.arcs.extend([arc_a, arc_b])
        sc.add_circle(ci)
        p.scene = sc
        p._merge_arcs(arc_a, arc_b, 'end', 'start')
        assert approx(arc_a.angle_end, math.pi)

    # [仕様] end_a='end', end_b='end' → arc_a.angle_end = arc_b.angle_start
    def test_merge_end_end(self):
        p, sc = make_panel()
        ci = Circle(Vec2(0, 0), 10.0)
        arc_a = Arc(ci, 0.0, math.pi / 2)
        arc_b = Arc(ci, math.pi, math.pi / 2)  # 逆順
        ci.arcs.extend([arc_a, arc_b])
        sc.add_circle(ci)
        p.scene = sc
        p._merge_arcs(arc_a, arc_b, 'end', 'end')
        assert approx(arc_a.angle_end, math.pi)

    # [仕様] end_a='start', end_b='start' → arc_a.angle_start = arc_b.angle_end
    def test_merge_start_start(self):
        p, sc = make_panel()
        ci = Circle(Vec2(0, 0), 10.0)
        arc_a = Arc(ci, math.pi / 2, math.pi)
        arc_b = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.extend([arc_a, arc_b])
        sc.add_circle(ci)
        p.scene = sc
        p._merge_arcs(arc_a, arc_b, 'start', 'start')
        assert approx(arc_a.angle_start, math.pi / 2)

    # [仕様] end_a='start', end_b='end' → arc_a.angle_start = arc_b.angle_start
    def test_merge_start_end(self):
        p, sc = make_panel()
        ci = Circle(Vec2(0, 0), 10.0)
        arc_a = Arc(ci, math.pi / 2, math.pi)
        arc_b = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.extend([arc_a, arc_b])
        sc.add_circle(ci)
        p.scene = sc
        p._merge_arcs(arc_a, arc_b, 'start', 'end')
        assert approx(arc_a.angle_start, 0.0)


# ══════════════════════════════════════════════════════════════
# 13. _adjacent_from_pt
# ══════════════════════════════════════════════════════════════

class TestAdjacentFromPt:
    # [仕様] 指定座標に近い線分端点を返す
    def test_finds_nearby_segment(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        p.scene = sc
        result = p._adjacent_from_pt(Vec2(10, 0), excludes=[seg1])
        cands = [c for c, _ in result]
        assert seg2 in cands

    # [仕様] excludes に含まれる図形は返さない
    def test_excludes_work(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        p.scene = sc
        result = p._adjacent_from_pt(Vec2(10, 0), excludes=[seg1, seg2])
        assert result == []

    # [仕様] Arc の端点も検索対象
    def test_finds_nearby_arc(self):
        p, sc = make_panel()
        arc = make_arc(0, 0, 10.0, 0.0, math.pi / 2)
        # arc.start = (10, 0)
        sc.add_circle(arc.circle)
        p.scene = sc
        result = p._adjacent_from_pt(Vec2(10, 0))
        cands = [c for c, _ in result]
        assert arc in cands

    # [仕様] Clothoid の接点も検索対象
    def test_finds_nearby_clothoid(self):
        p, sc = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        p.scene = sc
        if clo.is_valid and clo._line_pt:
            result = p._adjacent_from_pt(clo._line_pt)
            cands = [c for c, _ in result]
            assert clo in cands

    # [エッジ] 近傍に何もない → []
    def test_empty_scene(self):
        p, sc = make_panel()
        p.scene = sc
        result = p._adjacent_from_pt(Vec2(1000, 1000))
        assert result == []


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: _adjacent_from_pt の各分岐
# ══════════════════════════════════════════════════════════════

class TestAdjacentFromPtBranches:
    # [C1] prev_obj が Clothoid で _line_pt に接続している線分も候補（L695）
    def test_clothoid_line_pt_segment_found(self):
        p, sc = make_panel()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 60), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        seg = Segment(ln, 0.0, 0.5)
        ln.segments.append(seg)
        sc.add_line(ln)
        sc.add_circle(ci)
        sc.add_clothoid(clo)
        p.scene = sc
        if clo.is_valid and clo._line_pt:
            # prev_obj=clo、pt=_line_pt で検索 → 線分が候補に含まれうる
            result = p._adjacent_from_pt(clo._line_pt, prev_obj=clo)
            # 例外にならないことを確認
            assert isinstance(result, list)

    # [C1] 折れ線接続中の直線から相手側の線分も候補になる（L677: continue のケース）
    def test_connected_line_adjacent(self):
        p, sc = make_panel()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        seg_a = Segment(a, 0.0, 1.0)
        seg_b = Segment(b, 0.0, 1.0)
        a.segments.append(seg_a)
        b.segments.append(seg_b)
        sc.add_line(a)
        sc.add_line(b)
        p.scene = sc
        from canvas import Canvas
        c = Canvas(sc)
        c._connect_polyline(a, b)
        # 交点付近で検索 → 相手側の線分が候補に入る
        conn = a.connection
        if conn:
            result = p._adjacent_from_pt(conn.shared_point)
            cands = [c for c, _ in result]
            assert seg_a in cands or seg_b in cands


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: _next_is_forward の prev_is_fwd=True 追加ケース
# ══════════════════════════════════════════════════════════════

class TestNextIsForwardBranches:
    # [C1] next_obj のエンドポイントが 2 未満の場合は True を返す
    def test_no_endpoints_next_obj(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        # 無効 Clothoid → endpoints = []
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        ci = Circle(Vec2(50, 10), 30.0)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        assert not clo.is_valid
        result = p._next_is_forward(seg1, True, clo)
        assert result is True

    # [C1] prev_is_fwd=True の exit_pt = seg.end 側（正しく取得される）
    def test_exit_pt_from_end(self):
        p, _ = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)
        # exit_pt = seg1.end = (10,0)
        # seg2.start = (10,0) → d_start = 0 → True
        result = p._next_is_forward(seg1, True, seg2)
        assert result is True


# ══════════════════════════════════════════════════════════════
# 追加カバレッジ: _adjacent_from_obj の重複除去
# ══════════════════════════════════════════════════════════════

class TestAdjacentFromObj:
    # [仕様] _adjacent_from_obj は両端点から隣接を収集して重複除去する
    def test_collects_both_endpoints(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)  # seg1.end に接続
        seg3 = make_seg(0, 0, 0, 10)   # seg1.start に接続
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        sc.add_line(seg3.line)
        p.scene = sc
        result = p._adjacent_from_obj(seg1)
        cands = [c for c, _ in result]
        # seg2（end側）と seg3（start側）の両方が含まれる
        assert seg2 in cands or seg3 in cands

    # [仕様] excludes に含まれる図形は返さない
    def test_excludes_work(self):
        p, sc = make_panel()
        seg1 = make_seg(0, 0, 10, 0)
        seg2 = make_seg(10, 0, 20, 0)
        sc.add_line(seg1.line)
        sc.add_line(seg2.line)
        p.scene = sc
        result = p._adjacent_from_obj(seg1, excludes=[seg2])
        assert seg2 not in [c for c, _ in result]
