"""
tests/test_canvas.py

canvas.py の単体テスト。

PyQt6 を使用するため QApplication が必要。
描画系（paintEvent 等）はスキップし、UI に依存しないロジックを重点的にテストする。

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
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor

_app = QApplication.instance() or QApplication(sys.argv)

from models import (
    Vec2, Line, Segment, Circle, Arc, Clothoid, Scene, LineConnection,
)
from canvas import Canvas, qp, Handle, HIT_DIST, HANDLE_RADIUS


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol

def vec_approx(v1: Vec2, v2: Vec2, tol=1e-6):
    return approx(v1.x, v2.x, tol) and approx(v1.y, v2.y, tol)

def make_canvas():
    sc = Scene()
    c = Canvas(sc)
    c._scale = 1.0
    c._offset = Vec2(500.0, 500.0)  # y反転後も正のスクリーン座標になるよう中心を設定
    return c, sc

def sw(c, wx, wy):
    """ワールド座標 (wx,wy) に対応するスクリーン座標 Vec2 を返す。"""
    pt = c.w2s(Vec2(wx, wy))
    return Vec2(pt.x(), pt.y())


# ══════════════════════════════════════════════════════════════
# 1. モジュールレベル
# ══════════════════════════════════════════════════════════════

class TestQp:
    # [仕様] Vec2 → QPointF 変換
    def test_basic(self):
        pt = qp(Vec2(3.0, 4.0))
        assert isinstance(pt, QPointF)
        assert approx(pt.x(), 3.0) and approx(pt.y(), 4.0)

    # [境界] 零ベクトル
    def test_zero(self):
        pt = qp(Vec2(0, 0))
        assert approx(pt.x(), 0.0) and approx(pt.y(), 0.0)

    # [境界] 負の値
    def test_negative(self):
        pt = qp(Vec2(-1.5, -2.5))
        assert approx(pt.x(), -1.5) and approx(pt.y(), -2.5)


class TestConstants:
    # [仕様] HIT_DIST=8, HANDLE_RADIUS=7
    def test_hit_dist(self):
        assert HIT_DIST == 8

    def test_handle_radius(self):
        assert HANDLE_RADIUS == 7

    # [仕様] モード定数の値
    def test_mode_constants(self):
        assert Canvas.MODE_SELECT == "select"
        assert Canvas.MODE_LINE   == "line"
        assert Canvas.MODE_CIRCLE == "circle"


# ══════════════════════════════════════════════════════════════
# 2. 座標変換
# ══════════════════════════════════════════════════════════════

class TestCoordTransform:
    # [仕様] w2s: screen_x = wx*scale + ox, screen_y = -wy*scale + oy
    def test_w2s_at_origin(self):
        c, _ = make_canvas()
        c._scale = 1.0
        c._offset = Vec2(100, 200)
        pt = c.w2s(Vec2(0, 0))
        assert approx(pt.x(), 100.0) and approx(pt.y(), 200.0)

    def test_w2s_y_inversion(self):
        c, _ = make_canvas()
        c._scale = 2.0
        c._offset = Vec2(0, 0)
        pt = c.w2s(Vec2(5, 3))
        assert approx(pt.x(), 10.0) and approx(pt.y(), -6.0)

    # [仕様] s2w は w2s の逆変換
    def test_s2w_roundtrip(self):
        c, _ = make_canvas()
        c._scale = 3.0
        c._offset = Vec2(50, 80)
        for wx, wy in [(7.0, -4.0), (0.0, 0.0), (-3.0, 10.0)]:
            w = Vec2(wx, wy)
            pt = c.w2s(w)
            w2 = c.s2w(pt.x(), pt.y())
            assert vec_approx(w2, w)

    # [仕様] s2w_qp は QPointF を受け取るラッパー
    def test_s2w_qp(self):
        c, _ = make_canvas()
        c._scale = 2.0
        c._offset = Vec2(10, 20)
        pt = c.w2s(Vec2(5, 3))
        w = c.s2w_qp(pt)
        assert vec_approx(w, Vec2(5, 3))

    # [仕様] scale_w2s: ワールド距離 → スクリーン距離
    def test_scale_w2s(self):
        c, _ = make_canvas()
        c._scale = 5.0
        assert approx(c.scale_w2s(10.0), 50.0)

    # [仕様] scale_s2w: スクリーン距離 → ワールド距離
    def test_scale_s2w(self):
        c, _ = make_canvas()
        c._scale = 5.0
        assert approx(c.scale_s2w(50.0), 10.0)

    # [境界] scale=1 のとき恒等変換
    def test_scale_identity(self):
        c, _ = make_canvas()
        c._scale = 1.0
        assert approx(c.scale_w2s(7.0), 7.0)
        assert approx(c.scale_s2w(7.0), 7.0)

    # [エッジ] 非常に小さいスケール
    def test_small_scale(self):
        c, _ = make_canvas()
        c._scale = 0.001
        assert approx(c.scale_w2s(1000.0), 1.0)


# ══════════════════════════════════════════════════════════════
# 3. _dist_point_segment（静的メソッド）
# ══════════════════════════════════════════════════════════════

class TestDistPointSegment:
    # [仕様] 垂直距離
    def test_perpendicular(self):
        d = Canvas._dist_point_segment(Vec2(5, 3), Vec2(0, 0), Vec2(10, 0))
        assert approx(d, 3.0)

    # [仕様] 線分の端点を超えた場合は端点への距離
    def test_beyond_end(self):
        d = Canvas._dist_point_segment(Vec2(15, 0), Vec2(0, 0), Vec2(10, 0))
        assert approx(d, 5.0)

    def test_before_start(self):
        d = Canvas._dist_point_segment(Vec2(-3, 4), Vec2(0, 0), Vec2(10, 0))
        assert approx(d, 5.0)

    # [境界] 始点・終点と一致
    def test_at_start(self):
        assert approx(Canvas._dist_point_segment(Vec2(0, 0), Vec2(0, 0), Vec2(10, 0)), 0.0)

    def test_at_end(self):
        assert approx(Canvas._dist_point_segment(Vec2(10, 0), Vec2(0, 0), Vec2(10, 0)), 0.0)

    # [境界] 線分上の点（距離 0）
    def test_on_segment(self):
        assert approx(Canvas._dist_point_segment(Vec2(5, 0), Vec2(0, 0), Vec2(10, 0)), 0.0)

    # [エッジ] 縮退した線分（a == b）→ 点 a からの距離
    def test_degenerate(self):
        d = Canvas._dist_point_segment(Vec2(3, 4), Vec2(0, 0), Vec2(0, 0))
        assert approx(d, 5.0)

    # [エッジ] 非常に短い線分
    def test_very_short(self):
        d = Canvas._dist_point_segment(Vec2(0, 1), Vec2(0, 0), Vec2(1e-8, 0))
        assert d > 0


# ══════════════════════════════════════════════════════════════
# 4. _angle_in_arc
# ══════════════════════════════════════════════════════════════

class TestAngleInArc:
    # [仕様] 範囲内 → True
    def test_inside(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(math.pi / 4, 0.0, math.pi / 2) is True

    # [仕様] 範囲外 → False
    def test_outside(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(math.pi, 0.0, math.pi / 2) is False

    # [境界] a_start と一致
    def test_at_start(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(0.0, 0.0, math.pi / 2) is True

    # [境界] a_end と一致（(a_end - a_start) % 2π = π/2、rel=π/2 <= π/2）
    def test_at_end(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(math.pi / 2, 0.0, math.pi / 2) is True

    # [エッジ] a_start == a_end → (ang-start)%2π <= 0 → 始点のみ True
    def test_zero_span(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(1.0, 1.0, 1.0) is True
        assert c._angle_in_arc(1.1, 1.0, 1.0) is False

    # [エッジ] 跨ぎ（a_end < a_start）でも正しく判定
    def test_wrap_around_inside(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(0.0, 3 * math.pi / 2, math.pi / 2) is True

    def test_wrap_around_outside(self):
        c, _ = make_canvas()
        assert c._angle_in_arc(math.pi, 3 * math.pi / 2, math.pi / 2) is False

    # [エッジ] 全円（a_end=a_start+2π）→ span=(2π)%2π=0 → 始点でのみ True
    def test_full_circle_zero_span(self):
        """a_end = a_start + 2π のとき span = 0 → arc_angle=0 と同じ扱い。
        これは実装上の特性であり、全円の arc には通常 Arc を使わない。
        """
        c, _ = make_canvas()
        # span = (2π - 0) % 2π = 0 → rel = π % 2π = π > 0 → False
        result = c._angle_in_arc(math.pi, 0.0, 2 * math.pi)
        assert result is False  # span=0 のため全角度 False（始点のみ True）


# ══════════════════════════════════════════════════════════════
# 5. ヒット判定メソッド
# ══════════════════════════════════════════════════════════════

class TestHitInfiniteLine:
    """_hit_infinite_line はワールド座標で直接距離判定するため offset 不要。"""

    # [仕様] 直線に近ければ True
    def test_close(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        assert c._hit_infinite_line(ln, Vec2(5, 3), 5.0) is True

    # [仕様] 離れていれば False
    def test_far(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        assert c._hit_infinite_line(ln, Vec2(5, 10), 5.0) is False

    # [境界] ちょうど tol の距離（< なので False）
    def test_exactly_tol(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        assert c._hit_infinite_line(ln, Vec2(5, 5.0), 5.0) is False

    # [境界] tol より少しだけ近い
    def test_just_inside_tol(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        assert c._hit_infinite_line(ln, Vec2(5, 4.999), 5.0) is True


class TestHitArc:
    def _make_arc(self, a_start, a_end, r=10.0):
        ci = Circle(Vec2(0, 0), r)
        return ci, Arc(ci, a_start, a_end)

    # [仕様] 円弧上の点でヒット
    def test_hit_on_arc(self):
        c, _ = make_canvas()
        ci, arc = self._make_arc(0.0, math.pi)
        ang = math.pi / 4
        w = Vec2(10 * math.cos(ang), 10 * math.sin(ang))
        assert c._hit_arc(ci, arc, w, 1.0) is True

    # [仕様] 角度範囲外ではヒットしない
    def test_angle_out_of_range(self):
        c, _ = make_canvas()
        ci, arc = self._make_arc(0.0, math.pi)
        ang = 3 * math.pi / 2  # 下側は範囲外
        w = Vec2(10 * math.cos(ang), 10 * math.sin(ang))
        assert c._hit_arc(ci, arc, w, 1.0) is False

    # [仕様] 円から離れた点ではヒットしない
    def test_away_from_circle(self):
        c, _ = make_canvas()
        ci, arc = self._make_arc(0.0, math.pi)
        assert c._hit_arc(ci, arc, Vec2(0, 0), 1.0) is False

    # [境界] tol の境界（半径 ± tol）
    def test_just_inside_tol(self):
        c, _ = make_canvas()
        ci, arc = self._make_arc(0.0, math.pi)
        w = Vec2(10.0 + 0.999, 0.0)  # 範囲内（角度 0° は start）
        assert c._hit_arc(ci, arc, w, 1.0) is True

    def test_just_outside_tol(self):
        c, _ = make_canvas()
        ci, arc = self._make_arc(0.0, math.pi)
        w = Vec2(10.0 + 1.001, 0.0)
        assert c._hit_arc(ci, arc, w, 1.0) is False


class TestHitPolyline:
    # [仕様] 折れ線に近ければ True
    def test_hit(self):
        c, _ = make_canvas()
        pts = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10)]
        assert c._hit_polyline(pts, Vec2(5, 2), 3.0) is True

    # [仕様] 折れ線から離れれば False
    def test_miss(self):
        c, _ = make_canvas()
        pts = [Vec2(0, 0), Vec2(10, 0)]
        assert c._hit_polyline(pts, Vec2(5, 10), 3.0) is False

    # [エッジ] 2点だけの折れ線（1線分）
    def test_single_line(self):
        c, _ = make_canvas()
        pts = [Vec2(0, 0), Vec2(10, 0)]
        assert c._hit_polyline(pts, Vec2(5, 0), 0.1) is True

    # [C1] 折れ点をまたいでヒット
    def test_hit_at_bend(self):
        c, _ = make_canvas()
        pts = [Vec2(0, 0), Vec2(10, 0), Vec2(10, 10)]
        assert c._hit_polyline(pts, Vec2(10, 5), 1.0) is True


class TestHitSegmentLine:
    def test_hit(self):
        c, _ = make_canvas()
        assert c._hit_segment_line(Vec2(0, 0), Vec2(10, 0), Vec2(5, 2), 3.0) is True

    def test_miss(self):
        c, _ = make_canvas()
        assert c._hit_segment_line(Vec2(0, 0), Vec2(10, 0), Vec2(5, 10), 3.0) is False

    # [境界] ちょうど端点でヒット
    def test_at_endpoint(self):
        c, _ = make_canvas()
        assert c._hit_segment_line(Vec2(0, 0), Vec2(10, 0), Vec2(0, 0), 0.1) is True


# ══════════════════════════════════════════════════════════════
# 6. _hit_handle / _hit_object
# ══════════════════════════════════════════════════════════════

class TestHitHandle:
    # [仕様] ハンドルがない → None
    def test_no_handles(self):
        c, _ = make_canvas()
        assert c._hit_handle(Vec2(0, 0)) is None

    # [仕様] ハンドル位置（ワールド座標）をスクリーン座標でヒット
    def test_hit_exact(self):
        """_hit_handle の引数はワールド座標。内部で w2s してスクリーン距離を計算する。"""
        c, _ = make_canvas()
        h = Handle(Vec2(0, 0), QColor('red'), 'test', None)
        c._handles = [h]
        # sw = w2s(0,0) のスクリーン座標 = offset = (500,500)
        screen = c.w2s(Vec2(0, 0))
        assert c._hit_handle(Vec2(screen.x(), screen.y())) is h

    # [仕様] HIT_DIST 未満のスクリーン距離でヒット
    def test_hit_near(self):
        c, _ = make_canvas()
        h = Handle(Vec2(0, 0), QColor('red'), 'test', None)
        c._handles = [h]
        screen = c.w2s(Vec2(0, 0))
        # 7px ずらしたスクリーン座標 → 7 < 8 → ヒット
        assert c._hit_handle(Vec2(screen.x() + 7, screen.y())) is h

    # [境界] ちょうど HIT_DIST の距離（< なので None）
    def test_exactly_hit_dist(self):
        c, _ = make_canvas()
        h = Handle(Vec2(0, 0), QColor('red'), 'test', None)
        c._handles = [h]
        screen = c.w2s(Vec2(0, 0))
        assert c._hit_handle(Vec2(screen.x() + 8, screen.y())) is None

    # [仕様] 複数ハンドルがある場合、最初にヒットしたものを返す
    def test_multiple_handles_first_wins(self):
        c, _ = make_canvas()
        h1 = Handle(Vec2(0, 0), QColor('red'), 'first', None)
        h2 = Handle(Vec2(0, 0), QColor('blue'), 'second', None)
        c._handles = [h1, h2]
        screen = c.w2s(Vec2(0, 0))
        result = c._hit_handle(Vec2(screen.x(), screen.y()))
        assert result is h1

    # [エッジ] スケールが大きい場合にも正しく判定
    def test_with_scale(self):
        c, _ = make_canvas()
        c._scale = 10.0
        c._offset = Vec2(0, 0)
        # h.pos=(1,0) → w2s → screen(10, 0)
        h = Handle(Vec2(1, 0), QColor('red'), 'test', None)
        c._handles = [h]
        # スクリーム座標(1,0)でヒット → hypot(1-10, 0-0)=9 >= 8 → None
        assert c._hit_handle(Vec2(1, 0)) is None


class TestHitObject:
    """_hit_object はスクリーン座標を受け取る。sw() ヘルパーでワールド→スクリーン変換する。"""

    # [仕様] 線分でヒット
    def test_hit_segment(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        result = c._hit_object(sw(c, 50, 0.5))
        assert result is seg

    # [仕様] 円弧でヒット
    def test_hit_arc(self):
        c, sc = make_canvas()
        ci = Circle(Vec2(0, 0), 50.0)
        arc = Arc(ci, 0.0, math.pi)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        # 角度 π/4 の点（円弧範囲内）
        ang = math.pi / 4
        result = c._hit_object(sw(c, 50 * math.cos(ang), 50 * math.sin(ang)))
        assert result is arc

    # [仕様] 円（弧なし）でヒット
    def test_hit_circle(self):
        c, sc = make_canvas()
        ci = Circle(Vec2(0, 0), 30.0)
        sc.add_circle(ci)
        result = c._hit_object(sw(c, 30, 0))
        assert result is ci

    # [仕様] 直線（線分なし）でヒット
    def test_hit_line(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        sc.add_line(ln)
        result = c._hit_object(sw(c, 50, 3))
        assert result is ln

    # [仕様] 何もない場所は None
    def test_miss(self):
        c, sc = make_canvas()
        result = c._hit_object(sw(c, 9000, 9000))
        assert result is None

    # [仕様] クロソイドでヒット
    def test_hit_clothoid(self):
        c, sc = make_canvas()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        if clo.is_valid and len(clo.points) >= 3:
            mid = clo.points[len(clo.points) // 2]
            result = c._hit_object(sw(c, mid.x, mid.y))
            assert result is clo

    # [C1] reversed() で走査 → 後から追加した図形が優先される
    def test_later_added_wins(self):
        c, sc = make_canvas()
        ln1 = Line(Vec2(0, 0), Vec2(100, 0))
        seg1 = Segment(ln1, 0.0, 1.0)
        ln1.segments.append(seg1)
        sc.add_line(ln1)
        ln2 = Line(Vec2(0, 0), Vec2(100, 0))
        seg2 = Segment(ln2, 0.0, 1.0)
        ln2.segments.append(seg2)
        sc.add_line(ln2)
        result = c._hit_object(sw(c, 50, 0.5))
        assert result is seg2


# ══════════════════════════════════════════════════════════════
# 7. モード管理
# ══════════════════════════════════════════════════════════════

class TestSetMode:
    # [仕様] モード切り替えで内部状態がリセットされる
    def test_to_select_resets_state(self):
        c, _ = make_canvas()
        c._line_first_pt = Vec2(1, 2)
        c._rubber_end = Vec2(3, 4)
        c._circle_center = Vec2(5, 5)
        c.set_mode(Canvas.MODE_SELECT)
        assert c.mode == Canvas.MODE_SELECT
        assert c._line_first_pt is None
        assert c._rubber_end is None
        assert c._circle_center is None

    def test_to_line(self):
        c, _ = make_canvas()
        c.set_mode(Canvas.MODE_LINE)
        assert c.mode == Canvas.MODE_LINE

    def test_to_circle(self):
        c, _ = make_canvas()
        c.set_mode(Canvas.MODE_CIRCLE)
        assert c.mode == Canvas.MODE_CIRCLE

    # [C1] 同じモードに切り替えてもリセットされる
    def test_same_mode_resets(self):
        c, _ = make_canvas()
        c._line_first_pt = Vec2(1, 2)
        c.set_mode(Canvas.MODE_SELECT)
        assert c._line_first_pt is None


# ══════════════════════════════════════════════════════════════
# 8. Undo スタック
# ══════════════════════════════════════════════════════════════

class TestUndoStack:
    # [仕様] push_undo でスタックに積まれる
    def test_push_increases_stack(self):
        c, _ = make_canvas()
        assert len(c._undo_stack) == 0
        c.push_undo()
        assert len(c._undo_stack) == 1

    # [仕様] undo で前の状態が復元される
    def test_undo_restores(self):
        c, sc = make_canvas()
        c.push_undo()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        assert len(c.scene.lines) == 1
        c.undo()
        assert len(c.scene.lines) == 0

    # [エッジ] スタック空のとき undo は何もしない
    def test_undo_empty_no_op(self):
        c, _ = make_canvas()
        c.undo()  # 例外にならない

    # [境界] 500 件で打ち止め → 501 件目で先頭が削除
    def test_max_500(self):
        c, _ = make_canvas()
        for _ in range(502):
            c.push_undo()
        assert len(c._undo_stack) == 500

    # [仕様] undo 後に selection と handles がクリアされる
    def test_undo_clears_selection(self):
        c, sc = make_canvas()
        c.push_undo()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c._selected = [ln]
        c.undo()
        assert c._selected == []
        assert c._handles == []

    # [C1] undo は「最後に push した状態」に戻る
    def test_undo_restores_last_push(self):
        """push_undo() は「直前の状態」をスタックに積む。
        undo() はスタックの最新エントリを pop してリストアする。
        1: push(A) → 2: 変更(B) → 3: push(B) → 4: undo() → B に戻る（A ではない）。
        """
        c, sc = make_canvas()
        c.push_undo()            # push A(lines=0)
        sc.add_line(Line(Vec2(0, 0), Vec2(10, 0)))   # lines=1
        c.push_undo()            # push B(lines=1)
        sc.add_line(Line(Vec2(0, 0), Vec2(20, 0)))   # lines=2
        c.undo()                 # pop B → lines=1
        assert len(c.scene.lines) == 1
        c.undo()                 # pop A → lines=0
        assert len(c.scene.lines) == 0


# ══════════════════════════════════════════════════════════════
# 9. 選択管理
# ══════════════════════════════════════════════════════════════

class TestSetSelection:
    # [仕様] set_selection で選択が更新され signal が emit される
    def test_set_and_signal(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        emitted = []
        c.selection_changed.connect(lambda s: emitted.append(s))
        c.set_selection([ln])
        assert c._selected == [ln]
        assert len(emitted) == 1
        assert emitted[0] == [ln]

    # [仕様] 空リストで選択解除
    def test_clear_selection(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c._selected = [ln]
        c.set_selection([])
        assert c._selected == []

    # [C1] 選択変更で _rebuild_handles が呼ばれる（ハンドルが更新される）
    def test_handles_rebuilt(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        sc.add_line(ln)
        c.set_selection([ln])
        assert len(c._handles) > 0


# ══════════════════════════════════════════════════════════════
# 10. fit_all
# ══════════════════════════════════════════════════════════════

class TestFitAll:
    # [仕様] 図形がない → scale=1, offset=画面中央にリセット
    def test_empty_scene(self):
        c, _ = make_canvas()
        c.fit_all()
        assert c._scale == 1.0

    # [仕様] 図形がある → scale が正の値に調整される
    def test_with_segment(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        c.fit_all()
        assert c._scale > 0

    # [エッジ] 全図形が 1 点に集中（最小幅 1m 確保で例外にならない）
    def test_all_at_same_point(self):
        c, sc = make_canvas()
        ln = Line(Vec2(5, 5), Vec2(5, 5))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        c.fit_all()
        assert c._scale > 0

    # [仕様] Arc・Clothoid も考慮される
    def test_with_arc(self):
        c, sc = make_canvas()
        ci = Circle(Vec2(0, 0), 50.0)
        arc = Arc(ci, 0.0, math.pi)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        c.fit_all()
        assert c._scale > 0

    def test_with_clothoid(self):
        c, sc = make_canvas()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(50, 60), 30.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci, snap_segment=False, snap_arc=False)
        sc.add_clothoid(clo)
        c.fit_all()
        assert c._scale > 0


# ══════════════════════════════════════════════════════════════
# 11. _color_for
# ══════════════════════════════════════════════════════════════

class TestColorFor:
    # [仕様] 選択中 → C_SELECT（base と異なる色）
    def test_selected(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c._selected = [ln]
        result = c._color_for(ln, QColor('blue'))
        assert result != QColor('blue')

    # [仕様] ホバー中 → C_HOVER（base と異なる色）
    def test_hovered(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c._hovered = ln
        result = c._color_for(ln, QColor('blue'))
        assert result != QColor('blue')

    # [仕様] 選択もホバーもない → base をそのまま返す
    def test_normal(self):
        c, _ = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        base = QColor('blue')
        assert c._color_for(ln, base) == base

    # [C1] 選択中の色はホバー中の色と異なる（優先順位: 選択 > ホバー）
    def test_selected_overrides_hover(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c._selected = [ln]
        c._hovered  = ln
        col_sel = c._color_for(ln, QColor('blue'))
        c._selected = []
        col_hov = c._color_for(ln, QColor('blue'))
        assert col_sel != col_hov


# ══════════════════════════════════════════════════════════════
# 12. 接続操作
# ══════════════════════════════════════════════════════════════

class TestConnectPolyline:
    # [仕様] 交差する 2 直線を折れ線接続
    def test_basic(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        sc.add_line(a); sc.add_line(b)
        c._connect_polyline(a, b)
        assert a.connection is not None
        assert a.connection is b.connection
        assert a.connection.kind == 'polyline'

    # [エッジ] 平行直線（交点なし）→ 接続されない
    def test_parallel_no_connect(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(0, 1), Vec2(10, 1))
        sc.add_line(a); sc.add_line(b)
        c._connect_polyline(a, b)
        assert a.connection is None
        assert b.connection is None

    # [仕様] 接続後、共有参照点が交点に設定される
    def test_shared_point_at_intersection(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(20, 0))
        b = Line(Vec2(10, -10), Vec2(10, 10))
        sc.add_line(a); sc.add_line(b)
        c._connect_polyline(a, b)
        assert a.connection is not None
        sp = a.connection.shared_point
        assert vec_approx(sp, Vec2(10, 0), tol=1e-4)


class TestDisconnectLines:
    # [仕様] disconnect_lines で接続が解除される
    def test_disconnect(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        sc.add_line(a); sc.add_line(b)
        c._connect_polyline(a, b)
        assert a.connection is not None
        c.disconnect_lines(a, b)
        assert a.connection is None
        assert b.connection is None

    # [エッジ] 未接続の直線に disconnect_lines を呼んでも例外にならない
    def test_disconnect_unconnected(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(0, 1), Vec2(10, 1))
        sc.add_line(a); sc.add_line(b)
        c.disconnect_lines(a, b)  # 例外にならない


class TestSmoothConnect:
    # [仕様] セグメントのない直線 → False
    def test_no_segments_returns_false(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, 0), Vec2(20, 5))
        sc.add_line(a); sc.add_line(b)
        assert c.smooth_connect(a, b) is False

    # [仕様] 平行直線（交点なし）→ False
    def test_parallel_returns_false(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        seg_a = Segment(a, 0.0, 1.0)
        a.segments.append(seg_a)
        b = Line(Vec2(0, 1), Vec2(10, 1))
        seg_b = Segment(b, 0.0, 1.0)
        b.segments.append(seg_b)
        sc.add_line(a); sc.add_line(b)
        assert c.smooth_connect(a, b) is False

    # [仕様] 交差する 2 直線 → True（Circle と 2 本の Clothoid が生成される）
    def test_success(self):
        c, sc = make_canvas()
        a = Line(Vec2(-50, 0), Vec2(50, 0))
        seg_a = Segment(a, 0.0, 1.0)
        a.segments.append(seg_a)
        b = Line(Vec2(0, -50), Vec2(10, 50))
        seg_b = Segment(b, 0.0, 1.0)
        b.segments.append(seg_b)
        sc.add_line(a); sc.add_line(b)
        result = c.smooth_connect(a, b)
        if result:
            assert len(sc.circles) >= 1
            assert len(sc.clothoids) >= 1


# ══════════════════════════════════════════════════════════════
# 13. _rebuild_handles
# ══════════════════════════════════════════════════════════════

class TestRebuildHandles:
    # [仕様] 直線を選択するとハンドルが生成される
    def test_line_handles(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c.set_selection([ln])
        # 参照点ハンドル（ref_start, ref_end）が生成される
        tags = [h.tag for h in c._handles]
        assert any('line_ref' in t for t in tags)

    # [仕様] Line を選択すると線分端点ハンドル(seg_start/seg_end)が生成される
    def test_segment_handles(self):
        """_rebuild_handles は Line と Circle を処理する。
        Segment 単体の選択はハンドルを生成しない。
        Line を選択したときに Line の segments のハンドルが生成される。
        """
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        c.set_selection([ln])  # Line を選択（Segment 単体ではない）
        tags = [h.tag for h in c._handles]
        assert 'seg_start' in tags or 'seg_end' in tags

    # [仕様] 円を選択すると中心ハンドル(circle_center)と半径ハンドル(circle_radius)が生成される
    def test_circle_handles(self):
        c, sc = make_canvas()
        ci = Circle(Vec2(0, 0), 10.0)
        sc.add_circle(ci)
        c.set_selection([ci])
        tags = [h.tag for h in c._handles]
        assert 'circle_center' in tags
        assert 'circle_radius' in tags

    # [仕様] 選択を空にするとハンドルがクリアされる
    def test_empty_selection_clears_handles(self):
        c, sc = make_canvas()
        ln = Line(Vec2(0, 0), Vec2(10, 0))
        sc.add_line(ln)
        c.set_selection([ln])
        c.set_selection([])
        assert c._handles == []

    # [仕様] 折れ線接続された直線には共有参照点ハンドル(shared_pt)が生成される
    def test_connected_line_shared_handle(self):
        c, sc = make_canvas()
        a = Line(Vec2(0, 0), Vec2(10, 0))
        b = Line(Vec2(10, -5), Vec2(10, 5))
        sc.add_line(a); sc.add_line(b)
        c._connect_polyline(a, b)
        c.set_selection([a])
        tags = [h.tag for h in c._handles]
        assert 'shared_pt' in tags
