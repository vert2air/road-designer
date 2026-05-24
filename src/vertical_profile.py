"""
縦断線形データモデル

平面線形要素（Segment / Arc / Clothoid）と縦断線形データを橋渡しする
ElementProfile・VerticalAlignment・GradeLine・VerticalCurve と、
ユーティリティ関数 plan_length_of をまとめたモジュール。

plan_length_of は Segment・Arc・Clothoid を型に依らず扱う統一インターフェース。
ElementProfile が平面距離 ↔ 標高の 2 座標系をブリッジし、
VerticalAlignment・GradeLine・VerticalCurve が縦断設計データを保持する。
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from models import new_id, Segment, Arc, Clothoid


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
    id: int = field(default_factory=new_id)
    element_id: int = -1    # 対応する Segment/Arc/Clothoid の id
    element_type: str = ""    # 'segment' | 'arc' | 'clothoid'
    plan_length: float = 0.0   # この要素の平面長 [m]
    reversed_flag: bool = False  # True なら終点→始点の向きで使われている
    elev_start: float = 0.0   # 始端標高 [m]（正順の始点側）
    elev_end: float = 0.0   # 終端標高 [m]（隣接要素と共有）
    grade_lines: list['GradeLine'] = field(default_factory=list)
    vertical_curves: list['VerticalCurve'] = field(default_factory=list)

    def to_dict(self) -> dict:
        """すべてのフィールドを含む辞書に変換する（JSON シリアライズ用）。

        Returns
        -------
        dict
            id・element_id・element_type・plan_length・reversed_flag・
            elev_start・elev_end・grade_lines・vertical_curves をキーとする辞書。
            grade_lines / vertical_curves は各要素の to_dict() リスト。
        """
        return {
            "id": self.id,
            "element_id": self.element_id,
            "element_type": self.element_type,
            "plan_length": self.plan_length,
            "reversed_flag": self.reversed_flag,
            "elev_start": self.elev_start,
            "elev_end": self.elev_end,
            "grade_lines": [g.to_dict() for g in self.grade_lines],
            "vertical_curves": [v.to_dict() for v in self.vertical_curves],
        }

    @staticmethod
    def from_dict(d: dict) -> 'ElementProfile':
        """辞書から ElementProfile を復元する（JSON デシリアライズ用）。

        Parameters
        ----------
        d : dict
            to_dict() が返した辞書、またはそれと互換のマッピング。
            存在しないキーはデフォルト値（id=new_id(), element_id=-1 など）で補完する。

        Returns
        -------
        ElementProfile
            復元されたインスタンス。grade_lines / vertical_curves の各要素も
            GradeLine.from_dict / VerticalCurve.from_dict で復元される。
        """
        ep = ElementProfile()
        ep.id = d.get("id", new_id())
        ep.element_id = d.get("element_id", -1)
        ep.element_type = d.get("element_type", "")
        ep.plan_length = d.get("plan_length", 0.0)
        ep.reversed_flag = d.get("reversed_flag", False)
        ep.elev_start = d.get("elev_start", 0.0)
        ep.elev_end = d.get("elev_end", 0.0)
        ep.grade_lines = [GradeLine.from_dict(g)
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
    """後方互換用の縦断線形データコンテナ。

    旧フォーマットで保存された grade_lines / vertical_curves を読み込むためだけに使う。
    新規データは ElementProfile を使う。

    Attributes
    ----------
    id : int
        グローバルユニーク ID。
    nickname : str
        ユーザーが付けた任意の名前。
    grade_lines : list[GradeLine]
        勾配直線のリスト。
    vertical_curves : list[VerticalCurve]
        縦断曲線のリスト。
    """
    id: int = field(default_factory=new_id)
    nickname: str = ""
    grade_lines: list['GradeLine'] = field(default_factory=list)
    vertical_curves: list['VerticalCurve'] = field(default_factory=list)

    def to_dict(self) -> dict:
        """すべてのフィールドを含む辞書に変換する（JSON シリアライズ用）。

        Returns
        -------
        dict
            id・nickname・grade_lines・vertical_curves をキーとする辞書。
            grade_lines / vertical_curves は各要素の to_dict() リスト。
        """
        return {
            "id": self.id,
            "nickname": self.nickname,
            "grade_lines": [g.to_dict() for g in self.grade_lines],
            "vertical_curves": [v.to_dict() for v in self.vertical_curves],
        }

    @staticmethod
    def from_dict(d: dict) -> 'VerticalAlignment':
        """辞書から VerticalAlignment を復元する（JSON デシリアライズ用）。

        Parameters
        ----------
        d : dict
            to_dict() が返した辞書、またはそれと互換のマッピング。
            存在しないキーはデフォルト値（id=new_id(), nickname='', リスト=[]）で補完する。

        Returns
        -------
        VerticalAlignment
            復元されたインスタンス。
        """
        va = VerticalAlignment()
        va.id = d.get("id", new_id())
        va.nickname = d.get("nickname", "")
        va.grade_lines = [GradeLine.from_dict(g)
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
    dist_end: float = 100.0
    elev_end: float = 0.0
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

    def to_dict(self) -> dict:
        """数値フィールドを含む辞書に変換する（JSON シリアライズ用）。

        next_curve / prev_curve はメモリ上の参照のみで保存対象外。

        Returns
        -------
        dict
            id・dist_start・elev_start・dist_end・elev_end をキーとする辞書。
        """
        return {"id": self.id,
                "dist_start": self.dist_start, "elev_start": self.elev_start,
                "dist_end": self.dist_end, "elev_end": self.elev_end}

    @staticmethod
    def from_dict(d: dict) -> 'GradeLine':
        """辞書から GradeLine を復元する（JSON デシリアライズ用）。

        Parameters
        ----------
        d : dict
            to_dict() が返した辞書。id・dist_start・elev_start・
            dist_end・elev_end キーが必須。

        Returns
        -------
        GradeLine
            復元されたインスタンス。next_curve / prev_curve は None のまま。
        """
        g = GradeLine()
        g.id = d["id"]
        g.dist_start = d["dist_start"]
        g.elev_start = d["elev_start"]
        g.dist_end = d["dist_end"]
        g.elev_end = d["elev_end"]
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
        return (self.vpc_elev + self.g1 / 100 * x
                + (self.g2 - self.g1) / (2 * self.length) / 100 * x ** 2)

    def to_dict(self) -> dict:
        """すべてのフィールドを含む辞書に変換する（JSON シリアライズ用）。

        Returns
        -------
        dict
            id・pvi_dist・pvi_elev・g1・g2・length・prev_line_id・
            next_line_id をキーとする辞書。
        """
        return {
            "id": self.id, "pvi_dist": self.pvi_dist,
            "pvi_elev": self.pvi_elev,
            "g1": self.g1, "g2": self.g2, "length": self.length,
            "prev_line_id": self.prev_line_id,
            "next_line_id": self.next_line_id}

    @staticmethod
    def from_dict(d: dict) -> 'VerticalCurve':
        """辞書から VerticalCurve を復元する（JSON デシリアライズ用）。

        Parameters
        ----------
        d : dict
            to_dict() が返した辞書。辞書のキーをそのままインスタンス属性に
            setattr で書き込む。存在しないキーはデフォルト値のまま残る。

        Returns
        -------
        VerticalCurve
            復元されたインスタンス。
        """
        v = VerticalCurve()
        for k in d:
            setattr(v, k, d[k])
        return v


def make_empty_profile() -> 'ElementProfile':
    """空の ElementProfile を生成するファクトリ関数。

    選択なしで縦断線形ウィンドウを開いたとき等、
    平面線形要素と対応しないプロファイルが必要な場合に使う。

    Returns
    -------
    ElementProfile
        すべてのフィールドがデフォルト値（element_id=-1、plan_length=0.0 など）の
        新規インスタンス。
    """
    return ElementProfile()
