"""
road_viewer.py  ―  Panda3D による道路 3D 走行ビューア

平面線形（Segment / Arc / Clothoid）と縦断線形（ElementProfile）から
3D 中心線を生成し、道路メッシュを表示して車が走る。

座標系変換:
  設計アプリ  (x右, y上, ワールド) → Panda3D (x右, y奥, z上)
  変換: P3D.x = world.x,  P3D.y = world.y,  P3D.z = height

メッシュ生成関数は ``_road_mesh`` モジュールに分離されている。
"""
from __future__ import annotations
import math
import sys
import json
import logging

# ─── Panda3D ──────────────────────────────────────────────────
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    LPoint3, LColor,
    AmbientLight, DirectionalLight,
    TextNode, LineSegs,
)
from direct.task import Task
from direct.gui.OnscreenText import OnscreenText

# ─── 設計モデル ────────────────────────────────────────────────
sys.path.insert(0, ".")
from models import (  # noqa: E402
    Scene, Segment, Arc, Clothoid, ElementProfile,
    plan_length_of,
)

# ─── メッシュ生成ユーティリティ（backward-compat re-export 含む）─
from _road_mesh import (  # noqa: E402
    build_centerline, build_road_mesh, build_car_box,
    build_center_line_node, build_piers, build_road_markings,
    build_ground, _elem_endpoints_xy,
)


def _elem_fwd_vec(elem: dict, forward: bool) -> tuple[float, float]:
    """要素グラフノード `elem` を `forward` 方向に走行したときの先頭接線ベクトルを返す。

    `points_xy` が存在する場合は点列端から、なければ start/end キーから接線を計算し
    単位ベクトルに正規化して返す。

    Parameters
    ----------
    elem : dict
        `_elem_graph` のノード辞書（"points_xy", "start", "end" キーを持つ）。
    forward : bool
        True のとき始点→終点方向、False のとき終点→始点方向。

    Returns
    -------
    tuple[float, float]
        進行方向の単位ベクトル (dx, dy)。
    """
    pts = elem.get("points_xy") or []
    if len(pts) >= 2:
        p0, p1 = (pts[0], pts[1]) if forward else (pts[-1], pts[-2])
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    else:
        sx, sy = elem["start"]
        ex, ey = elem["end"]
        dx, dy = (ex - sx, ey - sy) if forward else (sx - ex, sy - ey)
    ln = math.hypot(dx, dy) or 1.0
    return dx / ln, dy / ln


# ─── 純粋ロジック関数（Panda3D 不要・単体テスト可能）─────────────────

def interp_cl(cl: list, dist: float):
    """任意の中心線 cl 上の累積距離 dist に対応する位置・方向を線形補間して返す。

    Parameters
    ----------
    cl : list[tuple]
        中心線点列 ``[(x, y, z, dist), ...]``。
    dist : float
        累積距離 [m]。cl の範囲外のとき末端の位置と ``(1, 0, 0)`` 方向を返す。

    Returns
    -------
    tuple[tuple, tuple, tuple]
        * pos (x, y, z): ワールド座標
        * fwd (dx, dy, dz): 進行方向の単位ベクトル
        * right (rx, ry, rz): 右方向の単位ベクトル（fwd の xy 平面直交）
    """
    n = len(cl)
    if n == 0:
        return (0, 0, 0), (1, 0, 0), (0, -1, 0)
    for i in range(n - 1):
        d0 = cl[i][3]
        d1 = cl[i + 1][3]
        if d0 <= dist <= d1:
            t = (dist - d0) / (d1 - d0) if d1 > d0 else 0
            x = cl[i][0] + (cl[i + 1][0] - cl[i][0]) * t
            y = cl[i][1] + (cl[i + 1][1] - cl[i][1]) * t
            z = cl[i][2] + (cl[i + 1][2] - cl[i][2]) * t
            dx = cl[i + 1][0] - cl[i][0]
            dy = cl[i + 1][1] - cl[i][1]
            dz = cl[i + 1][2] - cl[i][2]
            ln = math.hypot(dx, dy, dz) or 1
            fwd = (dx / ln, dy / ln, dz / ln)
            right = (fwd[1], -fwd[0], 0)
            return (x, y, z), fwd, right
    x, y, z, _ = cl[-1]
    return (x, y, z), (1, 0, 0), (0, -1, 0)


def bearing_str(fwd_x: float, fwd_y: float) -> str:
    """進行方向ベクトル (fwd_x, fwd_y) を 8 方位文字列に変換する。

    座標系: x=東, y=北（設計アプリのワールド座標系に準拠）。

    Parameters
    ----------
    fwd_x, fwd_y : float
        進行方向の単位ベクトル。

    Returns
    -------
    str
        ``"N"`` / ``"NE"`` / ``"E"`` / ``"SE"`` / ``"S"`` / ``"SW"`` /
        ``"W"`` / ``"NW"`` のいずれか。
    """
    deg = math.degrees(math.atan2(fwd_y, fwd_x))
    brg = (90.0 - deg) % 360.0
    idx = int((brg + 22.5) / 45.0) % 8
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][idx]


def make_elem_cl(elem: dict, forward: bool):
    """要素辞書から 3D 中心線を生成して ``(cl, total)`` を返す。

    Parameters
    ----------
    elem : dict
        ``elem_graph`` のノード辞書
        （``plan_length``, ``heights``, ``points_xy``, ``start``, ``end`` キー）。
    forward : bool
        True のとき正順（start→end）、False のとき逆順（end→start）で生成する。

    Returns
    -------
    tuple[list[tuple], float]
        ``(cl, total)``。cl は ``[(x, y, z, dist), ...]``、total は計画延長 [m]。
    """
    pl = elem["plan_length"]
    heights = elem.get("heights", [[0.0, 0.0], [pl, 0.0]])
    pts_xy = elem.get("points_xy", None)
    if not forward:
        if pts_xy:
            pts_xy = list(reversed(pts_xy))
        heights = [[pl - h[0], h[1]] for h in reversed(heights)]

    def _elev(d):
        if not heights:
            return 0.0
        if d <= heights[0][0]:
            return heights[0][1]
        for k in range(len(heights) - 1):
            d0, z0 = heights[k]
            d1, z1 = heights[k + 1]
            if d0 <= d <= d1:
                t = (d - d0) / (d1 - d0) if d1 > d0 else 0
                return z0 + (z1 - z0) * t
        return heights[-1][1]

    new_cl = []
    if pts_xy and len(pts_xy) >= 2:
        cum = [0.0]
        for k in range(1, len(pts_xy)):
            dx = pts_xy[k][0] - pts_xy[k - 1][0]
            dy = pts_xy[k][1] - pts_xy[k - 1][1]
            cum.append(cum[-1] + math.hypot(dx, dy))
        total = cum[-1]
        scale = pl / total if total > 1e-9 else 1.0
        for k, (xy, cd) in enumerate(zip(pts_xy, cum)):
            d = cd * scale
            new_cl.append((xy[0], xy[1], _elev(d), d))
    else:
        sx, sy = elem["start"] if forward else elem["end"]
        ex, ey = elem["end"] if forward else elem["start"]
        n = max(2, int(pl * 0.5))
        for i in range(n + 1):
            t = i / n
            d = pl * t
            new_cl.append((sx + (ex - sx) * t, sy +
                          (ey - sy) * t, _elev(d), d))
    return new_cl, pl


def find_next_candidates(elem_graph: list, cur_id, ex: float, ey: float,
                         exit_clo_ref, ad_tol: float = 1.0) -> list:
    """隣接する走行候補要素を検索して ``[(elem, forward), ...]`` を返す。

    ``exit_clo_ref`` がある場合は Clothoid 接点の clothoid_id/side が一致する
    要素を最優先で返す。ない場合は末端座標からの距離が ``ad_tol`` 以内の要素を返す。

    Parameters
    ----------
    elem_graph : list[dict]
        全要素グラフ。
    cur_id : int or None
        現在走行中の要素 ID（候補から除外）。
    ex, ey : float
        現在チェーン末端のワールド座標。
    exit_clo_ref : dict or None
        現在要素末端の Clothoid 接点参照
        ``{"clothoid_id": int, "side": "line"|"circle"}`` 形式。
    ad_tol : float
        隣接判定の距離閾値 [m]（デフォルト 1.0 m）。

    Returns
    -------
    list[tuple[dict, bool]]
        ``(elem, forward)`` のタプルリスト。forward=True は正順走行。
    """
    cands = []
    for elem in elem_graph:
        if elem["id"] == cur_id:
            continue
        sx, sy = elem["start"]
        ex2, ey2 = elem["end"]
        s_ref = elem.get("start_clo_ref")
        e_ref = elem.get("end_clo_ref")
        if exit_clo_ref is not None:
            cid = exit_clo_ref["clothoid_id"]
            side = exit_clo_ref["side"]
            if s_ref and s_ref["clothoid_id"] == cid and s_ref["side"] == side:
                cands.append((elem, True))
                continue
            if e_ref and e_ref["clothoid_id"] == cid and e_ref["side"] == side:
                cands.append((elem, False))
                continue
        else:
            if math.hypot(ex - sx, ey - sy) < ad_tol:
                cands.append((elem, True))
            elif math.hypot(ex - ex2, ey - ey2) < ad_tol:
                cands.append((elem, False))
    return cands


class RoadViewer(ShowBase):
    """Panda3D による道路 3D 走行ビューア。

    平面線形チェーンの 3D 中心線上を車が自動走行する。
    オートドライブモード（``_auto_drive=True``）では ``elem_graph`` を参照して
    交差点をランダムに選択しながら走行を継続する。
    ワープ境界（WARP_BOUNDARY）を超えたとき、パックマン式のトーラス空間ワープで
    対向端にテレポートして同方向に走行を続ける。

    周囲車両（トラフィック）は自車と同じ elem_graph を走り、ランダムな速度係数で
    個別に動く（``_traffic`` リスト）。

    Attributes
    ----------
    cl : list[tuple]
        走行チェーンの初期 3D 中心線 [(x, y, z, dist), ...]。
    speed : float
        走行速度 [m/s]。
    view_mode : str
        カメラモード。"follow"（追従）/ "onboard"（運転席）/
        "overview"（追従俯瞰）/ "overview_fixed"（固定俯瞰）。
    paused : bool
        True のとき走行を一時停止する。
    WARP_BOUNDARY : float
        ワープ境界距離 [m]。|x| または |y| がこの値を超えたらワープする。
    """
    SPEED_DEFAULT = 30.0   # m/s
    CAM_BEHIND = 20.0   # 外部視点: 後方距離
    CAM_ABOVE = 6.0    # 外部視点: 高さ
    CAM_EYE_H = 1.5    # 車載視点: 目の高さ
    CAM_OVERVIEW_H = 500.0  # 俯瞰視点: 高度 [m]

    #: ワープ境界 [m]。|x| または |y| がこの値を超えたら符号を反転してワープ
    WARP_BOUNDARY = 500.0

    #: ホイールベース [m]。タイヤ切れ角 = WHEELBASE × 曲率
    WHEELBASE = 2.7
    #: ステアリングギア比。表示上の回転角 = タイヤ切れ角 × この値
    STEER_DISPLAY_RATIO = 14.0

    def __init__(self, centerline: list[tuple],
                 display_segs: list[list[tuple]] = None,
                 elem_graph: list[dict] = None,
                 start_info: dict = None,
                 warp_boundary: float = None):
        """
        Parameters
        ----------
        centerline : list[tuple]
            走行チェーンの 3D 中心線点列 [(x,y,z,dist), ...]。
        display_segs : list[list[tuple]], optional
            背景表示用の中心線セグメント群。
        elem_graph : list[dict], optional
            オートドライブ用の全要素グラフ。各要素は
            {id, type, start:[x,y], end:[x,y], plan_length} の辞書。
        start_info : dict, optional
            走行開始要素の情報 {id, forward}。
        warp_boundary : float, optional
            ワープ境界距離 [m]。None のとき WARP_BOUNDARY クラス定数を使う。
        """
        ShowBase.__init__(self)
        self.cl = centerline
        self.disp_segs = display_segs or []
        self.dist = 0.0
        self.speed = self.SPEED_DEFAULT
        self.view_mode = "follow"
        # 固定俯瞰視点のカメラ位置（overview_fixed モードで使用）
        self._overview_pos = (0.0, 0.0)  # (x, y) ワールド座標
        self._pan_prev_mouse = None       # パン操作の前フレームマウス位置
        self.paused = False
        self._total = centerline[-1][3] if centerline else 0.0
        self._auto_drive = (elem_graph is not None)  # True: オートドライブモード
        self._elem_graph = elem_graph or []
        self._start_info = start_info
        self._warp_boundary = (
            warp_boundary if warp_boundary is not None
            else self.WARP_BOUNDARY)

        # オートドライブ状態
        self._ad_cur_id = start_info["id"] if start_info else None
        self._ad_forward = start_info["forward"] if start_info else True
        self._ad_cl = centerline             # 現在走行中の中心線
        self._ad_total = self._total
        self._ad_dist = 0.0                    # 現在のチェーン内距離

        # ── 周囲車両（トラフィック）──────────────────────────
        #: 初期台数（自車の前後それぞれ N 台）
        self.TRAFFIC_EACH = 5
        #: 初期車間距離 [m]
        self.TRAFFIC_GAP = 20.0
        self._traffic: list = []

        self._build_scene()
        self._setup_hud()
        self._setup_lighting()
        self.taskMgr.add(self._move_task, "move")
        self._setup_keys()

        # HUD 用の現在位置・方向（最初のフレームまでは (0,0,0), (1,0,0)）
        self._cur_pos = (0.0, 0.0, 0.0)
        self._cur_fwd = (1.0, 0.0, 0.0)
        # 現在位置の符号付き曲率 [1/m]（左曲がり正）
        self._cur_kappa = 0.0

        # 走行履歴スタック（← で最大 _AD_HISTORY_MAX 要素分戻れる）
        # 各エントリ: {"cl": [...], "total": float, "dist": float,
        #              "cur_id": int, "forward": bool}
        self._AD_HISTORY_MAX = 10
        self._ad_history: list = []   # インデックス0が最古
        self._ad_history_idx = -1     # -1: 最新（リアルタイム走行中）

        # マウス無効化（デフォルトのカメラ操作を切る）
        self.disableMouse()

    # ─── シーン構築 ──────────────────────────────────────────
    HALF_WIDTH = 1.75   # 道路半幅 [m]（全幅3.5mの半分）
    ROAD_SURFACE = True   # 路面表示の初期状態

    def _build_scene(self):
        """3D シーンを構築する。

        背景要素（``disp_segs``）と走行チェーン（``cl``）それぞれについて
        道路メッシュ・中心線・白線・橋脚を生成して render に追加する。
        全要素の重心を中心とした地面平板も追加する。
        最後に自車直方体と周囲車両を初期配置する。
        """
        self._surface_nodes = []   # 路面メッシュノードのリスト（on/off用）

        # 全要素の背景道路メッシュ（要素ごとに独立して生成）
        for seg_cl in self.disp_segs:
            if len(seg_cl) < 2:
                continue
            bg_node = build_road_mesh(
                seg_cl, half_width=self.HALF_WIDTH,
                color_override=LColor(0.28, 0.28, 0.28, 1))
            np = self.render.attachNewNode(bg_node)
            np.set_light_off()
            np.set_two_sided(True)   # 両面描画
            self._surface_nodes.append(np)
            bg_cl = build_center_line_node(
                seg_cl,
                color_override=LColor(0.5, 0.5, 0.5, 1))
            self.render.attachNewNode(bg_cl)
            self.render.attachNewNode(
                build_road_markings(seg_cl, self.HALF_WIDTH))
            self.render.attachNewNode(build_piers(seg_cl, self.HALF_WIDTH))

        # 走行チェーンの道路メッシュ
        road_np = self.render.attachNewNode(
            build_road_mesh(self.cl, half_width=self.HALF_WIDTH,
                            color_override=LColor(0.38, 0.38, 0.38, 1)))
        road_np.set_light_off()
        road_np.set_two_sided(True)   # 両面描画
        self._surface_nodes.append(road_np)
        self.render.attachNewNode(build_center_line_node(
            self.cl, color_override=LColor(1.0, 0.9, 0.1, 1)))
        self.render.attachNewNode(
            build_road_markings(self.cl, self.HALF_WIDTH))
        self.render.attachNewNode(build_piers(self.cl, self.HALF_WIDTH))

        # 初期状態を反映
        self._apply_surface_visible(self.ROAD_SURFACE)

        # 地面
        all_pts = []
        for seg in self.disp_segs:
            all_pts.extend(seg)
        all_pts.extend(self.cl)
        if not all_pts:
            all_pts = self.cl
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        self.render.attachNewNode(build_ground(cx, cy))

        # 自車（直方体）
        self.car_np = self.render.attachNewNode("car")
        ego_box = self.car_np.attachNewNode(build_car_box(4.0, 2.0, 1.5))
        ego_box.setLightOff()
        self._update_car_pose(0.0)

        # 周囲車両を初期化
        self._init_traffic()

    # ─── 周囲車両（トラフィック）────────────────────────────────

    def _init_traffic(self):
        """周囲車両を初期配置する。

        自車が最後尾となり、前方に「選択した道路の長さ ÷ TRAFFIC_GAP」台を
        ``TRAFFIC_GAP`` [m] 間隔で一列に並べる。

        配置イメージ（進行方向 →）:
          [先頭] ... [car2] [car1] [自車（最後尾）]
        """
        if not self._elem_graph:
            return

        # 選択した走行チェーンの総延長から台数を決定
        road_length = self._total if self._total > 0 else self.TRAFFIC_GAP
        total = max(1, int(road_length / self.TRAFFIC_GAP))

        for k in range(total, 0, -1):
            # k=total が先頭（最も前）、k=1 が自車の直前
            self._add_traffic_car(offset=self.TRAFFIC_GAP * k)

    def _add_traffic_car(self, offset: float = 0.0):
        """周囲車両を 1 台追加する。

        ``offset`` は自車チェーン上の距離オフセット [m]（正=前方、負=後方）。
        オフセット先の要素・距離を elem_graph から解決し、初期状態を設定する。

        Parameters
        ----------
        offset : float
            自車からの初期距離オフセット [m]。
        """
        import random

        # NodePath 生成
        np_root = self.render.attachNewNode(f"traffic_{len(self._traffic)}")
        box = np_root.attachNewNode(build_car_box(4.0, 2.0, 1.5))
        box.setLightOff()
        box.setColorScale(0.4, 0.7, 1.0, 1.0)

        # 初期位置: 自車チェーンをオフセットした位置から出発
        cur_cl = list(self._ad_cl)
        cur_total = self._ad_total
        cur_id = self._ad_cur_id
        cur_fwd = self._ad_forward
        init_dist = self._ad_dist + offset

        # オフセットが正のとき: チェーンを進む
        while init_dist > cur_total and cur_total > 0:
            overflow = init_dist - cur_total
            cur_cl, cur_total, cur_id, cur_fwd, init_dist = \
                self._chain_advance_fwd(cur_cl, cur_id, cur_fwd, overflow)
            if cur_id is None:   # ワープ済み
                break

        # オフセットが負のとき: チェーンを逆に辿る
        while init_dist < 0 and cur_total > 0:
            # 逆方向に走行していた要素を探す（簡易: 現在チェーンを反転）
            # 現在チェーンの先頭座標
            sx, sy = cur_cl[0][0], cur_cl[0][1]
            if len(cur_cl) >= 2:
                dx = cur_cl[0][0] - cur_cl[1][0]
                dy = cur_cl[0][1] - cur_cl[1][1]
                ln2 = math.hypot(dx, dy) or 1.0
                rfwd_x, rfwd_y = dx / ln2, dy / ln2
            else:
                rfwd_x, rfwd_y = -1.0, 0.0

            cur_elem = next(
                (e for e in self._elem_graph if e["id"] == cur_id), None)
            exit_clo_ref = None
            if cur_elem:
                exit_clo_ref = cur_elem.get(
                    "start_clo_ref" if cur_fwd else "end_clo_ref")

            cands = self._find_next_candidates(cur_id, sx, sy, exit_clo_ref)
            cands = [
                (e, f) for e, f in cands
                if (rfwd_x * _elem_fwd_vec(e, f)[0]
                    + rfwd_y * _elem_fwd_vec(e, f)[1] >= 0)]
            if not cands:
                break

            chosen_elem, chosen_fwd = random.choice(cands)
            cl2, total2 = self._make_elem_cl(chosen_elem, chosen_fwd)
            cur_cl = cl2
            cur_total = total2
            cur_id = chosen_elem["id"]
            cur_fwd = chosen_fwd
            init_dist = total2 + init_dist  # total2 - need

        init_dist = max(0.0, min(init_dist, cur_total))

        car_state = {
            "np": np_root,
            "cl": cur_cl,
            "total": cur_total,
            "dist": init_dist,
            "cur_id": cur_id,
            "forward": cur_fwd,
            "speed_mul": random.uniform(0.7, 1.3),  # 個別速度係数（±30%）
        }
        self._traffic.append(car_state)
        # 初期位置にセット
        self._update_traffic_car_pose(car_state)

    def _find_next_candidates(self, cur_id, ex, ey, exit_clo_ref):
        """モジュールレベルの :func:`find_next_candidates` に委譲する。"""
        return find_next_candidates(
            self._elem_graph, cur_id, ex, ey, exit_clo_ref, self.AD_TOL)

    def _chain_advance_fwd(
            self, cur_cl: list, cur_id, cur_fwd: bool,
            overflow: float) -> tuple:
        """チェーン末端から次の要素に前進遷移する共通ロジック。

        ``_step_traffic_car`` と ``_add_traffic_car`` の前進ループで使う。
        候補が見つかればランダムに選択して遷移し、なければワープする。

        Parameters
        ----------
        cur_cl : list
            現在の中心線点列 [(x, y, z, dist), ...]。
        cur_id : int or None
            現在要素の ID。
        cur_fwd : bool
            現在の走行方向（True=正順）。
        overflow : float
            チェーン末端を超えた余剰距離 [m]。

        Returns
        -------
        tuple
            ``(new_cl, new_total, new_cur_id, new_fwd, new_dist)``。
            ワープ時は ``new_cur_id=None``。
        """
        import random

        end_pt = cur_cl[-1]
        ex, ey = end_pt[0], end_pt[1]
        if len(cur_cl) >= 2:
            dx = cur_cl[-1][0] - cur_cl[-2][0]
            dy = cur_cl[-1][1] - cur_cl[-2][1]
            ln = math.hypot(dx, dy) or 1.0
            fwd_x, fwd_y = dx / ln, dy / ln
        else:
            fwd_x, fwd_y = 1.0, 0.0

        cur_elem = next(
            (e for e in self._elem_graph if e["id"] == cur_id), None)
        exit_clo_ref = None
        if cur_elem:
            key = "end_clo_ref" if cur_fwd else "start_clo_ref"
            exit_clo_ref = cur_elem.get(key)

        cands = self._find_next_candidates(cur_id, ex, ey, exit_clo_ref)
        cands = [(e, f) for e, f in cands
                 if fwd_x * _elem_fwd_vec(e, f)[0]
                 + fwd_y * _elem_fwd_vec(e, f)[1] >= 0]

        if cands:
            chosen_elem, chosen_fwd = random.choice(cands)
            cl2, total2 = self._make_elem_cl(chosen_elem, chosen_fwd)
            return (cl2, total2, chosen_elem["id"],
                    chosen_fwd, min(overflow, total2))

        # 候補なし → ワープ
        B = self._warp_boundary
        new_x = -ex if abs(ex) > B else ex
        new_y = -ey if abs(ey) > B else ey
        z_end = cur_cl[-1][2]
        pl = 100.0
        n = 50
        warp_cl = [
            (new_x + fwd_x * pl * t / n,
             new_y + fwd_y * pl * t / n,
             z_end, pl * t / n)
            for t in range(n + 1)]
        return warp_cl, pl, None, cur_fwd, min(overflow, pl)

    def _make_elem_cl(self, elem, forward):
        """モジュールレベルの :func:`make_elem_cl` に委譲する。"""
        return make_elem_cl(elem, forward)

    def _update_traffic_car_pose(self, car: dict):
        """周囲車両 1 台の NodePath の位置・姿勢を更新する。

        :meth:`_interp_cl` でチェーン上の位置・方向を求め、
        Panda3D の座標系（heading/pitch/roll）に変換して setHpr する。

        Parameters
        ----------
        car : dict
            ``_traffic`` リストの要素。"np"・"cl"・"dist" キーを使う。
        """
        pos, fwd, _ = self._interp_cl(car["cl"], car["dist"])
        np_root = car["np"]
        np_root.setPos(pos[0], pos[1], pos[2])
        heading = math.degrees(math.atan2(-fwd[0], fwd[1]))
        pitch = math.degrees(math.atan2(fwd[2], math.hypot(fwd[0], fwd[1])))
        np_root.setHpr(heading, pitch, 0)

    def _step_traffic_car(self, car: dict, dt: float):
        """周囲車両 1 台を 1 フレーム分進める。

        チェーン末端を超えたとき :meth:`_find_next_candidates` で次の要素を探し、
        候補があればランダムに選択して :meth:`_make_elem_cl` で新しい中心線を生成する。
        候補がない場合はワープ処理を行う。

        Parameters
        ----------
        car : dict
            ``_traffic`` リストの要素。
        dt : float
            フレーム経過時間 [s]。
        """
        car["dist"] += self.speed * car.get("speed_mul", 1.0) * dt
        if car["dist"] < car["total"]:
            return

        overflow = car["dist"] - car["total"]
        cl, total, cid, fwd, dist = self._chain_advance_fwd(
            car["cl"], car["cur_id"], car["forward"], overflow)
        car["cl"] = cl
        car["total"] = total
        car["cur_id"] = cid
        car["forward"] = fwd
        car["dist"] = dist

    def _overview_pan(self):
        """固定俯瞰モードでのマウスパン・ホイールズーム処理。

        右ボタンまたは中ボタンのドラッグで _overview_pos を移動する。
        ホイールはキーでズームする（P/M と同様に overview 高度を変更）。
        """
        try:
            mwn = self.mouseWatcherNode
            if not mwn.hasMouse():
                self._pan_prev_mouse = None
                return

            mx = mwn.getMouseX()
            my = mwn.getMouseY()

            from panda3d.core import MouseButton
            right_down = mwn.isButtonDown(MouseButton.two())
            middle_down = mwn.isButtonDown(MouseButton.three())

            if not (right_down or middle_down):
                self._pan_prev_mouse = None
                return

            if self._pan_prev_mouse is None:
                self._pan_prev_mouse = (mx, my)
                return

            px, py = self._pan_prev_mouse
            dx = mx - px
            dy = my - py
            self._pan_prev_mouse = (mx, my)

            # マウス移動量をワールド座標の移動量に変換
            scale = self.CAM_OVERVIEW_H * 0.8
            ox, oy = self._overview_pos
            self._overview_pos = (ox - dx * scale, oy + dy * scale)
        except Exception as e:
            logging.warning("_overview_pan error: %s", e)
            self._pan_prev_mouse = None

    def _overview_zoom_in(self):
        """俯瞰視点でカメラを近づける（I キー）。"""
        if self.view_mode in ("overview", "overview_fixed"):
            self.CAM_OVERVIEW_H = max(10.0, self.CAM_OVERVIEW_H * 0.8)

    def _overview_zoom_out(self):
        """俯瞰視点でカメラを遠ざける（K キー）。"""
        if self.view_mode in ("overview", "overview_fixed"):
            self.CAM_OVERVIEW_H = min(5000.0, self.CAM_OVERVIEW_H * 1.25)

    def _add_one_traffic(self):
        """周囲車両を 1 台追加する。

        自車の進行方向に沿って、現在いる全車両の中で最も前にいる車の
        さらに TRAFFIC_GAP [m] 前に配置する。
        車両がいない場合は自車から TRAFFIC_GAP [m] 前に配置する。
        """
        # 自車の現在位置・方向
        cur_cl = self._ad_cl if self._auto_drive else self.cl
        cur_dist = self._ad_dist if self._auto_drive else self.dist
        ego_pos, ego_fwd, _ = self._interp_cl(cur_cl, cur_dist)
        ex, ey = ego_pos[0], ego_pos[1]
        fx, fy = ego_fwd[0], ego_fwd[1]

        # 自車前方にいる各車両の「自車からの前方距離」を計算
        # 内積が正 = 前方
        max_forward_dist = 0.0   # 自車基準の前方距離（負なら後方）
        for car in self._traffic:
            pos, _, _ = self._interp_cl(car["cl"], car["dist"])
            dx = pos[0] - ex
            dy = pos[1] - ey
            dot = dx * fx + dy * fy   # 前方が正
            if dot > max_forward_dist:
                max_forward_dist = dot

        # 最前列から TRAFFIC_GAP 前に追加（車両がいなければ自車から TRAFFIC_GAP 前）
        new_offset = max_forward_dist + self.TRAFFIC_GAP
        self._add_traffic_car(offset=new_offset)

    def _remove_one_traffic(self):
        """周囲車両を 1 台削除する（末尾）。"""
        if self._traffic:
            car = self._traffic.pop()
            car["np"].removeNode()

    def _apply_surface_visible(self, visible: bool):
        """路面メッシュノードの表示/非表示を一括切り替える。

        Parameters
        ----------
        visible : bool
            True のとき show()、False のとき hide() を呼ぶ。
        """
        for np in self._surface_nodes:
            if visible:
                np.show()
            else:
                np.hide()

    def _toggle_surface(self):
        """R キーで路面メッシュの表示/非表示を切り替える。"""
        self.ROAD_SURFACE = not self.ROAD_SURFACE
        self._apply_surface_visible(self.ROAD_SURFACE)

    def _setup_lighting(self):
        """環境光と平行光（太陽光）をシーンに設定する。

        環境光: 明度 0.45 のグレー（全方向一様照明）。
        平行光: 明度 0.85 のやや暖色（HPR=45/-45/0 の斜め上方から照射）。
        """
        alight = AmbientLight("ambient")
        alight.set_color(LColor(0.45, 0.45, 0.45, 1))
        self.render.set_light(self.render.attachNewNode(alight))

        dlight = DirectionalLight("sun")
        dlight.set_color(LColor(0.85, 0.85, 0.75, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.set_hpr(45, -45, 0)
        self.render.set_light(dlnp)

    def _setup_hud(self):
        """速度・距離・方位などを表示する HUD テキストを初期化する。

        ``OnscreenText`` を左上に配置し、``_update_hud`` でフレームごとに更新する。
        ステアリングホイールグラフィックは :meth:`_setup_steering_wheel` で別途作成。
        """
        self.hud = OnscreenText(
            text="", pos=(-1.3, 0.9), scale=0.05,
            fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ALeft, mayChange=True)
        self._setup_steering_wheel()

    def _setup_steering_wheel(self):
        """ステアリングホイールグラフィックを右下 HUD に作成する。

        ``LineSegs`` で描いたリム・スポーク・ハブを ``aspect2d`` に配置し、
        ``_steer_np`` ノードパスを毎フレーム ``set_r()`` で回転させることで
        ハンドルの切れ角を視覚的に表示する。

        * リム : 白い円（32 分割）
        * スポーク : 上（黄）・左下（白）・右下（白）の 3 本
        * ハブ : 小円
        * 固定マーカー : 12 時位置を示す黄色三角（回転しない）
        * ラベル : ホイール下に回転角・タイヤ切れ角テキスト
        """
        RADIUS = 0.10   # リム半径 [aspect2d 座標]
        HUB_R = 0.018   # ハブ半径
        # ホイール中心の aspect2d 座標（右下）
        WX, WZ = 1.1, -0.78

        ls = LineSegs()
        ls.set_thickness(2.0)

        # ── リム（白） ──
        ls.set_color(0.9, 0.9, 0.9, 1.0)
        N = 32
        for i in range(N + 1):
            a = 2 * math.pi * i / N
            x = RADIUS * math.cos(a)
            z = RADIUS * math.sin(a)
            if i == 0:
                ls.move_to(x, 0, z)
            else:
                ls.draw_to(x, 0, z)

        # ── 左下・右下スポーク（白・細） ──
        for deg in (210, 330):
            a = math.radians(deg)
            ls.set_color(0.9, 0.9, 0.9, 1.0)
            ls.move_to(
                HUB_R * math.cos(a), 0,
                HUB_R * math.sin(a))
            ls.draw_to(
                RADIUS * math.cos(a), 0,
                RADIUS * math.sin(a))

        # ── ハブ（白） ──
        ls.set_color(0.9, 0.9, 0.9, 1.0)
        for i in range(13):
            a = 2 * math.pi * i / 12
            x = HUB_R * math.cos(a)
            z = HUB_R * math.sin(a)
            if i == 0:
                ls.move_to(x, 0, z)
            else:
                ls.draw_to(x, 0, z)

        node = ls.create()
        self._steer_np = self.aspect2d.attach_new_node(node)
        self._steer_np.set_pos(WX, 0, WZ)

        # ── 12 時スポーク（黒・太）別 LineSegs で太さを独立設定 ──
        ls12 = LineSegs()
        ls12.set_thickness(15.0)
        ls12.set_color(0.0, 0.0, 0.0, 1.0)
        a12 = math.radians(90)
        ls12.move_to(
            HUB_R * math.cos(a12), 0,
            HUB_R * math.sin(a12))
        ls12.draw_to(
            RADIUS * math.cos(a12), 0,
            RADIUS * math.sin(a12))
        # _steer_np の子にすることでホイールと一緒に回転する
        self._steer_np.attach_new_node(ls12.create())

        # ── 固定マーカー（12 時を示す下向き三角、回転しない） ──
        # リム外側 + 少し余白の位置に先端、上方向に底辺
        MR = RADIUS + 0.014   # 先端のリムからの距離
        HW = 0.011            # 三角の半幅
        MH = 0.020            # 三角の高さ
        lm = LineSegs()
        lm.set_thickness(2.5)
        lm.set_color(1.0, 1.0, 0.0, 1.0)   # 黄
        lm.move_to(0, 0, MR + MH)           # 左上頂点
        lm.draw_to(HW, 0, MR + MH)         # 右上頂点
        lm.draw_to(0, 0, MR)               # 下向き先端
        lm.draw_to(-HW, 0, MR + MH)        # 左上頂点に戻る
        lm.draw_to(HW, 0, MR + MH)         # 閉じる
        marker_node = lm.create()
        self._steer_marker_np = self.aspect2d.attach_new_node(
            marker_node)
        self._steer_marker_np.set_pos(WX, 0, WZ)

        # ラベル（ホイール下）
        self._steer_label = OnscreenText(
            text="0 deg  (tire 0.0)",
            pos=(WX, WZ - 0.14), scale=0.045,
            fg=(1, 1, 0.4, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ACenter, mayChange=True)

    def _setup_keys(self):
        """キーバインドを登録する。

        * ``Escape``: アプリ終了
        * ``V``: カメラモード切替（follow ↔ onboard）
        * ``O``: 俯瞰視点サイクル（follow/onboard → overview → overview_fixed → follow）
        * ``R``: 路面メッシュ表示切替
        * ``Space``: 一時停止/再開
        * ``A``: オートドライブモード切替
        * ``↑``/``↓``: 速度 ±10 m/s
        * ``←``/``→``: 100m 後退/前進
        * ``P``/``Shift+P``: 周囲車両 1 台追加/削除
        * ``I``/``K``: 俯瞰カメラ近づく/遠ざかる
        """
        self.accept("escape", sys.exit)
        self.accept("v", self._toggle_view)
        self.accept("o", self._toggle_overview)
        self.accept("r", self._toggle_surface)
        self.accept("space", self._toggle_pause)
        self.accept("a", self._toggle_auto_drive)
        self.accept("arrow_up", lambda: self._change_speed(+10))
        self.accept("arrow_down", lambda: self._change_speed(-10))
        self.accept("arrow_left", self._rewind)
        self.accept("arrow_right", self._forward)
        # 台数増減: p = plus（増やす）、m = minus（減らす）
        self.accept("p", self._add_one_traffic)
        self.accept("shift-p", self._remove_one_traffic)
        # 俯瞰ズーム: i=近づく、k=遠ざかる（overview/overview_fixed で有効）
        self.accept("i", self._overview_zoom_in)
        self.accept("k", self._overview_zoom_out)

    # ─── 走行処理 ────────────────────────────────────────────
    def _move_task(self, task):
        """毎フレーム呼ばれる Panda3D タスク関数。

        一時停止でなければ走行距離を進める（オートドライブ: :meth:`_ad_step`、
        通常: ``self.cl`` 上をループ）。
        その後、自車・カメラ・周囲車両の位置姿勢を更新して HUD を描き直す。

        Parameters
        ----------
        task : Task
            Panda3D のタスクオブジェクト（戻り値は ``Task.cont`` で継続）。

        Returns
        -------
        Task.cont
            タスクを継続することを Panda3D に通知する定数。
        """
        # 固定俯瞰視点のパン（右ドラッグまたは中ドラッグ）
        if self.view_mode == "overview_fixed":
            self._overview_pan()

        if not self.paused:
            dt = globalClock.get_dt()  # noqa: F821
            if self._auto_drive:
                self._ad_step(dt)
            elif self._total > 0:
                self.dist = (self.dist + self.speed * dt) % self._total

        cur_cl = self._ad_cl if self._auto_drive else self.cl
        cur_dist = self._ad_dist if self._auto_drive else self.dist
        self._update_car_pose_cl(cur_cl, cur_dist)
        self._update_camera_cl(cur_cl, cur_dist)

        # HUD 用に現在の位置・方向を保存
        pos, fwd, _ = self._interp_cl(cur_cl, cur_dist)
        self._cur_pos = pos
        self._cur_fwd = fwd
        self._cur_kappa = self._curvature_at(cur_cl, cur_dist)

        # 周囲車両を更新
        if not self.paused:
            for car in self._traffic:
                self._step_traffic_car(car, dt)
                self._update_traffic_car_pose(car)

        self._update_hud()
        return Task.cont

    # ─── オートドライブ ─────────────────────────────────────
    #: 隣接判定の距離閾値 [m]（端点がこの距離以内なら接続とみなす）
    AD_TOL = 1.0

    def _ad_step(self, dt: float):
        """オートドライブの 1 フレーム処理。

        ``_ad_dist`` を速度×経過時間だけ進め、チェーン末端を超えたとき
        :meth:`_ad_advance` を呼んで次の要素に遷移する。

        Parameters
        ----------
        dt : float
            フレーム経過時間 [s]。
        """
        if self._ad_total <= 0:
            return
        self._ad_dist += self.speed * dt
        if self._ad_dist < self._ad_total:
            return  # まだチェーン内

        # 末端を超えた余剰距離を次チェーンに引き継ぐ
        overflow = self._ad_dist - self._ad_total
        self._ad_advance(overflow)

    def _ad_advance(self, overflow: float = 0.0):
        """チェーン末端に達したとき次の走行要素を決定する。

        Parameters
        ----------
        overflow : float
            前チェーンの末端を超えた余剰距離 [m]。次チェーンの開始位置に加算して
            位置が連続して見えるようにする（ジャンプ防止）。

        1. 現在の末端座標から候補を探す（AD_TOL 以内の端点を持つ要素）。
        2. 候補が 1 つ → それを選ぶ。
        3. 候補が複数 → ランダムに選ぶ。
        4. 候補なし → ワープ処理（境界を超えていたら符号を反転）。
        """
        import random

        # 現在チェーンの末端座標
        end_pt = self._ad_cl[-1]   # (x, y, z, dist)
        ex, ey = end_pt[0], end_pt[1]

        # 走行方向の接線（末端2点から計算）
        if len(self._ad_cl) >= 2:
            dx = self._ad_cl[-1][0] - self._ad_cl[-2][0]
            dy = self._ad_cl[-1][1] - self._ad_cl[-2][1]
            ln = math.hypot(dx, dy) or 1.0
            fwd_x, fwd_y = dx / ln, dy / ln
        else:
            fwd_x, fwd_y = 1.0, 0.0

        # 候補を収集（現在要素以外で末端に接続する要素）
        # Clothoid接点を経由する接続は、接点のclothoid_id/sideが一致するかで判定する
        cur_elem = next((e for e in self._elem_graph
                         if e["id"] == self._ad_cur_id), None)

        # 現在要素の末端の Clothoid 接点参照（正順走行 → end_clo_ref, 逆順 → start_clo_ref）
        if cur_elem is not None:
            if self._ad_forward:
                exit_clo_ref = cur_elem.get("end_clo_ref")
            else:
                exit_clo_ref = cur_elem.get("start_clo_ref")
        else:
            exit_clo_ref = None

        candidates = []   # [(elem_dict, forward), ...]
        for elem in self._elem_graph:
            if elem["id"] == self._ad_cur_id:
                continue
            sx, sy = elem["start"]
            ex2, ey2 = elem["end"]
            s_ref = elem.get("start_clo_ref")
            e_ref = elem.get("end_clo_ref")

            # 接続判定: 同じ Clothoid 接点を共有しているか（最優先）
            if exit_clo_ref is not None:
                cid = exit_clo_ref["clothoid_id"]
                side = exit_clo_ref["side"]
                # 候補の start_clo_ref が同じ接点 → 正順で入る
                if (s_ref is not None
                        and s_ref["clothoid_id"] == cid
                        and s_ref["side"] == side):
                    candidates.append((elem, True))
                    continue
                # 候補の end_clo_ref が同じ接点 → 逆順で入る
                if (e_ref is not None
                        and e_ref["clothoid_id"] == cid
                        and e_ref["side"] == side):
                    candidates.append((elem, False))
                    continue

            # Clothoid 接点参照がない場合は座標距離で判定（AD_TOL 以内）
            if exit_clo_ref is None:
                if math.hypot(ex - sx, ey - sy) < self.AD_TOL:
                    candidates.append((elem, True))
                elif math.hypot(ex - ex2, ey - ey2) < self.AD_TOL:
                    candidates.append((elem, False))

        # 遷移前に現在状態を履歴に積む
        self._ad_history_push()

        # 進行方向フィルタ: 現在の進行方向と逆向きの候補を除外する
        # 候補の走行方向と現在の fwd の内積が負（逆向き）のものは除外
        ok = [(e, f) for e, f in candidates
              if (fwd_x * _elem_fwd_vec(e, f)[0]
                  + fwd_y * _elem_fwd_vec(e, f)[1]) >= 0.0]
        candidates = ok if ok else candidates

        # Clothoid接点参照フィルタ後に候補なしの場合、
        # 座標距離でフォールバックして同方向の候補を探す（0.97mギャップ等への対応）
        if not candidates:
            dist_cands = []
            for elem in self._elem_graph:
                if elem["id"] == self._ad_cur_id:
                    continue
                sx, sy = elem["start"]
                ex2, ey2 = elem["end"]
                if math.hypot(ex - sx, ey - sy) < self.AD_TOL:
                    dist_cands.append((elem, True))
                elif math.hypot(ex - ex2, ey - ey2) < self.AD_TOL:
                    dist_cands.append((elem, False))
            ok = [(e, f) for e, f in dist_cands
                  if (fwd_x * _elem_fwd_vec(e, f)[0]
                      + fwd_y * _elem_fwd_vec(e, f)[1]) >= 0.0]
            candidates = ok if ok else dist_cands

        if candidates:
            # 候補あり: 1つならそれ、複数ならランダム
            chosen_elem, chosen_fwd = random.choice(candidates)
            self._ad_start_elem(chosen_elem, chosen_fwd, overflow)
        else:
            # 候補なし: ワープ処理
            self._ad_warp(ex, ey, fwd_x, fwd_y, overflow)

    def _ad_start_elem(self, elem: dict, forward: bool, overflow: float = 0.0):
        """elem を走行開始する中心線を生成してリセットする。

        縦断高さは elem["heights"] [[dist, elev], ...] から線形補間する。
        forward=False のとき始点/終点と heights を逆順にして使う。

        Parameters
        ----------
        overflow : float
            前チェーンの余剰距離。_ad_dist の初期値に設定して位置を連続させる。
        """
        pl = elem["plan_length"]
        heights = elem.get("heights", [[0.0, 0.0], [pl, 0.0]])
        pts_xy = elem.get("points_xy", None)  # [[x, y], ...] 正順

        if not forward:
            # 逆順: 点列を反転、heights の dist も反転
            if pts_xy:
                pts_xy = list(reversed(pts_xy))
            heights = [[pl - h[0], h[1]] for h in reversed(heights)]

        def _elev(d):
            """dist d に対する高さを heights から線形補間して返す。"""
            if not heights:
                return 0.0
            if d <= heights[0][0]:
                return heights[0][1]
            for k in range(len(heights) - 1):
                d0, z0 = heights[k]
                d1, z1 = heights[k + 1]
                if d0 <= d <= d1:
                    t = (d - d0) / (d1 - d0) if d1 > d0 else 0.0
                    return z0 + (z1 - z0) * t
            return heights[-1][1]

        # points_xy から累積距離を計算して (x, y, z, dist) の中心線を生成
        new_cl = []
        if pts_xy and len(pts_xy) >= 2:
            # 各点間の距離を積算して dist を計算
            cum_d = [0.0]
            for k in range(1, len(pts_xy)):
                dx = pts_xy[k][0] - pts_xy[k - 1][0]
                dy = pts_xy[k][1] - pts_xy[k - 1][1]
                cum_d.append(cum_d[-1] + math.hypot(dx, dy))
            total_pts = cum_d[-1]
            # dist を pl にスケーリング（点列の合計長と plan_length が一致するとは限らない）
            scale = pl / total_pts if total_pts > 1e-9 else 1.0
            for k, (xy, cd) in enumerate(zip(pts_xy, cum_d)):
                d = cd * scale
                z = _elev(d)
                new_cl.append((xy[0], xy[1], z, d))
        else:
            # フォールバック: 直線補間
            sx, sy = elem["start"] if forward else elem["end"]
            ex, ey = elem["end"] if forward else elem["start"]
            n = max(2, int(pl * 0.5))
            for i in range(n + 1):
                t = i / n
                d = pl * t
                z = _elev(d)
                new_cl.append((sx + (ex - sx) * t, sy + (ey - sy) * t, z, d))

        self._ad_cur_id = elem["id"]
        self._ad_forward = forward
        self._ad_cl = new_cl
        self._ad_total = pl
        # 余剰距離を引き継いで位置を連続させる（チェーン長を超える場合は末端にクランプ）
        self._ad_dist = min(overflow, pl)

    def _ad_warp(self, ex: float, ey: float, fwd_x: float, fwd_y: float,
                 overflow: float = 0.0):
        """候補なしのとき境界ワープして同方向に走行を続ける。

        パックマン式（トーラス空間）: 境界を超えた座標軸の符号だけを反転し、
        **進行方向は変えない**。

        例: x=+550(右端)を超えて右向きに走行中
              → x=-550(左端)に移動して、**同じ右向きで**走行継続
        例: y=-520(下端)を超えて下向きに走行中
              → y=+520(上端)に移動して、**同じ下向きで**走行継続

        超えていない軸は座標も方向も一切変えない。
        """
        B = self._warp_boundary
        new_x, new_y = ex, ey

        if abs(ex) > B:
            new_x = -ex    # x 座標の符号を反転（向きは変えない）

        if abs(ey) > B:
            new_y = -ey    # y 座標の符号を反転（向きは変えない）

        # ワープ先から同じ方向に仮の直線チェーンを生成
        pl = 100.0
        n = 50
        z_end = self._ad_cl[-1][2] if self._ad_cl else 0.0
        new_cl = []
        for i in range(n + 1):
            t = i / n
            x = new_x + fwd_x * pl * t   # 方向はそのまま
            y = new_y + fwd_y * pl * t
            d = pl * t
            new_cl.append((x, y, z_end, d))

        self._ad_cl = new_cl
        self._ad_total = pl
        self._ad_dist = min(overflow, pl)
        self._ad_cur_id = None

    def _update_car_pose(self, dist: float):
        """固定チェーン ``self.cl`` 上の dist での自車位置・姿勢を更新する（後方互換）。

        Parameters
        ----------
        dist : float
            チェーン上の累積距離 [m]。
        """
        self._update_car_pose_cl(self.cl, dist)

    def _update_car_pose_cl(self, cl: list, dist: float):
        """任意の中心線 cl 上の dist での自車位置・姿勢を更新する。

        :meth:`_interp_cl` で位置・方向を求め、Panda3D の heading/pitch に変換して
        ``car_np`` の位置・姿勢をセットする。

        Parameters
        ----------
        cl : list[tuple]
            中心線点列 [(x, y, z, dist), ...]。
        dist : float
            チェーン上の累積距離 [m]。
        """
        pos, fwd, _ = self._interp_cl(cl, dist)
        self.car_np.set_pos(pos)
        heading = math.degrees(math.atan2(-fwd[0], fwd[1]))
        pitch = math.degrees(math.atan2(fwd[2], math.hypot(fwd[0], fwd[1])))
        self.car_np.set_hpr(heading, pitch, 0)

    def _update_camera_cl(self, cl: list, dist: float):
        """現在の view_mode に応じてカメラ位置・姿勢を更新する。

        * ``"follow"``: 自車後方 CAM_BEHIND m・上方 CAM_ABOVE m から前方注視。
        * ``"overview"``: 自車真上 CAM_OVERVIEW_H m から鉛直下向き。
        * ``"overview_fixed"``: ``_overview_pos`` の真上から鉛直下向き（マウスパン可能）。
        * ``"onboard"``: 運転席視点（前方 2m 、高さ CAM_EYE_H m）。

        Parameters
        ----------
        cl : list[tuple]
            中心線点列 [(x, y, z, dist), ...]。
        dist : float
            チェーン上の累積距離 [m]。
        """
        pos, fwd, _ = self._interp_cl(cl, dist)
        if self.view_mode == "follow":
            back = (-fwd[0] * self.CAM_BEHIND,
                    -fwd[1] * self.CAM_BEHIND,
                    self.CAM_ABOVE)
            cam_pos = LPoint3(pos[0] + back[0], pos[1] +
                              back[1], pos[2] + back[2])
            self.camera.set_pos(cam_pos)
            look_ahead = 5.0
            look = LPoint3(pos[0] + fwd[0] * look_ahead,
                           pos[1] + fwd[1] * look_ahead,
                           pos[2] + fwd[2] * look_ahead)
            self.camera.look_at(look)
        elif self.view_mode == "overview":
            # 自車追従俯瞰: 自車の真上を追従
            self.camera.set_pos(
                LPoint3(pos[0], pos[1], pos[2] + self.CAM_OVERVIEW_H))
            self.camera.set_hpr(0, -90, 0)
        elif self.view_mode == "overview_fixed":
            # 固定俯瞰: カメラ位置を固定（マウスホイールで高度変更可能）
            ox, oy = self._overview_pos
            self.camera.set_pos(LPoint3(ox, oy, self.CAM_OVERVIEW_H))
            self.camera.set_hpr(0, -90, 0)
        else:
            # 運転席視点
            eye_forward = 2.0
            eye = LPoint3(pos[0] + fwd[0] * eye_forward,
                          pos[1] + fwd[1] * eye_forward,
                          pos[2] + self.CAM_EYE_H)
            look = LPoint3(pos[0] + fwd[0] * 20,
                           pos[1] + fwd[1] * 20,
                           pos[2] + fwd[2] * 20 + self.CAM_EYE_H)
            self.camera.set_pos(eye)
            self.camera.look_at(look)

    @staticmethod
    def _bearing_str(fwd_x: float, fwd_y: float) -> str:
        """モジュールレベルの :func:`bearing_str` に委譲する。"""
        return bearing_str(fwd_x, fwd_y)

    def _update_hud(self):
        """HUD テキストを現在の走行状態で更新する。

        表示内容: 一時停止状態・オートドライブ情報（走行要素名・方向・進捗）・
        現在座標・方位・累積距離・速度・カメラモード・路面状態・周囲車両台数。
        非 ASCII のニックネームは ASCII に安全なフォールバック形式で表示する。
        """
        mode_str = {
            "follow": "Follow", "onboard": "Onboard",
            "overview": "Overview(track)",
            "overview_fixed": "Overview(fixed)",
        }.get(self.view_mode, self.view_mode)
        pause_str = "[PAUSED]\n" if self.paused else ""
        surface_str = "ON" if self.ROAD_SURFACE else "OFF"

        # 現在位置・方向
        px, py, pz = self._cur_pos
        fwd_x, fwd_y = self._cur_fwd[0], self._cur_fwd[1]
        bearing = self._bearing_str(fwd_x, fwd_y)

        if self._auto_drive:
            cur_dist = self._ad_dist
            cur_total = self._ad_total
            # 走行中の図形名を elem_graph から取得
            elem_name = "---"
            if self._ad_cur_id is not None:
                for e in self._elem_graph:
                    if e["id"] == self._ad_cur_id:
                        nick = e.get("nickname", f"#{e['id']}")
                        # OnscreenText はデフォルトフォントが ASCII のみ対応
                        # 非ASCII文字を含む場合は ASCII 安全な形式にフォールバック
                        try:
                            nick.encode("ascii")
                            elem_name = nick
                        except UnicodeEncodeError:
                            elem_name = f"#{e['id']}({e['type']})"
                        break
            else:
                elem_name = "(warp)"
            fwd_str = "->" if self._ad_forward else "<-"
            # 履歴参照中の表示
            if self._ad_history_idx >= 0:
                hist_str = (f"[History {self._ad_history_idx + 1}/"
                            f"{len(self._ad_history)}]  <- back  -> fwd\n")
            else:
                hist_str = ""
            auto_str = (
                f"[AUTO] {elem_name} {fwd_str}  "
                f"{cur_dist:.0f}/{cur_total:.0f} m\n"
                f"{hist_str}"
            )
        else:
            cur_dist = self.dist
            cur_total = self._total
            auto_str = ""

        # 舵角: δ = WHEELBASE × κ（ラジアン）→ 度数
        steer_deg = math.degrees(self.WHEELBASE * self._cur_kappa)
        wheel_rot = steer_deg * self.STEER_DISPLAY_RATIO
        # Panda3D の set_r は正=時計回り（右）なので符号を反転して
        # 左曲がり（κ正）→ 反時計回り（ハンドル左切り）に対応させる
        self._steer_np.set_r(-wheel_rot)
        self._steer_label.setText(
            f"{wheel_rot:+.0f} deg"
            f"  (tire {steer_deg:+.1f})")

        self.hud.setText(
            f"{pause_str}"
            f"{auto_str}"
            f"Pos: ({px:.1f}, {py:.1f})  Alt: {pz:.1f} m\n"
            f"Dir: {bearing}  ({fwd_x:+.2f}, {fwd_y:+.2f})\n"
            f"Dist: {cur_dist:.0f} / {cur_total:.0f} m\n"
            f"Speed: {self.speed:.0f} m/s"
            f" ({self.speed*3.6:.0f} km/h)\n"
            f"View: {mode_str} [V/O]"
            f"  Surface: {surface_str} [R]  Auto [A]\n"
            f"Up/Down:Speed  Left/Right:Jump"
            f"  Space:Pause  Esc:Quit\n"
            f"Traffic: {len(self._traffic)} cars"
            f"  P:Add  Shift-P:Remove"
        )

    # ─── 補間 ────────────────────────────────────────────────

    @staticmethod
    def _curvature_at(cl: list, dist: float) -> float:
        """中心線上の dist における符号付き曲率 [1/m] を返す。

        隣接する接線ベクトルの変化量 Δθ / Δs で近似する。
        左曲がりを正、右曲がりを負とする（平面視点で y 軸が北）。

        Parameters
        ----------
        cl : list[tuple]
            3D 中心線点列 [(x, y, z, dist), ...]。
        dist : float
            現在の累積距離 [m]。

        Returns
        -------
        float
            符号付き曲率 [1/m]。直線では 0、点数不足では 0。
        """
        if len(cl) < 3:
            return 0.0

        # dist に最も近いインデックスを二分探索
        lo, hi = 0, len(cl) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cl[mid][3] < dist:
                lo = mid + 1
            else:
                hi = mid
        idx = max(1, min(lo, len(cl) - 2))

        x0, y0 = cl[idx - 1][0], cl[idx - 1][1]
        x1, y1 = cl[idx][0], cl[idx][1]
        x2, y2 = cl[idx + 1][0], cl[idx + 1][1]

        dx1, dy1 = x1 - x0, y1 - y0
        dx2, dy2 = x2 - x1, y2 - y1
        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 < 1e-9 or len2 < 1e-9:
            return 0.0

        # 単位接線ベクトル t1, t2 のクロス積 → 符号付き Δθ
        t1x, t1y = dx1 / len1, dy1 / len1
        t2x, t2y = dx2 / len2, dy2 / len2
        cross = t1x * t2y - t1y * t2x  # sin(Δθ) ≈ Δθ（微小角）
        ds = (len1 + len2) * 0.5
        return cross / ds if ds > 1e-9 else 0.0

    def _interp(self, dist: float):
        """固定チェーン ``self.cl`` 上の dist に対する位置・方向を返す（後方互換）。

        Parameters
        ----------
        dist : float
            ``self.cl`` 上の累積距離 [m]。

        Returns
        -------
        tuple
            ``(pos, fwd, right)`` のタプル。:meth:`_interp_cl` の戻り値と同じ形式。
        """
        return self._interp_cl(self.cl, dist)

    def _interp_cl(self, cl: list, dist: float):
        """モジュールレベルの :func:`interp_cl` に委譲する。"""
        return interp_cl(cl, dist)

    # ─── 操作 ────────────────────────────────────────────────

    def _toggle_view(self):
        """V キーで follow ↔ onboard カメラモードを切り替える。"""
        self.view_mode = "onboard" if self.view_mode == "follow" else "follow"

    def _toggle_overview(self):
        """O キーで俯瞰視点をサイクルする。

        follow / onboard → overview（自車追従）→ overview_fixed（カメラ固定）→ follow
        """
        if self.view_mode in ("follow", "onboard"):
            # 現在の自車位置を固定俯瞰の初期位置として保存
            cur_cl = self._ad_cl if self._auto_drive else self.cl
            cur_dist = self._ad_dist if self._auto_drive else self.dist
            pos, _, _ = self._interp_cl(cur_cl, cur_dist)
            self._overview_pos = (pos[0], pos[1])
            self.view_mode = "overview"
        elif self.view_mode == "overview":
            # 追従俯瞰 → 固定俯瞰（現在のカメラ位置を固定）
            self.view_mode = "overview_fixed"
        else:
            # 固定俯瞰 → 通常追従
            self.view_mode = "follow"

    def _toggle_pause(self):
        """Space キーで走行の一時停止/再開を切り替える。"""
        self.paused = not self.paused

    def _toggle_auto_drive(self):
        """A キーでオートドライブモードを切り替える。"""
        self._auto_drive = not self._auto_drive
        if self._auto_drive and self._start_info:
            # オートドライブ開始時は元の走行チェーンにリセット
            self._ad_cl = self.cl
            self._ad_total = self._total
            self._ad_dist = self.dist  # 現在位置から再開
            self._ad_cur_id = self._start_info["id"]
            self._ad_forward = self._start_info["forward"]

    def _change_speed(self, delta: float):
        """走行速度を変更する（最小 1.0 m/s でクランプ）。

        Parameters
        ----------
        delta : float
            速度の変化量 [m/s]。正で加速、負で減速。
        """
        self.speed = max(1.0, self.speed + delta)

    def _ad_history_push(self):
        """現在のオートドライブ状態を履歴スタックに積む。

        履歴参照中（_ad_history_idx >= 0）は push しない（巻き戻し中の
        自動遷移による上書きを防ぐ）。
        最大 _AD_HISTORY_MAX 件を保持し、古いものは捨てる。
        """
        if self._ad_history_idx >= 0:
            return  # 履歴参照中は積まない
        snap = {
            "cl": self._ad_cl,
            "total": self._ad_total,
            "dist": self._ad_dist,
            "cur_id": self._ad_cur_id,
            "forward": self._ad_forward,
        }
        self._ad_history.append(snap)
        if len(self._ad_history) > self._AD_HISTORY_MAX:
            self._ad_history.pop(0)

    def _rewind(self):
        """← キーで 100m 後退する（オートドライブ時は履歴スタックを使う）。

        オートドライブモードでは ``_ad_dist - 100`` がゼロ未満になると
        ``_ad_history`` から前の要素を復元する。
        非オートドライブでは ``self.dist`` を 100m 戻す（最小 0）。
        """
        if self._auto_drive:
            new_dist = self._ad_dist - 100
            if new_dist < 0 and self._ad_history:
                if self._ad_history_idx < 0:
                    self._ad_history_idx = len(self._ad_history) - 1
                elif self._ad_history_idx > 0:
                    self._ad_history_idx -= 1
                if self._ad_history_idx >= 0:
                    snap = self._ad_history[self._ad_history_idx]
                    self._ad_cl = snap["cl"]
                    self._ad_total = snap["total"]
                    self._ad_dist = 0.0
                    self._ad_cur_id = snap["cur_id"]
                    self._ad_forward = snap["forward"]
                    # カメラ方向を即時更新（次フレームを待たない）
                    pos, fwd, _ = self._interp_cl(self._ad_cl, self._ad_dist)
                    self._cur_pos = pos
                    self._cur_fwd = fwd
            else:
                self._ad_dist = max(0.0, new_dist)
        else:
            self.dist = max(0, self.dist - 100)

    def _forward(self):
        """→ キーで 100m 前進する（オートドライブ履歴参照中は次の要素に進む）。

        オートドライブの履歴参照中（``_ad_history_idx >= 0``）は
        ``_ad_history`` の次エントリを復元する。
        最新状態（``_ad_history_idx == -1``）になったらリアルタイム走行に戻る。
        非オートドライブでは ``self.dist`` を 100m 進める（最大 total）。
        """
        if self._auto_drive:
            if self._ad_history_idx >= 0:
                self._ad_history_idx += 1
                if self._ad_history_idx >= len(self._ad_history):
                    self._ad_history_idx = -1
                else:
                    snap = self._ad_history[self._ad_history_idx]
                    self._ad_cl = snap["cl"]
                    self._ad_total = snap["total"]
                    self._ad_dist = 0.0
                    self._ad_cur_id = snap["cur_id"]
                    self._ad_forward = snap["forward"]
                    # カメラ方向を即時更新
                    pos, fwd, _ = self._interp_cl(self._ad_cl, self._ad_dist)
                    self._cur_pos = pos
                    self._cur_fwd = fwd
            else:
                self._ad_dist = min(self._ad_total, self._ad_dist + 100)
        else:
            self.dist = min(self._total, self.dist + 100)


# ══════════════════════════════════════════════════════════════
#   エントリーポイント：設計アプリから呼ばれる
# ══════════════════════════════════════════════════════════════

def _build_display_segs(scene: Scene, all_display: list) -> list:
    """背景表示用の中心線セグメント群を生成して返す。

    ``all_display`` が None または空のとき空リストを返す。
    """
    segs = []
    if not all_display:
        return segs
    for obj in all_display:
        ep = next((e for e in scene.element_profiles
                   if e.element_id == obj.id), None)
        if ep is None:
            ep = ElementProfile()
        ep.plan_length = plan_length_of(obj)
        if ep.plan_length < 0.001:
            continue
        cl = build_centerline([obj], [ep], [False], n_per_m=0.5)
        if cl:
            segs.append(cl)
    return segs


def _build_clo_ref_map(clothoids: list) -> dict:
    """Clothoid 接点の座標→参照辞書を構築して返す。

    key: ``(round(x, 3), round(y, 3))``
    value: ``{"clothoid_id": int, "side": "line"|"circle"}``
    """
    clo_ref_map: dict = {}
    for clo in clothoids:
        if not clo.is_valid:
            continue
        for side, pt in [("line", clo._line_pt),
                         ("circle", clo._circle_pt)]:
            if pt is None:
                continue
            key = (round(pt.x, 3), round(pt.y, 3))
            clo_ref_map.setdefault(key, []).append(
                {"clothoid_id": clo.id, "side": side})
    return clo_ref_map


def _build_elem_graph(
        scene: Scene, all_elems: list, clo_ref_map: dict) -> list:
    """全要素からオートドライブ用の elem_graph を構築して返す。

    各エントリは ``{id, type, nickname, start, end, plan_length,
    heights, points_xy, start_clo_ref, end_clo_ref}`` の辞書。
    """
    def _lookup(x, y):
        refs = clo_ref_map.get((round(x, 3), round(y, 3)))
        return refs[0] if refs else None

    def _sample_points_xy(obj, n_pts):
        """要素の平面形状点列を n_pts 分割でサンプリングする。"""
        pts = []
        if isinstance(obj, Segment):
            for i in range(n_pts + 1):
                t = i / n_pts
                pts.append([
                    obj.start.x + (obj.end.x - obj.start.x) * t,
                    obj.start.y + (obj.end.y - obj.start.y) * t,
                ])
        elif isinstance(obj, Arc):
            ci = obj.circle
            a0 = obj.angle_start
            span = obj.arc_angle()
            for i in range(n_pts + 1):
                ang = a0 + span * i / n_pts
                pts.append([
                    ci.center.x + ci.radius * math.cos(ang),
                    ci.center.y + ci.radius * math.sin(ang),
                ])
        elif isinstance(obj, Clothoid):
            raw = obj.points
            if raw:
                cum = [0.0]
                for k in range(1, len(raw)):
                    dx = raw[k].x - raw[k - 1].x
                    dy = raw[k].y - raw[k - 1].y
                    cum.append(cum[-1] + math.hypot(dx, dy))
                total = cum[-1]
                for i in range(n_pts + 1):
                    target = total * i / n_pts
                    for k in range(len(cum) - 1):
                        if cum[k] <= target <= cum[k + 1]:
                            r = ((target - cum[k])
                                 / (cum[k + 1] - cum[k])
                                 if cum[k + 1] > cum[k] else 0)
                            pts.append([
                                raw[k].x + (raw[k+1].x - raw[k].x) * r,
                                raw[k].y + (raw[k+1].y - raw[k].y) * r,
                            ])
                            break
                    else:
                        pts.append([raw[-1].x, raw[-1].y])
        return pts

    elem_graph = []
    for obj in all_elems:
        ep = next((e for e in scene.element_profiles
                   if e.element_id == obj.id), None)
        pl = ep.plan_length if ep else plan_length_of(obj)
        pts = _elem_endpoints_xy(obj)
        if pts is None:
            continue
        s, e = pts

        # 縦断高さをサンプリング
        n_h = max(2, int(pl * 0.2))
        if ep:
            heights = [[pl * i / n_h, ep.elev_at(pl * i / n_h)]
                       for i in range(n_h + 1)]
        else:
            heights = [[0.0, 0.0], [pl, 0.0]]

        # 平面形状点列
        points_xy = _sample_points_xy(obj, max(4, int(pl * 0.5)))
        if not points_xy:
            points_xy = [[s.x, s.y], [e.x, e.y]]

        elem_graph.append({
            "id": obj.id,
            "type": type(obj).__name__,
            "nickname": scene.get_nickname(obj.id),
            "start": [s.x, s.y],
            "end": [e.x, e.y],
            "plan_length": pl,
            "heights": heights,
            "points_xy": points_xy,
            # None: 接点なし / dict: Clothoid 接点参照
            "start_clo_ref": _lookup(s.x, s.y),
            "end_clo_ref": _lookup(e.x, e.y),
        })
    return elem_graph


def prepare_viewer_data(scene: Scene,
                        elements: list,
                        profiles: list,
                        rev_flags: list[bool],
                        all_display: list = None) -> dict:
    """走行チェーンと背景表示データを計算して辞書で返す（I/O なし・純粋関数）。

    `launch_viewer` から呼ばれる。I/O を伴わないため単体テスト可能。

    Parameters
    ----------
    scene : Scene
        現在のシーン（背景要素の ElementProfile 取得に使う）。
    elements : list[Segment | Arc | Clothoid]
        走行チェーンの要素リスト（resolve_chain 済み）。
    profiles : list[ElementProfile]
        各走行要素に対応する縦断データ。
    rev_flags : list[bool]
        各走行要素の逆順フラグ。
    all_display : list, optional
        背景として表示する全要素のリスト。None のとき背景なし。

    Returns
    -------
    dict
        ``{"centerline_3d", "display_segments", "elem_graph",
        "start_info"}`` の辞書。JSON シリアライズ可能。
    """
    display_segs = _build_display_segs(scene, all_display)

    all_elems = []
    for ln in scene.lines:
        all_elems.extend(ln.segments)
    for ci in scene.circles:
        all_elems.extend(ci.arcs)
    all_elems.extend(scene.clothoids)

    clo_ref_map = _build_clo_ref_map(scene.clothoids)
    elem_graph = _build_elem_graph(scene, all_elems, clo_ref_map)

    start_info = None
    if elements:
        first = elements[0]
        pts = _elem_endpoints_xy(first)
        if pts:
            start_info = {"id": first.id, "forward": not rev_flags[0]}

    return {
        "centerline_3d": build_centerline(elements, profiles, rev_flags),
        "display_segments": display_segs,
        "elem_graph": elem_graph,
        "start_info": start_info,
    }


def launch_viewer(scene: Scene,
                  elements: list,
                  profiles: list,
                  rev_flags: list[bool],
                  all_display: list = None,
                  warp_boundary: float = None):
    """設計アプリのメインウィンドウから呼ぶ。別プロセスで Panda3D ウィンドウを起動する。

    :func:`prepare_viewer_data` でデータを計算し、一時 JSON ファイルに書き出して
    ``subprocess.Popen`` でこのスクリプト自身を別プロセスとして起動する。

    Parameters
    ----------
    scene : Scene
        現在のシーン（背景表示用の ElementProfile 参照と elem_graph 構築に使う）。
    elements : list[Segment | Arc | Clothoid]
        走行チェーンの要素リスト（resolve_chain 済み）。
    profiles : list[ElementProfile]
        各走行要素に対応する縦断データ。
    rev_flags : list[bool]
        各走行要素の逆順フラグ。
    all_display : list, optional
        背景として表示する全要素のリスト。None のとき背景なし。
    warp_boundary : float, optional
        オートドライブのワープ境界 [m]。None のとき RoadViewer.WARP_BOUNDARY(=500m)。
    """
    import subprocess
    import tempfile
    import os

    data = prepare_viewer_data(
        scene, elements, profiles, rev_flags, all_display)

    # warp_boundary をデータに含める（デフォルトはクラス定数）
    data["warp_boundary"] = warp_boundary  # None のとき RoadViewer がデフォルト値を使う

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False)
    tmp.close()

    subprocess.Popen(
        [sys.executable, __file__, tmp.name],
        cwd=os.path.dirname(os.path.abspath(__file__)))


def _main_from_file(path: str):
    """JSON ファイルからビューアデータを読み込んで RoadViewer を起動する。

    :func:`launch_viewer` が生成した一時 JSON ファイルを別プロセスで読み込む
    エントリーポイント。``__main__`` ブロックから呼ばれる。

    Parameters
    ----------
    path : str
        :func:`prepare_viewer_data` の結果を JSON 形式で保存したファイルのパス。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    centerline = [tuple(p) for p in data["centerline_3d"]]
    display_segs = [[tuple(p) for p in seg]
                    for seg in data.get("display_segments", [])]
    elem_graph = data.get("elem_graph", None)
    start_info = data.get("start_info", None)
    warp_boundary = data.get("warp_boundary", None)

    if not centerline:
        print("No centerline data.")
        return

    app = RoadViewer(centerline, display_segs,
                     elem_graph=elem_graph,
                     start_info=start_info,
                     warp_boundary=warp_boundary)
    app.run()


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        _main_from_file(sys.argv[1])
    else:
        # テスト用: 単純な直線コースを走る
        centerline = [(i * 2.0, 0.0, 0.0, i * 2.0) for i in range(200)]
        app = RoadViewer(centerline)
        app.run()
