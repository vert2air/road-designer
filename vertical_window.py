"""
縦断線形設計ウィンドウ
"""
from __future__ import annotations
import math
from typing import Optional, List
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QDoubleSpinBox, QGroupBox, QScrollArea, QFrame,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath, QFont

from models import (Vec2, GradeLine, VerticalCurve, Scene,
                    Segment, Arc, Clothoid, new_id)


def _make_spinbox(val: float, lo: float = -1e6, hi: float = 1e6,
                  step: float = 1.0, decimals: int = 3) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(val)
    return sb


# ─── カラーバー色 ────────────────────────────────────────────
CB_SEGMENT  = QColor( 60, 120, 220)
CB_CLOTHOID = QColor( 40, 180,  80)
CB_ARC      = QColor(120,  40, 180)


class ProfileCanvas(QWidget):
    """縦断線形キャンバス"""
    selection_changed = pyqtSignal(object)

    def __init__(self, scene: Scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._grade_lines:     List[GradeLine]     = scene.grade_lines
        self._vertical_curves: List[VerticalCurve] = scene.vertical_curves
        self._plan_elements: list = []  # 平面線形要素 (Segment/Arc/Clothoid)

        # ビュー
        self._offset = Vec2(80, 300)
        self._scale_x = 2.0   # px/m (距離)
        self._scale_y = 5.0   # px/m (標高)
        self._selected: Optional[object] = None

        # ドラッグ
        self._pan_start: Optional[Vec2] = None
        self._pan_offset_start: Optional[Vec2] = None
        self._mode = "select"   # "select" | "grade"
        self._grade_first: Optional[tuple] = None  # (dist, elev)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_plan_elements(self, elements: list):
        self._plan_elements = elements
        self.update()

    def set_mode(self, mode: str):
        self._mode = mode
        self._grade_first = None

    # ─── 座標変換 ─────────────────────────────────────────────
    def w2s(self, dist: float, elev: float) -> QPointF:
        x = dist * self._scale_x + self._offset.x
        y = -elev * self._scale_y + self._offset.y
        return QPointF(x, y)

    def s2w(self, sx: float, sy: float) -> tuple[float, float]:
        dist = (sx - self._offset.x) / self._scale_x
        elev = -(sy - self._offset.y) / self._scale_y
        return dist, elev

    # ─── 描画 ─────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(28, 28, 32))

        self._draw_grid(painter)
        self._draw_colorbar(painter)
        self._draw_grade_lines(painter)
        self._draw_vertical_curves(painter)
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
        """平面線形カラーバーを上端に描画"""
        if not self._plan_elements:
            return
        cb_h = 20  # px
        cb_y = 2
        font = QFont(); font.setPointSize(8)
        painter.setFont(font)

        total_dist = sum(self._element_length(e) for e in self._plan_elements)
        if total_dist < 1e-9:
            return

        dist_cursor = 0.0
        for elem in self._plan_elements:
            L = self._element_length(elem)
            color = self._element_color(elem)
            x0 = self.w2s(dist_cursor, 0).x()
            x1 = self.w2s(dist_cursor + L, 0).x()
            painter.fillRect(int(x0), cb_y, max(int(x1-x0), 1), cb_h, color)
            # ラベル
            painter.setPen(QPen(QColor(255,255,255)))
            eid = getattr(elem, 'id', None)
            name = self.scene.nicknames.get(eid, "")
            kind = ("線分" if isinstance(elem, Segment) else
                    "クロ" if isinstance(elem, Clothoid) else "円弧")
            label = f"{kind}" + (f"[{name}]" if name else "") + f" {L:.0f}m"
            painter.drawText(int(x0)+2, cb_y, max(int(x1-x0)-4, 1), cb_h,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             label)
            # 境界線
            painter.setPen(QPen(QColor(80,80,80), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(x1), cb_y, int(x1), self.height())
            dist_cursor += L

    def _element_length(self, elem) -> float:
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
        if isinstance(elem, Segment):  return CB_SEGMENT
        if isinstance(elem, Arc):      return CB_ARC
        if isinstance(elem, Clothoid): return CB_CLOTHOID
        return QColor(128,128,128)

    def _draw_grade_lines(self, painter: QPainter):
        pen = QPen(QColor(100, 160, 240), 2)
        painter.setPen(pen)
        for gl in self._grade_lines:
            p1 = self.w2s(gl.dist_start, gl.elev_start)
            p2 = self.w2s(gl.dist_end,   gl.elev_end)
            painter.drawLine(p1, p2)
            # 端点
            painter.setBrush(QBrush(QColor(100,160,240)))
            for pt in [p1, p2]:
                painter.drawEllipse(pt, 4, 4)

    def _draw_vertical_curves(self, painter: QPainter):
        pen = QPen(QColor(240, 180, 60), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for vc in self._vertical_curves:
            path = QPainterPath()
            n = 64
            first = True
            for i in range(n+1):
                d = vc.vpc_dist + vc.length * i / n
                e = vc.elevation_at(d)
                p = self.w2s(d, e)
                if first:
                    path.moveTo(p); first = False
                else:
                    path.lineTo(p)
            painter.drawPath(path)
            # VPC/VPT
            painter.setBrush(QBrush(QColor(240,180,60)))
            for pt in [self.w2s(vc.vpc_dist, vc.vpc_elev),
                       self.w2s(vc.vpt_dist, vc.vpt_elev)]:
                painter.drawEllipse(pt, 5, 5)

    def _draw_axes(self, painter: QPainter):
        pen = QPen(QColor(100,100,100), 1)
        painter.setPen(pen)
        font = QFont(); font.setPointSize(8)
        painter.setFont(font)
        w, h = self.width(), self.height()
        # X 軸ラベル
        dist0, _ = self.s2w(0, 0)
        dist1, _ = self.s2w(w, 0)
        raw_x = (dist1 - dist0) / 6
        if raw_x > 0:
            mag = 10 ** math.floor(math.log10(raw_x))
            steps = [1,2,5,10]
            gx = mag * min((s for s in steps if s*mag >= raw_x*0.8), default=10)
            d = math.ceil(dist0/gx)*gx
            while d <= dist1:
                sp = self.w2s(d, 0)
                painter.drawText(int(sp.x())-20, h-16, 40, 16,
                                 Qt.AlignmentFlag.AlignCenter, f"{d:.0f}")
                d += gx

    def wheelEvent(self, event):
        delta = event.angleDelta()
        mods  = event.modifiers()
        pos   = event.position()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            factor = 1.15 if delta.y() > 0 else 1/1.15
            self._scale_y *= factor
        else:
            factor = 1.15 if delta.y() > 0 else 1/1.15
            cx = pos.x()
            self._offset = Vec2(cx + (self._offset.x - cx) * factor,
                                self._offset.y)
            self._scale_x *= factor
        self.update()

    def mousePressEvent(self, event):
        pos = event.position()
        sx, sy = pos.x(), pos.y()
        btn = event.button()
        if btn == Qt.MouseButton.MiddleButton or \
           (btn == Qt.MouseButton.LeftButton and self._mode == "select"):
            self._pan_start = Vec2(sx, sy)
            self._pan_offset_start = Vec2(self._offset.x, self._offset.y)
        elif btn == Qt.MouseButton.LeftButton and self._mode == "grade":
            dist, elev = self.s2w(sx, sy)
            if self._grade_first is None:
                self._grade_first = (dist, elev)
            else:
                d0, e0 = self._grade_first
                gl = GradeLine(dist_start=d0, elev_start=e0,
                               dist_end=dist, elev_end=elev)
                self.scene.grade_lines.append(gl)
                self._grade_first = (dist, elev)
                self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        sx, sy = pos.x(), pos.y()
        if self._pan_start and event.buttons() & (Qt.MouseButton.MiddleButton |
                                                    Qt.MouseButton.LeftButton):
            dx = sx - self._pan_start.x
            dy = sy - self._pan_start.y
            self._offset = Vec2(self._pan_offset_start.x + dx,
                                self._pan_offset_start.y + dy)
            self.update()

    def mouseReleaseEvent(self, event):
        self._pan_start = None

    def fit_all(self):
        if not self._grade_lines and not self._vertical_curves:
            return
        ds, es = [], []
        for gl in self._grade_lines:
            ds += [gl.dist_start, gl.dist_end]
            es += [gl.elev_start, gl.elev_end]
        for vc in self._vertical_curves:
            ds += [vc.vpc_dist, vc.vpt_dist]
            es += [vc.vpc_elev, vc.vpt_elev]
        if not ds: return
        dmin,dmax = min(ds),max(ds)
        emin,emax = min(es),max(es)
        md = max(dmax-dmin, 1); me = max(emax-emin, 1)
        mg = 0.1
        self._scale_x = self.width()  / (md*(1+2*mg))
        self._scale_y = self.height() / (me*(1+2*mg))
        self._offset  = Vec2(self.width()/2  - (dmin+dmax)/2*self._scale_x,
                             self.height()/2 + (emin+emax)/2*self._scale_y)
        self.update()


class VerticalAlignmentWindow(QMainWindow):
    """縦断線形設計ウィンドウ"""

    def __init__(self, scene: Scene, plan_elements: list, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.setWindowTitle("縦断線形設計")
        self.resize(1000, 600)

        # ─── 中央ウィジェット ─────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self._canvas = ProfileCanvas(scene, self)
        self._canvas.set_plan_elements(plan_elements)
        splitter.addWidget(self._canvas)

        # 右パネル
        right = QWidget()
        right.setMinimumWidth(240)
        right.setMaximumWidth(320)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 4, 4, 4)

        # モードボタン
        mode_grp = QGroupBox("モード")
        mode_lay = QHBoxLayout(mode_grp)
        btn_sel   = QPushButton("[S] 選択")
        btn_grade = QPushButton("[G] 勾配直線")
        btn_sel.setCheckable(True);   btn_sel.setChecked(True)
        btn_grade.setCheckable(True)
        btn_sel.clicked.connect(lambda: (self._canvas.set_mode("select"),
                                          btn_grade.setChecked(False),
                                          btn_sel.setChecked(True)))
        btn_grade.clicked.connect(lambda: (self._canvas.set_mode("grade"),
                                            btn_sel.setChecked(False),
                                            btn_grade.setChecked(True)))
        mode_lay.addWidget(btn_sel)
        mode_lay.addWidget(btn_grade)
        right_lay.addWidget(mode_grp)

        # 全体表示
        btn_fit = QPushButton("全体表示 (Ctrl+0)")
        btn_fit.clicked.connect(self._canvas.fit_all)
        right_lay.addWidget(btn_fit)

        # 勾配直線一覧
        self._grade_list_grp = QGroupBox("勾配直線一覧")
        self._grade_list_lay = QVBoxLayout(self._grade_list_grp)
        right_lay.addWidget(self._grade_list_grp)

        right_lay.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([700, 300])

        self._refresh_grade_list()

    def _refresh_grade_list(self):
        while self._grade_list_lay.count():
            item = self._grade_list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for gl in self.scene.grade_lines:
            lbl = QLabel(
                f"距離 {gl.dist_start:.1f}→{gl.dist_end:.1f}m  "
                f"標高 {gl.elev_start:.1f}→{gl.elev_end:.1f}m  "
                f"勾配 {gl.gradient:.2f}%"
            )
            self._grade_list_lay.addWidget(lbl)
            # 縦断曲線挿入ボタン
            row = QHBoxLayout()
            sb_len = _make_spinbox(50.0, 1.0, 10000.0, 10.0, 1)
            sb_len.setPrefix("L=")
            sb_len.setSuffix("m")
            btn_ins = QPushButton("縦断曲線挿入")
            def make_insert(g=gl, sb=sb_len):
                def do_insert():
                    self._insert_vertical_curve(g, sb.value())
                return do_insert
            btn_ins.clicked.connect(make_insert())
            row.addWidget(sb_len)
            row.addWidget(btn_ins)
            self._grade_list_lay.addLayout(row)

    def _insert_vertical_curve(self, gl: GradeLine, length: float):
        """勾配直線 gl の後に縦断曲線を挿入"""
        idx = self.scene.grade_lines.index(gl)
        if idx + 1 >= len(self.scene.grade_lines):
            return
        gl2 = self.scene.grade_lines[idx + 1]
        # PVI は gl の終点 (= gl2 の始点)
        pvi_d = gl.dist_end
        pvi_e = gl.elev_end
        vc = VerticalCurve(
            pvi_dist=pvi_d, pvi_elev=pvi_e,
            g1=gl.gradient, g2=gl2.gradient,
            length=length
        )
        # 勾配直線を VPC/VPT まで短縮
        gl.dist_end  = vc.vpc_dist
        gl.elev_end  = vc.vpc_elev
        gl2.dist_start = vc.vpt_dist
        gl2.elev_start = vc.vpt_elev
        self.scene.vertical_curves.append(vc)
        self._canvas.update()
        self._refresh_grade_list()
