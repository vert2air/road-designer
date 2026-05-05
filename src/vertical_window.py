"""縦断線形設計ウィンドウ。

ProfileCanvas と VerticalAlignmentWindow の 2 クラスで構成される。

設計方針「編集は全体、保存は要素単位」:
- `set_plan_elements()`: 各 ElementProfile の grade_lines を累積距離に変換して
  チェーン全体の _grade_lines に統合し、要素境界を意識せず横断的に編集できる。
- `save_to_profiles()`: 閉じる際にチェーン全体の _grade_lines を各要素の距離範囲
  に切り出して ElementProfile に書き戻す。
"""
from __future__ import annotations
import math
from typing import Optional, List
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QDoubleSpinBox, QGroupBox, QScrollArea, QFrame,
    QSplitter, QSizePolicy
)
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QFont

from models import (Vec2, GradeLine, VerticalCurve, VerticalAlignment,
                    Scene, Segment, Arc, Clothoid, new_id)


def _make_spinbox(val: float, lo: float = -1e6, hi: float = 1e6,
                  step: float = 1.0, decimals: int = 3) -> QDoubleSpinBox:
    """設定済みの QDoubleSpinBox を生成して返すファクトリ関数。

    Parameters
    ----------
    val : float
        初期値。
    lo, hi : float, optional
        最小・最大値。
    step : float, optional
        単一ステップ量。
    decimals : int, optional
        小数点以下桁数。
    """
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(val)
    return sb


def _separator() -> QFrame:
    """右パネル内の水平区切り線（HLine）を返す。"""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


# ─── カラーバー色 ────────────────────────────────────────────
CB_SEGMENT  = QColor( 60, 120, 220)
CB_CLOTHOID = QColor( 40, 180,  80)
CB_ARC      = QColor(120,  40, 180)


class ProfileCanvas(QWidget):
    """縦断線形設計ウィンドウの中核キャンバス。

    「編集は全体、保存は要素単位」の設計方針に基づき、チェーン全体の
    grade_lines を累積距離で統合した状態を _grade_lines で保持して編集する。
    ウィンドウを閉じるときに save_to_profiles() が各 ElementProfile に切り出す。

    Signals
    -------
    selection_changed(object)
        選択した GradeLine/VerticalCurve/None が変わったときに emit する。
    mouse_world_pos(float, float)
        マウスカーソルの縦断座標（累積距離, 標高）を emit する。

    Class Attributes
    ----------------
    HANDLE_R : int = 6
        ハンドルの描画半径 [px]。
    HIT_TOL : int = 8
        図形ヒット判定の許容距離 [px]。
    CB_H : int = 26
        カラーバーの高さ [px]。
    """
    selection_changed     = Signal(object)
    mouse_world_pos       = Signal(float, float)

    HANDLE_R = 6   # ハンドル半径 [px]
    HIT_TOL  = 8   # ヒット許容距離 [px]
    CB_H     = 26  # カラーバー高さ [px]

    def __init__(self, scene: Scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._plan_elements: list = []
        self._profiles:      list = []   # list[ElementProfile] 要素単位のデータ

        # チェーン全体の勾配直線・縦断曲線（累積距離で管理）
        # これを直接編集し、保存時に要素単位に切り出す
        self._grade_lines:     List[GradeLine]     = []
        self._vertical_curves: List[VerticalCurve] = []

        # 各要素の累積開始距離 [element_idx → dist_offset]
        self._elem_offsets: List[float] = []

        # ビュー
        self._offset = Vec2(80, 300)
        self._scale_x = 2.0
        self._scale_y = 5.0
        self._selected: Optional[object] = None

        # ドラッグ状態
        self._pan_start: Optional[Vec2] = None
        self._pan_offset_start: Optional[Vec2] = None
        self._drag_handle: Optional[dict] = None
        self._drag_start_screen: Optional[Vec2] = None
        self._mouse_moved_px: float = 0.0

        self._mode = "select"
        self._grade_first: Optional[tuple] = None
        self._mouse_screen: Optional[tuple] = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ─── 公開メソッド ─────────────────────────────────────────
    def set_plan_elements(self, elements: list, profiles: list,
                          rev_flags: list = None):
        """平面線形要素チェーンと対応する ElementProfile を設定してキャンバスを初期化する。

        各 ElementProfile の grade_lines を累積距離に変換してチェーン全体の
        _grade_lines に統合する。rev_flags[i]=True の要素は dist/elev を反転して
        統合する。統合後に `_snap_grade_lines('both')` で境界標高を揃える。

        Parameters
        ----------
        elements : list[Segment | Arc | Clothoid]
            チェーン順に並んだ平面線形要素。
        profiles : list[ElementProfile]
            各要素に対応する縦断データ（elements と同じ順序・長さ）。
        rev_flags : list[bool], optional
            各要素を逆順で使うかどうかのフラグ。None のとき全要素 False。
        各 profile の grade_lines を累積距離に変換してチェーン全体の
        _grade_lines / _vertical_curves に統合する。
        """
        self._plan_elements = elements
        self._profiles      = profiles
        self._rev_flags     = rev_flags if rev_flags else [False] * len(profiles)

        # 累積オフセットを計算
        offsets = []
        acc = 0.0
        for ep in profiles:
            offsets.append(acc)
            acc += ep.plan_length
        self._elem_offsets = offsets

        # 各 profile の grade_lines を累積距離に変換して統合
        # rev=True の要素は dist を (plan_length - dist) に反転する
        # grade_lines は plan_length の範囲 [0, plan_length] でクリップしてから使う
        self._grade_lines     = []
        self._vertical_curves = []
        for ep, offset, rev in zip(profiles, offsets, self._rev_flags):
            L = ep.plan_length
            for gl in ep.grade_lines:
                # plan_length の範囲でクリップ
                gs = max(gl.dist_start, 0.0)
                ge = min(gl.dist_end,   L)
                if ge - gs < 0.001:
                    continue
                # クリップ後の標高を補間
                gs_elev = self._elev_at(gs, gl)
                ge_elev = self._elev_at(ge, gl)
                if rev:
                    merged = GradeLine(
                        dist_start = offset + (L - ge),
                        elev_start = ge_elev,
                        dist_end   = offset + (L - gs),
                        elev_end   = gs_elev)
                else:
                    merged = GradeLine(
                        dist_start = gs + offset,
                        elev_start = gs_elev,
                        dist_end   = ge + offset,
                        elev_end   = ge_elev)
                merged.id = gl.id
                self._grade_lines.append(merged)

            for vc in ep.vertical_curves:
                # plan_length の範囲でクリップ
                if vc.vpc_dist >= L - 0.001 or vc.vpt_dist <= 0.001:
                    continue
                if rev:
                    merged_vc = VerticalCurve(
                        pvi_dist = offset + (L - vc.pvi_dist),
                        pvi_elev = vc.pvi_elev,
                        g1 = -vc.g2, g2 = -vc.g1,
                        length = vc.length)
                else:
                    merged_vc = VerticalCurve(
                        pvi_dist = vc.pvi_dist + offset,
                        pvi_elev = vc.pvi_elev,
                        g1 = vc.g1, g2 = vc.g2,
                        length = vc.length,
                        prev_line_id = vc.prev_line_id,
                        next_line_id = vc.next_line_id)
                merged_vc.id = vc.id
                self._vertical_curves.append(merged_vc)

        self._grade_lines.sort(key=lambda g: g.dist_start)
        # 統合後に隣接要素間の境界標高を揃える
        self._snap_grade_lines('both')
        self.update()

    def save_to_profiles(self):
        """チェーン全体の _grade_lines/_vertical_curves を各 ElementProfile に書き戻す。

        VerticalAlignmentWindow.closeEvent から呼ばれる。
        各要素の距離範囲 [offset, offset+L] で GradeLine/VerticalCurve を
        クリップし、rev=True の要素は dist/elev を逆順変換して保存する。
        保存後に ep.elev_at(0.0) / ep.elev_at(L) で始終端標高を更新する。
        """
        rev_flags = getattr(self, '_rev_flags', [False] * len(self._profiles))
        for ep, offset, rev in zip(self._profiles, self._elem_offsets, rev_flags):
            L = ep.plan_length
            d_start = offset
            d_end   = offset + L

            # この要素の範囲に含まれる grade_lines を切り出し
            ep.grade_lines = []
            for gl in self._grade_lines:
                s = max(gl.dist_start, d_start)
                e = min(gl.dist_end,   d_end)
                if e - s < 0.01:
                    continue
                s_elev = self._elev_at(s, gl)
                e_elev = self._elev_at(e, gl)
                if rev:
                    # 逆順に戻す
                    new_gl = GradeLine(
                        dist_start = L - (e - offset),
                        elev_start = e_elev,
                        dist_end   = L - (s - offset),
                        elev_end   = s_elev)
                else:
                    new_gl = GradeLine(
                        dist_start = s - offset,
                        elev_start = s_elev,
                        dist_end   = e - offset,
                        elev_end   = e_elev)
                ep.grade_lines.append(new_gl)
            ep.grade_lines.sort(key=lambda g: g.dist_start)

            # 縦断曲線も同様にクリップして保存
            ep.vertical_curves = []
            for vc in self._vertical_curves:
                if vc.vpc_dist >= d_end - 0.01 or vc.vpt_dist <= d_start + 0.01:
                    continue
                rel_pvi = vc.pvi_dist - offset
                if rev:
                    new_vc = VerticalCurve(
                        pvi_dist = L - rel_pvi,
                        pvi_elev = vc.pvi_elev,
                        g1 = -vc.g2, g2 = -vc.g1,
                        length = vc.length)
                else:
                    new_vc = VerticalCurve(
                        pvi_dist = rel_pvi,
                        pvi_elev = vc.pvi_elev,
                        g1 = vc.g1, g2 = vc.g2,
                        length = vc.length)
                ep.vertical_curves.append(new_vc)

            # 要素の始端・終端標高を更新（縦断曲線があればそちらを優先）
            if ep.grade_lines:
                ep.elev_start = ep.elev_at(0.0)
                ep.elev_end   = ep.elev_at(ep.plan_length)

    @staticmethod
    def _elev_at(dist: float, gl: GradeLine) -> float:
        """GradeLine 1 本上の線形補間標高を返す（内部ヘルパー）。

        set_plan_elements と save_to_profiles でのクリップ後の標高補間に使う。
        dist が gl の範囲外でも計算を行う（呼び出し元が範囲チェック済み）。

        Parameters
        ----------
        dist : float
            標高を求める累積距離 [m]。
        gl : GradeLine
            対象の勾配直線。

        Returns
        -------
        float
            線形補間した標高 [m]。dist_end == dist_start のとき elev_start を返す。
        """
        if abs(gl.dist_end - gl.dist_start) < 1e-9:
            return gl.elev_start
        t = (dist - gl.dist_start) / (gl.dist_end - gl.dist_start)
        return gl.elev_start + (gl.elev_end - gl.elev_start) * t

    def set_mode(self, mode: str):
        """描画モードを変更し、入力途中の状態をリセットする。

        Parameters
        ----------
        mode : str
            "select" または "grade"。
        """
        self._mode = mode
        self._grade_first = None

    # ─── 座標変換 ─────────────────────────────────────────────
    def w2s(self, dist: float, elev: float) -> QPointF:
        """縦断座標（累積距離, 標高）→ スクリーン座標（QPointF）に変換する。

        y 軸が反転する（標高上向き正 → スクリーン下向き正）。

        Parameters
        ----------
        dist : float
            チェーン始端からの累積距離 [m]。
        elev : float
            標高 [m]。

        Returns
        -------
        QPointF
            スクリーン座標。
        """
        x =  dist * self._scale_x + self._offset.x
        y = -elev * self._scale_y + self._offset.y
        return QPointF(x, y)

    def s2w(self, sx: float, sy: float) -> tuple[float, float]:
        """スクリーン座標 → 縦断座標（累積距離, 標高）に変換する（w2s の逆変換）。

        Parameters
        ----------
        sx, sy : float
            スクリーン座標（ピクセル）。

        Returns
        -------
        tuple[float, float]
            (累積距離 [m], 標高 [m])。
        """
        dist = (sx - self._offset.x) / self._scale_x
        elev = -(sy - self._offset.y) / self._scale_y
        return dist, elev

    def wheelEvent(self, event):
        delta = event.angleDelta()
        mods  = event.modifiers()
        pos   = event.position()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            factor = 1.15 if delta.y() > 0 else 1 / 1.15
            self._scale_y *= factor
        else:
            factor = 1.15 if delta.y() > 0 else 1 / 1.15
            cx = pos.x()
            self._offset = Vec2(cx + (self._offset.x - cx) * factor, self._offset.y)
            self._scale_x *= factor
        self.update()

    def _grade_lines_sorted(self) -> list:
        """_grade_lines を dist_start の昇順でソートした新しいリストを返す。

        Returns
        -------
        list[GradeLine]
            dist_start の昇順に並んだ GradeLine のリスト。
        """
        return sorted(self._grade_lines, key=lambda g: g.dist_start)

    def _vc_for_pvi(self, dist: float) -> Optional['VerticalCurve']:
        """指定 dist を PVI とする縦断曲線を返す。

        `_build_grade_props` で PVI に縦断曲線が既にあるかどうかの確認に使う。

        Parameters
        ----------
        dist : float
            PVI の累積距離 [m]。

        Returns
        -------
        VerticalCurve or None
            |vc.pvi_dist - dist| < 0.01 を満たす最初の縦断曲線。なければ None。
        """
        for vc in self._vertical_curves:
            if abs(vc.pvi_dist - dist) < 0.01:
                return vc
        return None

    def _vc_at(self, dist: float) -> Optional['VerticalCurve']:
        """指定 dist が VPC〜VPT 範囲内に含まれる縦断曲線を返す。

        Parameters
        ----------
        dist : float
            確認する累積距離 [m]。

        Returns
        -------
        VerticalCurve or None
            vpc_dist-0.001 ≤ dist ≤ vpt_dist+0.001 を満たす最初の縦断曲線。
        """
        for vc in self._vertical_curves:
            if vc.vpc_dist - 0.001 <= dist <= vc.vpt_dist + 0.001:
                return vc
        return None

    def _elevation_at(self, dist: float) -> Optional[float]:
        """累積距離 dist での標高を返す（縦断曲線優先）。

        描画（_draw_profile）とスナップ点の標高取得に使う。

        Parameters
        ----------
        dist : float
            累積距離 [m]。

        Returns
        -------
        float or None
            標高 [m]。縦断曲線→勾配直線の順で検索し、どちらも該当しなければ None。
        """
        # まず縦断曲線
        for vc in self._vertical_curves:
            if vc.vpc_dist - 0.001 <= dist <= vc.vpt_dist + 0.001:
                return vc.elevation_at(dist)
        # 勾配直線
        for gl in self._grade_lines:
            if gl.dist_start - 0.001 <= dist <= gl.dist_end + 0.001:
                t = ((dist - gl.dist_start) / (gl.dist_end - gl.dist_start)
                     if abs(gl.dist_end - gl.dist_start) > 1e-9 else 0)
                return gl.elev_start + (gl.elev_end - gl.elev_start) * t
        return None

    # ─── ハンドル列挙 ─────────────────────────────────────────
    def _snap_grade_lines(self, changed_end: str = 'both'):
        """隣接する GradeLine の端点を強制一致させて隙間ゼロを保証する。

        勾配直線の追加・ドラッグ・数値入力のいずれの後も呼ばれる。
        set_plan_elements の末尾でも 'both' で呼ばれ、チェーン統合後の
        境界標高不整合を自動修正する。

        Parameters
        ----------
        changed_end : str, optional
            'end'  : 前→後方向に伝播。変更した終端値を次の GradeLine の始端へ。
            'start': 後→前方向に伝播。
            'both' : 両方向（デフォルト）。_grade_lines が空のとき何もしない。
        """
        gls = self._grade_lines_sorted()
        if not gls:
            return

        if changed_end in ('end', 'both'):
            # 前→後方向: 前の終端に次の始端を合わせる
            for i in range(len(gls) - 1):
                g_next = gls[i + 1]
                g_cur  = gls[i]
                g_next.dist_start = g_cur.dist_end
                g_next.elev_start = g_cur.elev_end

        if changed_end in ('start', 'both'):
            # 後→前方向: 後の始端に前の終端を合わせる
            for i in range(len(gls) - 1, 0, -1):
                g_cur  = gls[i]
                g_prev = gls[i - 1]
                g_prev.dist_end = g_cur.dist_start
                g_prev.elev_end = g_cur.elev_start

    def _get_handles(self) -> list[dict]:
        """GradeLine の全端点からハンドル辞書のリストを生成する。

        隣接する GradeLine の境界点（dist が 0.01m 以内）は共有ハンドルに統合する。

        Returns
        -------
        list[dict]
            各ハンドルは {'dist': float, 'elev': float, 'partners': list[(GradeLine, str)]}。
            'partners' は [(GradeLine, 'start'|'end'), ...] のリスト。
        """
        gls  = self._grade_lines_sorted()
        seen: dict[int, dict] = {}   # key=round(dist*100) → ハンドル
        handles = []

        for gl in gls:
            for end in ('start', 'end'):
                dist = gl.dist_start if end == 'start' else gl.dist_end
                elev = gl.elev_start if end == 'start' else gl.elev_end
                key  = round(dist * 100)   # 0.01m 単位でグループ化
                if key in seen:
                    seen[key]['partners'].append((gl, end))
                else:
                    h = {'dist': dist, 'elev': elev, 'partners': [(gl, end)]}
                    seen[key] = h
                    handles.append(h)

        # 隣接する勾配直線の境界点を共有ハンドルとして統合
        # gls[i].dist_end ≈ gls[i+1].dist_start → 同じハンドルにまとめる
        for i in range(len(gls) - 1):
            g_cur  = gls[i]
            g_next = gls[i + 1]
            if abs(g_next.dist_start - g_cur.dist_end) < 0.01:
                key_end   = round(g_cur.dist_end   * 100)
                key_start = round(g_next.dist_start * 100)
                if key_end != key_start and key_end in seen and key_start in seen:
                    # 2つのハンドルを統合：key_end に key_start の partners を追加
                    h_end   = seen[key_end]
                    h_start = seen[key_start]
                    for p in h_start['partners']:
                        if p not in h_end['partners']:
                            h_end['partners'].append(p)
                    # key_start のハンドルを削除
                    handles = [h for h in handles if h is not h_start]
                    seen.pop(key_start, None)

        return handles

    def _hit_handle(self, sx: float, sy: float) -> Optional[dict]:
        """スクリーン座標 (sx, sy) に HANDLE_R+2 px 以内のハンドルを返す。

        選択モード以外は常に None を返す。

        Parameters
        ----------
        sx, sy : float
            スクリーン座標（ピクセル）。

        Returns
        -------
        dict or None
            ヒットしたハンドル辞書。ヒットなし、または選択モード以外は None。
        """
        if self._mode != "select":
            return None
        for h in self._get_handles():
            p = self.w2s(h['dist'], h['elev'])
            if math.hypot(sx - p.x(), sy - p.y()) < self.HANDLE_R + 2:
                return h
        return None

    # ─── 描画 ─────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(28, 28, 32))
        self._draw_grid(painter)
        self._draw_colorbar(painter)
        self._draw_profile(painter)
        self._draw_handles(painter)
        self._draw_rubber(painter)
        self._draw_axes(painter)

    def _draw_grid(self, painter: QPainter):
        pen = QPen(QColor(45, 50, 55))
        pen.setWidth(1)
        painter.setPen(pen)
        w, h = self.width(), self.height()
        # 水平グリッド
        raw_y = h / self._scale_y / 5
        mag = 10 ** math.floor(math.log10(raw_y)) if raw_y > 0 else 1
        steps = [1,2,5,10]
        gy = mag * min((s for s in steps if s*mag >= raw_y*0.8), default=10)
        dist0, elev0 = self.s2w(0, h)
        dist1, elev1 = self.s2w(w, 0)
        ey0 = math.floor(elev0/gy)*gy
        e = ey0
        while e <= elev1 + gy:
            sp = self.w2s(0, e)
            painter.drawLine(0, int(sp.y()), w, int(sp.y()))
            e += gy
        # 垂直グリッド
        raw_x = w / self._scale_x / 5
        mag_x = 10 ** math.floor(math.log10(raw_x)) if raw_x > 0 else 1
        gx = mag_x * min((s for s in steps if s*mag_x >= raw_x*0.8), default=10)
        dx0 = math.floor(dist0/gx)*gx
        d = dx0
        while d <= dist1 + gx:
            sp = self.w2s(d, 0)
            painter.drawLine(int(sp.x()), 0, int(sp.x()), h)
            d += gx

    def _draw_colorbar(self, painter: QPainter):
        """平面線形カラーバーをキャンバス上端に描画する。

        各要素の累積距離範囲を Segment=青・Clothoid=緑・Arc=紫で色分けし、
        ニックネームと平面長をラベル表示する。要素境界に縦の破線を描く。
        """
        if not self._plan_elements:
            return
        cb_y = 2
        font = QFont(); font.setPointSize(8)
        painter.setFont(font)

        for idx, elem in enumerate(self._plan_elements):
            if idx >= len(self._elem_offsets):
                break
            offset = self._elem_offsets[idx]
            L = self._profiles[idx].plan_length if idx < len(self._profiles) else 0
            color = self._element_color(elem)
            x0 = self.w2s(offset,     0).x()
            x1 = self.w2s(offset + L, 0).x()
            painter.fillRect(int(x0), cb_y, max(int(x1-x0), 1), self.CB_H, color)
            # ラベル
            painter.setPen(QPen(QColor(255,255,255)))
            eid = getattr(elem, 'id', None)
            name = self.scene.nicknames.get(eid, "")
            kind = ("線分" if isinstance(elem, Segment) else
                    "クロ" if isinstance(elem, Clothoid) else "円弧")
            label = f"{kind}" + (f"[{name}]" if name else "") + f" {L:.0f}m"
            painter.drawText(int(x0)+2, cb_y, max(int(x1-x0)-4, 1), self.CB_H,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             label)
            # 要素境界の縦線
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(x1), cb_y, int(x1), self.height())

    def _element_length(self, elem) -> float:
        """平面線形要素の平面長を返す（カラーバー幅の計算用）。

        Parameters
        ----------
        elem : Segment or Arc or Clothoid
            平面長を求める要素。

        Returns
        -------
        float
            平面長 [m]。Clothoid は points を累積した折れ線長で近似する。
        """
        if isinstance(elem, Segment):
            return elem.length()
        elif isinstance(elem, Arc):
            return elem.arc_length()
        elif isinstance(elem, Clothoid):
            if elem.is_valid and len(elem.points) >= 2:
                total = 0.0
                for i in range(len(elem.points)-1):
                    total += (elem.points[i+1] - elem.points[i]).length()
                return total
        return 0.0

    def _element_color(self, elem) -> QColor:
        """要素種別に対応するカラーバー用の QColor を返す。

        Parameters
        ----------
        elem : Segment or Arc or Clothoid or any
            色を決定する要素。非対応型はグレーを返す。

        Returns
        -------
        QColor
            Segment=青（CB_SEGMENT）、Arc=紫（CB_ARC）、Clothoid=緑（CB_CLOTHOID）、
            その他=グレー。
        """
        if isinstance(elem, Segment):  return CB_SEGMENT
        if isinstance(elem, Arc):      return CB_ARC
        if isinstance(elem, Clothoid): return CB_CLOTHOID
        return QColor(128,128,128)

    def _draw_profile(self, painter: QPainter):
        """勾配直線と縦断曲線をチェーン全体にわたって描画する。

        VPC〜VPT の範囲は放物線（32 分割の折れ線近似）で、それ以外は
        勾配直線をそのまま描画する。
        """
        gls = self._grade_lines_sorted()
        if not gls:
            return

        # 縦断曲線の範囲セット（VPC〜VPT）
        vc_ranges = [(vc.vpc_dist, vc.vpt_dist, vc) for vc in self._vertical_curves]

        for gl in gls:
            is_sel = (gl is self._selected)
            line_color = QColor(240, 200, 80) if is_sel else QColor(100, 160, 240)
            vc_color   = QColor(240, 140, 40) if is_sel else QColor(240, 180, 60)

            d0, d1 = gl.dist_start, gl.dist_end
            if abs(d1 - d0) < 1e-9:
                continue

            my_vcs = [(v0, v1, vc) for v0, v1, vc in vc_ranges
                      if v0 < d1 - 0.001 and v1 > d0 + 0.001]

            def gl_elev(d, _gl=gl):
                t = ((d - _gl.dist_start) / (_gl.dist_end - _gl.dist_start)
                     if abs(_gl.dist_end - _gl.dist_start) > 1e-9 else 0)
                return _gl.elev_start + (_gl.elev_end - _gl.elev_start) * t

            def is_in_vc(d):
                return any(v0 - 0.001 <= d <= v1 + 0.001 for v0, v1, _ in my_vcs)

            # 直線部分
            painter.setPen(QPen(line_color, 2))
            n_steps = max(2, int((d1 - d0) * self._scale_x / 4))
            prev_screen = None
            for i in range(n_steps + 1):
                dd = d0 + (d1 - d0) * i / n_steps
                if is_in_vc(dd):
                    prev_screen = None
                    continue
                p = self.w2s(dd, gl_elev(dd))
                if prev_screen is not None:
                    painter.drawLine(prev_screen, p)
                prev_screen = p

            # 縦断曲線（放物線）部分
            painter.setPen(QPen(vc_color, 2))
            for v0, v1, vc in my_vcs:
                path = QPainterPath()
                n = 64
                first = True
                for i in range(n + 1):
                    dd = v0 + (v1 - v0) * i / n
                    ee = vc.elevation_at(dd)
                    if math.isnan(ee):
                        continue
                    p = self.w2s(dd, ee)
                    if first:
                        path.moveTo(p); first = False
                    else:
                        path.lineTo(p)
                if not first:
                    painter.drawPath(path)

        # VPC/VPT マーカー
        for vc in self._vertical_curves:
            is_sel = (vc is self._selected)
            col = QColor(240, 140, 40) if is_sel else QColor(240, 180, 60)
            painter.setBrush(QBrush(col))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            for dd, ee in [(vc.vpc_dist, vc.vpc_elev), (vc.vpt_dist, vc.vpt_elev)]:
                painter.drawEllipse(self.w2s(dd, ee), 4, 4)

    def _draw_rubber(self, painter: QPainter):
        """勾配直線モードで始点確定後、マウス位置までのラバー線（点線）を描画する。"""
        if self._mode != "grade" or self._grade_first is None:
            return
        if self._mouse_screen is None:
            return
        d0, e0 = self._grade_first
        sx, sy = self._mouse_screen
        p1 = self.w2s(d0, e0)
        p2 = QPointF(sx, sy)
        pen = QPen(QColor(200, 200, 200, 160), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        # 始点マーカー（小さい×）
        painter.setPen(QPen(QColor(200, 200, 200, 200), 1))
        r = 4
        painter.drawLine(QPointF(p1.x()-r, p1.y()-r), QPointF(p1.x()+r, p1.y()+r))
        painter.drawLine(QPointF(p1.x()+r, p1.y()-r), QPointF(p1.x()-r, p1.y()+r))

    def _draw_axes(self, painter: QPainter):
        """距離軸（水平）と標高軸（垂直）のグリッドラベルを描画する。"""
        pen = QPen(QColor(120, 120, 120), 1)
        painter.setPen(pen)
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        w, h = self.width(), self.height()

        # 距離軸（X）ラベル
        dist0, _ = self.s2w(0, 0)
        dist1, _ = self.s2w(w, 0)
        raw_x = max((dist1 - dist0) / 6, 1e-9)
        if raw_x > 0:
            mag = 10 ** math.floor(math.log10(raw_x))
            gx = mag * min((s for s in [1, 2, 5, 10] if s * mag >= raw_x * 0.8),
                           default=10)
            d = math.ceil(dist0 / gx) * gx
            while d <= dist1 + gx:
                sp = self.w2s(d, 0)
                painter.drawText(int(sp.x()) - 25, h - 18, 50, 16,
                                 Qt.AlignmentFlag.AlignCenter, f"{d:.0f}")
                d += gx

        # 標高軸（Y）ラベル
        _, elev0 = self.s2w(0, h)
        _, elev1 = self.s2w(0, 0)
        raw_y = max((elev1 - elev0) / 5, 1e-9)
        if raw_y > 0:
            mag = 10 ** math.floor(math.log10(raw_y))
            gy = mag * min((s for s in [1, 2, 5, 10] if s * mag >= raw_y * 0.8),
                           default=10)
            e = math.ceil(elev0 / gy) * gy
            while e <= elev1 + gy:
                sp = self.w2s(0, e)
                painter.drawText(2, int(sp.y()) - 8, 72, 16,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 f"{e:.1f}m")
                e += gy

    def _draw_handles(self, painter: QPainter):
        """勾配直線の全端点ハンドルを描画する（_get_handles が返すリストを使う）。"""
        if self._mode != "select":
            return
        for h in self._get_handles():
            p = self.w2s(h['dist'], h['elev'])
            is_sel = any(gl is self._selected for gl, _ in h['partners'])
            color = QColor(240, 160, 40) if is_sel else QColor(160, 160, 160)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(p, self.HANDLE_R, self.HANDLE_R)

    def mousePressEvent(self, event):
        pos = event.position()
        sx, sy = pos.x(), pos.y()
        btn = event.button()

        if btn == Qt.MouseButton.MiddleButton:
            self._pan_start = Vec2(sx, sy)
            self._pan_offset_start = Vec2(self._offset.x, self._offset.y)
            return

        if btn == Qt.MouseButton.LeftButton and self._mode == "select":
            # ハンドルヒット？
            h = self._hit_handle(sx, sy)
            if h:
                self._drag_handle = h
                self._drag_start_screen = Vec2(sx, sy)
                self._mouse_moved_px = 0.0
                return
            # 図形ヒット？
            hit = self._hit_test(sx, sy)
            if hit is not self._selected:
                self._selected = hit
                self.selection_changed.emit(hit)
                self.update()
            # パン開始
            self._pan_start = Vec2(sx, sy)
            self._pan_offset_start = Vec2(self._offset.x, self._offset.y)

        elif btn == Qt.MouseButton.LeftButton and self._mode == "grade":
            dist, elev = self.s2w(sx, sy)

            # チェーン全体の長さ（area_end）
            total_len = sum(ep.plan_length for ep in self._profiles) if self._profiles else float('inf')

            # スナップ候補: 既存端点 + 区間端 (0, total_len)
            snap_pts = [(0.0, None), (total_len, None)]
            for gl in self._grade_lines:
                snap_pts.append((gl.dist_start, gl.elev_start))
                snap_pts.append((gl.dist_end,   gl.elev_end))

            def snap_dist(d, e):
                """最も近いスナップ点（既存端点・区間端）に吸着する。

                x 方向が 12px 以内のスナップ候補のうち最近傍に吸着する。
                標高はスナップ点のものを使い、スナップ点が None なら入力値のまま。

                Parameters
                ----------
                d : float
                    入力の累積距離 [m]。
                e : float
                    入力の標高 [m]。

                Returns
                -------
                tuple[float, float]
                    吸着後の (dist, elev)。
                """
                best_d, best_e, best_px = d, e, float('inf')
                for sd, se in snap_pts:
                    px = abs(d - sd) * self._scale_x
                    if px < 12 and px < best_px:
                        best_px = px
                        best_d  = sd
                        best_e  = se if se is not None else e
                return best_d, best_e

            if self._grade_first is None:
                dist, elev = snap_dist(dist, elev)
                self._grade_first = (dist, elev)
            else:
                d0, e0 = self._grade_first
                dist, elev = snap_dist(dist, elev)

                if abs(dist - d0) < 0.01:
                    return  # 始点と終点が同じ距離は無効

                new_start = min(d0, dist)
                new_end   = max(d0, dist)
                new_elev_start = e0    if d0 <= dist else elev
                new_elev_end   = elev  if d0 <= dist else e0

                # チェーン範囲外はクリップ
                if total_len > 0:
                    new_start = max(0.0, min(new_start, total_len))
                    new_end   = max(0.0, min(new_end,   total_len))
                if abs(new_end - new_start) < 0.01:
                    return

                # 既存勾配直線のうち新しい範囲と重複するものを切り取る
                # 重複部分を削除し、はみ出し部分を残す
                new_gls = []
                for gl in self._grade_lines:
                    gs, ge = gl.dist_start, gl.dist_end
                    if ge <= new_start + 0.001 or gs >= new_end - 0.001:
                        # 重複なし → そのまま残す
                        new_gls.append(gl)
                    else:
                        # 重複あり → 新範囲の外側部分を残す
                        if gs < new_start - 0.001:
                            # 左側はみ出し部分を残す
                            elev_at_split = self._elev_at(new_start, gl)
                            left_gl = GradeLine(dist_start=gs, elev_start=gl.elev_start,
                                                dist_end=new_start, elev_end=elev_at_split)
                            new_gls.append(left_gl)
                        if ge > new_end + 0.001:
                            # 右側はみ出し部分を残す
                            elev_at_split = self._elev_at(new_end, gl)
                            right_gl = GradeLine(dist_start=new_end, elev_start=elev_at_split,
                                                 dist_end=ge, elev_end=gl.elev_end)
                            new_gls.append(right_gl)

                # 新しい勾配直線を追加
                new_gl = GradeLine(dist_start=new_start, elev_start=new_elev_start,
                                   dist_end=new_end, elev_end=new_elev_end)
                new_gls.append(new_gl)
                new_gls.sort(key=lambda g: g.dist_start)
                self._grade_lines.clear()
                self._grade_lines.extend(new_gls)

                # 隣接する勾配直線の端点を強制スナップ
                self._snap_grade_lines()

                self._grade_first = (dist, elev)
                self.selection_changed.emit(None)
                self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        sx, sy = pos.x(), pos.y()
        btns = event.buttons()

        # ハンドルドラッグ
        if self._drag_handle is not None and btns & Qt.MouseButton.LeftButton:
            if self._drag_start_screen:
                self._mouse_moved_px = math.hypot(
                    sx - self._drag_start_screen.x,
                    sy - self._drag_start_screen.y)
            if self._mouse_moved_px > 2:
                new_dist, new_elev = self.s2w(sx, sy)
                self._apply_handle_drag(self._drag_handle, new_dist, new_elev)
                self.update()
            # ドラッグ中もマウス座標を通知
            dist, elev = self.s2w(sx, sy)
            self._mouse_screen = (sx, sy)
            self.mouse_world_pos.emit(dist, elev)
            return

        # パン
        if self._pan_start and btns & (Qt.MouseButton.MiddleButton |
                                        Qt.MouseButton.LeftButton):
            dx = sx - self._pan_start.x
            dy = sy - self._pan_start.y
            if self._mode == "select" and math.hypot(dx, dy) < 4:
                return
            self._offset = Vec2(self._pan_offset_start.x + dx,
                                self._pan_offset_start.y + dy)
            self.update()

        # マウス座標を更新してラバー線・座標表示を更新
        self._mouse_screen = (sx, sy)
        dist, elev = self.s2w(sx, sy)
        self.mouse_world_pos.emit(dist, elev)
        if self._mode == "grade" and self._grade_first is not None:
            self.update()  # ラバー線の再描画

    def _apply_handle_drag(self, h: dict, new_dist: float, new_elev: float):
        """ハンドルのドラッグ操作を GradeLine と VerticalCurve に反映する。

        partners に含まれるすべての GradeLine の端点を new_dist/new_elev に更新する
        ため、共有ハンドル（境界点）では隣接する 2 本の GradeLine が同時に追従する。
        ドラッグした点を PVI とする縦断曲線があれば pvi_dist/pvi_elev を追従させ
        `_recalc_vc_gradients` で g1/g2 を再計算する。最後に `_snap_grade_lines`
        を呼んで隙間をゼロに揃える。

        Parameters
        ----------
        h : dict
            `_get_handles` が返すハンドル辞書。
        new_dist : float
            ドラッグ先の累積距離 [m]。
        new_elev : float
            ドラッグ先の標高 [m]。
        """
        old_dist = h['dist']

        # partners の全勾配直線の端点を更新
        for gl, end in h['partners']:
            if end == 'start':
                gl.dist_start = new_dist
                gl.elev_start = new_elev
            else:
                gl.dist_end   = new_dist
                gl.elev_end   = new_elev

        # ハンドル座標を更新
        h['dist'] = new_dist
        h['elev'] = new_elev

        # この点を PVI とする縦断曲線を追従させる
        for vc in self._vertical_curves:
            if abs(vc.pvi_dist - old_dist) < 0.01:
                vc.pvi_dist = new_dist
                vc.pvi_elev = new_elev
                self._recalc_vc_gradients(vc)

        # ドラッグ後に隣接直線を強制スナップ（隙間ゼロを保証）
        self._snap_grade_lines()

    def _recalc_vc_gradients(self, vc: 'VerticalCurve'):
        """縦断曲線 vc の前後に位置する GradeLine から g1, g2 を再計算する。

        GradeLine の端点が変更された後（ドラッグ・数値入力）に呼ばれる。
        pvi_dist を基準に前（≤ pvi_dist）の最後の GradeLine から g1 を、
        後（≥ pvi_dist）の最初の GradeLine から g2 を取得する。

        Parameters
        ----------
        vc : VerticalCurve
            再計算対象の縦断曲線。
        """
        gls = sorted(self._grade_lines, key=lambda g: g.dist_start)
        prev_gl = next((gl for gl in reversed(gls)
                        if gl.dist_end <= vc.pvi_dist + 0.01), None)
        next_gl = next((gl for gl in gls
                        if gl.dist_start >= vc.pvi_dist - 0.01), None)
        if prev_gl:
            vc.g1 = prev_gl.gradient
        if next_gl:
            vc.g2 = next_gl.gradient

    def mouseReleaseEvent(self, event):
        if self._drag_handle is not None:
            # 全縦断曲線の勾配を再確定
            for vc in self._vertical_curves:
                self._recalc_vc_gradients(vc)
            self._drag_handle = None
            self._drag_start_screen = None
            self.selection_changed.emit(self._selected)
        self._pan_start = None
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            if isinstance(self._selected, GradeLine):
                self._delete_grade_line(self._selected)
        elif event.key() == Qt.Key.Key_Escape:
            # 勾配直線モードの入力をリセット
            if self._grade_first is not None:
                self._grade_first = None
                self._mouse_screen = None
                self.update()
        super().keyPressEvent(event)

    def _delete_grade_line(self, gl: GradeLine):
        """勾配直線を削除し、関連する縦断曲線もあわせて削除する。

        gl の dist_start または dist_end と pvi_dist が 0.01m 以内の
        縦断曲線を先に除去してから gl を _grade_lines から除去する。
        selection_changed を emit して右パネルを更新する。

        Parameters
        ----------
        gl : GradeLine
            削除する勾配直線。_grade_lines に含まれない場合は何もしない。
        """
        if gl not in self._grade_lines:
            return
        # この勾配直線が prev or next の縦断曲線を削除
        to_remove = [vc for vc in self._vertical_curves
                     if vc.prev_line_id == gl.id or vc.next_line_id == gl.id
                     or abs(vc.pvi_dist - gl.dist_end) < 0.01
                     or abs(vc.pvi_dist - gl.dist_start) < 0.01]
        for vc in to_remove:
            self._vertical_curves.remove(vc)
        self._grade_lines.remove(gl)
        self._selected = None
        self.selection_changed.emit(None)
        self.update()

    def _hit_test(self, sx: float, sy: float) -> Optional[object]:
        """スクリーン座標 (sx, sy) に最も近い GradeLine/VerticalCurve を返す。

        ヒット許容距離は TOL_PX=8.0 px。勾配直線は線分との距離で、
        縦断曲線は 32 分割の折れ線近似で最短距離を計算する。

        Parameters
        ----------
        sx, sy : float
            スクリーン座標（ピクセル）。

        Returns
        -------
        GradeLine or VerticalCurve or None
            最も近い図形。TOL_PX 以内にない場合は None。
        """
        TOL_PX = 8.0  # ヒット許容距離 [px]
        best_obj  = None
        best_dist = TOL_PX

        # 勾配直線: 線分との距離
        for gl in self._grade_lines:
            p1 = self.w2s(gl.dist_start, gl.elev_start)
            p2 = self.w2s(gl.dist_end,   gl.elev_end)
            d  = self._dist_point_seg(sx, sy, p1.x(), p1.y(), p2.x(), p2.y())
            if d < best_dist:
                best_dist = d
                best_obj  = gl

        # 縦断曲線: 折れ線近似で距離
        for vc in self._vertical_curves:
            n = 32
            prev = None
            for i in range(n + 1):
                dd = vc.vpc_dist + vc.length * i / n
                ee = vc.elevation_at(dd)
                cur = self.w2s(dd, ee)
                if prev is not None:
                    d = self._dist_point_seg(sx, sy,
                                             prev.x(), prev.y(),
                                             cur.x(), cur.y())
                    if d < best_dist:
                        best_dist = d
                        best_obj  = vc
                prev = cur

        return best_obj

    @staticmethod
    def _dist_point_seg(px: float, py: float,
                        ax: float, ay: float,
                        bx: float, by: float) -> float:
        """点 (px, py) からスクリーン座標上の線分 (ax,ay)-(bx,by) への最短距離を返す。

        `_hit_test` 内で勾配直線との距離計算に使う。

        Returns
        -------
        float
            最短距離 [px]。線分が縮退（長さゼロ）のとき始点からの距離を返す。
        """
        dx, dy = bx - ax, by - ay
        l2 = dx*dx + dy*dy
        if l2 < 1e-12:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / l2))
        return math.hypot(px - (ax + t*dx), py - (ay + t*dy))

    def fit_all(self):
        """全 GradeLine/VerticalCurve が収まるよう 10% マージンでビューを調整する。

        図形がない場合はデフォルト値（scale_x=2.0, scale_y=5.0）にリセットする。
        """
        gls = self._grade_lines_sorted()
        if not gls:
            return
        ds, es = [], []
        for gl in gls:
            ds += [gl.dist_start, gl.dist_end]
            es += [gl.elev_start, gl.elev_end]
        for vc in self._vertical_curves:
            ds += [vc.vpc_dist, vc.vpt_dist]
            es += [vc.vpc_elev, vc.vpt_elev]
        if not ds:
            return
        dmin, dmax = min(ds), max(ds)
        emin, emax = min(es), max(es)
        md = max(dmax - dmin, 1)
        me = max(emax - emin, 1)
        mg = 0.1
        self._scale_x = self.width()  / (md * (1 + 2 * mg))
        self._scale_y = self.height() / (me * (1 + 2 * mg))
        self._offset  = Vec2(self.width() / 2  - (dmin + dmax) / 2 * self._scale_x,
                             self.height() / 2 + (emin + emax) / 2 * self._scale_y)
        self.update()


def _make_empty_profile():
    """空の ElementProfile を生成する（選択なしで縦断線形を開いた場合）"""
    from models import ElementProfile
    return ElementProfile()


class VerticalAlignmentWindow(QMainWindow):
    """縦断線形設計ウィンドウ。

    ProfileCanvas（左）と右パネル（プロパティ・操作）を QSplitter で左右分割する。
    ProfileCanvas の selection_changed シグナルを受けて _refresh_props を呼ぶ。
    閉じる際（closeEvent）に ProfileCanvas.save_to_profiles() を呼んで各
    ElementProfile にデータを書き戻す。
    """

    def __init__(self, scene: Scene, profiles: list,
                 plan_elements: list, rev_flags: list, parent=None):
        """
        Parameters
        ----------
        scene : Scene
            現在のシーン（ニックネーム参照用）。
        profiles : list[ElementProfile]
            チェーン順に並んだ縦断データ。
        plan_elements : list[Segment | Arc | Clothoid]
            チェーン順の平面線形要素。
        rev_flags : list[bool]
            各要素の逆順フラグ。
        parent : QWidget, optional
            親ウィジェット。None のとき独立ウィンドウとして表示する。
        """
        super().__init__(parent)
        self.scene    = scene
        self.profiles = profiles
        self.rev_flags = rev_flags   # list[ElementProfile]

        # タイトルを要素の種別で分かりやすく表示
        if plan_elements:
            def elem_label(obj):
                """平面線形要素のカラーバーラベル文字列を返す。

                Returns
                -------
                str
                    "{種別}[{ニックネーム}] {平面長:.0f}m" 形式の文字列。
                """
                if isinstance(obj, Segment):
                    return f"線分#{obj.id}"
                if isinstance(obj, Arc):
                    return f"円弧#{obj.id}"
                if isinstance(obj, Clothoid):
                    return f"クロソイド#{obj.id}"
                return f"#{obj.id}"
            title = "縦断線形 [" + " → ".join(elem_label(e) for e in plan_elements) + "]"
        else:
            title = "縦断線形設計"
        self.setWindowTitle(title)
        self.resize(1000, 600)

        # ─── 中央ウィジェット ─────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self._canvas = ProfileCanvas(scene, self)
        self._canvas.set_plan_elements(plan_elements, profiles, rev_flags)
        splitter.addWidget(self._canvas)

        # ─── 右パネル ─────────────────────────────────────────
        right = QWidget()
        right.setMinimumWidth(240)
        right.setMaximumWidth(340)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 4, 4, 4)

        # モードボタン
        mode_grp = QGroupBox("モード")
        mode_lay = QHBoxLayout(mode_grp)
        self._btn_sel   = QPushButton("[S] 選択")
        self._btn_grade = QPushButton("[G] 勾配直線")
        self._btn_sel.setCheckable(True);   self._btn_sel.setChecked(True)
        self._btn_grade.setCheckable(True)
        self._btn_sel.clicked.connect(self._set_select_mode)
        self._btn_grade.clicked.connect(self._set_grade_mode)
        mode_lay.addWidget(self._btn_sel)
        mode_lay.addWidget(self._btn_grade)
        right_lay.addWidget(mode_grp)

        # 全体表示
        btn_fit = QPushButton("全体表示 (Ctrl+0)")
        btn_fit.clicked.connect(self._canvas.fit_all)
        right_lay.addWidget(btn_fit)

        # マウス座標表示
        coord_grp = QGroupBox("マウス座標")
        coord_lay = QHBoxLayout(coord_grp)
        self._lbl_mouse_dist = QLabel("距離: ---")
        self._lbl_mouse_elev = QLabel("標高: ---")
        coord_lay.addWidget(self._lbl_mouse_dist)
        coord_lay.addWidget(self._lbl_mouse_elev)
        right_lay.addWidget(coord_grp)

        # プロパティ表示エリア（スクロール）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._prop_widget = QWidget()
        self._prop_layout = QVBoxLayout(self._prop_widget)
        self._prop_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._prop_widget)
        right_lay.addWidget(scroll, 1)

        splitter.addWidget(right)
        splitter.setSizes([700, 300])

        # シグナル接続
        self._canvas.selection_changed.connect(self._on_selection_changed)
        self._canvas.mouse_world_pos.connect(self._update_mouse_pos)

        # キャンバスのキーイベントをウィンドウで受け取る
        self._canvas.installEventFilter(self)

        self._refresh_props()

    # ─── モード切替 ──────────────────────────────────────────
    def _set_select_mode(self):
        """選択モードに切り替え、ツールボタンの checked 状態を更新する。"""
        self._canvas.set_mode("select")
        self._btn_sel.setChecked(True)
        self._btn_grade.setChecked(False)

    def _set_grade_mode(self):
        """勾配直線モードに切り替え、ツールボタンの checked 状態を更新する。"""
        self._canvas.set_mode("grade")
        self._btn_sel.setChecked(False)
        self._btn_grade.setChecked(True)

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key.Key_S:
            self._set_select_mode()
        elif k == Qt.Key.Key_G:
            self._set_grade_mode()
        elif k == Qt.Key.Key_Escape:
            self._canvas._grade_first = None
            self._canvas._mouse_screen = None
            self._canvas.update()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """ProfileCanvas のキーイベントをこのウィンドウで代わりに処理する。

        Parameters
        ----------
        obj : QObject
            イベントの発生元。
        event : QEvent
            受け取ったイベント。

        Returns
        -------
        bool
            KeyPress イベントを処理した場合 True。それ以外は super() に委譲。
        """
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(event)
            return True
        return False

    def closeEvent(self, event):
        """閉じる前に ProfileCanvas.save_to_profiles() を呼んで縦断データを保存する。"""
        self._canvas.save_to_profiles()
        super().closeEvent(event)

    # ─── マウス座標表示 ──────────────────────────────────────
    def _update_mouse_pos(self, dist: float, elev: float):
        """ProfileCanvas のマウス座標シグナルを受け取り、右パネルのラベルを更新する。

        Parameters
        ----------
        dist : float
            マウス位置の累積距離 [m]。
        elev : float
            マウス位置の標高 [m]。
        """
        self._lbl_mouse_dist.setText(f"距離: {dist:.3f} m")
        self._lbl_mouse_elev.setText(f"標高: {elev:.3f} m")

    # ─── 選択変更 ────────────────────────────────────────────
    def _on_selection_changed(self, obj):
        self._canvas.update()
        self._refresh_props()

    # ─── プロパティ表示 ──────────────────────────────────────
    def _clear_props(self):
        while self._prop_layout.count():
            item = self._prop_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _refresh_props(self):
        self._clear_props()
        sel = self._canvas._selected

        if sel is None:
            self._prop_layout.addWidget(QLabel("図形を選択してください"))
            self._build_grade_list()
            return

        if isinstance(sel, GradeLine):
            self._build_grade_props(sel)
        elif isinstance(sel, VerticalCurve):
            self._build_vc_props(sel)
        else:
            self._prop_layout.addWidget(QLabel("図形を選択してください"))

        self._build_grade_list()

    def _build_grade_props(self, gl: GradeLine):
        grp = QGroupBox("勾配直線プロパティ")
        lay = QVBoxLayout(grp)
        lay.addWidget(QLabel(f"ID: {gl.id}"))

        lay.addWidget(_separator())

        # 始点・終点の数値入力
        # 変更時は縦断曲線も追従させる
        lbl_grad   = QLabel(f"勾配: {gl.gradient:.4f} %")
        lbl_horiz  = QLabel(f"水平長: {gl.dist_end - gl.dist_start:.3f} m")

        def refresh_derived(changed_end='end'):
            """GradeLine の数値が変わった後、派生値の表示と隣接スナップを更新する。"""
            lbl_grad.setText(f"勾配: {gl.gradient:.4f} %")
            lbl_horiz.setText(f"水平長: {gl.dist_end - gl.dist_start:.3f} m")
            for vc in self._canvas._vertical_curves:
                self._canvas._recalc_vc_gradients(vc)
            self._canvas._snap_grade_lines(changed_end)
            self._canvas.update()
            # スナップで隣の直線の値も変わるため右パネルを再構築
            # （ただし無限ループを避けるため _block_grade_sb で保護）
            if not self._block_grade_sb:
                self._refresh_props()

        # SpinBox のブロックフラグ（シグナルループ防止）
        self._block_grade_sb = False

        def add_endpoint(label, get_dist, set_dist, get_elev, set_elev, end_type):
            """勾配直線の端点（始点または終点）の距離・標高入力フォームを生成する。

            Parameters
            ----------
            label : str
                フォームグループのラベル（例: "始点"）。
            get_dist, get_elev : callable
                現在の距離・標高を返すゲッター関数。
            set_dist, set_elev : callable
                距離・標高を設定するセッター関数。
            end_type : str
                'start' または 'end'。_snap_grade_lines に渡すスナップ方向。
            """            """end_type: 'start' or 'end' — どちらの端点か"""
            lay.addWidget(QLabel(label))
            row_d = QHBoxLayout()
            row_e = QHBoxLayout()
            sb_d = _make_spinbox(get_dist(), lo=-1e6, hi=1e6, step=1.0, decimals=3)
            sb_e = _make_spinbox(get_elev(), lo=-1e6, hi=1e6, step=0.1, decimals=3)

            def sync_sb():
                """スピンボックスの表示を現在値に同期する（コールバックの無限ループを防ぐ）。"""
                if self._block_grade_sb:
                    return
                self._block_grade_sb = True
                sb_d.setValue(get_dist())
                sb_e.setValue(get_elev())
                self._block_grade_sb = False

            def on_dist(v, _end=end_type):
                """距離スピンボックスの値変更コールバック。"""
                if self._block_grade_sb:
                    return
                self._block_grade_sb = True
                set_dist(v)
                for vc in self._canvas._vertical_curves:
                    if abs(vc.pvi_dist - v) < 0.01:
                        vc.pvi_dist = v
                self._block_grade_sb = False
                refresh_derived(_end)

            def on_elev(v, _end=end_type):
                """標高スピンボックスの値変更コールバック。"""
                if self._block_grade_sb:
                    return
                self._block_grade_sb = True
                set_elev(v)
                for vc in self._canvas._vertical_curves:
                    if abs(vc.pvi_dist - get_dist()) < 0.01:
                        vc.pvi_elev = v
                self._block_grade_sb = False
                refresh_derived(_end)

            sb_d.valueChanged.connect(on_dist)
            sb_e.valueChanged.connect(on_elev)
            row_d.addWidget(QLabel("距離:")); row_d.addWidget(sb_d); row_d.addWidget(QLabel("m"))
            row_e.addWidget(QLabel("標高:")); row_e.addWidget(sb_e); row_e.addWidget(QLabel("m"))
            lay.addLayout(row_d)
            lay.addLayout(row_e)

        add_endpoint("始点",
                     lambda: gl.dist_start, lambda v: setattr(gl, 'dist_start', v),
                     lambda: gl.elev_start, lambda v: setattr(gl, 'elev_start', v),
                     'start')
        add_endpoint("終点",
                     lambda: gl.dist_end,   lambda v: setattr(gl, 'dist_end',   v),
                     lambda: gl.elev_end,   lambda v: setattr(gl, 'elev_end',   v),
                     'end')

        lay.addWidget(lbl_horiz)
        lay.addWidget(lbl_grad)

        lay.addWidget(_separator())

        # 削除ボタン
        btn_del_gl = QPushButton("この勾配直線を削除")
        btn_del_gl.setStyleSheet("color: #e08080;")
        def do_delete_gl():
            """「この勾配直線を削除」ボタンのコールバック。"""
            self._canvas._delete_grade_line(gl)
            self._refresh_props()
        btn_del_gl.clicked.connect(do_delete_gl)
        lay.addWidget(btn_del_gl)

        # 次の勾配直線があれば縦断曲線挿入ボタン
        idx = self._canvas._grade_lines.index(gl) if gl in self._canvas._grade_lines else -1
        can_insert = (idx >= 0 and idx + 1 < len(self._canvas._grade_lines))
        # 既に縦断曲線があるか確認
        already_vc = any(
            abs(vc.pvi_dist - gl.dist_end) < 1e-6
            for vc in self._canvas._vertical_curves
        ) if can_insert else False

        lay.addWidget(_separator())
        sb_len = _make_spinbox(50.0, 1.0, 10000.0, 10.0, 1)
        sb_len.setPrefix("L="); sb_len.setSuffix(" m")
        btn_ins = QPushButton("縦断曲線を挿入")
        btn_ins.setEnabled(can_insert and not already_vc)
        if not can_insert:
            btn_ins.setToolTip("次の勾配直線が存在しません")
        elif already_vc:
            btn_ins.setToolTip("既に縦断曲線があります")

        def do_insert():
            """「縦断曲線を挿入」ボタンのコールバック。選択中の GradeLine の終端に縦断曲線を追加する。"""
            self._insert_vertical_curve(gl, sb_len.value())

        btn_ins.clicked.connect(do_insert)
        row = QHBoxLayout()
        row.addWidget(sb_len); row.addWidget(btn_ins)
        lay.addLayout(row)
        self._prop_layout.addWidget(grp)

    def _build_vc_props(self, vc: VerticalCurve):
        grp = QGroupBox("縦断曲線プロパティ")
        lay = QVBoxLayout(grp)

        lay.addWidget(QLabel(f"ID: {vc.id}"))
        lay.addWidget(QLabel(f"PVI距離:  {vc.pvi_dist:.3f} m"))
        lay.addWidget(QLabel(f"PVI標高:  {vc.pvi_elev:.3f} m"))
        lay.addWidget(QLabel(f"前勾配 g1: {vc.g1:.4f} %"))
        lay.addWidget(QLabel(f"後勾配 g2: {vc.g2:.4f} %"))
        dg = abs(vc.g2 - vc.g1)
        lay.addWidget(QLabel(f"勾配変化量: {dg:.4f} %"))

        lay.addWidget(_separator())

        # 曲線長 L — 変更可能
        lay.addWidget(QLabel("曲線長 L [m]:"))
        sb_L = _make_spinbox(vc.length, lo=1.0, hi=10000.0, step=10.0, decimals=1)

        def on_L_changed(val: float):
            """曲線長スピンボックスの値変更コールバック。VPC/VPT および前後 GradeLine の端点を追従させる。

            Parameters
            ----------
            val : float
                新しい曲線長 L [m]。
            """
            if val < 1.0:
                return
            # 勾配直線を VPC/VPT に合わせて再調整
            old_vpc = vc.vpc_dist
            old_vpt = vc.vpt_dist
            vc.length = val
            new_vpc = vc.vpc_dist
            new_vpt = vc.vpt_dist
            # 前後の勾配直線の端点を更新
            for gl in self._canvas._grade_lines:
                if abs(gl.dist_end - old_vpc) < 0.01:
                    gl.dist_end  = new_vpc
                    gl.elev_end  = vc.vpc_elev
                if abs(gl.dist_start - old_vpt) < 0.01:
                    gl.dist_start = new_vpt
                    gl.elev_start = vc.vpt_elev
            self._canvas.update()
            # 表示を更新（再帰を避けるため sb は直接更新しない）
            lbl_vpc.setText(f"VPC: 距離 {vc.vpc_dist:.3f} m  標高 {vc.vpc_elev:.3f} m")
            lbl_vpt.setText(f"VPT: 距離 {vc.vpt_dist:.3f} m  標高 {vc.vpt_elev:.3f} m")
            lbl_K.setText(f"K値: {vc.K:.2f} m/%")

        sb_L.valueChanged.connect(on_L_changed)
        lay.addWidget(sb_L)

        lay.addWidget(_separator())

        # 設計指標（読み取り専用ラベル）
        lbl_vpc = QLabel(f"VPC: 距離 {vc.vpc_dist:.3f} m  標高 {vc.vpc_elev:.3f} m")
        lbl_vpt = QLabel(f"VPT: 距離 {vc.vpt_dist:.3f} m  標高 {vc.vpt_elev:.3f} m")
        lbl_K   = QLabel(f"K値: {vc.K:.2f} m/%")
        lay.addWidget(lbl_vpc)
        lay.addWidget(lbl_vpt)
        lay.addWidget(lbl_K)

        lay.addWidget(_separator())

        # 削除ボタン
        btn_del = QPushButton("縦断曲線を削除")
        btn_del.setStyleSheet("color: #e08080;")
        def do_delete():
            self._delete_vertical_curve(vc)
        btn_del.clicked.connect(do_delete)
        lay.addWidget(btn_del)

        self._prop_layout.addWidget(grp)

    def _build_grade_list(self):
        """全 GradeLine を距離・勾配の一覧テーブルとして右パネル下部に表示する。

        _refresh_props の末尾で常に呼ばれ、選択状態によらず表示する。
        """
        grp = QGroupBox("勾配直線一覧")
        lay = QVBoxLayout(grp)
        for gl in self._canvas._grade_lines:
            lay.addWidget(QLabel(
                f"  {gl.dist_start:.1f}→{gl.dist_end:.1f} m  "
                f"勾配 {gl.gradient:.2f}%"
            ))
        if not self._canvas._grade_lines:
            lay.addWidget(QLabel("  (なし)"))
        self._prop_layout.addWidget(grp)

    # ─── 縦断曲線操作 ────────────────────────────────────────
    def _insert_vertical_curve(self, gl: GradeLine, length: float):
        """勾配直線 gl の終端（PVI）に曲線長 length の縦断曲線を挿入する。

        Parameters
        ----------
        gl : GradeLine
            PVI を提供する勾配直線（終端が PVI になる）。
        length : float
            縦断曲線の曲線長 L [m]。

        Notes
        -----
        gl が最後の GradeLine（次の GradeLine がない）場合は何もしない。
        挿入後に選択をリセットして _refresh_props を呼ぶ。
        """
        """
        勾配直線 gl の終点（= 次の勾配直線の始点 = PVI）に縦断曲線を挿入。
        勾配直線の端点は変更しない。PVI は gl.dist_end / gl.elev_end。
        """
        idx = self._canvas._grade_lines.index(gl)
        if idx + 1 >= len(self._canvas._grade_lines):
            return
        gl2 = self._canvas._grade_lines[idx + 1]
        pvi_d = gl.dist_end
        pvi_e = gl.elev_end
        vc = VerticalCurve(
            pvi_dist=pvi_d, pvi_elev=pvi_e,
            g1=gl.gradient, g2=gl2.gradient,
            length=length,
            prev_line_id=gl.id,
            next_line_id=gl2.id,
        )
        self._canvas._vertical_curves.append(vc)
        self._canvas._selected = None
        self._canvas.update()
        self._refresh_props()

    def _delete_vertical_curve(self, vc: VerticalCurve):
        """縦断曲線を _vertical_curves から削除する。

        Parameters
        ----------
        vc : VerticalCurve
            削除する縦断曲線。リストに存在しない場合は何もしない。

        Notes
        -----
        削除後に選択をリセットして _refresh_props を呼ぶ。
        """
        if vc not in self._canvas._vertical_curves:
            return
        self._canvas._vertical_curves.remove(vc)
        self._canvas._selected = None
        self._canvas.update()
        self._refresh_props()

