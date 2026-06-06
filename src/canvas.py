"""
メイン編集キャンバス

座標系:
  ワールド座標 → w2s() → スクリーン座標
  w2s: screen_y = -world_y * scale + offset_y  (y反転)

  QPainter.drawArc の角度はワールド座標(y上向き・反時計正)をそのまま渡す。
  startAngle_16 = int(round(+world_angle_deg * 16))  ← 符号反転不要
"""
from __future__ import annotations
import math
from collections import deque
from typing import Optional
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor,
                           QPolygonF, QPainterPath)

from models import (Vec2, Line, Segment, Circle, Arc, Clothoid, Scene,
                    LineConnection)

# ─── 色定数 ────────────────────────────────────────────────────
C_LINE_REF = QColor(160, 160, 160)
C_SEGMENT = QColor(60, 120, 220)
C_CIRCLE = QColor(140, 60, 200)
C_CIRCLE_DIM = QColor(180, 130, 220)
C_ARC = QColor(120, 40, 180)
C_CLOTHOID = QColor(40, 180, 80)
C_SELECT = QColor(240, 160, 20)
C_HOVER = QColor(240, 240, 20)
C_HANDLE_REF = QColor(130, 130, 130)
C_HANDLE_END = QColor(220, 50, 50)
C_HANDLE_RAD = QColor(40, 180, 80)
C_HANDLE_INT = QColor(220, 140, 20)

HANDLE_RADIUS = 7  # px

# ─── ヒットテスト閾値 ───────────────────────────────────────────
HIT_DIST = 8  # px


def qp(v: Vec2) -> QPointF:
    """Vec2 を QPointF に変換する。QPainter の各描画メソッドに渡す際に使う。

    Returns
    -------
    QPointF
        (v.x, v.y) を持つ QPointF。
    """
    return QPointF(v.x, v.y)


class Handle:
    """キャンバス上でドラッグ可能な図形操作ハンドル。

    選択中の図形に対して :meth:`Canvas._rebuild_handles` が生成し、
    ドラッグ操作の入力を :meth:`Canvas._do_drag` に橋渡しする。
    ハンドルはキャンバス外部から直接操作せず、Canvas 内部でのみ使用する。

    Attributes
    ----------
    pos : Vec2
        ハンドルのワールド座標。描画位置とヒットテストの基準。
    color : QColor
        ハンドルの塗り色。役割ごとに異なる（端点=赤、参照点=灰、半径=緑、交点=橙）。
    tag : str
        役割識別文字列（例: ``"seg_start"``, ``"arc_end"``, ``"circle_radius"``）。
        :meth:`Canvas._do_drag` がこの値でドラッグ処理を分岐する。
    owner : Line or Segment or Circle or Arc or LineConnection
        このハンドルが操作する図形オブジェクト。
    """

    def __init__(self, pos: Vec2, color: QColor, tag: str, owner):
        self.pos = pos
        self.color = color
        self.tag = tag    # 役割識別文字列
        self.owner = owner  # 関連する図形オブジェクト


class Canvas(QWidget):
    """道路線形の 2D 編集キャンバス。

    PySide6 の QWidget を継承し、ワールド座標系でワールド図形（Line/Circle/Clothoid）を
    描画・選択・ドラッグ編集する。Undo スタック（最大 500 件）を内蔵する。

    座標変換:
        ワールド → スクリーン: :meth:`w2s` （y 軸反転）
        スクリーン → ワールド: :meth:`s2w`

    Signals
    -------
    selection_changed : list
        選択図形リストが変わったときに emit される。
    scene_changed : ()
        シーンの内容が変わったときに emit される（undo/redo/ドラッグ完了など）。
    mouse_world_pos : (float, float)
        マウス移動のたびにワールド座標 (x, y) を emit する。
    hover_changed : object
        ホバー対象の図形が変わったときに emit される。None は非ホバー。

    Attributes
    ----------
    scene : Scene
        編集対象のシーン。
    mode : str
        現在の編集モード。MODE_SELECT / MODE_LINE / MODE_CIRCLE のいずれか。
    MODE_SELECT : str
        選択・ドラッグ・パンモード。
    MODE_LINE : str
        直線描画モード。クリックで始点→終点を指定する。
    MODE_CIRCLE : str
        円描画モード。クリック+ドラッグで中心→半径を指定する。
    """
    selection_changed = Signal(list)   # 選択図形リスト
    scene_changed = Signal()       # シーン変更
    mouse_world_pos = Signal(float, float)  # マウスのワールド座標
    hover_changed = Signal(object)         # ホバー中の図形（None のとき非ホバー）
    measure_dist_changed = Signal(float)   # ラバーバンド対角距離（非測定時 -1）

    MODE_SELECT = "select"
    MODE_LINE = "line"
    MODE_CIRCLE = "circle"

    def __init__(self, scene: Scene, parent=None):
        """キャンバスを初期化する。

        Parameters
        ----------
        scene : Scene
            編集対象のシーン。
        parent : QWidget, optional
            親ウィジェット。
        """
        super().__init__(parent)
        self.scene = scene
        self.mode = self.MODE_SELECT

        # ビュー変換: world → screen
        self._offset = Vec2(400, 300)   # スクリーン原点
        self._scale = 1.0              # pixel per meter

        # 選択・ホバー
        self._selected: list = []
        self._hovered: object = None

        # ドラッグ状態
        self._drag_obj: object = None
        self._drag_tag: str = ""
        self._drag_start_screen = None
        self._drag_start_world = None
        self._pan_start_screen = None
        self._pan_offset_start = None
        self._is_panning: bool = False
        self._mouse_moved_px: float = 0

        # 直線モード
        self._line_first_pt: Optional[Vec2] = None
        self._last_line: Optional[Line] = None  # 折れ線連続用
        self._rubber_end: Optional[Vec2] = None  # ラバー線終点

        # 円モード
        self._circle_center: Optional[Vec2] = None
        self._rubber_radius: float = 0.0

        # ラバーバンド選択（Shift+ドラッグ）
        self._rubber_select_start: Optional[Vec2] = None  # スクリーン座標
        self._rubber_select_end: Optional[Vec2] = None    # スクリーン座標

        # ハンドルキャッシュ
        self._handles: list[Handle] = []

        # undo スタック (最大 500)
        self._undo_stack: deque[dict] = deque(maxlen=500)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ─── 座標変換 ────────────────────────────────────────────
    def w2s(self, p: Vec2) -> QPointF:
        """ワールド座標 → スクリーン座標（QPointF）に変換する。

        y 軸が反転する（上向き正 → 下向き正）。

        Parameters
        ----------
        p : Vec2
            ワールド座標。

        Returns
        -------
        QPointF
            スクリーン座標。screen_x = p.x * scale + offset.x、
            screen_y = -p.y * scale + offset.y。
        """
        return QPointF(p.x * self._scale + self._offset.x,
                       -p.y * self._scale + self._offset.y)

    def s2w(self, x: float, y: float) -> Vec2:
        """スクリーン座標 → ワールド座標（Vec2）に変換する（w2s の逆変換）。

        Parameters
        ----------
        x, y : float
            スクリーン座標（ピクセル）。

        Returns
        -------
        Vec2
            ワールド座標。
        """
        return Vec2((x - self._offset.x) / self._scale,
                    -(y - self._offset.y) / self._scale)

    def s2w_qp(self, p: QPointF) -> Vec2:
        """QPointF を受け取る :meth:`s2w` のラッパー。

        Parameters
        ----------
        p : QPointF
            スクリーン座標。

        Returns
        -------
        Vec2
            ワールド座標。
        """
        return self.s2w(p.x(), p.y())

    def scale_w2s(self, d: float) -> float:
        """ワールド距離 [m] → スクリーン距離 [px] に変換する。

        Returns
        -------
        float
            d * scale [px]。
        """
        return d * self._scale

    def scale_s2w(self, d: float) -> float:
        """スクリーン距離 [px] → ワールド距離 [m] に変換する。

        Returns
        -------
        float
            d / scale [m]。
        """
        return d / self._scale

    # ─── モード変更 ──────────────────────────────────────────
    def set_mode(self, mode: str):
        """編集モードを切り替える。

        描画中の折れ線・円のラバー線状態をリセットし、カーソルを更新する。

        Parameters
        ----------
        mode : str
            MODE_SELECT / MODE_LINE / MODE_CIRCLE のいずれか。
        """
        self.mode = mode
        self._line_first_pt = None
        self._last_line = None
        self._rubber_end = None
        self._circle_center = None
        if mode == self.MODE_SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    # ─── Undo ────────────────────────────────────────────────
    def push_undo(self):
        """現在のシーン状態を Undo スタックに積む。

        破壊的操作（ドラッグ開始・図形追加・削除）の直前に呼ぶ。
        スタックは最大 500 件で、超過分は古い方から自動削除される。
        """
        state = self.scene.to_dict()
        self._undo_stack.append(state)

    def undo(self):
        """直前の push_undo 時点へシーンを復元する。

        スタックが空のとき何もしない。
        復元後は選択・ハンドルをクリアして ``selection_changed`` と
        ``scene_changed`` を emit する。
        """
        if not self._undo_stack:
            return
        state = self._undo_stack.pop()
        self.scene = Scene.from_dict(state)
        self._selected.clear()
        self._handles.clear()
        self.selection_changed.emit([])
        self.scene_changed.emit()
        self.update()

    # ─── 選択 ────────────────────────────────────────────────
    def set_selection(self, objs: list):
        """選択リストを外部から設定する。

        右パネル等、キャンバス外のコードから選択を変更したいときに使う。
        ハンドルを再構築して ``selection_changed`` を emit する。

        Parameters
        ----------
        objs : list
            新しく選択する図形オブジェクトのリスト。
        """
        self._selected = list(objs)
        self._rebuild_handles()
        self.selection_changed.emit(self._selected)
        self.update()

    def _rebuild_handles(self):
        """選択図形に対応するハンドルを再構築して ``_handles`` リストを更新する。

        クロソイドに吸着（snap）または分割（split）された端点はハンドルから除外する。
        Line の接続共有点（``LineConnection.shared_point``）は重複して追加しない。
        """
        self._handles.clear()
        seen_connections = set()

        # クロソイドにsnapされている端点を収集（ハンドルを出さない）
        snapped_seg_ends: set[tuple] = set()   # (seg_id, 'start'|'end')
        snapped_arc_ends: set[tuple] = set()   # (arc_id, 'start'|'end')
        for clo in self.scene.clothoids:
            if not clo.is_valid:
                continue
            if clo.snap_segment and clo._line_pt is not None:
                # snap=on: 線側接点に吸着している端点
                t_x = clo.line.project_t(clo._line_pt)
                for seg in clo.line.segments:
                    if abs(seg.t_end - t_x) < 1e-4:
                        snapped_seg_ends.add((seg.id, 'end'))
                    if abs(seg.t_start - t_x) < 1e-4:
                        snapped_seg_ends.add((seg.id, 'start'))
            if not clo.snap_segment and clo._split_seg_ids:
                # split=on: 分割端点（接点）はハンドル不要
                segs_by_id = {s.id: s for s in clo.line.segments}
                for sid in clo._split_seg_ids:
                    seg = segs_by_id.get(sid)
                    if seg:
                        # AX の end と XB の start が接点 → どちらも非表示
                        snapped_seg_ends.add((sid, 'end'))
                        snapped_seg_ends.add((sid, 'start'))
            if clo.snap_arc and clo._circle_pt is not None:
                ang = math.atan2(clo._circle_pt.y - clo.circle.center.y,
                                 clo._circle_pt.x - clo.circle.center.x)
                for arc in clo.circle.arcs:
                    if abs(arc.angle_start - ang) < 1e-4:
                        snapped_arc_ends.add((arc.id, 'start'))
                    if abs(arc.angle_end - ang) < 1e-4:
                        snapped_arc_ends.add((arc.id, 'end'))
            if not clo.snap_arc and clo._split_arc_ids:
                for aid in clo._split_arc_ids:
                    snapped_arc_ends.add((aid, 'end'))
                    snapped_arc_ends.add((aid, 'start'))

        for obj in self._selected:
            if isinstance(obj, Line):
                conn = obj.connection
                shared_pos = conn.shared_point if conn else None

                def is_shared(pt):
                    return (shared_pos is not None
                            and (pt - shared_pos).length() < 1e-6)

                rs, re = obj.ref_start, obj.ref_end
                if not is_shared(rs):
                    self._handles.append(
                        Handle(rs, C_HANDLE_REF, "line_ref_start", obj))
                if not is_shared(re):
                    self._handles.append(
                        Handle(re, C_HANDLE_REF, "line_ref_end", obj))

                for seg in obj.segments:
                    if (not is_shared(seg.start)
                            and (seg.id, 'start') not in snapped_seg_ends):
                        self._handles.append(
                            Handle(seg.start, C_HANDLE_END, "seg_start", seg))
                    if (not is_shared(seg.end)
                            and (seg.id, 'end') not in snapped_seg_ends):
                        self._handles.append(
                            Handle(seg.end, C_HANDLE_END, "seg_end", seg))

                if conn:
                    cid = id(conn)
                    if cid not in seen_connections:
                        seen_connections.add(cid)
                        self._handles.append(Handle(
                            conn.shared_point, C_HANDLE_INT,
                            "shared_pt", conn))

            elif isinstance(obj, Circle):
                self._handles.append(
                    Handle(obj.center, C_HANDLE_REF, "circle_center", obj))
                rad_pt = Vec2(obj.center.x + obj.radius, obj.center.y)
                self._handles.append(
                    Handle(rad_pt, C_HANDLE_RAD, "circle_radius", obj))
                for arc in obj.arcs:
                    if (arc.id, 'start') not in snapped_arc_ends:
                        self._handles.append(
                            Handle(arc.start, C_HANDLE_END, "arc_start", arc))
                    if (arc.id, 'end') not in snapped_arc_ends:
                        self._handles.append(
                            Handle(arc.end, C_HANDLE_END, "arc_end", arc))

    # ─── ヒットテスト ─────────────────────────────────────────
    def _hit_handle(self, sw: Vec2) -> Optional[Handle]:
        """スクリーン座標 sw に HIT_DIST (8px) 以内のハンドルを返す。

        Parameters
        ----------
        sw : Vec2
            スクリーン座標（ピクセル）。

        Returns
        -------
        Handle or None
            最初にヒットしたハンドル。なければ None。
        """
        px = HIT_DIST
        for h in self._handles:
            sp = self.w2s(h.pos)
            if math.hypot(sw.x - sp.x(), sw.y - sp.y()) < px:
                return h
        return None

    def _hit_object(self, sw: Vec2) -> Optional[object]:
        """ワールド座標 sw に最も近い図形オブジェクトを返す。

        優先順位（高→低）: Clothoid → Arc → Circle → Segment → Line。
        各リストを reversed() で走査するため、後から追加した図形が優先される。

        Parameters
        ----------
        sw : Vec2
            判定するワールド座標。

        Returns
        -------
        Clothoid or Arc or Circle or Segment or Line or None
            HIT_DIST 以内に最も近い図形。なければ None。
        """
        """ワールド座標 sw でヒットした図形を返す"""
        w = self.s2w(sw.x, sw.y)
        px = self.scale_s2w(HIT_DIST)

        # クロソイド
        for c in reversed(self.scene.clothoids):
            if self._hit_polyline(c.points, w, px):
                return c
        # 円弧
        for ci in reversed(self.scene.circles):
            for arc in ci.arcs:
                if self._hit_arc(ci, arc, w, px):
                    return arc
        # 円
        for ci in reversed(self.scene.circles):
            d = math.hypot(w.x - ci.center.x, w.y - ci.center.y)
            if abs(d - ci.radius) < px:
                return ci
        # 線分
        for ln in reversed(self.scene.lines):
            for seg in ln.segments:
                if self._hit_segment_line(seg.start, seg.end, w, px):
                    return seg
        # 直線（参照線）
        for ln in reversed(self.scene.lines):
            if self._hit_infinite_line(ln, w, px):
                return ln
        return None

    def _hit_polyline(self, pts: list[Vec2], w: Vec2, tol: float) -> bool:
        """折れ線（点列）が点 w から tol 以内を通るか判定する。

        Parameters
        ----------
        pts : list[Vec2]
            折れ線を構成するワールド座標の点列。
        w : Vec2
            判定するワールド座標。
        tol : float
            許容距離 [m]（ワールド単位）。

        Returns
        -------
        bool
            いずれかの線分が tol 以内に入れば True。
        """
        for i in range(len(pts) - 1):
            if self._dist_point_segment(w, pts[i], pts[i + 1]) < tol:
                return True
        return False

    def _hit_segment_line(self, a: Vec2, b: Vec2, w: Vec2, tol: float) -> bool:
        """線分 a-b が点 w から tol 以内か判定する。

        Parameters
        ----------
        a, b : Vec2
            線分の両端点（ワールド座標）。
        w : Vec2
            判定するワールド座標。
        tol : float
            許容距離 [m]（ワールド単位）。

        Returns
        -------
        bool
        """
        return self._dist_point_segment(w, a, b) < tol

    def _hit_infinite_line(self, ln: Line, w: Vec2, tol: float) -> bool:
        """無限直線 ln が点 w から tol 以内か判定する。

        Parameters
        ----------
        ln : Line
            判定する直線。
        w : Vec2
            判定するワールド座標。
        tol : float
            許容距離 [m]（ワールド単位）。

        Returns
        -------
        bool
        """
        return ln.distance_to(w) < tol

    def _hit_arc(self, ci: Circle, arc: Arc, w: Vec2, tol: float) -> bool:
        """円弧 arc が点 w から tol 以内か判定する。

        円弧の半径方向距離と角度範囲の両方を確認する。

        Parameters
        ----------
        ci : Circle
            arc が属する円。
        arc : Arc
            判定する円弧。
        w : Vec2
            判定するワールド座標。
        tol : float
            半径方向の許容距離 [m]（ワールド単位）。

        Returns
        -------
        bool
        """
        d = math.hypot(w.x - ci.center.x, w.y - ci.center.y)
        if abs(d - ci.radius) > tol:
            return False
        ang = math.atan2(w.y - ci.center.y, w.x - ci.center.x)
        return self._angle_in_arc(ang, arc.angle_start, arc.angle_end)

    def _angle_in_arc(self, ang: float, a_start: float, a_end: float) -> bool:
        """角度 ang が [a_start, a_end] の CCW 弧範囲に含まれるか判定する。

        Parameters
        ----------
        ang : float
            判定する角度 [rad]。
        a_start : float
            弧の開始角度 [rad]（ワールド座標、反時計正）。
        a_end : float
            弧の終了角度 [rad]（ワールド座標、反時計正）。

        Returns
        -------
        bool
        """
        span = (a_end - a_start) % (2 * math.pi)
        diff = (ang - a_start) % (2 * math.pi)
        return diff <= span

    @staticmethod
    def _dist_point_segment(p: Vec2, a: Vec2, b: Vec2) -> float:
        """点 p から線分 a-b への最短距離を返す。

        Parameters
        ----------
        p : Vec2
            判定する点。
        a, b : Vec2
            線分の両端点。

        Returns
        -------
        float
            最短距離 [m]。a == b のとき |p - a|。
        """
        ab = b - a
        l2 = ab.dot(ab)
        if l2 < 1e-24:
            return (p - a).length()
        t = max(0.0, min(1.0, (p - a).dot(ab) / l2))
        proj = a + ab * t
        return (p - proj).length()

    # ─── ラバーバンド選択 ────────────────────────────────────
    def _arc_in_rect(self, ci: Circle, arc: Arc,
                     wx0: float, wy0: float,
                     wx1: float, wy1: float) -> bool:
        """Arc が矩形 [wx0,wx1]×[wy0,wy1] に完全に含まれるか判定する。

        始点・終点と弧上のサンプル点（約 10° 刻み）が全て矩形内に
        収まるかどうかで判定する。

        Parameters
        ----------
        ci : Circle
            arc が属する円。
        arc : Arc
            判定する円弧。
        wx0, wy0, wx1, wy1 : float
            ワールド座標の矩形（wx0 < wx1、wy0 < wy1）。

        Returns
        -------
        bool
        """
        def in_r(x, y):
            return wx0 <= x <= wx1 and wy0 <= y <= wy1

        if not in_r(arc.start.x, arc.start.y):
            return False
        if not in_r(arc.end.x, arc.end.y):
            return False
        cx, cy, r = ci.center.x, ci.center.y, ci.radius
        span = arc.arc_angle()
        n = max(8, int(abs(span) / math.radians(10)))
        for i in range(1, n):
            ang = arc.angle_start + span * i / n
            if not in_r(cx + r * math.cos(ang), cy + r * math.sin(ang)):
                return False
        return True

    def _objects_in_world_rect(self, wx0: float, wy0: float,
                               wx1: float, wy1: float) -> list:
        """ワールド矩形 [wx0,wx1]×[wy0,wy1] に含まれる図形リストを返す。

        選択ルール:
        - Clothoid: 全点が矩形内 → Clothoid を追加
        - Arc: 全サンプル点が矩形内 → Arc と親 Circle を追加
        - Circle（弧なし）: バウンディングボックスが矩形内 → Circle を追加
        - Segment: 両端点が矩形内 → Segment と親 Line を追加

        重複は id() で排除し、追加順を保持して返す。

        Parameters
        ----------
        wx0, wy0, wx1, wy1 : float
            ワールド座標の矩形（wx0 < wx1、wy0 < wy1）。

        Returns
        -------
        list
            含まれる図形オブジェクトのリスト（重複なし）。
        """
        def in_r(x, y):
            return wx0 <= x <= wx1 and wy0 <= y <= wy1

        seen: set[int] = set()
        result: list = []

        def add(obj):
            oid = id(obj)
            if oid not in seen:
                seen.add(oid)
                result.append(obj)

        # Clothoid: 全点が矩形内
        for clo in self.scene.clothoids:
            if clo.points and all(in_r(p.x, p.y) for p in clo.points):
                add(clo)

        # 円弧あり → 含まれる Arc と親 Circle を追加
        # 円弧なし → バウンディングボックスで判定
        for ci in self.scene.circles:
            if ci.arcs:
                for arc in ci.arcs:
                    if self._arc_in_rect(ci, arc, wx0, wy0, wx1, wy1):
                        add(arc)
                        add(ci)
            else:
                cx, cy, rad = ci.center.x, ci.center.y, ci.radius
                if (in_r(cx - rad, cy) and in_r(cx + rad, cy)
                        and in_r(cx, cy - rad) and in_r(cx, cy + rad)):
                    add(ci)

        # Segment: 両端点が矩形内 → Segment と親 Line を追加
        for ln in self.scene.lines:
            for seg in ln.segments:
                if (in_r(seg.start.x, seg.start.y)
                        and in_r(seg.end.x, seg.end.y)):
                    add(seg)
                    add(ln)

        return result

    def _complete_rubber_select(self) -> list:
        """ラバーバンド矩形に含まれる図形リストを返す。

        スクリーン座標の矩形をワールド座標に変換し、
        :meth:`_objects_in_world_rect` を呼び出す。
        矩形サイズが 4px 未満のときは空リストを返す（クリック扱い）。

        Returns
        -------
        list
            選択された図形オブジェクトのリスト。
        """
        s, e = self._rubber_select_start, self._rubber_select_end
        if s is None or e is None:
            return []
        if abs(e.x - s.x) < 4 and abs(e.y - s.y) < 4:
            return []
        sx0, sy0 = min(s.x, e.x), min(s.y, e.y)
        sx1, sy1 = max(s.x, e.x), max(s.y, e.y)
        # スクリーン y 下向き → ワールド y 上向き
        # 画面上端(sy0) → ワールド y 最大、画面下端(sy1) → ワールド y 最小
        w_tl = self.s2w(sx0, sy0)
        w_br = self.s2w(sx1, sy1)
        return self._objects_in_world_rect(w_tl.x, w_br.y, w_br.x, w_tl.y)

    # ─── 全体表示 ────────────────────────────────────────────
    def fit_all(self):
        """全図形の AABB を計算し、10% マージンで画面全体に収まるよう表示を調整する。

        図形がない場合はスケール 1.0、中心原点にリセットする。
        全図形が 1 点に集中する場合は最小幅 1m を確保する。
        """
        pts = []
        for ln in self.scene.lines:
            pts.extend([ln.ref_start, ln.ref_end])
            for seg in ln.segments:
                pts.extend([seg.start, seg.end])
        for ci in self.scene.circles:
            r = ci.radius
            c = ci.center
            pts.extend([Vec2(c.x - r, c.y - r), Vec2(c.x + r, c.y + r)])
        for clo in self.scene.clothoids:
            pts.extend(clo.points)
        if not pts:
            self._offset = Vec2(self.width() / 2, self.height() / 2)
            self._scale = 1.0
            self.update()
            return
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        mx = max(xmax - xmin, 1.0)
        my = max(ymax - ymin, 1.0)
        margin = 0.1
        sx = self.width() / (mx * (1 + 2 * margin))
        sy = self.height() / (my * (1 + 2 * margin))
        self._scale = min(sx, sy)
        cx = (xmin + xmax) / 2
        cy = (ymin + ymax) / 2
        self._offset = Vec2(self.width() / 2 - cx * self._scale,
                            self.height() / 2 + cy * self._scale)
        self.update()

    # ─── 描画 ────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(30, 30, 35))

        self._draw_grid(painter)

        # 直線参照線
        for ln in self.scene.lines:
            self._draw_line_ref(painter, ln)
        # 線分
        for ln in self.scene.lines:
            for seg in ln.segments:
                self._draw_segment(painter, seg)
        # 円
        for ci in self.scene.circles:
            self._draw_circle(painter, ci)
        # 円弧
        for ci in self.scene.circles:
            for arc in ci.arcs:
                self._draw_arc(painter, arc)
        # クロソイド
        for clo in self.scene.clothoids:
            self._draw_clothoid(painter, clo)
        # ラバー線（描画モード）
        self._draw_rubber(painter)
        # ラバーバンド選択矩形（Shift+ドラッグ）
        self._draw_rubber_select(painter)
        # ハンドル
        self._draw_handles(painter)

    def _color_for(self, obj, base: QColor) -> QColor:
        """選択中・ホバー中に応じたハイライト色を返す。

        Returns
        -------
        QColor
            選択中 → 黄橙色（#FFA500）、ホバー中 → 黄色（#FFFF00）、
            それ以外 → base。
        """
        if obj in self._selected:
            return C_SELECT
        if obj is self._hovered:
            return C_HOVER
        return base

    def _draw_grid(self, painter: QPainter):
        """グリッドを描画する。

        グリッド間隔はズームレベルに応じて 1/2/5/10 の系列から自動選択する
        （スクリーン上で約 60px 以上の間隔を確保）。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        """
        pen = QPen(QColor(50, 55, 60))
        pen.setWidth(1)
        painter.setPen(pen)
        # グリッド間隔を適切に選択
        raw = self.scale_s2w(60)
        mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
        steps = [1, 2, 5, 10]
        grid = mag * min((s for s in steps if s *
                         mag >= raw * 0.9), default=10)
        w, h = self.width(), self.height()
        # 縦線
        x0 = self.s2w(0, 0).x
        x1 = self.s2w(w, 0).x
        gx0 = math.floor(x0 / grid) * grid
        x = gx0
        while x <= x1 + grid:
            sx = self.w2s(Vec2(x, 0)).x()
            painter.drawLine(int(sx), 0, int(sx), h)
            x += grid
        # 横線
        y0 = self.s2w(0, h).y
        y1 = self.s2w(0, 0).y
        gy0 = math.floor(y0 / grid) * grid
        y = gy0
        while y <= y1 + grid:
            sy = self.w2s(Vec2(0, y)).y()
            painter.drawLine(0, int(sy), w, int(sy))
            y += grid

    def _draw_line_ref(self, painter: QPainter, ln: Line):
        """直線参照線（破線）と参照点マーカー（小円）を描画する。

        直線は画面端を超える大きなスケールで両端を求め、画面端まで引き伸ばす。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        ln : Line
            描画する直線。
        """
        color = self._color_for(ln, C_LINE_REF)
        pen = QPen(color, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        # 画面端まで引く
        w, h = self.width(), self.height()
        d = ln.direction
        if abs(d.x) < 1e-9 and abs(d.y) < 1e-9:
            return
        # 参照始点から両方向に大きな距離
        big = self.scale_s2w(max(w, h) * 2)
        p1 = ln.ref_start - d * big
        p2 = ln.ref_start + d * big
        painter.drawLine(self.w2s(p1), self.w2s(p2))
        # 参照点マーカー
        pen2 = QPen(color, 1)
        painter.setPen(pen2)
        for pt in [ln.ref_start, ln.ref_end]:
            sp = self.w2s(pt)
            r = 3
            painter.drawEllipse(sp, r, r)

    def _draw_segment(self, painter: QPainter, seg: Segment):
        """線分を描画する。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        seg : Segment
            描画する線分。
        """
        color = self._color_for(seg, C_SEGMENT)
        pen = QPen(color, 3)
        painter.setPen(pen)
        painter.drawLine(self.w2s(seg.start), self.w2s(seg.end))

    def _draw_circle(self, painter: QPainter, ci: Circle):
        """円を描画する。

        円弧を持つ円は薄い点線、持たない円は通常の実線で描画する。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        ci : Circle
            描画する円。
        """
        has_arc = bool(ci.arcs)
        if has_arc:
            color = self._color_for(ci, C_CIRCLE_DIM)
            pen = QPen(color, 1, Qt.PenStyle.DotLine)
        else:
            color = self._color_for(ci, C_CIRCLE)
            pen = QPen(color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        c = self.w2s(ci.center)
        r = self.scale_w2s(ci.radius)
        painter.drawEllipse(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))

    def _draw_arc(self, painter: QPainter, arc: Arc):
        """円弧を描画する。

        Qt の ``drawArc`` はワールド座標（y 上向き、反時計正）の角度をそのまま使える。
        w2s の y 反転と Qt の角度定義が打ち消し合うため、符号反転は不要。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        arc : Arc
            描画する円弧。
        """
        ci = arc.circle
        color = self._color_for(arc, C_ARC)
        pen = QPen(color, 4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        c = self.w2s(ci.center)
        r = self.scale_w2s(ci.radius)
        # Qt drawArc の角度は数学座標（y上向き、反時計が正）で定義されており、
        # w2s の y 反転とは無関係に world 角度をそのまま使える。
        # startAngle: world の angle_start (度) * 16
        # spanAngle:  world の arc_angle  (度) * 16 (正 = 反時計 = CCW)
        start_ang_deg = math.degrees(arc.angle_start)
        span_ang_deg = math.degrees(arc.arc_angle())
        painter.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                        int(round(start_ang_deg * 16)),
                        int(round(span_ang_deg * 16)))

    def _draw_clothoid(self, painter: QPainter, clo: Clothoid):
        """クロソイド曲線と接点マーカー（菱形）を描画する。

        ``is_valid=False`` または ``points`` が空のとき何も描画しない。
        接点マーカーはドラッグ不可の表示専用で、ハンドルとは別に描画する。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        clo : Clothoid
            描画するクロソイド。
        """
        if not clo.is_valid or not clo.points:
            return
        color = self._color_for(clo, C_CLOTHOID)
        pen = QPen(color, 2)
        painter.setPen(pen)
        pts = clo.points
        path = QPainterPath(self.w2s(pts[0]))
        for p in pts[1:]:
            path.lineTo(self.w2s(p))
        painter.drawPath(path)

        # 接点マーカー（小さい菱形）
        # ハンドルではない（ドラッグ不可）ので選択状態に関係なく固定色で表示
        self._draw_contact_diamond(
            painter, clo._line_pt, QColor(255, 220, 60))  # 線側: 黄
        self._draw_contact_diamond(
            painter, clo._circle_pt, QColor(255, 140, 40))  # 円側: 橙

    def _draw_contact_diamond(self, painter: QPainter, pt,
                              color: QColor, half: float = 6.0):
        """接点を菱形マーカーで描画（ハンドルではない表示専用）"""
        if pt is None:
            return
        sp = self.w2s(pt)
        cx, cy = sp.x(), sp.y()
        diamond = QPolygonF([
            QPointF(cx, cy - half),  # 上
            QPointF(cx + half, cy),         # 右
            QPointF(cx, cy + half),  # 下
            QPointF(cx - half, cy),         # 左
        ])
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(diamond)
        painter.setBrush(Qt.BrushStyle.NoBrush)   # 後続の描画に影響しないようリセット

    def _draw_rubber(self, painter: QPainter):
        """ラバー線（描画中の仮表示）を描画する。

        直線モードでは始点から現在マウス位置への破線を、
        円モードでは中心から現在半径の円を描画する。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        """
        pen = QPen(QColor(200, 200, 200, 128), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if (self.mode == self.MODE_LINE
                and self._line_first_pt and self._rubber_end):
            painter.drawLine(self.w2s(self._line_first_pt),
                             self.w2s(self._rubber_end))
        elif (self.mode == self.MODE_CIRCLE
              and self._circle_center and self._rubber_radius > 0):
            c = self.w2s(self._circle_center)
            r = self.scale_w2s(self._rubber_radius)
            painter.drawEllipse(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))

    def _draw_rubber_select(self, painter: QPainter):
        """ラバーバンド選択矩形を半透明で描画する。

        Shift+ドラッグ中のみ描画する。青系の破線枠と半透明塗りで表示する。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        """
        if (self._rubber_select_start is None
                or self._rubber_select_end is None):
            return
        s, e = self._rubber_select_start, self._rubber_select_end
        x0, y0 = min(s.x, e.x), min(s.y, e.y)
        x1, y1 = max(s.x, e.x), max(s.y, e.y)
        rect = QRectF(x0, y0, x1 - x0, y1 - y0)
        painter.setPen(QPen(QColor(80, 200, 255), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor(80, 200, 255, 30)))
        painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 対角線（始点 → 終点）を実線で描画
        painter.setPen(QPen(QColor(80, 200, 255), 1, Qt.PenStyle.SolidLine))
        painter.drawLine(QPointF(s.x, s.y), QPointF(e.x, e.y))

    def _draw_handles(self, painter: QPainter):
        """選択中の図形のハンドルを円として描画する。

        Parameters
        ----------
        painter : QPainter
            描画先のペインター。
        """
        for h in self._handles:
            sp = self.w2s(h.pos)
            painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
            painter.setBrush(QBrush(h.color))
            painter.drawEllipse(sp, HANDLE_RADIUS, HANDLE_RADIUS)

    # ─── マウスイベント ──────────────────────────────────────
    def mousePressEvent(self, event):
        """マウスボタン押下イベントを処理する。

        **左ボタン + 選択モード**:

        1. :meth:`_hit_handle` でハンドルヒット判定。ヒットすれば
           :meth:`push_undo` を呼んでからドラッグ対象として ``_drag_obj``
           に設定する（ドラッグ前の状態を Undo スタックに保存）。
        2. ハンドルなし → :meth:`_hit_object` で図形ヒット判定。
           ``Shift`` なしでヒット: その図形のみ選択。
           ``Shift`` + ヒット: 選択のトグル。
           ヒットなし: 選択解除。
        3. :meth:`_rebuild_handles` → ``selection_changed.emit()``
        4. パン開始のための ``_pan_start_screen``・``_pan_offset_start`` を記録。

        **左ボタン + 直線モード**: :meth:`_line_click` を呼ぶ。

        **左ボタン + 円モード**: ``_circle_center = w`` に中心点を記憶する。
        リリース時に半径を確定する。

        **中ボタン**: ``_pan_start_screen`` / ``_pan_offset_start`` を記録して
        パンを開始する。

        Parameters
        ----------
        event : QMouseEvent
            PySide6 マウスイベント。
        """
        pos = event.position()
        sw = Vec2(pos.x(), pos.y())
        w = self.s2w(sw.x, sw.y)
        btn = event.button()

        if btn == Qt.MouseButton.MiddleButton:
            self._pan_start_screen = sw
            self._pan_offset_start = Vec2(self._offset.x, self._offset.y)
            self._is_panning = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if btn == Qt.MouseButton.LeftButton:
            self._drag_start_screen = sw
            self._mouse_moved_px = 0

            if self.mode == self.MODE_SELECT:
                # ハンドルヒット?
                h = self._hit_handle(sw)
                if h:
                    self.push_undo()          # ドラッグ前の状態を保存
                    self._drag_obj = h.owner
                    self._drag_tag = h.tag
                    return
                # 図形ヒット?
                hit = self._hit_object(sw)
                if hit is not None:
                    mods = event.modifiers()
                    if mods & Qt.KeyboardModifier.ShiftModifier:
                        if hit in self._selected:
                            self._selected.remove(hit)
                        else:
                            self._selected.append(hit)
                    else:
                        self._selected = [hit]
                    self._rebuild_handles()
                    self.selection_changed.emit(self._selected)
                    self.update()
                else:
                    mods = event.modifiers()
                    if mods & Qt.KeyboardModifier.ShiftModifier:
                        # Shift+空白ドラッグ → ラバーバンド選択開始
                        self._rubber_select_start = sw
                        self._rubber_select_end = sw
                    else:
                        self._pan_start_screen = sw
                        self._pan_offset_start = Vec2(
                            self._offset.x, self._offset.y)
                        self._is_panning = True
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)

            elif self.mode == self.MODE_LINE:
                self._line_click(w)

            elif self.mode == self.MODE_CIRCLE:
                self._circle_center = w
                self._rubber_radius = 0.0

    def mouseMoveEvent(self, event):
        """マウス移動イベントを処理する。

        パン中はオフセットを更新する。ドラッグ中は移動量が 2px を超えた時点で
        :meth:`_do_drag` を呼ぶ。直線/円モードのラバー線を更新し、
        ホバー対象を更新して ``hover_changed`` と ``mouse_world_pos`` を emit する。

        Parameters
        ----------
        event : QMouseEvent
            PySide6 マウスイベント。
        """
        pos = event.position()
        sw = Vec2(pos.x(), pos.y())
        w = self.s2w(sw.x, sw.y)

        if self._is_panning and self._pan_start_screen:
            dx = sw.x - self._pan_start_screen.x
            dy = sw.y - self._pan_start_screen.y
            self._mouse_moved_px = math.hypot(dx, dy)  # パン中も移動量を記録
            self._offset = Vec2(self._pan_offset_start.x + dx,
                                self._pan_offset_start.y + dy)
            self.update()
            return

        # ラバーバンド選択中: 終点を更新して再描画・距離を emit
        if self._rubber_select_start is not None:
            self._rubber_select_end = sw
            self.mouse_world_pos.emit(w.x, w.y)
            ws = self.s2w(self._rubber_select_start.x,
                          self._rubber_select_start.y)
            dist = math.hypot(w.x - ws.x, w.y - ws.y)
            self.measure_dist_changed.emit(dist)
            self.update()
            return

        if self._drag_start_screen:
            dx = sw.x - self._drag_start_screen.x
            dy = sw.y - self._drag_start_screen.y
            self._mouse_moved_px = math.hypot(dx, dy)
            if self._drag_obj is not None and self._mouse_moved_px > 2:
                self._do_drag(w)
                return

        # ラバー線
        if self.mode == self.MODE_LINE and self._line_first_pt:
            self._rubber_end = w
            self.update()
        elif self.mode == self.MODE_CIRCLE and self._circle_center and \
                event.buttons() & Qt.MouseButton.LeftButton:
            self._rubber_radius = (w - self._circle_center).length()
            self.update()

        # ホバー
        old = self._hovered
        self._hovered = self._hit_object(sw)
        if self._hovered is not old:
            self.update()
            self.hover_changed.emit(self._hovered)

        # マウスのワールド座標を通知
        self.mouse_world_pos.emit(w.x, w.y)

    def mouseReleaseEvent(self, event):
        """マウスボタンリリースイベントを処理する。

        **左ボタン（ドラッグ終了）**:

        * ``_drag_obj`` が設定されている場合、``selection_changed.emit()``
          を発行して右パネルのプロパティを即座に更新してから
          ``_drag_obj``・``_drag_tag`` をリセットする。

        **左ボタン（パン終了）**:

        * ``_mouse_moved_px < 4`` のとき、クリックとみなして選択解除する。

        **左ボタン（円モード）**:

        * ``_circle_center`` が設定されていれば ``radius = (w - center).length()``
          を計算し、``radius > 1e-3`` のとき :meth:`push_undo` 後に
          :class:`Circle` を生成して Scene に追加する。

        **中ボタン**: ``_is_panning = False`` でパンを終了する。

        Parameters
        ----------
        event : QMouseEvent
            PySide6 マウスイベント。
        """
        btn = event.button()
        pos = event.position()
        sw = Vec2(pos.x(), pos.y())
        w = self.s2w(sw.x, sw.y)

        if btn == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.setCursor(
                Qt.CursorShape.ArrowCursor if self.mode == self.MODE_SELECT
                else Qt.CursorShape.CrossCursor)
            return

        if btn == Qt.MouseButton.LeftButton:
            # ラバーバンド選択完了
            if self._rubber_select_start is not None:
                sel = self._complete_rubber_select()
                self._selected = sel
                self._rebuild_handles()
                self.selection_changed.emit(self._selected)
                self._rubber_select_start = None
                self._rubber_select_end = None
                self.measure_dist_changed.emit(-1.0)
                self.update()
                return

            if self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                if self._mouse_moved_px < 4:
                    # クリック扱い → 選択解除
                    self._selected.clear()
                    self._handles.clear()
                    self.selection_changed.emit([])
                    self.update()
            elif self.mode == self.MODE_CIRCLE and self._circle_center:
                r = (w - self._circle_center).length()
                if r > 1e-3:
                    self.push_undo()
                    ci = Circle(self._circle_center, r)
                    self.scene.add_circle(ci)
                    self.scene_changed.emit()
                self._circle_center = None
                self._rubber_radius = 0.0
                self.update()
            if self._drag_obj is not None:
                # ドラッグ完了 → 右パネルのプロパティを更新
                self.selection_changed.emit(self._selected)
            self._drag_obj = None
            self._drag_tag = ""
            self._drag_start_screen = None

    def wheelEvent(self, event):
        """マウスホイールによるズームを処理する。

        ホイール上方向で 1.15 倍、下方向で 1/1.15 倍にスケールする。
        マウスカーソル位置を中心にズームする（オフセットも更新）。

        Parameters
        ----------
        event : QWheelEvent
            PySide6 ホイールイベント。
        """
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        pos = event.position()
        cx, cy = pos.x(), pos.y()
        self._offset = Vec2(cx + (self._offset.x - cx) * factor,
                            cy + (self._offset.y - cy) * factor)
        self._scale *= factor
        self._rebuild_handles()
        self.update()

    def keyPressEvent(self, event):
        """キー押下イベントを処理する。

        * ``Escape``: 直線/円モードの描画中状態をリセットする。
        * ``Delete``: 選択中の図形を削除する（:meth:`_delete_selected`）。
        * ``Ctrl+Z``: Undo（:meth:`undo`）。

        Parameters
        ----------
        event : QKeyEvent
            PySide6 キーイベント。
        """
        k = event.key()
        if k == Qt.Key.Key_Escape:
            self._line_first_pt = None
            self._last_line = None
            self._rubber_end = None
            self._rubber_select_start = None
            self._rubber_select_end = None
            self.measure_dist_changed.emit(-1.0)
            self.update()
        elif k == Qt.Key.Key_Delete:
            self._delete_selected()
        elif (k == Qt.Key.Key_Z
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.undo()
        elif (k == Qt.Key.Key_S
              and not event.modifiers()
              & Qt.KeyboardModifier.ControlModifier):
            # [S] 選択モード
            pass  # メインウィンドウ側で処理
        self.update()

    # ─── 直線モード ──────────────────────────────────────────
    def _line_click(self, w: Vec2):
        """直線モードのクリック処理。

        1 回目のクリックで始点を記憶し、2 回目のクリックで Line+Segment を生成する。
        連続描画中（``_last_line`` が設定済み）は :meth:`_connect_polyline` で
        前の直線と折れ線接続する。

        Parameters
        ----------
        w : Vec2
            クリック位置のワールド座標。
        """
        if self._line_first_pt is None:
            self._line_first_pt = w
        else:
            self.push_undo()
            p = self._line_first_pt
            q = w
            # 直線作成
            ln = Line(p, q)
            # 線分を一本持たせる
            seg = Segment(ln, 0.0, 1.0)
            ln.segments.append(seg)
            self.scene.add_line(ln)
            # 折れ線連続接続
            if self._last_line is not None:
                self._connect_polyline(self._last_line, ln)
            self._last_line = ln
            self._line_first_pt = q
            self._rubber_end = q
            self.scene_changed.emit()
            self.update()

    def _connect_polyline(self, a: Line, b: Line):
        """2直線を折れ線接続する。

        2直線の交点を共有参照点として双方の参照点を更新し、
        ``LineConnection(kind="polyline")`` を生成して両直線に設定する。
        「a の交点に近い側」と「b の交点に近い側」を交点に合わせる。

        Parameters
        ----------
        a : Line
            接続する直線（前の直線）。
        b : Line
            接続する直線（次の直線）。
        """
        ix = a.intersect(b)
        if ix is None:
            return  # 平行

        # a: 交点に近い側の参照点を ix に
        if (a.ref_end - ix).length() <= (a.ref_start - ix).length():
            a.ref_end = ix
            a_end_shared = True
            for seg in a.segments:
                if seg.t_end > seg.t_start:
                    seg.t_end = 1.0
        else:
            a.ref_start = ix
            a_end_shared = False
            for seg in a.segments:
                if seg.t_end > seg.t_start:
                    seg.t_start = 0.0

        # b: 交点に近い側の参照点を ix に
        if (b.ref_start - ix).length() <= (b.ref_end - ix).length():
            b.ref_start = ix
            b_start_shared = True
            for seg in b.segments:
                if seg.t_end > seg.t_start:
                    seg.t_start = 0.0
        else:
            b.ref_end = ix
            b_start_shared = False
            for seg in b.segments:
                if seg.t_end > seg.t_start:
                    seg.t_end = 1.0

        conn = LineConnection("polyline", a, b, ix,
                              a_end_is_shared=a_end_shared,
                              b_start_is_shared=b_start_shared)
        a.connection = conn
        b.connection = conn

    # ─── ドラッグ処理 ─────────────────────────────────────────
    def _do_drag(self, w: Vec2):
        """ハンドルドラッグの各フレーム処理。

        ``_drag_obj`` と ``_drag_tag`` の組み合わせでドラッグ対象を識別し、
        ワールド座標 w に向けて図形を更新する。更新後は関連する Clothoid や
        スムーズ接続の円にも変更を伝播し、``scene_changed`` を emit する。

        Parameters
        ----------
        w : Vec2
            現在のマウスのワールド座標。
        """
        obj = self._drag_obj
        tag = self._drag_tag

        if isinstance(obj, Line):
            if tag == "line_ref_start":
                obj.ref_start = w
                self._propagate_line(obj)
            elif tag == "line_ref_end":
                obj.ref_end = w
                self._propagate_line(obj)

        elif isinstance(obj, Segment):
            ln = obj.line
            if tag == "seg_start":
                t = ln.project_t(w)
                obj.t_start = t
            elif tag == "seg_end":
                t = ln.project_t(w)
                obj.t_end = t

        elif isinstance(obj, Circle):
            if tag == "circle_center":
                if obj.bisector_origin and obj.bisector_dir:
                    # 二等分線上に束縛
                    bd = obj.bisector_dir
                    diff = w - obj.bisector_origin
                    t = diff.dot(bd)
                    obj.center = obj.bisector_origin + bd * t
                else:
                    obj.center = w
                self._propagate_circle(obj)
            elif tag == "circle_radius":
                r = (w - obj.center).length()
                if r > 1e-3:
                    obj.radius = r
                    self._propagate_circle(obj)

        elif isinstance(obj, Arc):
            ci = obj.circle
            if tag == "arc_start":
                ang = math.atan2(w.y - ci.center.y, w.x - ci.center.x)
                obj.angle_start = ang
            elif tag == "arc_end":
                ang = math.atan2(w.y - ci.center.y, w.x - ci.center.x)
                obj.angle_end = ang

        elif isinstance(obj, LineConnection):
            if tag == "shared_pt":
                la, lb = obj.line_a, obj.line_b
                # 記録済みの「どちら側が共有点か」に従って参照点を更新
                if obj.a_end_is_shared:
                    la.ref_end = w
                else:
                    la.ref_start = w
                if obj.b_start_is_shared:
                    lb.ref_start = w
                else:
                    lb.ref_end = w
                obj.shared_point = w
                # 両直線のクロソイド・smooth円を伝播
                self._propagate_line(la)
                self._propagate_line(lb)
                if obj.kind == "smooth" and obj.circle is not None:
                    self._update_smooth_circle(obj)

        self._rebuild_handles()
        self.scene_changed.emit()
        self.update()

    def _propagate_line(self, ln: Line, _updating_smooth: bool = False):
        """直線 ln の変更をクロソイドとスムーズ接続の円に伝播する。

        ``ln`` を参照する全クロソイドの ``compute()`` を呼び出す。
        ``_updating_smooth=False`` のとき、スムーズ接続の円も
        :meth:`_update_smooth_circle` で更新する（無限再帰を防ぐフラグ）。

        Parameters
        ----------
        ln : Line
            変更された直線。
        _updating_smooth : bool, optional
            True のとき smooth 円の更新をスキップする（内部再帰防止用）。
        """
        for clo in self.scene.clothoids:
            if clo.line is ln:
                clo.compute()
        if not _updating_smooth:
            conn = ln.connection
            if conn and conn.kind == "smooth" and conn.circle is not None:
                self._update_smooth_circle(conn)
        # TwoLineOffsetConstraint: 直線が動いたら円中心を追従させる
        self._propagate_two_line_oc_for_line(ln)

    def _propagate_circle(self, ci: Circle):
        """円 ``ci`` の変形をクロソイド・オフセット拘束に伝播する。

        円の中心または半径が変更されたあとに呼ばれる。
        :meth:`_propagate_line` と対になる存在。

        伝播の順序:

        1. ``ci`` を参照する全クロソイドに :meth:`Clothoid.compute` を呼ぶ
        2. :meth:`_propagate_offset_constraints` でオフセット拘束追従

        Parameters
        ----------
        ci : Circle
            変形した円。
        """
        for clo in self.scene.clothoids:
            if clo.circle is ci:
                clo.compute()
        # OffsetConstraint の追従
        self._propagate_offset_constraints(ci)

    def _propagate_offset_constraints(self, ci: 'Circle'):
        """オフセット拘束のうち ci を参照するものについて直線 S を再計算する。

        ci が circle_a または circle_b として含まれる OffsetConstraint に対して
        solve() を呼び出す。

        - solve=True  : 直線の参照点が更新される → 関連 Clothoid に伝播・再描画
        - solve=False : 距離拘束が矛盾（円が近すぎる等）→ 直線は変更しない。
                        ただし Clothoid は現在の直線位置に追従させる。
                        oc.feasible が False になるため呼び出し元は
                        視覚的なフィードバックを提供できる。

        Parameters
        ----------
        ci : Circle
            変化した円（center または radius が変わった円）。
        """
        for oc in self.scene.offset_constraints:
            if oc.circle_a is ci or oc.circle_b is ci:
                oc.solve()  # 成功/失敗を問わず呼ぶ（feasible フラグを更新）
                # 成功・失敗どちらの場合も Clothoid は現在の直線位置に追従させる
                self._propagate_line(oc.line)
                self.scene_changed.emit()
                self.update()
        # TwoLineOffsetConstraint（2直線-1円）の追従
        self._propagate_two_line_offset_constraints(ci)

    def _propagate_two_line_offset_constraints(self, ci: 'Circle'):
        """円 ci の半径変化を TwoLineOffsetConstraint に伝播する。

        ci が circle として含まれる TwoLineOffsetConstraint に対して
        solve() を呼び出し、円中心を再計算する（2直線は動かさない）。
        solve() 後に ci に付属するクロソイドを再計算する。

        Parameters
        ----------
        ci : Circle
            半径または位置が変化した円。
        """
        for oc in self.scene.two_line_offset_constraints:
            if oc.circle is ci:
                oc.solve()   # ci.center を更新（直線は動かさない）
                # ci.center が変わったのでクロソイドを再計算
                for clo in self.scene.clothoids:
                    if clo.circle is ci:
                        clo.compute()
                self.scene_changed.emit()
                self.update()

    def _propagate_two_line_oc_for_line(self, ln: 'Line'):
        """直線 ln の移動を TwoLineOffsetConstraint に伝播する。

        ln が line_a または line_b として含まれる TwoLineOffsetConstraint に
        対して solve() を呼び出し、円中心を再計算する。

        Parameters
        ----------
        ln : Line
            移動した直線。
        """
        for oc in self.scene.two_line_offset_constraints:
            if oc.line_a is ln or oc.line_b is ln:
                oc.solve()   # oc.circle.center を更新
                # 円に付属するクロソイドを再計算
                for clo in self.scene.clothoids:
                    if clo.circle is oc.circle:
                        clo.compute()
                self.scene_changed.emit()
                self.update()

    def _update_smooth_circle(self, conn: 'LineConnection'):
        """
        スムーズ接続の円を、現在の2直線の交点・二等分線に合わせて再配置する。
        直線からの距離 (bisector 上の t) を保ったまま中心を移動する。
        """
        la, lb = conn.line_a, conn.line_b
        ci = conn.circle
        if ci is None:
            return

        new_ix = la.intersect(lb)
        if new_ix is None:
            return

        # 両直線の「共有点と反対側の端点」
        def far_end(ln, shared):
            ds = (ln.ref_start - shared).length()
            de = (ln.ref_end - shared).length()
            return ln.ref_start if ds >= de else ln.ref_end

        P = far_end(la, new_ix)
        Q = far_end(lb, new_ix)

        dP = (P - new_ix).normalized()
        dQ = (Q - new_ix).normalized()
        bisect_sum = dP + dQ
        if bisect_sum.length() < 1e-9:
            return
        bisect = bisect_sum.normalized()

        if ci.bisector_dir is not None and ci.bisector_origin is not None:
            old_t = (ci.center - ci.bisector_origin).dot(ci.bisector_dir)
        else:
            old_t = (ci.center - new_ix).dot(bisect)

        ci.center = new_ix + bisect * old_t
        ci.bisector_origin = new_ix
        ci.bisector_dir = bisect
        conn.shared_point = new_ix
        conn.bisector_dir = bisect

        for line in (la, lb):
            ds = (line.ref_start - new_ix).length()
            de = (line.ref_end - new_ix).length()
            if ds <= de:
                line.ref_start = new_ix
            else:
                line.ref_end = new_ix

        for clo in self.scene.clothoids:
            if clo.circle is ci:
                clo.compute()

    # ─── 削除 ────────────────────────────────────────────────
    def _delete_selected(self):
        """選択中の全図形を削除する。

        :meth:`push_undo` で削除前の状態を保存してから削除する。
        型に応じて Scene の適切な remove メソッドを呼ぶ（Line/Circle/Clothoid）か、
        親コンテナから直接削除する（Segment→Line.segments、Arc→Circle.arcs）。
        削除後は選択・ハンドルをクリアして ``selection_changed`` と
        ``scene_changed`` を emit する。
        """
        if not self._selected:
            return
        self.push_undo()
        for obj in list(self._selected):
            if isinstance(obj, Line):
                self.scene.remove_line(obj)
            elif isinstance(obj, Circle):
                self.scene.remove_circle(obj)
            elif isinstance(obj, Clothoid):
                self.scene.remove_clothoid(obj)
            elif isinstance(obj, Segment):
                obj.line.segments.remove(obj)
            elif isinstance(obj, Arc):
                obj.circle.arcs.remove(obj)
        self._selected.clear()
        self._handles.clear()
        self.selection_changed.emit([])
        self.scene_changed.emit()
        self.update()

    # ─── スムーズ接続 ─────────────────────────────────────────
    def smooth_connect(self, line_a: Line, line_b: Line) -> bool:
        """2直線をクロソイド経由でスムーズ接続する（仕様書 手順 1〜6）。

        Parameters
        ----------
        line_a, line_b : Line
            接続する 2 直線。どちらも少なくとも 1 本の Segment を持つ必要がある。

        Returns
        -------
        bool
            成功のとき True。失敗条件: Segment がない / 平行 / 二等分線が零ベクトル。

        Notes
        -----
        デフォルト半径 R=50m、d=75m（d/R=1.5）でクロソイド存在条件 d>R を満たす。
        生成した Circle と 2 本の Clothoid を Scene に追加し、`kind="smooth"` に昇格する。
        """
        if not line_a.segments or not line_b.segments:
            return False
        ix = line_a.intersect(line_b)
        if ix is None:
            return False  # 平行

        self.push_undo()

        # 手順-1: 折れ線接続して共有参照点 X を確定
        self._connect_polyline(line_a, line_b)
        X = ix  # 交点 = 共有参照点

        # 手順-2: J, K の決定
        # 折れ線接続後の各直線で、X と異なる側の端点 P, Q を求める
        def far_end(ln, shared):
            """X と遠い側の参照点を返す"""
            if ((ln.ref_start - shared).length()
                    >= (ln.ref_end - shared).length()):
                return ln.ref_start
            return ln.ref_end

        P = far_end(line_a, X)
        Q = far_end(line_b, X)

        # PX → XQ の有向角の sin
        PX = (X - P)
        XQ = (Q - X)
        sin_val = PX.cross(XQ)

        # J は「UX方向」、K は「VX方向」で UX→XV の有向角が 180° 以下
        if sin_val >= 0:
            J, J_far = line_a, P
            K, K_far = line_b, Q
        else:
            J, J_far = line_b, Q
            K, K_far = line_a, P

        # J の reversed_flag: J_far → X の方向が effective_direction になるとき
        # effective_direction は reversed=False なら ref_start→ref_end
        # J の X 側の端点が ref_end なら reversed=False でよい (X が ref_end)
        # J の X 側の端点が ref_start なら reversed=True にして方向を逆に
        J_x_is_ref_end = (J.ref_end - X).length() < (J.ref_start - X).length()
        K_x_is_ref_end = (K.ref_end - X).length() < (K.ref_start - X).length()
        # J の実効方向: J_far → X
        # reversed=False → ref_start→ref_end が実効方向
        # J_far が ref_start, X が ref_end → reversed=False ✓
        # J_far が ref_end, X が ref_start → reversed=True ✓
        J_rev = not J_x_is_ref_end   # X が ref_start なら reversed=True
        K_rev = not K_x_is_ref_end

        # 手順-3: 角 UXV の二等分線
        # 仕様: XU = U-X 方向, XV = V-X 方向 の和を正規化
        XU = (J_far - X).normalized()   # X → J_far と逆 = J_far から X を見た方向
        XV = (K_far - X).normalized()
        bisect = (XU + XV)
        if bisect.length() < 1e-9:
            return False
        bisect = bisect.normalized()

        # 手順-4: 二等分線上に円を配置
        R_default = 50.0
        d_default = R_default * 1.5   # d/R = 1.5 > 1 でクロソイド存在条件を満たす
        center = X + bisect * d_default
        ci = Circle(center, R_default)
        ci.bisector_origin = X
        ci.bisector_dir = bisect
        self.scene.add_circle(ci)

        # 手順-5: クロソイド E (J + ci) — 左カーブになる
        clo_e = Clothoid(J, ci, reversed_flag=J_rev,
                         snap_segment=True, snap_arc=True)
        self.scene.add_clothoid(clo_e)

        # 手順-6: クロソイド F (K + ci) — 右カーブになる
        clo_f = Clothoid(K, ci, reversed_flag=K_rev,
                         snap_segment=True, snap_arc=True)
        self.scene.add_clothoid(clo_f)

        # 接続情報を smooth に昇格
        conn = line_a.connection
        if conn:
            conn.kind = "smooth"
            conn.circle = ci
            conn.bisector_dir = bisect

        self.scene_changed.emit()
        self.update()
        return True

    def disconnect_lines(self, line_a: Line, line_b: Line):
        """2直線の接続を解除する（折れ線/スムーズ共通）。

        両直線の `connection` を None に設定する。push_undo() を呼ぶ。
        """
        self.push_undo()
        line_a.connection = None
        line_b.connection = None
        self.scene_changed.emit()
        self.update()
