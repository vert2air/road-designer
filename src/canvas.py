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
                    LineConnection, effective_set)

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
C_BBOX = QColor(80, 160, 255, 180)     # AABB 枠線
C_BBOX_VERTEX = QColor(80, 160, 255)   # 頂点ハンドル
C_BBOX_DIAG = QColor(255, 160, 40)     # 対角線

HANDLE_RADIUS = 7  # px
BBOX_VERTEX_R = 6   # px  AABB 頂点ハンドル半径
BBOX_EDGE_W = 10    # px  辺のヒット幅（片側）

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
    measure_dist_changed : float
        ラバーバンド選択中の対角ワールド距離 [m] を emit する。
        非測定時（終了・キャンセル時）は -1 を emit して表示を消す。

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

        # 複数選択時の AABB 変換ドラッグ
        # mode: None | 'translate' | 'scale' | 'rotate'
        self._bbox_drag_mode: Optional[str] = None
        self._bbox_drag_start_w: Optional[Vec2] = None   # ドラッグ開始ワールド座標
        self._bbox_drag_snapshot: Optional[dict] = None  # ドラッグ開始時のスナップショット
        self._bbox_drag_aabb = None  # ドラッグ開始時の AABB（固定値）

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

    # ─── AABB 変換ドラッグ（複数選択時）────────────────────────

    def _is_multi_select(self) -> bool:
        """複数の独立した図形が選択されているか判定する。"""
        return len(effective_set(self._selected)) >= 2

    def _selection_aabb(self):
        """選択図形の AABB を (min_x, min_y, max_x, max_y) で返す。

        有効点が無ければ None を返す。
        """
        pts = []
        for obj in self._selected:
            if isinstance(obj, Line):
                for seg in obj.segments:
                    pts += [(seg.start.x, seg.start.y),
                            (seg.end.x, seg.end.y)]
                if not obj.segments:
                    pts += [(obj.ref_start.x, obj.ref_start.y),
                            (obj.ref_end.x, obj.ref_end.y)]
            elif isinstance(obj, Circle):
                r = obj.radius
                pts += [(obj.center.x - r, obj.center.y),
                        (obj.center.x + r, obj.center.y),
                        (obj.center.x, obj.center.y - r),
                        (obj.center.x, obj.center.y + r)]
            elif isinstance(obj, Clothoid) and obj.points:
                pts += [(p.x, p.y) for p in obj.points]
            elif isinstance(obj, Segment):
                pts += [(obj.start.x, obj.start.y),
                        (obj.end.x, obj.end.y)]
            elif isinstance(obj, Arc):
                ci = obj.circle
                if ci:
                    r = ci.radius
                    pts += [(ci.center.x - r, ci.center.y),
                            (ci.center.x + r, ci.center.y),
                            (ci.center.x, ci.center.y - r),
                            (ci.center.x, ci.center.y + r)]
        if not pts:
            return None
        xs, ys = zip(*pts)
        return min(xs), min(ys), max(xs), max(ys)

    def _bbox_corners_s(self, aabb):
        """AABB の 4 頂点をスクリーン座標で返す（TL, TR, BR, BL 順）。

        aabb は (min_x, min_y, max_x, max_y) のタプル。
        """
        mn_x, mn_y, mx_x, mx_y = aabb
        return [
            self.w2s(Vec2(mn_x, mx_y)),  # TL（ワールドy上 → スクリーン上）
            self.w2s(Vec2(mx_x, mx_y)),  # TR
            self.w2s(Vec2(mx_x, mn_y)),  # BR
            self.w2s(Vec2(mn_x, mn_y)),  # BL
        ]

    def _hit_bbox(self, sw: Vec2):
        """スクリーン座標 sw が AABB ハンドルに当たるか判定する。

        Returns
        -------
        str or None
            'vertex_0'..'vertex_3' / 'edge_0'..'edge_3' / 'diagonal' / None
            頂点優先、対角線次、辺の順で判定する。
        """
        if not self._is_multi_select():
            return None
        aabb = self._selection_aabb()
        if aabb is None:
            return None
        corners = self._bbox_corners_s(aabb)

        # 頂点ヒット（最優先）
        for i, c in enumerate(corners):
            if math.hypot(sw.x - c.x(), sw.y - c.y()) <= BBOX_VERTEX_R + 4:
                return f'vertex_{i}'

        # 対角線ヒット（線分との距離）
        mn_x, mn_y, mx_x, mx_y = aabb

        def dist_to_seg_s(ax, ay, bx, by, px, py):
            dx, dy = bx - ax, by - ay
            t = ((px - ax) * dx + (py - ay) * dy) / (
                dx * dx + dy * dy + 1e-12)
            t = max(0.0, min(1.0, t))
            return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

        for i in range(2):
            a, b = corners[i], corners[i + 2]
            d = dist_to_seg_s(a.x(), a.y(), b.x(), b.y(), sw.x, sw.y)
            if d <= 8:
                return 'diagonal'

        # 辺ヒット（辺の中点付近）
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            d = dist_to_seg_s(a.x(), a.y(), b.x(), b.y(), sw.x, sw.y)
            if d <= BBOX_EDGE_W:
                return f'edge_{i}'

        return None

    def _snapshot_selected(self) -> dict:
        """選択図形の現在ジオメトリをスナップショットとして返す。

        ドラッグ中に「開始時の状態」から変換を計算するために使う。
        """
        snap = {}
        effective = effective_set(self._selected)
        for obj in effective:
            if isinstance(obj, Line):
                snap[id(obj)] = {
                    'ref_start': Vec2(obj.ref_start.x, obj.ref_start.y),
                    'ref_end': Vec2(obj.ref_end.x, obj.ref_end.y),
                }
            elif isinstance(obj, Circle):
                snap[id(obj)] = {
                    'center': Vec2(obj.center.x, obj.center.y),
                    'radius': obj.radius,
                    'arc_angles': [(a.angle_start, a.angle_end)
                                   for a in obj.arcs],
                }
        return snap

    def _apply_snapshot(self, snap: dict):
        """スナップショットを選択図形に復元する（ドラッグ中の再適用用）。"""
        effective = effective_set(self._selected)
        for obj in effective:
            s = snap.get(id(obj))
            if s is None:
                continue
            if isinstance(obj, Line):
                obj.ref_start = Vec2(s['ref_start'].x, s['ref_start'].y)
                obj.ref_end = Vec2(s['ref_end'].x, s['ref_end'].y)
            elif isinstance(obj, Circle):
                obj.center = Vec2(s['center'].x, s['center'].y)
                obj.radius = s['radius']
                for arc, (as_, ae) in zip(obj.arcs, s['arc_angles']):
                    arc.angle_start = as_
                    arc.angle_end = ae

    def _bbox_apply_translate(self, dx: float, dy: float):
        """スナップショットから復元し dx/dy 平行移動を適用する。"""
        self._apply_snapshot(self._bbox_drag_snapshot)
        effective = effective_set(self._selected)
        moved_ids: set = set()
        for obj in effective:
            if isinstance(obj, Line):
                obj.ref_start = Vec2(obj.ref_start.x + dx,
                                     obj.ref_start.y + dy)
                obj.ref_end = Vec2(obj.ref_end.x + dx, obj.ref_end.y + dy)
                moved_ids.add(id(obj))
            elif isinstance(obj, Circle):
                obj.center = Vec2(obj.center.x + dx, obj.center.y + dy)
                moved_ids.add(id(obj))
        self._recompute_after_bbox(moved_ids)

    def _bbox_apply_scale(self, factor: float, center: Vec2):
        """スナップショットから復元し center 基準で factor 倍拡縮する。"""
        if abs(factor) < 1e-6:
            return
        self._apply_snapshot(self._bbox_drag_snapshot)
        effective = effective_set(self._selected)
        cx, cy = center.x, center.y

        def sc(v: Vec2) -> Vec2:
            return Vec2(cx + (v.x - cx) * factor,
                        cy + (v.y - cy) * factor)

        moved_ids: set = set()
        for obj in effective:
            if isinstance(obj, Line):
                obj.ref_start = sc(obj.ref_start)
                obj.ref_end = sc(obj.ref_end)
                moved_ids.add(id(obj))
            elif isinstance(obj, Circle):
                obj.center = sc(obj.center)
                obj.radius = obj.radius * abs(factor)
                moved_ids.add(id(obj))
        self._recompute_after_bbox(moved_ids)

    def _bbox_apply_rotate(self, angle_rad: float, center: Vec2):
        """スナップショットから復元し center 基準で angle_rad 回転する。"""
        self._apply_snapshot(self._bbox_drag_snapshot)
        effective = effective_set(self._selected)
        cx, cy = center.x, center.y
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        def rot(v: Vec2) -> Vec2:
            dx_r = v.x - cx
            dy_r = v.y - cy
            return Vec2(cx + dx_r * cos_a - dy_r * sin_a,
                        cy + dx_r * sin_a + dy_r * cos_a)

        moved_ids: set = set()
        for obj in effective:
            if isinstance(obj, Line):
                obj.ref_start = rot(obj.ref_start)
                obj.ref_end = rot(obj.ref_end)
                moved_ids.add(id(obj))
            elif isinstance(obj, Circle):
                obj.center = rot(obj.center)
                for arc in obj.arcs:
                    arc.angle_start += angle_rad
                    arc.angle_end += angle_rad
                moved_ids.add(id(obj))
        self._recompute_after_bbox(moved_ids)

    def _recompute_after_bbox(self, moved_ids: set):
        """AABB 変換後にクロソイドを再計算して画面を更新する。"""
        for clo in self.scene.clothoids:
            if id(clo.line) in moved_ids or id(clo.circle) in moved_ids:
                clo.compute()
        self._rebuild_handles()
        self.update()

    def _draw_bbox_handles(self, painter: QPainter):
        """複数選択時の AABB 変換ハンドルを描画する。

        頂点（塗り潰し円）・辺（矩形の線）・対角線（破線）・中心点を描く。
        """
        if not self._is_multi_select():
            return
        aabb = self._selection_aabb()
        if aabb is None:
            return
        mn_x, mn_y, mx_x, mx_y = aabb
        corners = self._bbox_corners_s(aabb)

        # 矩形枠（辺）
        pen = QPen(C_BBOX, 1.5, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        poly = QPolygonF([c for c in corners])
        painter.drawPolygon(poly)

        # 対角線（1点鎖線）
        pen_diag = QPen(C_BBOX_DIAG, 1.5, Qt.PenStyle.DashDotLine)
        painter.setPen(pen_diag)
        painter.drawLine(corners[0], corners[2])
        painter.drawLine(corners[1], corners[3])

        # AABB 中心（小さい十字）
        cx_s = self.w2s(Vec2((mn_x + mx_x) / 2, (mn_y + mx_y) / 2))
        painter.setPen(QPen(C_BBOX_DIAG, 1.5))
        r = 5
        painter.drawLine(
            QPointF(cx_s.x() - r, cx_s.y()),
            QPointF(cx_s.x() + r, cx_s.y()))
        painter.drawLine(
            QPointF(cx_s.x(), cx_s.y() - r),
            QPointF(cx_s.x(), cx_s.y() + r))

        # 頂点ハンドル
        painter.setPen(QPen(C_BBOX_VERTEX, 1.5))
        painter.setBrush(QBrush(C_BBOX_VERTEX))
        for c in corners:
            painter.drawEllipse(c, BBOX_VERTEX_R, BBOX_VERTEX_R)

    def _rebuild_handles(self):
        """選択図形に対応するハンドルを再構築して ``_handles`` リストを更新する。

        クロソイドに拘束された端点はハンドルから除外する:

        - snap=True: ``seg.clothoid_start/end``・``arc.clothoid_start/end`` が
          有効なクロソイド ID を指す端点のみ除外する
        - snap=False: ``_split_seg_ids`` に含まれる分割線分は両端とも除外する
          （クロソイドが自動生成した分割線分はユーザーが直接動かせない）

        Line の接続共有点（``LineConnection.shared_point``）は重複して追加しない。
        複数選択時の AABB 変換ハンドルはここでは生成しない
        （:meth:`_draw_bbox_handles` / :meth:`_hit_bbox` が直接扱う）。
        """
        self._handles.clear()
        seen_connections = set()

        # クロソイドにsnapされている���点を収集（ハンドルを出さない）
        snapped_seg_ends: set[tuple] = set()   # (seg_id, 'start'|'end')
        snapped_arc_ends: set[tuple] = set()   # (arc_id, 'start'|'end')
        clothoid_ids = {clo.id for clo in self.scene.clothoids
                        if clo.is_valid}
        for obj in self._selected:
            if isinstance(obj, Line):
                # snap=False で分割された線分: 両端ともハンドル不要
                # (クロソイドが自動生成した分割線分はユーザーが直接動かせない)
                split_ids: set[int] = set()
                for clo in self.scene.clothoids:
                    if (clo.is_valid and not clo.snap_segment
                            and clo.line is obj):
                        split_ids.update(clo._split_seg_ids)
                for seg in obj.segments:
                    if seg.id in split_ids:
                        snapped_seg_ends.add((seg.id, 'start'))
                        snapped_seg_ends.add((seg.id, 'end'))
                    else:
                        # snap=True: clothoid_end/start の付���た端点のみ除外
                        if seg.clothoid_end in clothoid_ids:
                            snapped_seg_ends.add((seg.id, 'end'))
                        if seg.clothoid_start in clothoid_ids:
                            snapped_seg_ends.add((seg.id, 'start'))
            elif isinstance(obj, Circle):
                for arc in obj.arcs:
                    if arc.clothoid_start in clothoid_ids:
                        snapped_arc_ends.add((arc.id, 'start'))
                    if arc.clothoid_end in clothoid_ids:
                        snapped_arc_ends.add((arc.id, 'end'))

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
        """シーン全体を描画する。

        描画順: グリッド → 参照線 → 線分 → 円 → 円弧 → クロソイド →
        ラバー線（直線/円モード）→ ラバーバンド選択矩形 →
        AABB 変換ハンドル（複数選択時）→ ハンドル。

        Parameters
        ----------
        event : QPaintEvent
            PySide6 ペイントイベント。
        """
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
        # AABB 変換ハンドル（複数選択時）
        self._draw_bbox_handles(painter)
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

        **左ボタン + 選択モード**（判定順）:

        1. 複数選択中は :meth:`_hit_bbox` で AABB 変換ハンドルを最優先判定。
           ヒットすれば :meth:`push_undo` 後に ``_bbox_drag_mode`` を設定し、
           スナップショットと開始時 AABB を記録してドラッグ開始。
        2. :meth:`_hit_handle` でハンドルヒット判定。ヒットすれば
           :meth:`push_undo` を呼んでからドラッグ対象として ``_drag_obj``
           に設定する（ドラッグ前の状態を Undo スタックに保存）。
        3. ハンドルなし → :meth:`_hit_object` で図形ヒット判定。
           ``Shift`` なしでヒット: その図形のみ選択。
           ``Shift`` + ヒット: 選択のトグル。
        4. 図形ヒットなし: ``Shift`` ありならラバーバンド選択を開始、
           なしならパンを開始。

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
                # AABB 変換ハンドルヒット?（複数選択時、通常ハンドルより優先）
                bbox_hit = self._hit_bbox(sw)
                if bbox_hit is not None:
                    self.push_undo()
                    self._bbox_drag_mode = bbox_hit
                    self._bbox_drag_start_w = w
                    self._bbox_drag_snapshot = self._snapshot_selected()
                    # ドラッグ開始時の AABB を固定（毎フレーム再計算すると発散）
                    self._bbox_drag_aabb = self._selection_aabb()
                    return

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

        処理優先順: パン → ラバーバンド選択（終点更新 +
        ``measure_dist_changed`` で対角距離を通知）→ AABB 変換ドラッグ
        （:meth:`_do_bbox_drag`）→ ハンドルドラッグ（移動量 2px 超で
        :meth:`_do_drag`）→ 直線/円モードのラバー線とホバー更新。
        ホバー変化時は ``hover_changed``、移動のたびに ``mouse_world_pos``
        を emit する。

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

        # AABB 変換ドラッグ中
        if self._bbox_drag_mode is not None and self._bbox_drag_start_w:
            self._do_bbox_drag(w)
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

        **左ボタン（AABB 変換ドラッグ完了）**:

        * ``_bbox_drag_*`` をリセットし、``scene_changed.emit()`` でコミット
          してから ``selection_changed.emit()`` で右パネルを更新する。

        **左ボタン（ラバーバンド選択完了）**:

        * :meth:`_complete_rubber_select` の結果を選択に反映し、
          ``measure_dist_changed.emit(-1.0)`` で距離表示を消す。

        **左ボタン（パン終了）**:

        * ``_mouse_moved_px < 4`` のとき、クリックとみなして選択解除する。

        **左ボタン（円モード）**:

        * ``_circle_center`` が設定されていれば ``radius = (w - center).length()``
          を計算し、``radius > 1e-3`` のとき :meth:`push_undo` 後に
          :class:`Circle` を生成して Scene に追加する。

        **左ボタン（ハンドルドラッグ完了）**:

        * ``_drag_obj`` が設定されている場合、``selection_changed.emit()``
          を発行して右パネルのプロパティを即座に更新してから
          ``_drag_obj``・``_drag_tag`` をリセットする。

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
            # AABB 変換ドラッグ完了
            if self._bbox_drag_mode is not None:
                self._bbox_drag_mode = None
                self._bbox_drag_start_w = None
                self._bbox_drag_snapshot = None
                self._bbox_drag_aabb = None
                self.scene_changed.emit()
                self.selection_changed.emit(self._selected)
                return

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

        * ``Escape``: 直線モードの連続入力とラバーバンド選択をリセットし、
          ``measure_dist_changed.emit(-1.0)`` で距離表示を消す。
        * ``Delete``: 選択中の図形を削除する（:meth:`_delete_selected`）。
        * ``Ctrl+Z``: Undo（:meth:`undo`）。
        * モード切替（S/L/C）はメインウィンドウ側のアクションが処理する。

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

    # ─── AABB 変換ドラッグ処理 ───────────────────────────────────
    def _do_bbox_drag(self, w: Vec2):
        """AABB 変換ドラッグの各フレーム処理。

        _bbox_drag_mode に応じて平行移動・拡大縮小・回転を適用する。
        スナップショットから毎フレーム再計算するため累積誤差が出ない。

        Parameters
        ----------
        w : Vec2
            現在のマウスワールド座標。
        """
        mode = self._bbox_drag_mode
        start = self._bbox_drag_start_w
        if mode is None or start is None:
            return

        # ドラッグ開始時に固定した AABB を使う（毎フレーム再計算すると発散）
        aabb = self._bbox_drag_aabb
        if aabb is None:
            return
        mn_x, mn_y, mx_x, mx_y = aabb
        cx = (mn_x + mx_x) / 2
        cy = (mn_y + mx_y) / 2
        center = Vec2(cx, cy)

        if mode.startswith('edge_'):
            # 平行移動: ドラッグ差分をそのまま適用
            dx = w.x - start.x
            dy = w.y - start.y
            self._bbox_apply_translate(dx, dy)

        elif mode.startswith('vertex_'):
            # 拡大縮小: X/Y それぞれの倍率を求め大きい方を採用（XY同率）
            idx = int(mode[-1])
            corners_w = [
                Vec2(mn_x, mx_y), Vec2(mx_x, mx_y),
                Vec2(mx_x, mn_y), Vec2(mn_x, mn_y),
            ]
            orig_corner = corners_w[idx]
            orig_dx = abs(orig_corner.x - cx)
            orig_dy = abs(orig_corner.y - cy)
            cur_dx = abs(w.x - cx)
            cur_dy = abs(w.y - cy)
            fx = cur_dx / orig_dx if orig_dx > 1e-6 else 1.0
            fy = cur_dy / orig_dy if orig_dy > 1e-6 else 1.0
            factor = max(fx, fy)
            self._bbox_apply_scale(factor, center)

        elif mode == 'diagonal':
            # 回転: ドラッグ開始点→中心の角度と現在点→中心の角度の差
            start_ang = math.atan2(start.y - cy, start.x - cx)
            cur_ang = math.atan2(w.y - cy, w.x - cx)
            angle_rad = cur_ang - start_ang
            self._bbox_apply_rotate(angle_rad, center)

    # ─── ドラッグ処理 ─────────────────────────────────────────
    def _do_drag(self, w: Vec2):
        """ハンドルドラッグの各フレーム処理。

        型ごとのサブメソッドにディスパッチし、最後に伝播・再描画を行う。

        Parameters
        ----------
        w : Vec2
            現在のマウスのワールド座標。
        """
        obj = self._drag_obj
        tag = self._drag_tag

        if isinstance(obj, Line):
            self._drag_line(obj, tag, w)
        elif isinstance(obj, Segment):
            self._drag_segment(obj, tag, w)
        elif isinstance(obj, Circle):
            self._drag_circle(obj, tag, w)
        elif isinstance(obj, Arc):
            self._drag_arc(obj, tag, w)
        elif isinstance(obj, LineConnection):
            self._drag_connection(obj, tag, w)

        self._rebuild_handles()
        self.scene_changed.emit()
        self.update()

    def _drag_line(self, obj: Line, tag: str, w: Vec2):
        """Line ハンドルのドラッグ処理。"""
        if tag == "line_ref_start":
            obj.ref_start = w
        elif tag == "line_ref_end":
            obj.ref_end = w
        self._propagate_line(obj)

    def _drag_segment(self, obj: Segment, tag: str, w: Vec2):
        """Segment ハンドルのドラッグ処理（t 値更新）。"""
        ln = obj.line
        if tag == "seg_start":
            obj.t_start = ln.project_t(w)
        elif tag == "seg_end":
            obj.t_end = ln.project_t(w)

    def _drag_circle(self, obj: Circle, tag: str, w: Vec2):
        """Circle ハンドルのドラッグ処理。"""
        if tag == "circle_center":
            if obj.bisector_origin and obj.bisector_dir:
                # 二等分線上に束縛
                bd = obj.bisector_dir
                t = (w - obj.bisector_origin).dot(bd)
                obj.center = obj.bisector_origin + bd * t
            else:
                obj.center = w
            self._propagate_circle(obj)
        elif tag == "circle_radius":
            r = (w - obj.center).length()
            if r > 1e-3:
                obj.radius = r
                self._propagate_circle(obj)

    def _drag_arc(self, obj: Arc, tag: str, w: Vec2):
        """Arc ハンドルのドラッグ処理（角度更新）。"""
        ci = obj.circle
        ang = math.atan2(w.y - ci.center.y, w.x - ci.center.x)
        if tag == "arc_start":
            obj.angle_start = ang
        elif tag == "arc_end":
            obj.angle_end = ang

    def _drag_connection(self, obj: LineConnection, tag: str, w: Vec2):
        """LineConnection 共有点のドラッグ処理。"""
        if tag != "shared_pt":
            return
        la, lb = obj.line_a, obj.line_b
        if obj.a_end_is_shared:
            la.ref_end = w
        else:
            la.ref_start = w
        if obj.b_start_is_shared:
            lb.ref_start = w
        else:
            lb.ref_end = w
        obj.shared_point = w
        self._propagate_line(la)
        self._propagate_line(lb)
        if obj.kind == "smooth" and obj.circle is not None:
            self._update_smooth_circle(obj)

    def _propagate_line(self, ln: Line, _updating_smooth: bool = False):
        """直線 ln の変更をクロソイドと接続先に伝播する。

        ``ln`` を参照する全クロソイドの ``compute()`` を呼び出す。
        ``_updating_smooth=False`` のとき:

        - スムーズ接続の円を :meth:`_update_smooth_circle` で更新する。
        - 折れ線接続の相手直線を :meth:`_follow_polyline_connection`
          で平行移動して共有端点を追従させる。

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
            if conn is not None:
                if conn.kind == "smooth" and conn.circle is not None:
                    self._update_smooth_circle(conn)
                elif conn.kind == "polyline":
                    self._follow_polyline_connection(conn, ln)
        # TwoLineOffsetConstraint: 直線が動いたら円中心を追従させる
        self._propagate_two_line_oc_for_line(ln)

    def _propagate_circle(self, ci: Circle):
        """円 ``ci`` の変形をクロソイド・オフセット拘束に伝播する。

        円の中心または半径が変更されたあとに呼ばれる。
        :meth:`_propagate_line` と対になる存在。

        伝播の順序:

        1. ``ci`` を参照する全クロソイドに :meth:`Clothoid.compute` を呼ぶ
        2. :meth:`_propagate_two_line_offset_constraints` で
           TwoLineOffsetConstraint を先に解いて ``ci.center`` を確定させる。
           （半径変化時に 2直線からの距離を維持するため先行させる）
        3. :meth:`_propagate_offset_constraints` でオフセット拘束追従

        Parameters
        ----------
        ci : Circle
            変形した円。
        """
        for clo in self.scene.clothoids:
            if clo.circle is ci:
                clo.compute()
        # TwoLineOC を先に解いて ci.center を確定させる（半径変化への対応）
        self._propagate_two_line_offset_constraints(ci)
        # 確定した ci.center を使って OffsetConstraint を解く
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

        末尾で :meth:`_propagate_two_line_offset_constraints` も呼び、
        TwoLineOffsetConstraint（2直線-1円）への連鎖伝播を行う。

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

        円中心の更新後に :meth:`_propagate_offset_constraints` を呼ぶことで、
        その円を参照する OffsetConstraint への連鎖伝播も行う。

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
                # 連鎖: 更新された円を参照する OffsetConstraint にも伝播
                # （TwoLineOC の solve は冪等なので無限ループにはならない）
                self._propagate_offset_constraints(oc.circle)
                self.scene_changed.emit()
                self.update()

    # ─── 外部公開・伝播ヘルパー ──────────────────────────────────
    def propagate_from_circle(self, ci: 'Circle'):
        """外部（プロパティパネル等）から円 ci の変化をチェーン伝播させる。

        TwoLineOC の solve 済み ci.center を使って OffsetConstraint を解き、
        さらに下流の TwoLineOC まで連鎖させる。
        伝播完了後に repaint() で即時再描画する（update() の遅延を避ける）。
        """
        self._propagate_offset_constraints(ci)
        self._rebuild_handles()   # ハンドルのキャッシュを最新ジオメトリで更新
        self.scene_changed.emit()
        self.update()

    def propagate_from_line(self, ln: 'Line'):
        """外部（プロパティパネル等）から直線 ln の変化をチェーン伝播させる。

        :meth:`_propagate_line` を呼ぶことで、クロソイド再計算・
        スムーズ接続の円の再配置・折れ線接続の追従・TwoLineOC 連鎖を
        まとめて実行する。
        """
        self._propagate_line(ln)
        self._rebuild_handles()   # ハンドルのキャッシュを最新ジオメトリで更新
        self.scene_changed.emit()
        self.update()

    def _follow_polyline_connection(
            self, conn: 'LineConnection', moved: Line):
        """折れ線接続で moved が動いたとき、接続先の直線を平行移動して追従させる。

        moved の共有端点が ``conn.shared_point`` から移動していた場合、
        差分ベクトル ``delta`` で接続先直線を丸ごと平行移動し
        ``conn.shared_point`` を更新する。その後 :meth:`_propagate_line`
        を再帰的に呼んで接続先直線のクロソイド等も更新する。

        再帰防止: ``conn.shared_point`` を先に更新するため、接続先直線の
        :meth:`_propagate_line` が再び本メソッドを呼んでも
        ``delta.length() < 1e-9`` の判定で即座に返る。

        Parameters
        ----------
        conn : LineConnection
            2直線間の折れ線接続オブジェクト。
        moved : Line
            今回移動した直線。
        """
        la, lb = conn.line_a, conn.line_b
        if moved is la:
            new_pt = (la.ref_end if conn.a_end_is_shared
                      else la.ref_start)
            other = lb
        elif moved is lb:
            new_pt = (lb.ref_start if conn.b_start_is_shared
                      else lb.ref_end)
            other = la
        else:
            return

        delta = new_pt - conn.shared_point
        if delta.length() < 1e-9:
            return   # 変化なし → 再帰終端

        conn.shared_point = new_pt   # 先に更新して再帰を止める

        # 接続先直線を平行移動（方向を変えずに端点を追従させる）
        other.ref_start = other.ref_start + delta
        other.ref_end = other.ref_end + delta

        # 接続先に伝播（クロソイド再計算・TwoLineOC 追従 etc.）
        self._propagate_line(other)

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

        return True

    def disconnect_lines(self, line_a: Line, line_b: Line):
        """2直線の接続を解除する（折れ線/スムーズ共通）。

        両直線の `connection` を None に設定する。push_undo() を呼ぶ。
        """
        self.push_undo()
        line_a.connection = None
        line_b.connection = None
