"""
道路設計アプリ データモデル

━━━ 座標系の定義 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【ワールド座標 (World Coordinates)】
  仕様書が定義する数学座標系。本アプリのすべてのモデルデータはここで定義する。
  ・x 軸: 右向き正 (3時方向)
  ・y 軸: 上向き正 (12時方向)
  ・角度: 反時計回りを正、x軸=0°
  ・Vec2、Line、Circle、Arc、Clothoid の座標・角度はすべてワールド座標

【スクリーン座標 (Screen Coordinates)】
  Qt ウィジェット上のピクセル座標。描画時に Canvas.w2s() で変換する。
  ・x 軸: 右向き正 (ワールドと同じ)
  ・y 軸: 下向き正 (ワールドと逆) ← 注意
  ・変換: screen_x = world_x * scale + offset_x
           screen_y = -world_y * scale + offset_y

【Qt drawArc の角度】
  QPainter.drawArc(rect, startAngle, spanAngle) の角度は
  「スクリーン座標」ではなく「数学座標（y上向き）」で解釈される。
  → ワールド座標の角度をそのまま渡せばよい（y反転不要）
  ・startAngle_16 = int(round(angle_start_deg * 16))
  ・spanAngle_16  = int(round(arc_angle_deg   * 16))  ← 正=反時計

━━━ Arc の定義 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  arc.angle_start から反時計回り (CCW) に arc.angle_end まで至る弧。
  arc_angle() = (angle_end - angle_start) % (2π)  ← 常に正
  仕様書:
    左カーブのクロソイドと接続 → arc.angle_start = circle_pt の角度
    右カーブのクロソイドと接続 → arc.angle_end   = circle_pt の角度
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import math
import itertools
from dataclasses import dataclass, field
from typing import Optional

# ─── ユニーク ID ─────────────────────────────────────────────
_id_counter = itertools.count(1)

def new_id() -> int:
    return next(_id_counter)

def _reset_id_counter_after(max_id: int):
    """ファイル読み込み後、既存IDより大きい値からカウンタを再開する"""
    global _id_counter
    _id_counter = itertools.count(max_id + 1)

# ─── 基本型 ──────────────────────────────────────────────────
@dataclass
class Vec2:
    x: float
    y: float

    def __add__(self, o):  return Vec2(self.x + o.x, self.y + o.y)
    def __sub__(self, o):  return Vec2(self.x - o.x, self.y - o.y)
    def __mul__(self, s):  return Vec2(self.x * s, self.y * s)
    def __rmul__(self, s): return self.__mul__(s)
    def __neg__(self):     return Vec2(-self.x, -self.y)
    def dot(self, o):      return self.x * o.x + self.y * o.y
    def cross(self, o):    return self.x * o.y - self.y * o.x
    def length(self):      return math.hypot(self.x, self.y)
    def normalized(self):
        l = self.length()
        return Vec2(self.x / l, self.y / l) if l > 1e-12 else Vec2(1, 0)
    def perp(self):        return Vec2(-self.y, self.x)
    def tuple(self):       return (self.x, self.y)

    def __iter__(self):
        return iter((self.x, self.y))

    def to_dict(self):
        return {"x": self.x, "y": self.y}

    @staticmethod
    def from_dict(d):
        return Vec2(d["x"], d["y"])


# ─── 直線 ────────────────────────────────────────────────────
class Line:
    """参照始点・参照終点で定義される有向直線"""

    def __init__(self, ref_start: Vec2, ref_end: Vec2, line_id: int = None):
        self.id = line_id if line_id is not None else new_id()
        self.ref_start = ref_start  # 参照始点
        self.ref_end   = ref_end    # 参照終点
        self.segments: list[Segment] = []
        # 折れ線/スムーズ接続情報
        self.connection: Optional[LineConnection] = None

    @property
    def direction(self) -> Vec2:
        return (self.ref_end - self.ref_start).normalized()

    @property
    def angle(self) -> float:
        d = self.ref_end - self.ref_start
        return math.atan2(d.y, d.x)

    def project_point(self, p: Vec2) -> Vec2:
        """点 p を直線に正射影した点を返す"""
        d = self.direction
        t = (p - self.ref_start).dot(d)
        return self.ref_start + d * t

    def project_t(self, p: Vec2) -> float:
        """点 p の直線上のパラメータ t を返す（ref_start=0, ref_end=1）"""
        d = self.ref_end - self.ref_start
        l2 = d.dot(d)
        if l2 < 1e-24:
            return 0.0
        return (p - self.ref_start).dot(d) / l2

    def point_at(self, t: float) -> Vec2:
        """パラメータ t の点を返す"""
        return self.ref_start + (self.ref_end - self.ref_start) * t

    def distance_to(self, p: Vec2) -> float:
        d = self.direction
        return abs((p - self.ref_start).cross(d))

    def signed_dist(self, p: Vec2) -> float:
        """直線の左側が正の符号付き距離 (Clothoid.py の signed_dist 相当)"""
        d = self.direction
        pm = p - self.ref_start
        return d.cross(pm)   # direction × (p - ref_start): 左側が正

    def project(self, p: Vec2) -> Vec2:
        """project_point の別名 (Clothoid.py との互換用)"""
        return self.project_point(p)

    @property
    def left_normal(self) -> Vec2:
        """直線の左法線 (CCW90)"""
        d = self.direction
        return Vec2(-d.y, d.x)

    def intersect(self, other: 'Line') -> Optional[Vec2]:
        """2直線の交点（存在すれば）"""
        d1 = self.ref_end - self.ref_start
        d2 = other.ref_end - other.ref_start
        denom = d1.cross(d2)
        if abs(denom) < 1e-12:
            return None
        diff = other.ref_start - self.ref_start
        t = diff.cross(d2) / denom
        return self.ref_start + d1 * t

    def to_dict(self):
        return {
            "id": self.id,
            "ref_start": self.ref_start.to_dict(),
            "ref_end":   self.ref_end.to_dict(),
            "segments":  [s.to_dict() for s in self.segments],
        }

    @staticmethod
    def from_dict(d):
        ln = Line(Vec2.from_dict(d["ref_start"]), Vec2.from_dict(d["ref_end"]), d["id"])
        ln.segments = [Segment.from_dict(s, ln) for s in d.get("segments", [])]
        return ln


# ─── 線分 ────────────────────────────────────────────────────
class Segment:
    """直線の部分区間"""

    def __init__(self, line: Line, t_start: float = 0.0, t_end: float = 1.0, seg_id: int = None):
        self.id     = seg_id if seg_id is not None else new_id()
        self.line   = line
        self.t_start = t_start
        self.t_end   = t_end
        # snap 接続
        self.snap_prev: Optional[Segment] = None  # 自分の始点 = 相手の終点
        self.snap_next: Optional[Segment] = None  # 自分の終点 = 相手の始点

    @property
    def start(self) -> Vec2:
        return self.line.point_at(self.t_start)

    @property
    def end(self) -> Vec2:
        return self.line.point_at(self.t_end)

    def length(self) -> float:
        return (self.end - self.start).length()

    def to_dict(self):
        return {"id": self.id, "t_start": self.t_start, "t_end": self.t_end}

    @staticmethod
    def from_dict(d, line: Line):
        return Segment(line, d["t_start"], d["t_end"], d["id"])


# ─── 直線接続 ────────────────────────────────────────────────
@dataclass
class LineConnection:
    """2直線間の折れ線/スムーズ接続"""
    kind: str           # "polyline" | "smooth"
    line_a: 'Line'
    line_b: 'Line'
    shared_point: Vec2  # 共有参照点
    # どちらの参照点が共有点か: True = ref_end, False = ref_start
    a_end_is_shared: bool = True   # line_a.ref_end が共有点
    b_start_is_shared: bool = True # line_b.ref_start が共有点
    # smooth 専用
    circle: Optional['Circle'] = None
    bisector_dir: Optional[Vec2] = None  # 二等分線方向
    line_j_reversed: bool = False
    line_k_reversed: bool = False


# ─── 円 ──────────────────────────────────────────────────────
class Circle:
    def __init__(self, center: Vec2, radius: float, circle_id: int = None):
        self.id     = circle_id if circle_id is not None else new_id()
        self.center = center
        self.radius = radius
        self.arcs:  list[Arc] = []
        # smooth 接続での制約
        self.bisector_origin: Optional[Vec2] = None
        self.bisector_dir:    Optional[Vec2] = None

    def to_dict(self):
        return {
            "id": self.id,
            "center": self.center.to_dict(),
            "radius": self.radius,
            "arcs": [a.to_dict() for a in self.arcs],
        }

    @staticmethod
    def from_dict(d):
        c = Circle(Vec2.from_dict(d["center"]), d["radius"], d["id"])
        c.arcs = [Arc.from_dict(a, c) for a in d.get("arcs", [])]
        return c


# ─── 円弧 ────────────────────────────────────────────────────
class Arc:
    """円の部分区間（反時計回り）"""

    def __init__(self, circle: Circle, angle_start: float, angle_end: float, arc_id: int = None):
        self.id          = arc_id if arc_id is not None else new_id()
        self.circle      = circle
        self.angle_start = angle_start  # ラジアン
        self.angle_end   = angle_end

    @property
    def start(self) -> Vec2:
        c = self.circle
        return Vec2(c.center.x + c.radius * math.cos(self.angle_start),
                    c.center.y + c.radius * math.sin(self.angle_start))

    @property
    def end(self) -> Vec2:
        c = self.circle
        return Vec2(c.center.x + c.radius * math.cos(self.angle_end),
                    c.center.y + c.radius * math.sin(self.angle_end))

    def arc_angle(self) -> float:
        """弧長角（反時計回りの角度差）"""
        a = (self.angle_end - self.angle_start) % (2 * math.pi)
        return a

    def arc_length(self) -> float:
        return self.circle.radius * self.arc_angle()

    def to_dict(self):
        return {"id": self.id, "angle_start": self.angle_start, "angle_end": self.angle_end}

    @staticmethod
    def from_dict(d, circle: Circle):
        return Arc(circle, d["angle_start"], d["angle_end"], d["id"])


# ─── クロソイド計算 (Clothoid.py のロジックを使用) ───────────────
_FRESNEL_N = 500


def _fresnel_xy_tau(tau_end: float, R: float, n: int = _FRESNEL_N
                    ) -> tuple[float, float]:
    """
    クロソイド終点の局所座標変位 (xe, ye) を返す。
    L = 2R*τ,  A² = RL,  x = ∫cos(s²/2A²)ds,  y = ∫sin(s²/2A²)ds
    (Clothoid.py の _fresnel_xy と同等)
    """
    if tau_end < 1e-9:
        return 0.0, 0.0
    L = 2.0 * R * tau_end
    A2 = R * L
    x, y = 0.0, 0.0
    ds = L / n
    for i in range(n):
        s = (i + 0.5) * ds
        theta = s * s / (2.0 * A2)
        x += math.cos(theta) * ds
        y += math.sin(theta) * ds
    return x, y


def _find_tau(R: float, d_abs: float,
              max_tau: float = 2.0 * math.pi * 0.999) -> Optional[float]:
    """
    Fresnel 条件  y(τ) = d_abs - R·cos(τ)  を満たす τ∈(0, max_tau) を返す。
    d_abs > R が存在条件。(Clothoid.py の _find_tau と同等)
    """
    if d_abs <= R:
        return None

    def residual(tau: float) -> float:
        _, y = _fresnel_xy_tau(tau, R)
        return y - (d_abs - R * math.cos(tau))

    f_lo = residual(1e-4)
    f_hi = residual(max_tau)
    if f_lo * f_hi > 0:
        return None

    lo, hi = 1e-4, max_tau
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if residual(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


class Clothoid:
    """直線と円から定義されるクロソイド曲線"""

    def __init__(self, line: Line, circle: Circle,
                 reversed_flag: bool = False,
                 snap_segment: bool = True,
                 snap_arc: bool = True,
                 clothoid_id: int = None):
        self.id            = clothoid_id if clothoid_id is not None else new_id()
        self.line          = line
        self.circle        = circle
        self.reversed_flag = reversed_flag
        self.snap_segment  = snap_segment
        self.snap_arc      = snap_arc
        # キャッシュ
        self._valid:      bool           = False
        self._tau:        float          = 0.0
        self._line_pt:    Optional[Vec2] = None
        self._circle_pt:  Optional[Vec2] = None
        self._points:     list[Vec2]     = []
        # snap=off 時の分割管理（分割で生成した Segment/Arc の id リスト）
        self._split_seg_ids: list[int] = []
        self._split_arc_ids: list[int] = []

        self.compute()

    # ── 実効直線 ──────────────────────────────────────────────
    def _effective_line(self) -> Line:
        """reversed_flag を考慮した実効直線（ref_start/end を入れ替えた仮想 Line）"""
        ln = self.line
        if not self.reversed_flag:
            return ln
        rev = Line.__new__(Line)
        rev.id         = ln.id
        rev.ref_start  = ln.ref_end
        rev.ref_end    = ln.ref_start
        rev.segments   = ln.segments
        rev.connection = ln.connection
        return rev

    # ── カーブ方向 ────────────────────────────────────────────
    @property
    def effective_direction(self) -> Vec2:
        ln = self._effective_line()
        return (ln.ref_end - ln.ref_start).normalized()

    @property
    def effective_ref_start(self) -> Vec2:
        return self._effective_line().ref_start

    @property
    def is_left_curve(self) -> bool:
        """実効直線方向から円の中心への cross > 0 → 左カーブ"""
        eln = self._effective_line()
        d   = (eln.ref_end - eln.ref_start).normalized()
        pm  = self.circle.center - eln.ref_start
        return d.cross(pm) > 0

    # ── 計算本体 ──────────────────────────────────────────────
    def compute(self):
        """Clothoid.py の clothoid_data / clothoid_points ロジックで計算する"""
        self._valid     = False
        self._points    = []
        self._line_pt   = None
        self._circle_pt = None

        eln    = self._effective_line()
        circle = self.circle
        R      = circle.radius
        if R < 1e-9:
            return

        # signed_dist: eln の左側が正
        d_signed = eln.signed_dist(circle.center)
        d_abs    = abs(d_signed)

        tau = _find_tau(R, d_abs)
        if tau is None:
            return

        self._tau   = tau
        self._valid = True

        # --- clothoid_data 相当: 接点を計算 ---
        xe, _ye = _fresnel_xy_tau(tau, R)

        proj_center = eln.project_point(circle.center)   # Vec2
        direction   = eln.direction                        # Vec2
        left        = Vec2(-direction.y, direction.x)     # 左法線
        sign        = 1.0 if d_signed > 0 else -1.0

        # 円側接点 (clothoid_data の cc に相当)
        cc = Vec2(
            proj_center.x + direction.x * R * math.sin(tau)
                          + left.x * sign * (d_abs - R * math.cos(tau)),
            proj_center.y + direction.y * R * math.sin(tau)
                          + left.y * sign * (d_abs - R * math.cos(tau)),
        )
        # 線側接点 (clothoid_data の lc に相当)
        lc = Vec2(
            proj_center.x + direction.x * (R * math.sin(tau) - xe),
            proj_center.y + direction.y * (R * math.sin(tau) - xe),
        )

        self._line_pt   = lc
        self._circle_pt = cc

        # --- clothoid_points 相当: 点列を生成 ---
        L   = 2.0 * R * tau
        A2  = R * L
        left_n = left  # Vec2

        n_steps = max(80, int(tau / (2.0 * math.pi) * 512) + 40)
        n_int   = max(n_steps * 8, 800)
        ds_int  = L / n_int

        # 出力する弧長位置（等接線角度変化）
        output_s = []
        for i in range(1, n_steps + 1):
            theta_i = i * tau / n_steps
            s_i = math.sqrt(2.0 * A2 * theta_i)
            output_s.append(s_i)

        pts: list[Vec2] = [Vec2(lc.x, lc.y)]
        x_acc, y_acc = 0.0, 0.0
        out_idx = 0

        for i in range(n_int):
            s_mid = (i + 0.5) * ds_int
            theta = s_mid * s_mid / (2.0 * A2)
            x_acc += math.cos(theta) * ds_int
            y_acc += math.sin(theta) * ds_int
            s_cur = (i + 1) * ds_int

            while out_idx < len(output_s) and s_cur >= output_s[out_idx] - 1e-9:
                wx = lc.x + direction.x * x_acc + left_n.x * sign * y_acc
                wy = lc.y + direction.y * x_acc + left_n.y * sign * y_acc
                pts.append(Vec2(wx, wy))
                out_idx += 1

        self._points = pts
        self._update_snaps()

    # ── snap 更新 ─────────────────────────────────────────────
    def _update_snaps(self):
        if not self._valid:
            return
        # 線分: snap on → 端点移動、snap off → 線分分割
        if self.snap_segment:
            if self._line_pt is not None:
                self._apply_segment_snap()
        else:
            if self._line_pt is not None:
                self._apply_segment_split()
        # 円弧: snap on → 端点移動、snap off → 円弧分割
        if self.snap_arc:
            if self._circle_pt is not None:
                self._apply_arc_snap()
        else:
            if self._circle_pt is not None:
                self._apply_arc_split()

    # ── snap=on: 線分端点をスナップ ──────────────────────────
    def _apply_segment_snap(self):
        """線側接点に最も近い線分端点をスナップ（snap_segment=True 専用）"""
        if not self.line.segments:
            return
        self._clear_segment_split()   # snap=off で作った分割があれば解除
        contact  = self._line_pt
        best_seg = min(self.line.segments,
                       key=lambda s: min((s.start - contact).length(),
                                         (s.end   - contact).length()))
        t = self.line.project_t(contact)
        if not self.reversed_flag:
            best_seg.t_end = t
            if best_seg.t_start >= best_seg.t_end - 1e-9:
                best_seg.t_start = best_seg.t_end - 0.1
        else:
            best_seg.t_start = t
            if best_seg.t_end <= best_seg.t_start + 1e-9:
                best_seg.t_end = best_seg.t_start + 0.1

    # ── snap=off: 線分を接点で分割 ───────────────────────────
    def _apply_segment_split(self):
        """
        snap_segment=False 時、線側接点 X で最も近い線分 AB を
        AX と XB に分割する。既に分割済みなら端点を追従更新する。
        """
        if not self.line.segments:
            return
        contact = self._line_pt
        t_x = self.line.project_t(contact)

        # 既存の分割線分があれば追従更新（再分割しない）
        if self._split_seg_ids:
            segs_by_id = {s.id: s for s in self.line.segments}
            seg_ax = segs_by_id.get(self._split_seg_ids[0])
            seg_xb = segs_by_id.get(self._split_seg_ids[1]) if len(self._split_seg_ids) > 1 else None
            if seg_ax and seg_xb:
                seg_ax.t_end   = t_x
                seg_xb.t_start = t_x
                return
            # 分割線分が消えていたらリセット
            self._split_seg_ids = []

        # 分割元となる線分を選ぶ（自分が作った分割線分は除外）
        candidates = [s for s in self.line.segments if s.id not in self._split_seg_ids]
        if not candidates:
            return
        best_seg = min(candidates, key=lambda s: self._dist_to_seg(contact, s))

        # t_x が線分の範囲外なら分割しない
        if t_x <= best_seg.t_start + 1e-6 or t_x >= best_seg.t_end - 1e-6:
            return

        # 元の線分を AX に縮め、XB を新規追加
        t_orig_end    = best_seg.t_end
        best_seg.t_end = t_x                               # AX (元の線分を縮める)
        seg_xb = Segment(self.line, t_x, t_orig_end)       # XB (新規)
        self.line.segments.append(seg_xb)
        self.line.segments.sort(key=lambda s: s.t_start)
        self._split_seg_ids = [best_seg.id, seg_xb.id]

    def _clear_segment_split(self):
        """snap=off で作った分割線分を解除（AX+XB を元の AB に戻す）"""
        if not self._split_seg_ids:
            return
        segs_by_id = {s.id: s for s in self.line.segments}
        seg_ax = segs_by_id.get(self._split_seg_ids[0])
        seg_xb = segs_by_id.get(self._split_seg_ids[1]) if len(self._split_seg_ids) > 1 else None
        if seg_ax and seg_xb and seg_xb in self.line.segments:
            seg_ax.t_end = seg_xb.t_end   # AX の終端を XB の終端に戻す
            self.line.segments.remove(seg_xb)
        self._split_seg_ids = []

    @staticmethod
    def _dist_to_seg(pt: 'Vec2', seg: 'Segment') -> float:
        s, e = seg.start, seg.end
        d = e - s
        l2 = d.dot(d)
        if l2 < 1e-12:
            return (pt - s).length()
        t = max(0.0, min(1.0, (pt - s).dot(d) / l2))
        return (pt - (s + d * t)).length()

    # ── snap=on: 円弧端点をスナップ ──────────────────────────
    def _apply_arc_snap(self):
        """
        円側接点に円弧端点をスナップ（snap_arc=True 専用）。

        仕様書（数学座標系: y上向き, 反時計=正）:
          左カーブ → 円弧の始点 (angle_start) = circle_pt
          右カーブ → 円弧の終点 (angle_end)   = circle_pt
        """
        self._clear_arc_split()       # snap=off で作った分割があれば解除
        circle        = self.circle
        contact       = self._circle_pt
        angle_contact = math.atan2(contact.y - circle.center.y,
                                    contact.x - circle.center.x)
        if circle.arcs:
            def arc_dist(arc):
                a = arc.angle_start if self.is_left_curve else arc.angle_end
                return abs((a - angle_contact + math.pi) % (2 * math.pi) - math.pi)
            arc = min(circle.arcs, key=arc_dist)
        else:
            if self.is_left_curve:
                arc = Arc(circle, angle_contact, angle_contact + math.pi / 4)
            else:
                arc = Arc(circle, angle_contact - math.pi / 4, angle_contact)
            circle.arcs.append(arc)

        if self.is_left_curve:
            arc.angle_start = angle_contact
        else:
            arc.angle_end = angle_contact

    # ── snap=off: 円弧を接点で分割 ───────────────────────────
    def _apply_arc_split(self):
        """
        snap_arc=False 時、円側接点 X で最も近い円弧を
        (start→X) と (X→end) に分割する。既に分割済みなら端点を追従更新する。
        左カーブ: circle_pt = 始点側 → angle_start = X
        右カーブ: circle_pt = 終点側 → angle_end   = X
        """
        if not self.circle.arcs:
            return
        contact = self._circle_pt
        angle_x = math.atan2(contact.y - self.circle.center.y,
                              contact.x - self.circle.center.x)

        # 既存の分割円弧があれば追従更新
        if self._split_arc_ids:
            arcs_by_id = {a.id: a for a in self.circle.arcs}
            arc_ax = arcs_by_id.get(self._split_arc_ids[0])
            arc_xb = arcs_by_id.get(self._split_arc_ids[1]) if len(self._split_arc_ids) > 1 else None
            if arc_ax and arc_xb:
                # arc_ax: start→X, arc_xb: X→end
                arc_ax.angle_end   = angle_x
                arc_xb.angle_start = angle_x
                return
            self._split_arc_ids = []

        # 分割元となる円弧を選ぶ（接点が範囲内にあるもの）
        best_arc = None
        for a in self.circle.arcs:
            if a.id in self._split_arc_ids:
                continue
            span = a.arc_angle()
            rel  = (angle_x - a.angle_start) % (2 * math.pi)
            if 1e-4 < rel < span - 1e-4:   # 端点でなく内部に接点がある
                best_arc = a
                break
        if best_arc is None:
            return

        # 元の円弧を (start→X) に縮め、(X→end) を新規追加
        orig_end          = best_arc.angle_end
        best_arc.angle_end = angle_x                          # start→X
        arc_xb = Arc(self.circle, angle_x, orig_end)          # X→end
        self.circle.arcs.append(arc_xb)
        self._split_arc_ids = [best_arc.id, arc_xb.id]

    def _clear_arc_split(self):
        """snap=off で作った分割円弧を解除（元の円弧に戻す）"""
        if not self._split_arc_ids:
            return
        arcs_by_id = {a.id: a for a in self.circle.arcs}
        arc_ax = arcs_by_id.get(self._split_arc_ids[0])
        arc_xb = arcs_by_id.get(self._split_arc_ids[1]) if len(self._split_arc_ids) > 1 else None
        if arc_ax and arc_xb and arc_xb in self.circle.arcs:
            arc_ax.angle_end = arc_xb.angle_end
            self.circle.arcs.remove(arc_xb)
        self._split_arc_ids = []

    # ── プロパティ ─────────────────────────────────────────────
    @property
    def _A(self) -> float:
        """クロソイドパラメータ A = sqrt(R * L) = R * sqrt(2 * tau)"""
        if not self._valid:
            return 0.0
        R = self.circle.radius
        return R * math.sqrt(2.0 * self._tau)

    @property
    def line_contact(self) -> Optional[Vec2]:
        return self._line_pt

    @property
    def circle_contact(self) -> Optional[Vec2]:
        return self._circle_pt

    @property
    def points(self) -> list[Vec2]:
        return self._points

    @property
    def is_valid(self) -> bool:
        return self._valid

    def to_dict(self):
        return {
            "id":           self.id,
            "line_id":      self.line.id,
            "circle_id":    self.circle.id,
            "reversed_flag": self.reversed_flag,
            "snap_segment": self.snap_segment,
            "snap_arc":     self.snap_arc,
        }


# ─── 線分・円弧の端点接続 snap ──────────────────────────────
@dataclass
class SegmentSnap:
    """2本の線分の端点を接続する snap 情報"""
    seg_a_id: int
    end_a:    str   # 'start' or 'end'
    seg_b_id: int
    end_b:    str

    def to_dict(self):
        return {"seg_a_id": self.seg_a_id, "end_a": self.end_a,
                "seg_b_id": self.seg_b_id, "end_b": self.end_b}

    @staticmethod
    def from_dict(d) -> 'SegmentSnap':
        return SegmentSnap(d["seg_a_id"], d["end_a"],
                           d["seg_b_id"], d["end_b"])


@dataclass
class ArcSnap:
    """2本の円弧の端点を接続する snap 情報"""
    arc_a_id: int
    end_a:    str   # 'start' or 'end'
    arc_b_id: int
    end_b:    str

    def to_dict(self):
        return {"arc_a_id": self.arc_a_id, "end_a": self.end_a,
                "arc_b_id": self.arc_b_id, "end_b": self.end_b}

    @staticmethod
    def from_dict(d) -> 'ArcSnap':
        return ArcSnap(d["arc_a_id"], d["end_a"],
                       d["arc_b_id"], d["end_b"])


# ─── 縦断線形 ────────────────────────────────────────────────
@dataclass
class GradeLine:
    id: int = field(default_factory=new_id)
    dist_start: float = 0.0
    elev_start: float = 0.0
    dist_end:   float = 100.0
    elev_end:   float = 0.0
    next_curve: Optional['VerticalCurve'] = None
    prev_curve: Optional['VerticalCurve'] = None

    @property
    def gradient(self) -> float:
        dx = self.dist_end - self.dist_start
        if abs(dx) < 1e-9:
            return 0.0
        return (self.elev_end - self.elev_start) / dx * 100

    def to_dict(self):
        return {"id": self.id,
                "dist_start": self.dist_start, "elev_start": self.elev_start,
                "dist_end": self.dist_end, "elev_end": self.elev_end}

    @staticmethod
    def from_dict(d):
        g = GradeLine()
        g.id = d["id"]
        g.dist_start = d["dist_start"]; g.elev_start = d["elev_start"]
        g.dist_end   = d["dist_end"];   g.elev_end   = d["elev_end"]
        return g


@dataclass
class VerticalCurve:
    id: int = field(default_factory=new_id)
    pvi_dist: float = 0.0
    pvi_elev: float = 0.0
    g1: float = 0.0   # 前勾配 [%]
    g2: float = 0.0   # 後勾配 [%]
    length: float = 50.0
    prev_line_id: int = -1  # 前の勾配直線の id
    next_line_id: int = -1  # 次の勾配直線の id

    @property
    def vpc_dist(self): return self.pvi_dist - self.length / 2
    @property
    def vpt_dist(self): return self.pvi_dist + self.length / 2
    @property
    def vpc_elev(self): return self.pvi_elev - self.g1 / 100 * self.length / 2
    @property
    def vpt_elev(self): return self.pvi_elev + self.g2 / 100 * self.length / 2
    @property
    def K(self):
        dg = abs(self.g2 - self.g1)
        return self.length / dg if dg > 1e-9 else float('inf')

    def elevation_at(self, dist: float) -> float:
        x = dist - self.vpc_dist
        if x < 0 or x > self.length:
            return float('nan')
        return self.vpc_elev + self.g1 / 100 * x + (self.g2 - self.g1) / (2 * self.length) / 100 * x ** 2

    def to_dict(self):
        return {"id": self.id, "pvi_dist": self.pvi_dist, "pvi_elev": self.pvi_elev,
                "g1": self.g1, "g2": self.g2, "length": self.length,
                "prev_line_id": self.prev_line_id, "next_line_id": self.next_line_id}

    @staticmethod
    def from_dict(d):
        v = VerticalCurve()
        for k in d:
            setattr(v, k, d[k])
        return v


# ─── シーン（全データ保持） ───────────────────────────────────
class Scene:
    def __init__(self):
        self.lines:     list[Line]          = []
        self.circles:   list[Circle]        = []
        self.clothoids: list[Clothoid]      = []
        self.grade_lines:     list[GradeLine]    = []
        self.vertical_curves: list[VerticalCurve] = []
        self.segment_snaps: list[SegmentSnap] = []
        self.arc_snaps:     list[ArcSnap]     = []
        self.nicknames: dict[int, str] = {}   # id → nickname

    def get_nickname(self, obj_id: int, prefix: str = "") -> str:
        if obj_id in self.nicknames:
            return self.nicknames[obj_id]
        return f"nickname_{prefix}_{obj_id}"

    def set_nickname(self, obj_id: int, name: str):
        if name:
            self.nicknames[obj_id] = name
        elif obj_id in self.nicknames:
            del self.nicknames[obj_id]

    def add_line(self, line: Line) -> Line:
        self.lines.append(line)
        # デフォルトニックネーム
        if line.id not in self.nicknames:
            self.nicknames[line.id] = f"nickname_line_{line.id}"
        return line

    def add_circle(self, circle: Circle) -> Circle:
        self.circles.append(circle)
        if circle.id not in self.nicknames:
            self.nicknames[circle.id] = f"nickname_circle_{circle.id}"
        return circle

    def add_clothoid(self, clothoid: Clothoid) -> Clothoid:
        self.clothoids.append(clothoid)
        if clothoid.id not in self.nicknames:
            self.nicknames[clothoid.id] = f"nickname_clothoid_{clothoid.id}"
        return clothoid

    def remove_line(self, line: Line):
        # 関連クロソイドも削除
        related = [c for c in self.clothoids if c.line is line]
        for c in related:
            self.remove_clothoid(c)
        self.lines.remove(line)

    def remove_circle(self, circle: Circle):
        related = [c for c in self.clothoids if c.circle is circle]
        for c in related:
            self.remove_clothoid(c)
        self.circles.remove(circle)

    def remove_clothoid(self, clothoid: Clothoid):
        if clothoid in self.clothoids:
            self.clothoids.remove(clothoid)

    def clothoids_for(self, line: Line, circle: Circle) -> list[Clothoid]:
        return [c for c in self.clothoids if c.line is line and c.circle is circle]

    def connected_objects(self, obj) -> list:
        """obj に接続している図形一覧"""
        result = []
        if isinstance(obj, Line):
            for c in self.clothoids:
                if c.line is obj:
                    result.append(c)
            if obj.connection:
                conn = obj.connection
                other = conn.line_b if conn.line_a is obj else conn.line_a
                result.append(other)
        elif isinstance(obj, Circle):
            for c in self.clothoids:
                if c.circle is obj:
                    result.append(c)
        elif isinstance(obj, Clothoid):
            result.append(obj.line)
            result.append(obj.circle)
        return result

    def to_dict(self):
        def _with_nick(d: dict) -> dict:
            """dict の 'id' の次に 'nickname' を挿入して返す"""
            fid = d.get("id")
            nick = self.nicknames.get(fid)
            if nick is None:
                return d
            # id の直後に nickname を挿入（Python 3.7+ で dict 順序保証）
            result = {}
            for k, v in d.items():
                result[k] = v
                if k == "id":
                    result["nickname"] = nick
            return result

        def line_dict(ln: 'Line') -> dict:
            d = _with_nick(ln.to_dict())
            # 線分にもニックネームは不要（ID ベース）
            return d

        def circle_dict(ci: 'Circle') -> dict:
            d = _with_nick(ci.to_dict())
            return d

        return {
            "lines":           [line_dict(l) for l in self.lines],
            "circles":         [circle_dict(c) for c in self.circles],
            "clothoids":       [_with_nick(c.to_dict()) for c in self.clothoids],
            "grade_lines":     [g.to_dict() for g in self.grade_lines],
            "vertical_curves": [v.to_dict() for v in self.vertical_curves],
            "segment_snaps":   [s.to_dict() for s in self.segment_snaps],
            "arc_snaps":       [a.to_dict() for a in self.arc_snaps],
        }

    @staticmethod
    def from_dict(d) -> 'Scene':
        sc = Scene()
        lines_by_id   = {}
        circles_by_id = {}

        def _extract_nick(raw: dict, sc: 'Scene'):
            """raw dict から nickname を取り出して nicknames に登録する"""
            nick = raw.get("nickname")
            fid  = raw.get("id")
            if nick and fid is not None:
                sc.nicknames[fid] = nick

        for ld in d.get("lines", []):
            _extract_nick(ld, sc)
            ln = Line.from_dict(ld)
            sc.lines.append(ln)
            lines_by_id[ln.id] = ln
        for cd in d.get("circles", []):
            _extract_nick(cd, sc)
            ci = Circle.from_dict(cd)
            sc.circles.append(ci)
            circles_by_id[ci.id] = ci
        for cd in d.get("clothoids", []):
            _extract_nick(cd, sc)
            ln = lines_by_id.get(cd["line_id"])
            ci = circles_by_id.get(cd["circle_id"])
            if ln and ci:
                clo = Clothoid(ln, ci, cd.get("reversed_flag", False),
                               cd.get("snap_segment", False),
                               cd.get("snap_arc", False),
                               cd.get("id"))
                sc.clothoids.append(clo)
        sc.grade_lines     = [GradeLine.from_dict(g) for g in d.get("grade_lines", [])]
        sc.vertical_curves = [VerticalCurve.from_dict(v) for v in d.get("vertical_curves", [])]
        sc.segment_snaps   = [SegmentSnap.from_dict(s) for s in d.get("segment_snaps", [])]
        sc.arc_snaps       = [ArcSnap.from_dict(a)     for a in d.get("arc_snaps", [])]

        # 旧フォーマット互換: トップレベルの nicknames フィールド
        for k, v in d.get("nicknames", {}).items():
            sc.nicknames[int(k)] = v

        # 全IDを収集してカウンタを最大ID+1から再開（ID重複防止）
        all_ids = []
        for ln in sc.lines:
            all_ids.append(ln.id)
            all_ids.extend(s.id for s in ln.segments)
        for ci in sc.circles:
            all_ids.append(ci.id)
            all_ids.extend(a.id for a in ci.arcs)
        all_ids.extend(c.id for c in sc.clothoids)
        all_ids.extend(g.id for g in sc.grade_lines)
        all_ids.extend(v.id for v in sc.vertical_curves)
        if all_ids:
            _reset_id_counter_after(max(all_ids))

        return sc
