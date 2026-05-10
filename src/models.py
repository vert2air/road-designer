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
    """全図形種別を通じてユニークな整数 ID を発行する。

    アプリ起動時に 1 から開始し、呼び出しごとに単調増加する。
    ファイル読み込み後は `_reset_id_counter_after` によって既存 ID の最大値
    の次から再開されるため、新規生成と読み込み済みの ID が衝突しない。

    Returns
    -------
    int
        1 以上の整数。同一セッション内で重複しない。
    """
    return next(_id_counter)

def _reset_id_counter_after(max_id: int):
    """ファイル読み込み後に ID カウンタを既存 ID の次の値から再開する。

    `Scene.from_dict` の末尾で呼ばれ、読み込んだファイル内の全 ID の最大値
    を受け取る。これにより以後の `new_id()` 呼び出しが読み込み済み ID と
    衝突しなくなる。

    Parameters
    ----------
    max_id : int
        読み込んだファイル内の全 ID の最大値。0 を渡した場合は 1 から再開する。
    """
    global _id_counter
    _id_counter = itertools.count(max_id + 1)

# ─── 基本型 ──────────────────────────────────────────────────
@dataclass
class Vec2:
    """アプリ全体で使用する 2 次元ベクトル型。

    NumPy を使わず、道路幾何計算に必要な演算（内積・外積・正規化・90°回転）
    をこのクラスに集約する。`@dataclass` により `Vec2(x, y)` の簡潔な
    コンストラクタと `==` による等値比較を得る。

    `tuple()` と `__iter__` は QPainter への座標渡しや for ループでの
    アンパックのために提供する。

    Attributes
    ----------
    x : float
        x 成分（右向き正）。
    y : float
        y 成分（上向き正）。
    """
    x: float
    y: float

    def __add__(self, o):  return Vec2(self.x + o.x, self.y + o.y)
    def __sub__(self, o):  return Vec2(self.x - o.x, self.y - o.y)
    def __mul__(self, s):  return Vec2(self.x * s, self.y * s)
    def __rmul__(self, s): return self.__mul__(s)
    def __neg__(self):     return Vec2(-self.x, -self.y)
    def dot(self, o: 'Vec2') -> float:
        """内積 self·o を返す。

        Parameters
        ----------
        o : Vec2
            内積を取る相手ベクトル。

        Returns
        -------
        float
            self.x * o.x + self.y * o.y。直交ベクトル同士なら 0。

        Examples
        --------
        >>> Vec2(1, 0).dot(Vec2(0, 1))
        0.0
        >>> Vec2(1, 0).dot(Vec2(1, 0))
        1.0
        """
        return self.x * o.x + self.y * o.y

    def cross(self, o: 'Vec2') -> float:
        """2D 外積 self × o を返す。

        結果が正なら o は self の左側（CCW 方向）にある。
        `Line.signed_dist` や `Clothoid.is_left_curve` の判定に使う。

        Parameters
        ----------
        o : Vec2
            外積を取る相手ベクトル。

        Returns
        -------
        float
            self.x * o.y - self.y * o.x。正 = o が左側、負 = o が右側。

        Examples
        --------
        >>> Vec2(1, 0).cross(Vec2(0, 1))
        1.0
        >>> Vec2(1, 0).cross(Vec2(0, -1))
        -1.0
        """
        return self.x * o.y - self.y * o.x

    def length(self) -> float:
        """ベクトルの大きさ（ユークリッドノルム）を返す。

        Returns
        -------
        float
            math.hypot(self.x, self.y)。零ベクトルのとき 0.0。
        """
        return math.hypot(self.x, self.y)
    def normalized(self) -> 'Vec2':
        """単位ベクトルを返す。

        長さが 1e-12 未満のとき（実質的な零ベクトル）は Vec2(1, 0) を
        返す（除算ゼロ防止のフォールバック）。

        Returns
        -------
        Vec2
            大きさ 1 の同方向ベクトル。零ベクトルの場合は Vec2(1, 0)。
        """
        l = self.length()
        return Vec2(self.x / l, self.y / l) if l > 1e-12 else Vec2(1, 0)
    def perp(self) -> 'Vec2':
        """CCW に 90° 回転したベクトルを返す（左法線）。

        `direction.perp()` で `left_normal` を得るときに使う。
        `(dx, dy)` → `(-dy, dx)` の変換。

        Returns
        -------
        Vec2
            self を反時計回りに 90° 回転したベクトル。

        Examples
        --------
        >>> Vec2(1, 0).perp()
        Vec2(x=0.0, y=1.0)
        """
        return Vec2(-self.y, self.x)
    def tuple(self) -> tuple:
        """(x, y) タプルを返す。QPainter へ座標を渡す際に使う。"""
        return (self.x, self.y)

    def __iter__(self):
        return iter((self.x, self.y))

    def to_dict(self) -> dict:
        """{"x": float, "y": float} 形式の辞書に変換する。"""
        return {"x": self.x, "y": self.y}

    @staticmethod
    def from_dict(d: dict) -> 'Vec2':
        """{"x": float, "y": float} 形式の辞書から復元する。"""
        return Vec2(d["x"], d["y"])


# ─── 直線 ────────────────────────────────────────────────────
class Line:
    """参照始点・参照終点で定義される有向直線。

    参照点（`ref_start`/`ref_end`）は直線の方向を定義するための基準点で、
    実際の道路区間は `Segment` が表す。参照点が動くと、その直線上のすべての
    `Segment.start/end` が `point_at(t)` の動的計算で自動追従する。

    `connection` フィールドで他の `Line` との折れ線/スムーズ接続情報を保持する。
    接続の維持・更新は `Canvas` が担当する。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    ref_start : Vec2
        参照始点座標。
    ref_end : Vec2
        参照終点座標。
    segments : list[Segment]
        この直線が保持する線分のリスト。
    connection : LineConnection or None
        他の直線との接続情報。未接続なら None。
    """

    def __init__(self, ref_start: Vec2, ref_end: Vec2, line_id: int = None):
        """
        Parameters
        ----------
        ref_start : Vec2
            参照始点座標。
        ref_end : Vec2
            参照終点座標。
        line_id : int, optional
            指定しない場合は `new_id()` で採番する。
        """
        self.id = line_id if line_id is not None else new_id()
        self.ref_start = ref_start
        self.ref_end   = ref_end
        self.segments: list[Segment] = []
        self.connection: Optional[LineConnection] = None

    @property
    def direction(self) -> Vec2:
        """ref_start から ref_end への単位方向ベクトル。

        ref_start == ref_end のとき Vec2(1, 0) を返す（normalized のフォールバック）。
        """
        return (self.ref_end - self.ref_start).normalized()

    @property
    def angle(self) -> float:
        """直線の方向角（ラジアン）。範囲は (-π, π]。

        右パネルの方向角表示と `smooth_connect` でのカーブ方向判定に使う。
        """
        d = self.ref_end - self.ref_start
        return math.atan2(d.y, d.x)

    def project_point(self, p: Vec2) -> Vec2:
        """点 p を直線（無限延長）に正射影した最近接点を返す。

        `Clothoid.compute` での接点計算（円心から直線への垂線の足）に使う。

        Parameters
        ----------
        p : Vec2
            射影する点のワールド座標。

        Returns
        -------
        Vec2
            直線上の最近接点。`ref_start + direction * ((p - ref_start)·direction)`。

        Examples
        --------
        x 軸上の直線に (3, 4) を射影すると (3, 0) になる。
        """
        d = self.direction
        t = (p - self.ref_start).dot(d)
        return self.ref_start + d * t

    def project_t(self, p: Vec2) -> float:
        """点 p に対応する直線上のパラメータ t を返す（ref_start=0, ref_end=1）。

        線分端点の t 値更新（`_apply_segment_snap`）や
        Canvas でのドラッグ処理（端点を直線上に拘束）で使う。

        Parameters
        ----------
        p : Vec2
            パラメータを求める点。

        Returns
        -------
        float
            直線の長さがゼロのとき 0.0。値域に制限はなく直線外の点も返す。

        Examples
        --------
        ref_start=(0,0), ref_end=(10,0), p=(3,5) → 0.3
        """
        d = self.ref_end - self.ref_start
        l2 = d.dot(d)
        if l2 < 1e-24:
            return 0.0
        return (p - self.ref_start).dot(d) / l2

    def point_at(self, t: float) -> Vec2:
        """パラメータ t の点を返す。

        `Segment.start/end` が動的にこのメソッドを呼ぶ。参照点が変わると
        同じ t でも返す座標が変わるため、線分は自動的に追従する。

        Parameters
        ----------
        t : float
            0.0 = ref_start、1.0 = ref_end。範囲制限なし。

        Returns
        -------
        Vec2
            ref_start + (ref_end - ref_start) * t。
        """
        return self.ref_start + (self.ref_end - self.ref_start) * t

    def distance_to(self, p: Vec2) -> float:
        """点 p から直線（無限延長）への垂直距離（常に正）を返す。

        Canvas での図形ヒット判定（`_hit_infinite_line`）に使う。

        Parameters
        ----------
        p : Vec2
            距離を求める点。

        Returns
        -------
        float
            |direction × (p - ref_start)|。
        """
        d = self.direction
        return abs((p - self.ref_start).cross(d))

    def signed_dist(self, p: Vec2) -> float:
        """直線の左側が正の符号付き距離を返す。

        `Clothoid.is_left_curve` の判定（円が直線の左右どちらにあるか）と
        `Clothoid.compute` での接点計算に使う。

        Parameters
        ----------
        p : Vec2
            距離を求める点。

        Returns
        -------
        float
            direction × (p - ref_start)。左側が正、右側が負。

        Examples
        --------
        直線が x 軸正方向のとき p=(0,5) → 5.0、p=(0,-3) → -3.0
        """
        d = self.direction
        pm = p - self.ref_start
        return d.cross(pm)

    def project(self, p: Vec2) -> Vec2:
        """project_point の別名。`Clothoid.compute` 内から呼ばれる互換用エイリアス。"""
        return self.project_point(p)

    @property
    def left_normal(self) -> Vec2:
        """direction を CCW に 90° 回転した左法線ベクトル。

        `Clothoid.compute` での接点座標計算で使う。direction=(dx,dy) のとき
        (-dy, dx) を返す。
        """
        d = self.direction
        return Vec2(-d.y, d.x)

    def intersect(self, other: 'Line') -> Optional[Vec2]:
        """2直線の交点を返す。

        折れ線接続・スムーズ接続・`_update_smooth_circle` で交点 X の計算に使う。

        Parameters
        ----------
        other : Line
            交点を求める相手の直線。

        Returns
        -------
        Vec2 or None
            交点座標。平行（|denom| < 1e-12）または同一直線の場合は None。
        """
        d1 = self.ref_end - self.ref_start
        d2 = other.ref_end - other.ref_start
        denom = d1.cross(d2)
        if abs(denom) < 1e-12:
            return None
        diff = other.ref_start - self.ref_start
        t = diff.cross(d2) / denom
        return self.ref_start + d1 * t

    def to_dict(self) -> dict:
        """{"id", "ref_start", "ref_end", "segments"} 形式の辞書に変換する。"""
        return {
            "id": self.id,
            "ref_start": self.ref_start.to_dict(),
            "ref_end":   self.ref_end.to_dict(),
            "segments":  [s.to_dict() for s in self.segments],
        }

    @staticmethod
    def from_dict(d: dict) -> 'Line':
        """辞書から Line を復元する。segments も再構築する。"""
        ln = Line(Vec2.from_dict(d["ref_start"]), Vec2.from_dict(d["ref_end"]), d["id"])
        ln.segments = [Segment.from_dict(s, ln) for s in d.get("segments", [])]
        return ln


# ─── 線分 ────────────────────────────────────────────────────
class Segment:
    """直線（Line）上の部分区間として実際の道路線分を表す。

    位置を座標でなく割合 t（ref_start=0, ref_end=1）で管理するため、
    親 Line の参照点が変わっても自動的に追従する。クロソイドの snap 機能に
    よって端点が固定された状態の線分は、Canvas での通常のハンドル操作では
    変形できない。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    line : Line
        この線分が属する親直線への参照。
    t_start : float
        始点の位置パラメータ（ref_start=0, ref_end=1）。
    t_end : float
        終点の位置パラメータ。通常 t_start < t_end。
    """

    def __init__(self, line: Line, t_start: float = 0.0, t_end: float = 1.0, seg_id: int = None):
        """
        Parameters
        ----------
        line : Line
            この線分が属する親直線。
        t_start : float, optional
            始点パラメータ（デフォルト 0.0 = ref_start）。
        t_end : float, optional
            終点パラメータ（デフォルト 1.0 = ref_end）。
            t_start >= t_end は不正状態だが例外を投げない。
        seg_id : int, optional
            指定しない場合は `new_id()` で採番する。
        """
        self.id     = seg_id if seg_id is not None else new_id()
        self.line   = line
        self.t_start = t_start
        self.t_end   = t_end
        self.snap_prev: Optional[Segment] = None
        self.snap_next: Optional[Segment] = None

    @property
    def start(self) -> Vec2:
        """線分の始点座標（line.point_at(t_start) で動的に計算）。"""
        return self.line.point_at(self.t_start)

    @property
    def end(self) -> Vec2:
        """線分の終点座標（line.point_at(t_end) で動的に計算）。"""
        return self.line.point_at(self.t_end)

    def length(self) -> float:
        """線分の長さ [m] を返す。t_start == t_end のとき 0.0。"""
        return (self.end - self.start).length()

    def to_dict(self) -> dict:
        """{"id", "t_start", "t_end"} 形式の辞書に変換する。

        親 Line への参照はシリアライズしない（from_dict で再設定する）。
        """
        return {"id": self.id, "t_start": self.t_start, "t_end": self.t_end}

    @staticmethod
    def from_dict(d: dict, line: Line) -> 'Segment':
        """辞書と親 Line から Segment を復元する。

        Parameters
        ----------
        d : dict
            {"id", "t_start", "t_end"} を含む辞書。
        line : Line
            この線分が属する親直線（Line.from_dict が渡す）。
        """
        return Segment(line, d["t_start"], d["t_end"], d["id"])


# ─── 直線接続 ────────────────────────────────────────────────
@dataclass
class LineConnection:
    """2直線間の折れ線/スムーズ接続情報を保持するデータクラス。

    `line_a.connection` と `line_b.connection` が同一オブジェクトを参照する
    ことで 2 直線が接続状態を共有する（不変条件）。

    ライフサイクル:
    - 折れ線接続: `Canvas._connect_polyline` が生成し kind="polyline" で設定する
    - スムーズ昇格: `Canvas.smooth_connect` が kind を "smooth" に変更し
      circle・bisector_dir を追記する
    - 解除: `Canvas.disconnect_lines` が両直線の connection を None に設定する

    Attributes
    ----------
    kind : str
        "polyline" または "smooth"。
    line_a, line_b : Line
        接続される 2 直線。
    shared_point : Vec2
        2 直線の交点（共有参照点）の座標。
    a_end_is_shared : bool
        True のとき line_a.ref_end が共有点。
    b_start_is_shared : bool
        True のとき line_b.ref_start が共有点。
    circle : Circle or None
        スムーズ接続専用。2 本のクロソイドが共有する中間円。
    bisector_dir : Vec2 or None
        スムーズ接続専用。折れ角の二等分線方向。円中心の移動拘束に使う。
    line_j_reversed, line_k_reversed : bool
        スムーズ接続専用。各クロソイドを生成した実効直線の反転フラグ。
    """
    kind: str
    line_a: 'Line'
    line_b: 'Line'
    shared_point: Vec2
    a_end_is_shared: bool = True
    b_start_is_shared: bool = True
    circle: Optional['Circle'] = None
    bisector_dir: Optional[Vec2] = None
    line_j_reversed: bool = False
    line_k_reversed: bool = False


# ─── 円 ──────────────────────────────────────────────────────
class Circle:
    """クロソイド曲線の接続先となる円。

    スムーズ接続では 2 本のクロソイドが 1 つの Circle を共有し、
    クロソイドの `_circle_pt` が Arc 端点に snap される。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    center : Vec2
        中心座標。
    radius : float
        半径 [m]。
    arcs : list[Arc]
        この円が保持する円弧のリスト。
    bisector_origin : Vec2 or None
        スムーズ接続時に設定。円中心を二等分線上に拘束する際の基準点（交点 X）。
    bisector_dir : Vec2 or None
        スムーズ接続時に設定。二等分線方向の単位ベクトル。
        円中心ドラッグ時に `center = bisector_origin + bisector_dir * t` で移動を制限する。
    """

    def __init__(self, center: Vec2, radius: float, circle_id: int = None):
        """
        Parameters
        ----------
        center : Vec2
            中心座標。
        radius : float
            半径 [m]。
        circle_id : int, optional
            指定しない場合は `new_id()` で採番する。
        """
        self.id     = circle_id if circle_id is not None else new_id()
        self.center = center
        self.radius = radius
        self.arcs:  list[Arc] = []
        self.bisector_origin: Optional[Vec2] = None
        self.bisector_dir:    Optional[Vec2] = None

    def to_dict(self) -> dict:
        """{"id", "center", "radius", "arcs"} 形式の辞書に変換する。"""
        return {
            "id": self.id,
            "center": self.center.to_dict(),
            "radius": self.radius,
            "arcs": [a.to_dict() for a in self.arcs],
        }

    @staticmethod
    def from_dict(d: dict) -> 'Circle':
        """辞書から Circle を復元する。arcs も再構築する。"""
        c = Circle(Vec2.from_dict(d["center"]), d["radius"], d["id"])
        c.arcs = [Arc.from_dict(a, c) for a in d.get("arcs", [])]
        return c


# ─── 円弧 ────────────────────────────────────────────────────
class Arc:
    """円（Circle）上の部分区間。

    angle_start から CCW 方向に angle_end まで至る弧を表す。
    スムーズ接続では Clothoid の `_circle_pt` が snap され、
    この Arc の端点角度が接点角度に自動更新される。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    circle : Circle
        この円弧が属する親円への参照。
    angle_start : float
        弧の開始角度（ラジアン、x 軸正方向=0、CCW が正）。
    angle_end : float
        弧の終了角度（ラジアン）。
    """

    def __init__(self, circle: Circle, angle_start: float, angle_end: float, arc_id: int = None):
        """
        Parameters
        ----------
        circle : Circle
            この円弧が属する親円。
        angle_start : float
            開始角度（ラジアン）。
        angle_end : float
            終了角度（ラジアン）。
        arc_id : int, optional
            指定しない場合は `new_id()` で採番する。

        Notes
        -----
        コンストラクタは `circle.arcs.append(self)` を行わない。
        追加は呼び出し元の責任とする。
        """
        self.id          = arc_id if arc_id is not None else new_id()
        self.circle      = circle
        self.angle_start = angle_start
        self.angle_end   = angle_end

    @property
    def start(self) -> Vec2:
        """angle_start に対応する円周上の始点座標。"""
        c = self.circle
        return Vec2(c.center.x + c.radius * math.cos(self.angle_start),
                    c.center.y + c.radius * math.sin(self.angle_start))

    @property
    def end(self) -> Vec2:
        """angle_end に対応する円周上の終点座標。"""
        c = self.circle
        return Vec2(c.center.x + c.radius * math.cos(self.angle_end),
                    c.center.y + c.radius * math.sin(self.angle_end))

    def arc_angle(self) -> float:
        """弧長角（CCW 方向の角度差）を返す（常に正）。

        Returns
        -------
        float
            (angle_end - angle_start) % (2π)。angle_start == angle_end のとき 0.0。
        """
        return (self.angle_end - self.angle_start) % (2 * math.pi)

    def arc_length(self) -> float:
        """弧長 [m] を返す。radius * arc_angle()。"""
        return self.circle.radius * self.arc_angle()

    def to_dict(self) -> dict:
        """{"id", "angle_start", "angle_end"} 形式の辞書に変換する。"""
        return {"id": self.id, "angle_start": self.angle_start, "angle_end": self.angle_end}

    @staticmethod
    def from_dict(d: dict, circle: Circle) -> 'Arc':
        """辞書と親 Circle から Arc を復元する。"""
        return Arc(circle, d["angle_start"], d["angle_end"], d["id"])


# ─── クロソイド計算 (Clothoid.py のロジックを使用) ───────────────
_FRESNEL_N = 500


def _fresnel_xy_tau(tau_end: float, R: float, n: int = _FRESNEL_N
                    ) -> tuple[float, float]:
    """クロソイド終点の局所座標変位 (xe, ye) を中点則で数値積分して返す。

    局所座標系は線側接点を原点とし、実効直線の方向を x 軸とする。
    `_find_tau` で全偏角 τ が求まった後、接点座標の計算に使う。

    Parameters
    ----------
    tau_end : float
        全偏角 τ [ラジアン]。1e-9 未満のとき (0.0, 0.0) を返す。
    R : float
        円の半径 [m]。
    n : int, optional
        積分ステップ数（デフォルト 500）。精度と速度のトレードオフ。

    Returns
    -------
    xe : float
        直線方向（x 軸）への変位 [m]。
    ye : float
        左法線方向（y 軸）への変位 [m]。

    Notes
    -----
    L = 2R·τ,  A² = R·L,  ds = L/n。各ステップの中点 s=(i+0.5)·ds で
    cos(s²/2A²) および sin(s²/2A²) を積分する（中点則）。
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
    """Fresnel 条件を満たす全偏角 τ を二分法で逆算する。

    直線と円の幾何関係から「どれだけ曲がれば円に接するか」を決定する
    クロソイド計算の核心部分。`Clothoid.compute` から呼ばれる。

    Parameters
    ----------
    R : float
        円の半径 [m]。
    d_abs : float
        円の中心から実効直線への垂直距離 [m]（常に正）。
    max_tau : float, optional
        探索上限（デフォルト ≒ 2π）。

    Returns
    -------
    float or None
        Fresnel 条件 ye(τ) = d_abs - R·cos(τ) を満たす τ（[1e-4, max_tau] の範囲）。
        d_abs <= R（直線が円の内部または接線）または解なしのとき None。

    Notes
    -----
    80 回の二分法で区間が ≈ 5e-27 に収束する。
    両端点の residual が同符号のとき解なしと判断して None を返す。
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
    """直線（Line）と円（Circle）から定義されるクロソイド曲線（Euler spiral）。

    直線から円弧へ曲率を連続的に変化させる遷移曲線。道路のスムーズ接続で
    直線と円弧の間に挿入される。

    `compute()` が接点座標と描画点列を計算してキャッシュする。
    参照する Line・Circle が変形するたびに `compute()` が再呼び出しされる。

    snap 機能により、線側接点は Segment 端点に、円側接点は Arc 端点に
    自動吸着する。`snap=False` のときは接点で線分・円弧を分割して管理する。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    line : Line
        参照する直線。
    circle : Circle
        参照する円。
    reversed_flag : bool
        True のとき line.ref_start と ref_end を入れ替えた実効直線を使う。
    snap_segment : bool
        True のとき線側接点に最も近い Segment 端点を吸着する。
    snap_arc : bool
        True のとき円側接点に最も近い Arc 端点を吸着する。
    """

    def __init__(self, line: Line, circle: Circle,
                 reversed_flag: bool = False,
                 snap_segment: bool = False,
                 snap_arc: bool = False,
                 clothoid_id: int = None):
        """
        Parameters
        ----------
        line : Line
            接続する直線。
        circle : Circle
            接続する円。
        reversed_flag : bool, optional
            True のとき line.ref_start/ref_end を入れ替えた実効直線を使う。
            同一 Line・Circle に 2 本のクロソイドを生成するときに使う。
        snap_segment : bool, optional
            True のとき線側接点に最も近い Segment 端点を接点座標に吸着する。
            False のとき線分を接点で分割して管理する。デフォルト False。
            スムーズ接続（`Canvas.smooth_connect`）で生成する場合のみ True を渡す。
        snap_arc : bool, optional
            True のとき円側接点に最も近い Arc 端点を接点角度に吸着する。
            False のとき円弧を接点で分割して管理する。デフォルト False。
            スムーズ接続（`Canvas.smooth_connect`）で生成する場合のみ True を渡す。
        clothoid_id : int, optional
            指定しない場合は `new_id()` で採番する。

        Notes
        -----
        コンストラクタ末尾で `compute()` を自動呼び出すため、返った時点で
        `_line_pt`・`_circle_pt`・`_points` が確定している（または _valid=False）。

        `_split_seg_ids`・`_split_arc_ids` は snap=False のときに分割した
        線分・円弧の ID ペアを追跡するためのリスト。接点が移動しても再分割せず
        端点の追従更新だけで済むようにするための仕組み。
        """
        self.id            = clothoid_id if clothoid_id is not None else new_id()
        self.line          = line
        self.circle        = circle
        self.reversed_flag = reversed_flag
        self.snap_segment  = snap_segment
        self.snap_arc      = snap_arc
        self._valid:      bool           = False
        self._tau:        float          = 0.0
        self._line_pt:    Optional[Vec2] = None
        self._circle_pt:  Optional[Vec2] = None
        self._points:     list[Vec2]     = []
        self._split_seg_ids: list[int] = []
        self._split_arc_ids: list[int] = []
        self.compute()

    # ── 実効直線 ──────────────────────────────────────────────
    def _effective_line(self) -> Line:
        """reversed_flag を考慮した実効直線を返す。

        reversed_flag=True のとき ref_start と ref_end を入れ替えた仮想 Line
        オブジェクトを生成して返す。id・segments・connection は元の Line と共有する。
        reversed_flag=False のとき元の Line をそのまま返す。

        Returns
        -------
        Line
            実効直線。reversed_flag=True のとき方向が反転した仮想 Line。
        """
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
        """実効直線の方向単位ベクトル。

        reversed_flag=True のとき元の Line.direction とは逆向きになる。
        ref_start == ref_end のとき Vec2(1, 0) にフォールバックする。
        `compute()` での接点計算と `is_left_curve` の判定に使う。
        """
        ln = self._effective_line()
        return (ln.ref_end - ln.ref_start).normalized()

    @property
    def effective_ref_start(self) -> Vec2:
        """実効直線の始点座標。

        reversed_flag=False → line.ref_start、
        reversed_flag=True  → line.ref_end。
        `compute()` で Fresnel 積分を実施座標系に変換する際の原点として使う。
        """
        return self._effective_line().ref_start

    @property
    def is_left_curve(self) -> bool:
        """このクロソイドが左カーブかどうかを返す。

        実効直線の方向ベクトルと（実効始点→円心）ベクトルの 2D 外積が正の
        とき True（円が直線の左側 = 左カーブ）。`_apply_arc_snap` での
        snap 先（angle_start か angle_end か）の決定に使う。
        """
        eln = self._effective_line()
        d   = (eln.ref_end - eln.ref_start).normalized()
        pm  = self.circle.center - eln.ref_start
        return d.cross(pm) > 0

    # ── 計算本体 ──────────────────────────────────────────────
    def compute(self):
        """接点座標と描画点列を再計算してキャッシュする。

        Line・Circle が変形するたびに `Canvas._propagate_line/_circle` から
        呼ばれる。計算失敗時は `_valid=False` を設定し、`_points=[]`・
        `_line_pt=None`・`_circle_pt=None` にリセットする。

        計算手順（成功時）:
        1. `_find_tau` で全偏角 τ を求める
        2. `_fresnel_xy_tau` で局所座標変位 (xe, ye) を計算
        3. 接点座標（円側 cc、線側 lc）をワールド座標に変換
        4. 等接線角度変化方式で描画点列を生成
           （n_steps = max(80, int(τ/(2π)·512)+40) 点）
        5. `_update_snaps()` で snap/split を適用

        Notes
        -----
        失敗条件: circle.radius < 1e-9、または d_abs <= R（直線が円の内部）、
        または `_find_tau` が None を返した（解なし）。
        """
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
        """snap/split 状態を現在の接点位置に同期する。

        `compute()` の末尾で呼ばれる。`snap_segment` と `snap_arc` は独立して
        設定でき、切り替え時（on→off）は切り替え先メソッドが前の状態
        (_split_*_ids) をクリアしてから新しい状態に移行する。
        """
        if not self._valid:
            return
        if self.snap_segment:
            if self._line_pt is not None:
                self._apply_segment_snap()
        else:
            if self._line_pt is not None:
                self._apply_segment_split()
        if self.snap_arc:
            if self._circle_pt is not None:
                self._apply_arc_snap()
        else:
            if self._circle_pt is not None:
                self._apply_arc_split()

    # ── snap=on: 線分端点をスナップ ──────────────────────────
    def _apply_segment_snap(self):
        """線側接点に最も近い Segment 端点を接点 t 値に移動する（snap_segment=True 専用）。

        最近傍線分の選択には端点距離でなく `_dist_to_seg`（線分全体への距離）を
        使うため、接点が線分の中央付近にある場合でも正しい線分を選べる。

        既存の `_split_seg_ids` があれば先にクリアする（snap=off からの切り替え）。

        Notes
        -----
        移動後に t_start >= t_end になる場合は反対端点を ±0.1 に強制移動して
        線分の縮退を防ぐ。
        """
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
        """線側接点 X で最も近い線分 AB を AX・XB に分割する（snap_segment=False 専用）。

        既に `_split_seg_ids` が設定済みの場合は AX.t_end と XB.t_start を
        現在の t_x に追従更新するだけで再分割しない（パフォーマンスと安定性）。

        Notes
        -----
        - 接点が線分の端点に非常に近い（t_x が境界から 1e-6 以内）場合は分割しない
        - 分割生成した線分の ID を `_split_seg_ids = [AX.id, XB.id]` に記録する
        - `_split_seg_ids` に含まれる線分は候補から除外（自己参照を防ぐ）
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
        """snap=off で分割した線分を元の 1 本に戻す。

        `_split_seg_ids[1]`（XB）を削除し、`_split_seg_ids[0]`（AX）の
        t_end を XB の元の t_end に戻す。その後 `_split_seg_ids` をクリアする。

        snap_segment: False → True の切り替え時と、`Scene.remove_clothoid` 時に呼ばれる。
        """
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
        """点 pt から線分 seg への最短距離を返す。

        `_apply_segment_snap` と `_apply_segment_split` で最近傍線分を
        選択するときに使う。端点距離でなく線分全体への距離を使うため、
        接点が線分の中央付近にある場合でも正しく選択できる。

        Parameters
        ----------
        pt : Vec2
            距離を求める点。
        seg : Segment
            対象の線分。

        Returns
        -------
        float
            線分が縮退（長さゼロ）のとき始点からの距離を返す。
        """
        s, e = seg.start, seg.end
        d = e - s
        l2 = d.dot(d)
        if l2 < 1e-12:
            return (pt - s).length()
        t = max(0.0, min(1.0, (pt - s).dot(d) / l2))
        return (pt - (s + d * t)).length()

    # ── snap=on: 円弧端点をスナップ ──────────────────────────
    def _apply_arc_snap(self):
        """円側接点に最も近い Arc 端点を接点角度に移動する（snap_arc=True 専用）。

        左カーブ → arc.angle_start を circle_pt の角度に設定する。
        右カーブ → arc.angle_end を circle_pt の角度に設定する。

        円弧が存在しない場合は中心角 45° の円弧を自動生成して circle.arcs に追加する。
        既存の `_split_arc_ids` があれば先にクリアする（snap=off からの切り替え）。
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
        """円側接点 X で最も近い円弧を 2 分割する（snap_arc=False 専用）。

        既に `_split_arc_ids` が設定済みの場合は arc_ax.angle_end と
        arc_xb.angle_start を現在の angle_x に追従更新するだけで再分割しない。

        分割対象の円弧は接点が内部に含まれるもの（端点から 1e-4 rad 以上内側）。
        `_split_arc_ids = [arc_ax.id, arc_xb.id]` に記録する。
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
        """snap=off で分割した円弧を元の 1 本に戻す。

        `_split_arc_ids[0]`（start→X）の angle_end を `_split_arc_ids[1]`（X→end）
        の angle_end で上書きし、`_split_arc_ids[1]` を circle.arcs から削除する。
        その後 `_split_arc_ids` をクリアする。

        snap_arc: False → True の切り替え時と、`Scene.remove_clothoid` 時に呼ばれる。
        """
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
        """クロソイドパラメータ A [m]。A = R·√(2τ) = √(R·L)。

        右パネルの情報表示に使う。`is_valid=False` のとき 0.0 を返す。
        """
        if not self._valid:
            return 0.0
        R = self.circle.radius
        return R * math.sqrt(2.0 * self._tau)

    @property
    def line_contact(self) -> Optional[Vec2]:
        """線側接点座標（実効直線上の点）。`compute()` でキャッシュ。無効時は None。"""
        return self._line_pt

    @property
    def circle_contact(self) -> Optional[Vec2]:
        """円側接点座標（円周上の点）。`compute()` でキャッシュ。無効時は None。"""
        return self._circle_pt

    @property
    def points(self) -> list[Vec2]:
        """描画点列（Vec2 リスト）。_line_pt から _circle_pt の順。無効時は空リスト。"""
        return self._points

    @property
    def is_valid(self) -> bool:
        """compute() が成功したとき True。失敗条件: radius<1e-9 / d_abs<=R / τ解なし。"""
        return self._valid

    def to_dict(self) -> dict:
        """{"id","line_id","circle_id","reversed_flag","snap_segment","snap_arc"} 形式の辞書に変換する。

        計算キャッシュ（_line_pt 等）はシリアライズしない。
        ロード後は `Scene.from_dict` 内で `compute()` が呼ばれてキャッシュが再構築される。
        """
        return {
            "id":            self.id,
            "line_id":       self.line.id,
            "circle_id":     self.circle.id,
            "reversed_flag": self.reversed_flag,
            "snap_segment":  self.snap_segment,
            "snap_arc":      self.snap_arc,
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


@dataclass
class OffsetConstraint:
    """直線 S を 2 円 A・B に対してオフセット拘束するデータクラス。

    直線 S の方向と位置を 2 円の中心からの距離で拘束する。
    A の中心から S への垂直距離 = A.radius + off_a を保つ。
    B の中心から S への垂直距離 = B.radius + off_b を保つ。
    円 A・B はスムーズ接続で生成された円（bisector_dir が設定された円）は不可。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    line : Line
        拘束される直線 S（循環参照回避のため object 型で保持）。
    circle_a : Circle
        円 A。
    circle_b : Circle
        円 B。
    off_a : float
        直線 S と円 A の外側オフセット量 [m]。正のとき外側、負のとき内側。
    off_b : float
        直線 S と円 B の外側オフセット量 [m]。
    feasible : bool
        最後の :meth:`solve` が成功した場合 ``True``。距離拘束が矛盾する
        （2 円が近すぎる等）と ``False`` になる。``False`` のとき直線は
        変更されず、次に ``solve`` が成功した時点で追従を再開する。

    Notes
    -----
    内部フィールド ``_eps_a``・``_eps_b`` は :meth:`__post_init__` で 0 に
    初期化され、:meth:`calc_offsets_from_current` で設定時点の符号が固定される。

    * ``_eps_a = -sign(signed_dist(circle_a))``
    * ``_eps_b =  sign(signed_dist(circle_b))``

    これにより「直線が 2 円の間にあるか外側にあるか」という法線方向が
    :meth:`solve` を通じて常に維持される。0 は未設定を表し、後方互換
    モード（全組み合わせを探索）で動作する。
    """
    id:       int    = field(default_factory=new_id)
    line:     object = None   # Line（循環参照回避のため object 型）
    circle_a: object = None   # Circle
    circle_b: object = None   # Circle
    off_a:    float  = 0.0
    off_b:    float  = 0.0
    feasible: bool   = True   # 最後の solve() が成功した場合 True

    def solve(self) -> bool:
        """off_a・off_b・_eps_a・_eps_b から直線 S の参照点を再計算する。

        直線 S の方程式を ``n·x = c``（``n``: 法線単位ベクトル、``c``: 切片）
        とする。各円の距離拘束:

        .. code-block:: text

            c = n · ca.center + ε_a · ra   （ra = ca.radius + off_a）
            s_a_new = -ε_a · ra
            s_b_new =  ε_b · rb
            n · (cb.center - ca.center) = ε_b · rb + ε_a · ra

        **解の選択**:

        * ``_eps_a``・``_eps_b`` が設定済み（非零）の場合はその 1 通りの
          ``(ε_a, ε_b)`` のみで解を求める（法線方向を設定時から維持）。
        * 未設定（0）の場合は 4 通りの全組み合わせを列挙して現在の直線方向
          との内積が最大のものを選ぶ（後方互換モード）。
        * ``sign_delta`` が 2 通り残る場合は現在の直線方向との内積で絞る。
        * ``cur_dir`` との内積が負なら ``d`` を反転して向きを揃える。

        成功時は各円の垂線の足を ``ref_start``・``ref_end`` に割り当て
        ``feasible = True`` を設定する。``ref_start`` に近い方の垂線の足を
        ``ref_start`` に割り当てる。

        Returns
        -------
        bool
            計算が成功し直線を更新したとき ``True``。
            2 円の中心が一致（``L < 1e-9``）または設定された ``(ε_a, ε_b)``
            で ``|rhs| > 1.0``（距離拘束が矛盾）のとき ``False``。
            ``False`` のとき ``feasible = False`` を設定し直線は変更しない。
        """
        if self.line is None or self.circle_a is None or self.circle_b is None:
            return False

        ca_center = self.circle_a.center
        cb_center = self.circle_b.center
        ra = self.circle_a.radius + self.off_a
        rb = self.circle_b.radius + self.off_b

        ab = cb_center - ca_center
        L  = ab.length()
        if L < 1e-9:
            self.feasible = False
            return False  # 2 円の中心が一致

        phi = math.atan2(ab.y, ab.x)
        cur_dir = self.line.direction

        # _eps_a・_eps_b は設定時に固定された符号（calc_offsets_from_current で設定）
        # 未設定（0）の場合は全組み合わせから現在方向で選ぶ（後方互換）
        eps_pairs = []
        if self._eps_a != 0 and self._eps_b != 0:
            eps_pairs = [(self._eps_a, self._eps_b)]
        else:
            eps_pairs = [(ea, eb) for ea in (+1, -1) for eb in (+1, -1)]

        candidates = []
        for eps_a, eps_b in eps_pairs:
            rhs = (eps_b * rb + eps_a * ra) / L
            if abs(rhs) > 1.0:
                continue
            delta = math.acos(max(-1.0, min(1.0, rhs)))
            for sign_delta in (+1, -1):
                theta = phi + sign_delta * delta
                n = Vec2(math.cos(theta), math.sin(theta))   # 法線
                d = Vec2(-math.sin(theta), math.cos(theta))  # 直線方向
                c = n.dot(ca_center) + eps_a * ra             # 切片
                candidates.append((d, n, c))

        if not candidates:
            self.feasible = False
            return False  # 距離拘束が矛盾（この eps_a, eps_b では解なし）

        # sign_delta が 2 通りある場合は現在の直線方向に近い方を選ぶ
        best = max(candidates, key=lambda t: abs(cur_dir.dot(t[0])))
        d, n, c = best

        # cur_dir との内積が負なら d を反転して向きを揃える
        if cur_dir.dot(d) < 0:
            d = Vec2(-d.x, -d.y)

        # 各円の中心から直線 S への垂線の足
        def foot(center):
            # 直線: n・x = c → 垂線の足は center - n*(n・center - c)
            t = n.dot(center) - c
            return center - n * t

        foot_a = foot(ca_center)
        foot_b = foot(cb_center)

        # ref_start に近い足を ref_start に割り当てる
        rs = self.line.ref_start
        if (foot_a - rs).length() <= (foot_b - rs).length():
            self.line.ref_start = foot_a
            self.line.ref_end   = foot_b
        else:
            self.line.ref_start = foot_b
            self.line.ref_end   = foot_a

        self.feasible = True
        return True


    def __post_init__(self):
        """内部フィールド ``_eps_a``・``_eps_b`` を初期化する。

        ``@dataclass`` のフィールドとして宣言できない可変デフォルト値を
        ここで設定する。``0`` は未設定を意味し、
        :meth:`calc_offsets_from_current` を呼ぶと実際の符号が設定される。
        未設定のまま :meth:`solve` を呼ぶと後方互換モード（4 通りの
        符号組み合わせを全探索）で動作する。
        """
        self._eps_a: int = 0
        self._eps_b: int = 0

    def calc_offsets_from_current(self) -> None:
        """現在の直線と 2 円の位置関係から off_a・off_b と符号フラグを算出する。

        オフセット拘束を設定した時点の位置に基づいて初期値と法線方向を決定する。

        * ``off_a = distance_to(circle_a.center) - circle_a.radius``
        * ``off_b = distance_to(circle_b.center) - circle_b.radius``

        法線方向符号の導出:

        * ``_eps_a = -sign(signed_dist(circle_a.center))``
          （circle_a が直線の左側なら ``_eps_a = -1``）
        * ``_eps_b =  sign(signed_dist(circle_b.center))``
          （circle_b が直線の左側なら ``_eps_b = +1``）

        これにより :meth:`solve` が「直線が 2 円の間にあるか外側にあるか」
        という位置関係を維持して解を選択できるようになる。

        ``line``・``circle_a``・``circle_b`` のいずれかが ``None`` の場合は
        何もしない。
        """
        if self.line is None or self.circle_a is None or self.circle_b is None:
            return
        da = self.line.distance_to(self.circle_a.center)
        db = self.line.distance_to(self.circle_b.center)
        self.off_a = da - self.circle_a.radius
        self.off_b = db - self.circle_b.radius
        sa = self.line.signed_dist(self.circle_a.center)
        sb = self.line.signed_dist(self.circle_b.center)
        self._eps_a = -1 if sa > 0 else +1
        self._eps_b = +1 if sb > 0 else -1

    def to_dict(self) -> dict:
        """{"id","line_id","ca_id","cb_id","off_a","off_b"} 形式の辞書に変換する。"""
        return {
            'id':      self.id,
            'line_id': self.line.id     if self.line     else None,
            'ca_id':   self.circle_a.id if self.circle_a else None,
            'cb_id':   self.circle_b.id if self.circle_b else None,
            'off_a':   self.off_a,
            'off_b':   self.off_b,
        }

    @staticmethod
    def from_dict(d: dict,
                  lines_by_id: dict,
                  circles_by_id: dict) -> 'OffsetConstraint':
        """辞書から OffsetConstraint を復元する。

        Parameters
        ----------
        d : dict
            to_dict() が返す形式の辞書。
        lines_by_id : dict[int, Line]
            id をキーとする Line の辞書。
        circles_by_id : dict[int, Circle]
            id をキーとする Circle の辞書。
        """
        oc = OffsetConstraint()
        oc.id       = d['id']
        oc.line     = lines_by_id.get(d.get('line_id'))
        oc.circle_a = circles_by_id.get(d.get('ca_id'))
        oc.circle_b = circles_by_id.get(d.get('cb_id'))
        oc.off_a    = d.get('off_a', 0.0)
        oc.off_b    = d.get('off_b', 0.0)
        return oc


def plan_length_of(obj) -> float:
    """平面線形要素の平面長（道路上の長さ）を型に依らず返す。

    `ElementProfile.plan_length` の設定、3D 中心線生成（`build_centerline`）、
    縦断線形ウィンドウの累積距離計算（`set_plan_elements`）など、型を問わず
    要素を扱う処理で広く使われる統一インターフェース。

    Parameters
    ----------
    obj : Segment or Arc or Clothoid or any
        平面長を求める要素。対応していない型は 0.0 を返す。

    Returns
    -------
    float
        平面長 [m]。Clothoid で `is_valid=False` または τ=0 のとき 0.0。
    """
    if isinstance(obj, Segment):
        return obj.length()
    if isinstance(obj, Arc):
        return obj.arc_length()
    if isinstance(obj, Clothoid):
        # クロソイド曲線長 = L = 2R·τ
        if obj.is_valid and obj._tau > 0:
            return 2.0 * obj.circle.radius * obj._tau
        return 0.0
    return 0.0


@dataclass
class ElementProfile:
    """平面線形要素（Segment/Arc/Clothoid）と縦断線形データを 1 対 1 で対応させるブリッジ。

    平面線形はワールド座標で定義され、縦断線形は「平面距離に対する標高」で定義される。
    ElementProfile がその 2 つの座標系を橋渡しする。

    grade_lines の距離はこの要素内の**相対距離**（始端=0、終端=plan_length）で管理する。
    チェーン全体の絶対距離への変換は `ProfileCanvas.set_plan_elements` が担当する。

    隣接要素との境界標高は `elev_end == 次要素の elev_start` で一致させる。
    `_snap_grade_lines('both')` がこの一致を保証する。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    element_id : int
        対応する Segment/Arc/Clothoid の ID。
    element_type : str
        'segment' / 'arc' / 'clothoid'。
    plan_length : float
        この要素の平面長 [m]。
    reversed_flag : bool
        True のとき、チェーン上でこの要素を終点→始点の向きで使っている。
        grade_lines の dist/elev は正順で保存し、使用時に逆順変換する。
    elev_start : float
        始端標高 [m]（チェーン上での進行方向の始点側）。
    elev_end : float
        終端標高 [m]（隣接要素と共有する境界値）。
    grade_lines : list[GradeLine]
        勾配直線のリスト。相対距離で管理。
    vertical_curves : list[VerticalCurve]
        縦断曲線のリスト。
    """
    id:           int   = field(default_factory=new_id)
    element_id:   int   = -1    # 対応する Segment/Arc/Clothoid の id
    element_type: str   = ""    # 'segment' | 'arc' | 'clothoid'
    plan_length:  float = 0.0   # この要素の平面長 [m]
    reversed_flag: bool = False  # True なら終点→始点の向きで使われている
    elev_start:   float = 0.0   # 始端標高 [m]（正順の始点側）
    elev_end:     float = 0.0   # 終端標高 [m]（隣接要素と共有）
    grade_lines:  list  = field(default_factory=list)   # list[GradeLine] 相対距離
    vertical_curves: list = field(default_factory=list) # list[VerticalCurve]

    def to_dict(self) -> dict:
        """すべてのフィールドを含む辞書に変換する（JSON シリアライズ用）。"""
        return {
            "id":              self.id,
            "element_id":      self.element_id,
            "element_type":    self.element_type,
            "plan_length":     self.plan_length,
            "reversed_flag":   self.reversed_flag,
            "elev_start":      self.elev_start,
            "elev_end":        self.elev_end,
            "grade_lines":     [g.to_dict() for g in self.grade_lines],
            "vertical_curves": [v.to_dict() for v in self.vertical_curves],
        }

    @staticmethod
    def from_dict(d: dict) -> 'ElementProfile':
        ep = ElementProfile()
        ep.id            = d.get("id", new_id())
        ep.element_id    = d.get("element_id", -1)
        ep.element_type  = d.get("element_type", "")
        ep.plan_length   = d.get("plan_length", 0.0)
        ep.reversed_flag = d.get("reversed_flag", False)
        ep.elev_start    = d.get("elev_start", 0.0)
        ep.elev_end      = d.get("elev_end", 0.0)
        ep.grade_lines   = [GradeLine.from_dict(g)
                            for g in d.get("grade_lines", [])]
        ep.vertical_curves = [VerticalCurve.from_dict(v)
                              for v in d.get("vertical_curves", [])]
        return ep

    def elev_at(self, rel: float) -> float:
        """この EP 内の相対距離 rel での標高を返す（縦断曲線優先）。

        `build_centerline` での 3D 点列生成と `save_to_profiles` での端点標高更新に使う。

        Parameters
        ----------
        rel : float
            EP 内の相対距離 [m]。[0, plan_length] にクリップされる。

        Returns
        -------
        float
            標高 [m]。優先順位:
            1. VPC-0.001 ≤ rel ≤ VPT+0.001 の VerticalCurve（放物線式）
            2. dist_start-0.001 ≤ rel ≤ dist_end+0.001 の GradeLine（線形補間）
            3. 該当なし → 0.0

        Examples
        --------
        GL: dist_start=0, elev_start=10, dist_end=100, elev_end=20 のとき
        elev_at(50) → 15.0、elev_at(0) → 10.0、elev_at(100) → 20.0
        """
        rel = max(0.0, min(rel, self.plan_length))
        for vc in self.vertical_curves:
            if vc.vpc_dist - 0.001 <= rel <= vc.vpt_dist + 0.001:
                e = vc.elevation_at(rel)
                if not math.isnan(e):
                    return e
        for gl in sorted(self.grade_lines, key=lambda g: g.dist_start):
            if gl.dist_start - 0.001 <= rel <= gl.dist_end + 0.001:
                span = gl.dist_end - gl.dist_start
                t = (rel - gl.dist_start) / span if abs(span) > 1e-9 else 0.0
                return gl.elev_start + (gl.elev_end - gl.elev_start) * t
        return 0.0


@dataclass
class VerticalAlignment:
    """
    後方互換用: 旧フォーマットの grade_lines / vertical_curves を保持する。
    新規データは ElementProfile を使う。
    """
    id: int = field(default_factory=new_id)
    nickname: str = ""
    grade_lines:     list = field(default_factory=list)
    vertical_curves: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "nickname":        self.nickname,
            "grade_lines":     [g.to_dict() for g in self.grade_lines],
            "vertical_curves": [v.to_dict() for v in self.vertical_curves],
        }

    @staticmethod
    def from_dict(d: dict) -> 'VerticalAlignment':
        va = VerticalAlignment()
        va.id             = d.get("id", new_id())
        va.nickname       = d.get("nickname", "")
        va.grade_lines    = [GradeLine.from_dict(g)
                             for g in d.get("grade_lines", [])]
        va.vertical_curves = [VerticalCurve.from_dict(v)
                              for v in d.get("vertical_curves", [])]
        return va
@dataclass
class GradeLine:
    """一定勾配の直線区間（縦断線形の基本要素）。

    dist_start〜dist_end の距離範囲と elev_start〜elev_end の標高で定義する。
    隣接する GradeLine の端点は `_snap_grade_lines()` によって強制一致させる。
    `next_curve`/`prev_curve` はメモリ上の参照のみでファイルには保存しない。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    dist_start, dist_end : float
        区間の始端・終端距離 [m]（EP 内の相対距離）。
    elev_start, elev_end : float
        始端・終端の標高 [m]。
    next_curve, prev_curve : VerticalCurve or None
        隣接する縦断曲線への参照（メモリ上のみ、ファイル非保存）。
    """
    id: int = field(default_factory=new_id)
    dist_start: float = 0.0
    elev_start: float = 0.0
    dist_end:   float = 100.0
    elev_end:   float = 0.0
    next_curve: Optional['VerticalCurve'] = None
    prev_curve: Optional['VerticalCurve'] = None

    @property
    def gradient(self) -> float:
        """勾配 [%]。右パネルの表示と _recalc_vc_gradients で g1/g2 の再計算に使う。

        Returns
        -------
        float
            (elev_end - elev_start) / (dist_end - dist_start) * 100。
            dist_end - dist_start < 1e-9 のとき 0.0。
        """
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
    """縦断曲線（放物線）を表すデータクラス。

    PVI（2勾配線の交点）を中心に VPC〜VPT の区間を放物線で結ぶ。
    `elevation_at(dist)` が範囲外で NaN を返すため、`ElementProfile.elev_at` が
    NaN を検出して GradeLine にフォールバックする。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    pvi_dist : float
        PVI の累積距離 [m]（勾配直線の終点距離と一致）。
    pvi_elev : float
        PVI の標高 [m]。
    g1 : float
        前勾配 [%]（VPC より手前の勾配直線の勾配）。
    g2 : float
        後勾配 [%]（VPT より先の勾配直線の勾配）。
    length : float
        曲線長 L [m]。VPC〜VPT の距離。
    prev_line_id, next_line_id : int
        前後の GradeLine の ID（ファイル保存用）。-1 は未設定。
    """
    id: int = field(default_factory=new_id)
    pvi_dist: float = 0.0
    pvi_elev: float = 0.0
    g1: float = 0.0
    g2: float = 0.0
    length: float = 50.0
    prev_line_id: int = -1
    next_line_id: int = -1

    @property
    def vpc_dist(self) -> float:
        """VPC（縦断曲線始点）の累積距離 [m]。pvi_dist - length/2。"""
        return self.pvi_dist - self.length / 2

    @property
    def vpt_dist(self) -> float:
        """VPT（縦断曲線終点）の累積距離 [m]。pvi_dist + length/2。"""
        return self.pvi_dist + self.length / 2

    @property
    def vpc_elev(self) -> float:
        """VPC の標高 [m]。pvi_elev - g1/100 * length/2。"""
        return self.pvi_elev - self.g1 / 100 * self.length / 2

    @property
    def vpt_elev(self) -> float:
        """VPT の標高 [m]。pvi_elev + g2/100 * length/2。"""
        return self.pvi_elev + self.g2 / 100 * self.length / 2

    @property
    def K(self) -> float:
        """K 値（縦断曲線の緩やかさの指標）[m/%]。

        「勾配が 1% 変化するのに必要な距離」を表す設計指標。
        大きいほど緩やかな縦断曲線。|g2-g1| < 1e-9 のとき inf を返す。
        """
        dg = abs(self.g2 - self.g1)
        return self.length / dg if dg > 1e-9 else float('inf')

    def elevation_at(self, dist: float) -> float:
        """累積距離 dist での標高を放物線式で返す。

        `ElementProfile.elev_at` から VPC〜VPT 範囲内の点に対して呼ばれる。

        Parameters
        ----------
        dist : float
            EP 内の相対距離 [m]（vpc_dist を原点とした局所距離 x = dist - vpc_dist で計算）。

        Returns
        -------
        float
            標高 [m]。x < 0 または x > length のとき float('nan')。
            放物線式: vpc_elev + (g1/100)·x + ((g2-g1)/(2·length)/100)·x²

        Examples
        --------
        g1=2%, g2=0%, L=100m, vpc_elev=10.0 のとき
        x=0 → 10.0m、x=50 → 10.5m、x=100 → 10.0m
        """
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
    """アプリケーション全体の唯一の状態保持者（Single Source of Truth）。

    すべての図形・縦断データ・ニックネームをこのオブジェクトが管理する。
    Undo 機能は `Canvas.push_undo` が `to_dict()` で Scene 全体を JSON に
    シリアライズしてスタックに積む方式で実現する。そのため Scene は常に
    完全にシリアライズ可能でなければならない。

    `segment_snaps`/`arc_snaps` は将来の拡張用フィールドで、現バージョンでは
    Clothoid の `_split_seg_ids`/`_split_arc_ids` が内部で分割管理を行うため
    実質未使用。

    Attributes
    ----------
    lines : list[Line]
        全直線。
    circles : list[Circle]
        全円。
    clothoids : list[Clothoid]
        全クロソイド。
    offset_constraints : list[OffsetConstraint]
        直線-2円のオフセット拘束。円の変形に合わせて直線が自動追従する。
    element_profiles : list[ElementProfile]
        縦断線形データ（要素単位）。
    vertical_alignments : list[VerticalAlignment]
        旧フォーマット互換用。新規データは使用しない。
    segment_snaps : list[SegmentSnap]
        線分端点の接続情報（現バージョンでは実質未使用）。
    arc_snaps : list[ArcSnap]
        円弧端点の接続情報（現バージョンでは実質未使用）。
    nicknames : dict[int, str]
        ID → ニックネームの辞書。
    """
    def __init__(self):
        self.lines:     list[Line]          = []
        self.circles:   list[Circle]        = []
        self.clothoids: list[Clothoid]      = []
        self.vertical_alignments: list[VerticalAlignment] = []  # 旧フォーマット互換
        self.element_profiles: list[ElementProfile] = []         # 要素単位の縦断データ
        self.segment_snaps: list[SegmentSnap] = []
        self.arc_snaps:     list[ArcSnap]     = []
        self.offset_constraints: list['OffsetConstraint'] = []
        self.nicknames: dict[int, str] = {}   # id → nickname

    def get_nickname(self, obj_id: int, prefix: str = "") -> str:
        """図形のニックネームを返す。未設定のとき "nickname_{prefix}_{obj_id}" を返す。

        Parameters
        ----------
        obj_id : int
            図形の ID。
        prefix : str, optional
            未設定時のデフォルト名に使うプレフィックス（例: "line", "circle"）。

        Returns
        -------
        str
            設定済みニックネーム、または "nickname_{prefix}_{obj_id}"。
        """
        if obj_id in self.nicknames:
            return self.nicknames[obj_id]
        return f"nickname_{prefix}_{obj_id}"

    def set_nickname(self, obj_id: int, name: str):
        """図形のニックネームを設定する。name が空文字のとき辞書から削除する。

        Parameters
        ----------
        obj_id : int
            図形の ID。
        name : str
            設定するニックネーム。空文字のとき既存エントリを削除する。
        """
        if name:
            self.nicknames[obj_id] = name
        elif obj_id in self.nicknames:
            del self.nicknames[obj_id]

    def add_line(self, line: Line) -> Line:
        """Line を lines リストに追加し、デフォルトニックネームを設定する。

        既存ニックネームは上書きしない。

        Returns
        -------
        Line
            引数の line をそのまま返す（メソッドチェーン用）。
        """
        self.lines.append(line)
        if line.id not in self.nicknames:
            self.nicknames[line.id] = f"nickname_line_{line.id}"
        return line

    def add_circle(self, circle: Circle) -> Circle:
        """Circle を circles リストに追加し、デフォルトニックネームを設定する。

        Returns
        -------
        Circle
            引数の circle をそのまま返す（メソッドチェーン用）。
        """
        self.circles.append(circle)
        if circle.id not in self.nicknames:
            self.nicknames[circle.id] = f"nickname_circle_{circle.id}"
        return circle

    def add_clothoid(self, clothoid: Clothoid) -> Clothoid:
        """Clothoid を clothoids リストに追加し、デフォルトニックネームを設定する。

        Returns
        -------
        Clothoid
            引数の clothoid をそのまま返す（メソッドチェーン用）。
        """
        self.clothoids.append(clothoid)
        if clothoid.id not in self.nicknames:
            self.nicknames[clothoid.id] = f"nickname_clothoid_{clothoid.id}"
        return clothoid

    def remove_line(self, line: Line):
        """Line と、それを参照するすべての Clothoid を削除する。

        Clothoid の削除は `remove_clothoid` 経由で行い、分割済み線分・円弧の
        復元（`_clear_segment_split`/`_clear_arc_split`）を確実に実行する。
        """
        related = [c for c in self.clothoids if c.line is line]
        for c in related:
            self.remove_clothoid(c)
        self.lines.remove(line)

    def remove_circle(self, circle: Circle):
        """Circle と、それを参照するすべての Clothoid を削除する。"""
        related = [c for c in self.clothoids if c.circle is circle]
        for c in related:
            self.remove_clothoid(c)
        self.circles.remove(circle)

    def remove_clothoid(self, clothoid: Clothoid):
        """Clothoid を clothoids リストから除去する。

        除去前に `_clear_segment_split()` と `_clear_arc_split()` を呼んで
        snap=off で分割した線分・円弧を元に戻す。
        """
        if clothoid in self.clothoids:
            clothoid._clear_segment_split()
            clothoid._clear_arc_split()
            self.clothoids.remove(clothoid)

    def clothoids_for(self, line: Line, circle: Circle) -> list[Clothoid]:
        """指定 Line と Circle の両方を参照する Clothoid のリストを返す。

        右パネルの _build_line_circle でクロソイドの本数（0/1/2）を判定するために使う。

        Returns
        -------
        list[Clothoid]
            該当する Clothoid のリスト。0〜2 要素。
        """
        return [c for c in self.clothoids if c.line is line and c.circle is circle]

    def connected_objects(self, obj) -> list:
        """obj に接続している図形の一覧を返す。

        右パネルの「関連図形」表示に使う。

        Parameters
        ----------
        obj : Line or Circle or Clothoid
            対象の図形。

        Returns
        -------
        list
            - Line: この直線を参照するクロソイド + 接続中の相手直線
            - Circle: この円を参照するクロソイド
            - Clothoid: 参照する直線と円
        """
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

    def _fix_duplicate_ids(self) -> None:
        """Scene 内の id 重複を検出して振り直す。

        `to_dict()` を呼ぶ前に実行することで保存ファイルの整合性を保証する。
        Line と Segment が同じ id を持つ場合など、通常の操作では起きないはずだが
        複数のファイルをマージしたり古い形式のファイルを読み込んだ際に発生しうる。
        """
        seen: set[int] = set()

        def _assign(obj) -> None:
            if obj.id in seen:
                obj.id = new_id()
            seen.add(obj.id)

        for ln in self.lines:
            _assign(ln)
            for seg in ln.segments:
                _assign(seg)
        for ci in self.circles:
            _assign(ci)
            for arc in ci.arcs:
                _assign(arc)
        for clo in self.clothoids:
            _assign(clo)
        for oc in self.offset_constraints:
            _assign(oc)

    def to_dict(self) -> dict:
        """シーン全体を JSON シリアライズ可能な辞書に変換する。

        呼び出し前に :meth:`_fix_duplicate_ids` を実行して ID 重複を修正する。
        各図形の辞書の ``'id'`` の直後に ``'nickname'`` を挿入して返す。
        ``offset_constraints`` も含む。
        Undo スタックへの積み込みとファイル保存の両方で使う。

        Returns
        -------
        dict
            JSON にシリアライズ可能な辞書。キー:
            ``lines``, ``circles``, ``clothoids``, ``offset_constraints``,
            ``element_profiles``, ``nicknames``。
        """
        self._fix_duplicate_ids()  # 保存前に id 重複を修正
        def _with_nick(d: dict) -> dict:
            """'id' の次に 'nickname' を挿入した辞書を返す（内部ヘルパー）。"""
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
            "lines":                [line_dict(l) for l in self.lines],
            "circles":              [circle_dict(c) for c in self.circles],
            "clothoids":            [_with_nick(c.to_dict()) for c in self.clothoids],
            "element_profiles":     [ep.to_dict() for ep in self.element_profiles],
            "vertical_alignments":  [va.to_dict() for va in self.vertical_alignments],
            "segment_snaps":        [s.to_dict() for s in self.segment_snaps],
            "arc_snaps":            [a.to_dict() for a in self.arc_snaps],
        }

    @staticmethod
    def from_dict(d: dict) -> 'Scene':
        """辞書から Scene を復元する。

        復元順序:

        1. ``lines``（``segments`` を含む）→ ``lines_by_id`` に格納。
           ``_resolve_id`` で ID が振り直された場合は元の ID でも同じ
           オブジェクトを引けるフォールバックエントリを追加する。
        2. ``circles``（``arcs`` を含む）→ ``circles_by_id`` に格納。同様に
           フォールバックエントリを追加する。
        3. ``clothoids``（``line_id``・``circle_id`` で参照解決）
        4. ``offset_constraints``（``line_id``・``ca_id``・``cb_id`` で参照解決）
        5. ``element_profiles``、``vertical_alignments``
        6. 旧フォーマット互換（トップレベルの ``grade_lines``/``vertical_curves``）
        7. 全 ID の最大値 + 1 でカウンタを再設定

        フォールバック参照の設計意図: ``_resolve_id`` によって line の ID が
        振り直された場合（保存ファイルに ``Line#6`` と ``Segment#6`` が同じ
        ID を持つ等）、振り直し後の ID だけでなく元の ID でも ``lines_by_id``
        を引けるようにすることで、clothoid の ``line_id`` が振り直し前の値を
        指していても参照を解決できクロソイドが消えなくなる。

        Parameters
        ----------
        d : dict
            :meth:`to_dict` が返す形式の辞書。旧フォーマット（トップレベル
            ``nicknames`` フィールド）との後方互換も維持する。

        Returns
        -------
        Scene
            復元された Scene オブジェクト。
        """
        sc = Scene()
        lines_by_id   = {}
        circles_by_id = {}

        def _extract_nick(raw: dict, sc: 'Scene'):
            nick = raw.get("nickname")
            fid  = raw.get("id")
            if nick and fid is not None:
                sc.nicknames[fid] = nick

        # ID衝突を検出して振り直すヘルパー
        seen_ids: set[int] = set()

        def _resolve_id(raw: dict) -> int:
            """rawの 'id' を取得し、衝突があれば新IDを割り当てる"""
            fid = raw.get("id")
            if fid is None:
                fid = new_id()
                raw["id"] = fid
            elif fid in seen_ids:
                fid = new_id()
                raw["id"] = fid
            seen_ids.add(fid)
            return fid

        # id_remap: 保存時の id → _resolve_id 後の id のマッピング
        # line/circle の id が振り直された場合でも clothoid の参照を維持する
        id_remap: dict[int, int] = {}

        for ld in d.get("lines", []):
            _extract_nick(ld, sc)
            original_id = ld.get("id")
            _resolve_id(ld)
            if original_id is not None and ld["id"] != original_id:
                id_remap[original_id] = ld["id"]
            for sd in ld.get("segments", []):
                _resolve_id(sd)
            ln = Line.from_dict(ld)
            sc.lines.append(ln)
            lines_by_id[ln.id] = ln
            # 元の id でも引けるようにする（remap前のid → ln）
            if original_id is not None and original_id != ln.id:
                lines_by_id[original_id] = ln

        for cd in d.get("circles", []):
            _extract_nick(cd, sc)
            original_id = cd.get("id")
            _resolve_id(cd)
            if original_id is not None and cd["id"] != original_id:
                id_remap[original_id] = cd["id"]
            for ad in cd.get("arcs", []):
                _resolve_id(ad)
            ci = Circle.from_dict(cd)
            sc.circles.append(ci)
            circles_by_id[ci.id] = ci
            # 元の id でも引けるようにする
            if original_id is not None and original_id != ci.id:
                circles_by_id[original_id] = ci

        for cd in d.get("clothoids", []):
            _extract_nick(cd, sc)
            _resolve_id(cd)
            ln = lines_by_id.get(cd["line_id"])
            ci = circles_by_id.get(cd["circle_id"])
            if ln and ci:
                clo = Clothoid(ln, ci, cd.get("reversed_flag", False),
                               cd.get("snap_segment", False),
                               cd.get("snap_arc", False),
                               cd.get("id"))
                sc.clothoids.append(clo)

        sc.element_profiles    = [ElementProfile.from_dict(ep)
                                   for ep in d.get("element_profiles", [])]
        sc.vertical_alignments = [
            VerticalAlignment.from_dict(va)
            for va in d.get("vertical_alignments", [])
        ]
        old_gls = d.get("grade_lines", [])
        old_vcs = d.get("vertical_curves", [])
        if old_gls or old_vcs:
            va = VerticalAlignment()
            va.nickname        = "default"
            va.grade_lines     = [GradeLine.from_dict(g) for g in old_gls]
            va.vertical_curves = [VerticalCurve.from_dict(v) for v in old_vcs]
            sc.vertical_alignments.append(va)

        sc.segment_snaps = [SegmentSnap.from_dict(s) for s in d.get("segment_snaps", [])]
        sc.arc_snaps     = [ArcSnap.from_dict(a)     for a in d.get("arc_snaps", [])]

        for k, v in d.get("nicknames", {}).items():
            sc.nicknames[int(k)] = v

        # IDカウンタをリセット
        all_ids = list(seen_ids)
        all_ids.extend(ep.id for ep in sc.element_profiles)
        for ep in sc.element_profiles:
            all_ids.extend(g.id for g in ep.grade_lines)
            all_ids.extend(v.id for v in ep.vertical_curves)
        for va in sc.vertical_alignments:
            all_ids.append(va.id)
            all_ids.extend(g.id for g in va.grade_lines)
            all_ids.extend(v.id for v in va.vertical_curves)
        if all_ids:
            _reset_id_counter_after(max(all_ids))

        return sc


# ── チェーン順序解決ユーティリティ ───────────────────────────────

SNAP_TOL = 1.0   # 端点が同一とみなす距離閾値 [m]


def _elem_endpoints(obj):
    """(start_pt, end_pt) を Vec2 で返す。取得できない場合は None。"""
    if isinstance(obj, Segment):
        return obj.start, obj.end
    if isinstance(obj, Arc):
        return obj.start, obj.end
    if isinstance(obj, Clothoid):
        if obj.is_valid and obj._line_pt and obj._circle_pt:
            return obj._line_pt, obj._circle_pt
    return None, None


def _pt_dist(a, b) -> float:
    """2点間の距離を返す。いずれかが None のとき inf を返す。

    `resolve_chain()` 内で端点距離の比較に使う。

    Parameters
    ----------
    a, b : Vec2 or None
        距離を求める 2 点。

    Returns
    -------
    float
        ユークリッド距離。いずれかが None のとき float('inf')。
    """
    if a is None or b is None:
        return float('inf')
    import math
    return math.hypot(a.x - b.x, a.y - b.y)


def tangent_at(obj, at_end: bool) -> tuple:
    """図形の端点での接線単位ベクトルを (dx, dy) で返す。

    `entry_tangent` と組み合わせて右パネルの [順]/[逆] 判定に使う。

    Parameters
    ----------
    obj : Segment or Arc or Clothoid
        接線を求める図形。
    at_end : bool
        False のとき始点側、True のとき終点側の接線を返す。

    Returns
    -------
    tuple[float, float]
        単位接線ベクトル (dx, dy)。Clothoid の points が 2 点未満のとき (1, 0)。

    Notes
    -----
    - Segment: 全域で一定（start→end 方向）
    - Arc: angle_start/end での (-sin, cos)
    - Clothoid: points の先頭/末尾 2 点の差分
    """
    import math
    if isinstance(obj, Segment):
        dx = obj.end.x - obj.start.x
        dy = obj.end.y - obj.start.y
        ln = math.hypot(dx, dy) or 1
        return (dx/ln, dy/ln)
    elif isinstance(obj, Arc):
        ang = obj.angle_end if at_end else obj.angle_start
        return (-math.sin(ang), math.cos(ang))
    elif isinstance(obj, Clothoid):
        raw = obj.points
        if raw and len(raw) >= 2:
            if at_end:
                dx = raw[-1].x - raw[-2].x
                dy = raw[-1].y - raw[-2].y
            else:
                dx = raw[1].x - raw[0].x
                dy = raw[1].y - raw[0].y
            ln = math.hypot(dx, dy) or 1
            return (dx/ln, dy/ln)
    return (1, 0)


def entry_tangent(obj, connect_at_start: bool):
    """「共有端点→近傍点」方向の単位ベクトルを返す。

    右パネルの [順]/[逆] ラベル表示で `tangent_at`（出口接線）と内積を取る
    入口方向ベクトルを提供する。

    Parameters
    ----------
    obj : Segment or Arc or Clothoid
        対象の図形。
    connect_at_start : bool
        True のとき共有端点が obj の始点側、False のとき終点側。

    Returns
    -------
    tuple[float, float] or None
        単位方向ベクトル (dx, dy)。取得できない場合（Clothoid が無効等）は None。

    Notes
    -----
    - Segment: 共有端点からもう一方の端点への方向
    - Arc: 共有端点から ±0.1° の近傍点への方向
    - Clothoid: points の共有端点の隣の点への方向
    """
    import math
    if isinstance(obj, Segment):
        if connect_at_start:
            dx = obj.end.x - obj.start.x
            dy = obj.end.y - obj.start.y
        else:
            dx = obj.start.x - obj.end.x
            dy = obj.start.y - obj.end.y
        ln = math.hypot(dx, dy) or 1
        return (dx/ln, dy/ln)
    elif isinstance(obj, Arc):
        DELTA = math.radians(0.1)
        if connect_at_start:
            ang0 = obj.angle_start
            ang1 = obj.angle_start + DELTA
        else:
            ang0 = obj.angle_end
            ang1 = obj.angle_end - DELTA
        R  = obj.circle.radius
        cx = obj.circle.center.x
        cy = obj.circle.center.y
        x0 = cx + R * math.cos(ang0); y0 = cy + R * math.sin(ang0)
        x1 = cx + R * math.cos(ang1); y1 = cy + R * math.sin(ang1)
        dx = x1 - x0; dy = y1 - y0
        ln = math.hypot(dx, dy) or 1
        return (dx/ln, dy/ln)
    elif isinstance(obj, Clothoid):
        raw = obj.points
        if not raw or len(raw) < 2:
            return None
        if connect_at_start:
            dx = raw[1].x - raw[0].x
            dy = raw[1].y - raw[0].y
        else:
            dx = raw[-2].x - raw[-1].x
            dy = raw[-2].y - raw[-1].y
        ln = math.hypot(dx, dy) or 1
        return (dx/ln, dy/ln)
    return None


def resolve_chain(elems, element_profiles=None):
    """
    Segment / Arc / Clothoid のリストから (順序付きリスト, reversed_flags) を返す。

    - 共有端点（SNAP_TOL 以内）を検出してチェーンの順序と向きを決定する
    - 既存の ElementProfile に reversed_flag が保存されている場合はそれを優先する
    - element_profiles: Scene.element_profiles のリスト（省略可）
    """
    if not elems:
        return [], []

    eps = element_profiles or []

    if len(elems) == 1:
        ep = next((e for e in eps if e.element_id == elems[0].id), None)
        return list(elems), [ep.reversed_flag if ep else False]

    pts = {id(e): _elem_endpoints(e) for e in elems}

    def connects_to_other(pt, exclude_elem):
        for e in elems:
            if e is exclude_elem:
                continue
            s, ep_ = pts[id(e)]
            if _pt_dist(pt, s) < SNAP_TOL or _pt_dist(pt, ep_) < SNAP_TOL:
                return True
        return False

    # 孤立端点を持つ要素を先頭候補とする
    candidates = []
    for cand in elems:
        s, e = pts[id(cand)]
        s_iso = s is not None and not connects_to_other(s, cand)
        e_iso = e is not None and not connects_to_other(e, cand)
        if s_iso and not e_iso:
            candidates.append((cand, False))   # 正順で先頭
        elif e_iso and not s_iso:
            candidates.append((cand, True))    # 逆順で先頭

    # 既存 ElementProfile の reversed_flag と一致する候補を優先
    if candidates:
        best_first = None
        for cand, cand_rev in candidates:
            ep_ex = next((e for e in eps if e.element_id == cand.id), None)
            saved_rev = ep_ex.reversed_flag if ep_ex else None
            if saved_rev is not None and saved_rev == cand_rev:
                best_first = (cand, cand_rev)
                break
        if best_first is None:
            best_first = candidates[0]
        first, first_rev = best_first
    else:
        first, first_rev = elems[0], False

    # 貪欲にチェーンを構築
    remaining = list(elems)
    chain     = [first]
    rev_flags = [first_rev]
    remaining.remove(first)

    while remaining:
        last_elem = chain[-1]
        last_rev  = rev_flags[-1]
        ls, le    = pts[id(last_elem)]
        cur_end   = le if not last_rev else ls

        best = None; best_rev = False; best_d = float('inf')
        for cand in remaining:
            cs, ce = pts[id(cand)]
            d_fwd = _pt_dist(cur_end, cs)
            d_rev = _pt_dist(cur_end, ce)
            if d_fwd < best_d:
                best_d = d_fwd; best = cand; best_rev = False
            if d_rev < best_d:
                best_d = d_rev; best = cand; best_rev = True

        if best is None or best_d > SNAP_TOL * 10:
            best = remaining[0]; best_rev = False

        chain.append(best)
        rev_flags.append(best_rev)
        remaining.remove(best)

    return chain, rev_flags
