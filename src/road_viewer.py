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
import math, sys, json, logging
from typing import Optional

# ─── Panda3D ──────────────────────────────────────────────────
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    GeomVertexFormat, GeomVertexData, GeomVertexWriter,
    Geom, GeomTriangles, GeomNode,
    NodePath, LVector3, LPoint3, LColor,
    AmbientLight, DirectionalLight,
    TextNode, CardMaker,
)
from direct.task import Task
from direct.gui.OnscreenText import OnscreenText

# ─── 設計モデル ────────────────────────────────────────────────
sys.path.insert(0, ".")
from models import (
    Scene, Segment, Arc, Clothoid, GradeLine, ElementProfile,
    plan_length_of, resolve_chain, tangent_at, entry_tangent, SNAP_TOL
)

# ─── メッシュ生成ユーティリティ（backward-compat re-export 含む）─
from _road_mesh import (
    build_centerline, build_road_mesh, build_car_box,
    build_center_line_node, build_piers, build_road_markings,
    build_ground, _elev_at_dist, _elem_endpoints_xy,
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
    """
    pts = elem.get("points_xy") or []
    if len(pts) >= 2:
        p0, p1 = (pts[0], pts[1]) if forward else (pts[-1], pts[-2])
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    else:
        sx, sy  = elem["start"]
        ex, ey  = elem["end"]
        dx, dy  = (ex - sx, ey - sy) if forward else (sx - ex, sy - ey)
    ln = math.hypot(dx, dy) or 1.0
    return dx / ln, dy / ln


class RoadViewer(ShowBase):
    SPEED_DEFAULT = 30.0   # m/s
    CAM_BEHIND    = 20.0   # 外部視点: 後方距離
    CAM_ABOVE     = 6.0    # 外部視点: 高さ
    CAM_EYE_H    = 1.5    # 車載視点: 目の高さ
    CAM_OVERVIEW_H = 500.0 # 俯瞰視点: 高度 [m]

    #: ワープ境界 [m]。|x| または |y| がこの値を超えたら符号を反転してワープ
    WARP_BOUNDARY = 500.0

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
        self.cl          = centerline
        self.disp_segs   = display_segs or []
        self.dist        = 0.0
        self.speed       = self.SPEED_DEFAULT
        self.view_mode   = "follow"
        # 固定俯瞰視点のカメラ位置（overview_fixed モードで使用）
        self._overview_pos = (0.0, 0.0)  # (x, y) ワールド座標
        self._pan_prev_mouse = None       # パン操作の前フレームマウス位置
        self.paused      = False
        self._total      = centerline[-1][3] if centerline else 0.0
        self._auto_drive = (elem_graph is not None)  # True: オートドライブモード
        self._elem_graph = elem_graph or []
        self._start_info = start_info
        self._warp_boundary = warp_boundary if warp_boundary is not None                               else self.WARP_BOUNDARY

        # オートドライブ状態
        self._ad_cur_id   = start_info["id"]      if start_info else None
        self._ad_forward  = start_info["forward"]  if start_info else True
        self._ad_cl       = centerline             # 現在走行中の中心線
        self._ad_total    = self._total
        self._ad_dist     = 0.0                    # 現在のチェーン内距離

        # ── 周囲車両（トラフィック）──────────────────────────
        #: 初期台数（自車の前後それぞれ N 台）
        self.TRAFFIC_EACH   = 5
        #: 初期車間距離 [m]
        self.TRAFFIC_GAP    = 20.0
        self._traffic: list = []

        self._build_scene()
        self._setup_hud()
        self._setup_lighting()
        self.taskMgr.add(self._move_task, "move")
        self._setup_keys()

        # HUD 用の現在位置・方向（最初のフレームまでは (0,0,0), (1,0,0)）
        self._cur_pos = (0.0, 0.0, 0.0)
        self._cur_fwd = (1.0, 0.0, 0.0)

        # 走行履歴スタック（← で最大 _AD_HISTORY_MAX 要素分戻れる）
        # 各エントリ: {"cl": [...], "total": float, "dist": float,
        #              "cur_id": int, "forward": bool}
        self._AD_HISTORY_MAX = 10
        self._ad_history: list = []   # インデックス0が最古
        self._ad_history_idx = -1     # -1: 最新（リアルタイム走行中）

        # マウス無効化（デフォルトのカメラ操作を切る）
        self.disableMouse()

    # ─── シーン構築 ──────────────────────────────────────────
    HALF_WIDTH   = 1.75   # 道路半幅 [m]（全幅3.5mの半分）
    ROAD_SURFACE = True   # 路面表示の初期状態

    def _build_scene(self):
        self._surface_nodes = []   # 路面メッシュノードのリスト（on/off用）

        # 全要素の背景道路メッシュ（要素ごとに独立して生成）
        for seg_cl in self.disp_segs:
            if len(seg_cl) < 2:
                continue
            bg_node = build_road_mesh(seg_cl, half_width=self.HALF_WIDTH,
                                      color_override=LColor(0.28, 0.28, 0.28, 1))
            np = self.render.attachNewNode(bg_node)
            np.set_light_off()
            np.set_two_sided(True)   # 両面描画
            self._surface_nodes.append(np)
            bg_cl = build_center_line_node(seg_cl,
                                           color_override=LColor(0.5, 0.5, 0.5, 1))
            self.render.attachNewNode(bg_cl)
            self.render.attachNewNode(build_road_markings(seg_cl, self.HALF_WIDTH))
            self.render.attachNewNode(build_piers(seg_cl, self.HALF_WIDTH))

        # 走行チェーンの道路メッシュ
        road_np = self.render.attachNewNode(
            build_road_mesh(self.cl, half_width=self.HALF_WIDTH,
                            color_override=LColor(0.38, 0.38, 0.38, 1)))
        road_np.set_light_off()
        road_np.set_two_sided(True)   # 両面描画
        self._surface_nodes.append(road_np)
        self.render.attachNewNode(
            build_center_line_node(self.cl, color_override=LColor(1.0, 0.9, 0.1, 1)))
        self.render.attachNewNode(build_road_markings(self.cl, self.HALF_WIDTH))
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
        cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
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
        import math, random

        # NodePath 生成
        np_root = self.render.attachNewNode(f"traffic_{len(self._traffic)}")
        box = np_root.attachNewNode(build_car_box(4.0, 2.0, 1.5))
        box.setLightOff()
        box.setColorScale(0.4, 0.7, 1.0, 1.0)

        # 初期位置: 自車チェーンをオフセットした位置から出発
        cur_cl    = list(self._ad_cl)
        cur_total = self._ad_total
        cur_id    = self._ad_cur_id
        cur_fwd   = self._ad_forward
        init_dist = self._ad_dist + offset

        # オフセットが正のとき: チェーンを進む
        while init_dist > cur_total and cur_total > 0:
            overflow = init_dist - cur_total
            # 同じ _ad_advance ロジックで次の要素を探す
            end_pt = cur_cl[-1]
            ex, ey = end_pt[0], end_pt[1]
            if len(cur_cl) >= 2:
                dx = cur_cl[-1][0] - cur_cl[-2][0]
                dy = cur_cl[-1][1] - cur_cl[-2][1]
                ln = math.hypot(dx, dy) or 1.0
                fwd_x, fwd_y = dx / ln, dy / ln
            else:
                fwd_x, fwd_y = 1.0, 0.0

            cur_elem = next((e for e in self._elem_graph if e["id"] == cur_id), None)
            exit_clo_ref = None
            if cur_elem:
                exit_clo_ref = cur_elem.get("end_clo_ref" if cur_fwd else "start_clo_ref")

            cands = self._find_next_candidates(cur_id, ex, ey, exit_clo_ref)
            cands = [(e, f) for e, f in cands
                     if fwd_x * _elem_fwd_vec(e, f)[0]
                      + fwd_y * _elem_fwd_vec(e, f)[1] >= 0]
            if not cands:
                # ワープ
                B = self._warp_boundary
                new_x = -ex if abs(ex) > B else ex
                new_y = -ey if abs(ey) > B else ey
                pl = 100.0; n = 50
                z_end = cur_cl[-1][2]
                cur_cl = [(new_x+fwd_x*pl*t/n, new_y+fwd_y*pl*t/n, z_end, pl*t/n)
                          for t in range(n+1)]
                cur_total = pl
                cur_id    = None
                init_dist = overflow
                break

            chosen_elem, chosen_fwd = random.choice(cands)
            cl2, total2 = self._make_elem_cl(chosen_elem, chosen_fwd)
            cur_cl    = cl2
            cur_total = total2
            cur_id    = chosen_elem["id"]
            cur_fwd   = chosen_fwd
            init_dist = overflow

        # オフセットが負のとき: チェーンを逆に辿る
        while init_dist < 0 and cur_total > 0:
            need = -init_dist
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

            cur_elem = next((e for e in self._elem_graph if e["id"] == cur_id), None)
            exit_clo_ref = None
            if cur_elem:
                exit_clo_ref = cur_elem.get("start_clo_ref" if cur_fwd else "end_clo_ref")

            cands = self._find_next_candidates(cur_id, sx, sy, exit_clo_ref)
            cands = [(e,f) for e,f in cands
                     if rfwd_x*_fwd_vec(e,f)[0]+rfwd_y*_fwd_vec(e,f)[1] >= 0]
            if not cands:
                break

            chosen_elem, chosen_fwd = random.choice(cands)
            cl2, total2 = self._make_elem_cl(chosen_elem, chosen_fwd)
            cur_cl    = cl2
            cur_total = total2
            cur_id    = chosen_elem["id"]
            cur_fwd   = chosen_fwd
            init_dist = total2 + init_dist  # total2 - need

        init_dist = max(0.0, min(init_dist, cur_total))

        car_state = {
            "np":        np_root,
            "cl":        cur_cl,
            "total":     cur_total,
            "dist":      init_dist,
            "cur_id":    cur_id,
            "forward":   cur_fwd,
            "speed_mul": random.uniform(0.7, 1.3),  # 個別速度係数（±30%）
        }
        self._traffic.append(car_state)
        # 初期位置にセット
        self._update_traffic_car_pose(car_state)

    def _find_next_candidates(self, cur_id, ex, ey, exit_clo_ref):
        """_ad_advance と同じ隣接候補探索を返す（(elem, forward) のリスト）。"""
        import math
        cands = []
        for elem in self._elem_graph:
            if elem["id"] == cur_id:
                continue
            sx, sy = elem["start"]
            ex2, ey2 = elem["end"]
            s_ref = elem.get("start_clo_ref")
            e_ref = elem.get("end_clo_ref")
            if exit_clo_ref is not None:
                cid = exit_clo_ref["clothoid_id"]
                side = exit_clo_ref["side"]
                if s_ref and s_ref["clothoid_id"]==cid and s_ref["side"]==side:
                    cands.append((elem, True)); continue
                if e_ref and e_ref["clothoid_id"]==cid and e_ref["side"]==side:
                    cands.append((elem, False)); continue
            else:
                if math.hypot(ex-sx, ey-sy) < self.AD_TOL:
                    cands.append((elem, True))
                elif math.hypot(ex-ex2, ey-ey2) < self.AD_TOL:
                    cands.append((elem, False))
        return cands

    def _make_elem_cl(self, elem, forward):
        """_ad_start_elem と同じロジックで (cl, total) を返す。"""
        import math
        pl = elem["plan_length"]
        heights = elem.get("heights", [[0.0,0.0],[pl,0.0]])
        pts_xy  = elem.get("points_xy", None)
        if not forward:
            if pts_xy: pts_xy = list(reversed(pts_xy))
            heights = [[pl-h[0],h[1]] for h in reversed(heights)]

        def _elev(d):
            if not heights: return 0.0
            if d <= heights[0][0]: return heights[0][1]
            for k in range(len(heights)-1):
                d0,z0 = heights[k]; d1,z1 = heights[k+1]
                if d0 <= d <= d1:
                    t = (d-d0)/(d1-d0) if d1>d0 else 0
                    return z0+(z1-z0)*t
            return heights[-1][1]

        new_cl = []
        if pts_xy and len(pts_xy) >= 2:
            cum = [0.0]
            for k in range(1, len(pts_xy)):
                dx = pts_xy[k][0]-pts_xy[k-1][0]
                dy = pts_xy[k][1]-pts_xy[k-1][1]
                cum.append(cum[-1]+math.hypot(dx,dy))
            total = cum[-1]
            scale = pl/total if total > 1e-9 else 1.0
            for k,(xy,cd) in enumerate(zip(pts_xy,cum)):
                d = cd*scale
                new_cl.append((xy[0],xy[1],_elev(d),d))
        else:
            sx,sy = elem["start"] if forward else elem["end"]
            ex,ey = elem["end"]   if forward else elem["start"]
            n = max(2,int(pl*0.5))
            for i in range(n+1):
                t = i/n; d = pl*t
                new_cl.append((sx+(ex-sx)*t, sy+(ey-sy)*t, _elev(d), d))
        return new_cl, pl

    def _update_traffic_car_pose(self, car: dict):
        """周囲車両 1 台の位置・姿勢を更新する。"""
        import math
        pos, fwd, _ = self._interp_cl(car["cl"], car["dist"])
        np_root = car["np"]
        np_root.setPos(pos[0], pos[1], pos[2])
        heading = math.degrees(math.atan2(-fwd[0], fwd[1]))
        pitch   = math.degrees(math.atan2(fwd[2], math.hypot(fwd[0], fwd[1])))
        np_root.setHpr(heading, pitch, 0)

    def _step_traffic_car(self, car: dict, dt: float):
        """周囲車両 1 台を 1 フレーム進める。"""
        import math, random

        car["dist"] += self.speed * car.get("speed_mul", 1.0) * dt
        if car["dist"] < car["total"]:
            return

        overflow = car["dist"] - car["total"]
        end_pt = car["cl"][-1]
        ex, ey = end_pt[0], end_pt[1]
        if len(car["cl"]) >= 2:
            dx = car["cl"][-1][0] - car["cl"][-2][0]
            dy = car["cl"][-1][1] - car["cl"][-2][1]
            ln = math.hypot(dx,dy) or 1.0
            fwd_x, fwd_y = dx/ln, dy/ln
        else:
            fwd_x, fwd_y = 1.0, 0.0

        cur_elem = next((e for e in self._elem_graph if e["id"] == car["cur_id"]), None)
        exit_clo_ref = None
        if cur_elem:
            exit_clo_ref = cur_elem.get("end_clo_ref" if car["forward"] else "start_clo_ref")

        cands = self._find_next_candidates(car["cur_id"], ex, ey, exit_clo_ref)
        cands = [(e, f) for e, f in cands
                 if fwd_x * _elem_fwd_vec(e, f)[0]
                  + fwd_y * _elem_fwd_vec(e, f)[1] >= 0]

        if cands:
            chosen_elem, chosen_fwd = random.choice(cands)
            cl2, total2 = self._make_elem_cl(chosen_elem, chosen_fwd)
            car["cl"]      = cl2
            car["total"]   = total2
            car["dist"]    = min(overflow, total2)
            car["cur_id"]  = chosen_elem["id"]
            car["forward"] = chosen_fwd
        else:
            # ワープ
            B = self._warp_boundary
            new_x = -ex if abs(ex) > B else ex
            new_y = -ey if abs(ey) > B else ey
            z_end = car["cl"][-1][2]
            pl = 100.0; n = 50
            car["cl"]    = [(new_x+fwd_x*pl*t/n, new_y+fwd_y*pl*t/n, z_end, pl*t/n)
                            for t in range(n+1)]
            car["total"] = pl
            car["dist"]  = min(overflow, pl)
            car["cur_id"] = None

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
            right_down  = mwn.isButtonDown(MouseButton.two())
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
        import math

        # 自車の現在位置・方向
        cur_cl   = self._ad_cl if self._auto_drive else self.cl
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
        for np in self._surface_nodes:
            if visible:
                np.show()
            else:
                np.hide()

    def _toggle_surface(self):
        self.ROAD_SURFACE = not self.ROAD_SURFACE
        self._apply_surface_visible(self.ROAD_SURFACE)

    def _setup_lighting(self):
        alight = AmbientLight("ambient")
        alight.set_color(LColor(0.45, 0.45, 0.45, 1))
        self.render.set_light(self.render.attachNewNode(alight))

        dlight = DirectionalLight("sun")
        dlight.set_color(LColor(0.85, 0.85, 0.75, 1))
        dlnp = self.render.attachNewNode(dlight)
        dlnp.set_hpr(45, -45, 0)
        self.render.set_light(dlnp)

    def _setup_hud(self):
        self.hud = OnscreenText(
            text="", pos=(-1.3, 0.9), scale=0.05,
            fg=(1,1,1,1), shadow=(0,0,0,1),
            align=TextNode.ALeft, mayChange=True)

    def _setup_keys(self):
        self.accept("escape",       sys.exit)
        self.accept("v",            self._toggle_view)
        self.accept("o",            self._toggle_overview)
        self.accept("r",            self._toggle_surface)
        self.accept("space",        self._toggle_pause)
        self.accept("a",            self._toggle_auto_drive)
        self.accept("arrow_up",     lambda: self._change_speed(+10))
        self.accept("arrow_down",   lambda: self._change_speed(-10))
        self.accept("arrow_left",   self._rewind)
        self.accept("arrow_right",  self._forward)
        # 台数増減: p = plus（増やす）、m = minus（減らす）
        self.accept("p",            self._add_one_traffic)
        self.accept("shift-p",      self._remove_one_traffic)
        # 俯瞰ズーム: i=近づく、k=遠ざかる（overview/overview_fixed で有効）
        self.accept("i",            self._overview_zoom_in)
        self.accept("k",            self._overview_zoom_out)

    # ─── 走行処理 ────────────────────────────────────────────
    def _move_task(self, task):
        # 固定俯瞰視点のパン（右ドラッグまたは中ドラッグ）
        if self.view_mode == "overview_fixed":
            self._overview_pan()

        if not self.paused:
            dt = globalClock.get_dt()
            if self._auto_drive:
                self._ad_step(dt)
            elif self._total > 0:
                self.dist = (self.dist + self.speed * dt) % self._total

        cur_cl   = self._ad_cl if self._auto_drive else self.cl
        cur_dist = self._ad_dist if self._auto_drive else self.dist
        self._update_car_pose_cl(cur_cl, cur_dist)
        self._update_camera_cl(cur_cl, cur_dist)

        # HUD 用に現在の位置・方向を保存
        pos, fwd, _ = self._interp_cl(cur_cl, cur_dist)
        self._cur_pos = pos
        self._cur_fwd = fwd

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
        """オートドライブの1フレーム処理。"""
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
            candidates = _direction_filter(dist_cands)

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
        pl      = elem["plan_length"]
        heights = elem.get("heights", [[0.0, 0.0], [pl, 0.0]])
        pts_xy  = elem.get("points_xy", None)  # [[x, y], ...] 正順

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
                dx = pts_xy[k][0] - pts_xy[k-1][0]
                dy = pts_xy[k][1] - pts_xy[k-1][1]
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
            ex, ey = elem["end"]   if forward else elem["start"]
            n = max(2, int(pl * 0.5))
            for i in range(n + 1):
                t = i / n
                d = pl * t
                z = _elev(d)
                new_cl.append((sx + (ex-sx)*t, sy + (ey-sy)*t, z, d))

        self._ad_cur_id  = elem["id"]
        self._ad_forward = forward
        self._ad_cl      = new_cl
        self._ad_total   = pl
        # 余剰距離を引き継いで位置を連続させる（チェーン長を超える場合は末端にクランプ）
        self._ad_dist    = min(overflow, pl)

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
        pl    = 100.0
        n     = 50
        z_end = self._ad_cl[-1][2] if self._ad_cl else 0.0
        new_cl = []
        for i in range(n + 1):
            t = i / n
            x = new_x + fwd_x * pl * t   # 方向はそのまま
            y = new_y + fwd_y * pl * t
            d = pl * t
            new_cl.append((x, y, z_end, d))

        self._ad_cl     = new_cl
        self._ad_total  = pl
        self._ad_dist   = min(overflow, pl)
        self._ad_cur_id = None

    def _update_car_pose(self, dist: float):
        self._update_car_pose_cl(self.cl, dist)

    def _update_car_pose_cl(self, cl: list, dist: float):
        pos, fwd, _ = self._interp_cl(cl, dist)
        self.car_np.set_pos(pos)
        heading = math.degrees(math.atan2(-fwd[0], fwd[1]))
        pitch   = math.degrees(math.atan2(fwd[2], math.hypot(fwd[0], fwd[1])))
        self.car_np.set_hpr(heading, pitch, 0)

    def _update_camera_cl(self, cl: list, dist: float):
        pos, fwd, _ = self._interp_cl(cl, dist)
        if self.view_mode == "follow":
            back = (-fwd[0] * self.CAM_BEHIND,
                    -fwd[1] * self.CAM_BEHIND,
                    self.CAM_ABOVE)
            cam_pos = LPoint3(pos[0]+back[0], pos[1]+back[1], pos[2]+back[2])
            self.camera.set_pos(cam_pos)
            look_ahead = 5.0
            look = LPoint3(pos[0] + fwd[0]*look_ahead,
                           pos[1] + fwd[1]*look_ahead,
                           pos[2] + fwd[2]*look_ahead)
            self.camera.look_at(look)
        elif self.view_mode == "overview":
            # 自車追従俯瞰: 自車の真上を追従
            self.camera.set_pos(LPoint3(pos[0], pos[1], pos[2] + self.CAM_OVERVIEW_H))
            self.camera.set_hpr(0, -90, 0)
        elif self.view_mode == "overview_fixed":
            # 固定俯瞰: カメラ位置を固定（マウスホイールで高度変更可能）
            ox, oy = self._overview_pos
            self.camera.set_pos(LPoint3(ox, oy, self.CAM_OVERVIEW_H))
            self.camera.set_hpr(0, -90, 0)
        else:
            # 運転席視点
            eye_forward = 2.0
            eye  = LPoint3(pos[0] + fwd[0]*eye_forward,
                           pos[1] + fwd[1]*eye_forward,
                           pos[2] + self.CAM_EYE_H)
            look = LPoint3(pos[0] + fwd[0]*20,
                           pos[1] + fwd[1]*20,
                           pos[2] + fwd[2]*20 + self.CAM_EYE_H)
            self.camera.set_pos(eye)
            self.camera.look_at(look)

    @staticmethod
    def _bearing_str(fwd_x: float, fwd_y: float) -> str:
        """進行方向ベクトル (fwd_x, fwd_y) を 8 方位文字列に変換する。

        座標系: x=東, y=北（設計アプリのワールド座標系に準拠）。

        Parameters
        ----------
        fwd_x, fwd_y : float
            進行方向の単位ベクトル。

        Returns
        -------
        str
            "N" / "NE" / "E" / "SE" / "S" / "SW" / "W" / "NW" のいずれか。
        """
        import math
        # atan2(y, x) → 北(+y)=90°, 東(+x)=0° の角度
        deg = math.degrees(math.atan2(fwd_y, fwd_x))
        # -180〜+180 → 0〜360（北=90°を0°に補正して時計回りに）
        # 方位角: 北=0°, 東=90°, 南=180°, 西=270°（時計回り）
        bearing = (90.0 - deg) % 360.0
        # 8方位に丸める（各方位 = 45° 幅）
        idx = int((bearing + 22.5) / 45.0) % 8
        return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][idx]

    def _update_hud(self):
        import math
        mode_str    = {"follow": "Follow", "onboard": "Onboard",
                       "overview": "Overview(track)",
                       "overview_fixed": "Overview(fixed)"}.get(self.view_mode, self.view_mode)
        pause_str   = "[PAUSED]\n" if self.paused else ""
        surface_str = "ON" if self.ROAD_SURFACE else "OFF"

        # 現在位置・方向
        px, py, pz = self._cur_pos
        fwd_x, fwd_y = self._cur_fwd[0], self._cur_fwd[1]
        bearing = self._bearing_str(fwd_x, fwd_y)

        if self._auto_drive:
            cur_dist  = self._ad_dist
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
            cur_dist  = self.dist
            cur_total = self._total
            auto_str  = ""

        self.hud.setText(
            f"{pause_str}"
            f"{auto_str}"
            f"Pos: ({px:.1f}, {py:.1f})  Alt: {pz:.1f} m\n"
            f"Dir: {bearing}  ({fwd_x:+.2f}, {fwd_y:+.2f})\n"
            f"Dist: {cur_dist:.0f} / {cur_total:.0f} m\n"
            f"Speed: {self.speed:.0f} m/s ({self.speed*3.6:.0f} km/h)\n"
            f"View: {mode_str} [V/O]  Surface: {surface_str} [R]  Auto [A]\n"
            f"Up/Down:Speed  Left/Right:Jump  Space:Pause  Esc:Quit\n"
            f"Traffic: {len(self._traffic)} cars  P:Add  Shift-P:Remove"
        )

    # ─── 補間 ────────────────────────────────────────────────
    def _interp(self, dist: float):
        """固定チェーン self.cl 上の dist に対する位置・方向を返す（後方互換）。"""
        return self._interp_cl(self.cl, dist)

    def _interp_cl(self, cl: list, dist: float):
        """任意の中心線 cl 上の累積距離 dist に対応する位置・方向を線形補間して返す。"""
        n = len(cl)
        if n == 0:
            return (0, 0, 0), (1, 0, 0), (0, -1, 0)
        for i in range(n - 1):
            d0 = cl[i][3]; d1 = cl[i+1][3]
            if d0 <= dist <= d1:
                t  = (dist - d0) / (d1 - d0) if d1 > d0 else 0
                x  = cl[i][0] + (cl[i+1][0] - cl[i][0]) * t
                y  = cl[i][1] + (cl[i+1][1] - cl[i][1]) * t
                z  = cl[i][2] + (cl[i+1][2] - cl[i][2]) * t
                dx = cl[i+1][0] - cl[i][0]
                dy = cl[i+1][1] - cl[i][1]
                dz = cl[i+1][2] - cl[i][2]
                ln = math.hypot(dx, dy, dz) or 1
                fwd   = (dx/ln, dy/ln, dz/ln)
                right = (fwd[1], -fwd[0], 0)
                return (x, y, z), fwd, right
        x, y, z, _ = cl[-1]
        return (x, y, z), (1, 0, 0), (0, -1, 0)


    # ─── 操作 ────────────────────────────────────────────────
    def _toggle_view(self):
        self.view_mode = "onboard" if self.view_mode == "follow" else "follow"

    def _toggle_overview(self):
        """O キーで俯瞰視点をサイクルする。

        follow / onboard → overview（自車追従）→ overview_fixed（カメラ固定）→ follow
        """
        if self.view_mode in ("follow", "onboard"):
            # 現在の自車位置を固定俯瞰の初期位置として保存
            cur_cl   = self._ad_cl if self._auto_drive else self.cl
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
        self.paused = not self.paused

    def _toggle_auto_drive(self):
        """A キーでオートドライブモードを切り替える。"""
        self._auto_drive = not self._auto_drive
        if self._auto_drive and self._start_info:
            # オートドライブ開始時は元の走行チェーンにリセット
            self._ad_cl    = self.cl
            self._ad_total = self._total
            self._ad_dist  = self.dist  # 現在位置から再開
            self._ad_cur_id  = self._start_info["id"]
            self._ad_forward = self._start_info["forward"]

    def _change_speed(self, delta: float):
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
            "cl":      self._ad_cl,
            "total":   self._ad_total,
            "dist":    self._ad_dist,
            "cur_id":  self._ad_cur_id,
            "forward": self._ad_forward,
        }
        self._ad_history.append(snap)
        if len(self._ad_history) > self._AD_HISTORY_MAX:
            self._ad_history.pop(0)

    def _rewind(self):
        if self._auto_drive:
            new_dist = self._ad_dist - 100
            if new_dist < 0 and self._ad_history:
                if self._ad_history_idx < 0:
                    self._ad_history_idx = len(self._ad_history) - 1
                elif self._ad_history_idx > 0:
                    self._ad_history_idx -= 1
                if self._ad_history_idx >= 0:
                    snap = self._ad_history[self._ad_history_idx]
                    self._ad_cl      = snap["cl"]
                    self._ad_total   = snap["total"]
                    self._ad_dist    = 0.0
                    self._ad_cur_id  = snap["cur_id"]
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
        if self._auto_drive:
            if self._ad_history_idx >= 0:
                self._ad_history_idx += 1
                if self._ad_history_idx >= len(self._ad_history):
                    self._ad_history_idx = -1
                else:
                    snap = self._ad_history[self._ad_history_idx]
                    self._ad_cl      = snap["cl"]
                    self._ad_total   = snap["total"]
                    self._ad_dist    = 0.0
                    self._ad_cur_id  = snap["cur_id"]
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
        {"centerline_3d": [...], "display_segments": [[...], ...]} 形式の辞書。
        JSON シリアライズ可能。
    """
    display_segs = []
    if all_display:
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
                display_segs.append(cl)

    # オートドライブ用: 全要素の端点グラフを構築
    all_elems = []
    for ln in scene.lines:
        all_elems.extend(ln.segments)
    for ci in scene.circles:
        all_elems.extend(ci.arcs)
    all_elems.extend(scene.clothoids)

    # ── Clothoid の接点情報を収集（端点とClothoidの対応マップ）──────────────
    # (x, y) → [(clothoid_id, "line"|"circle"), ...] のマップ
    # 各端点がどのClothoidのどちら側の接点かを記録する
    CLO_REF_TOL = 1e-4   # 接点との一致判定閾値 [m]
    clo_ref_map = {}     # key: (round(x,4), round(y,4)) → list of (clo_id, side)

    for clo in scene.clothoids:
        if not clo.is_valid:
            continue
        for side, pt in [("line", clo._line_pt), ("circle", clo._circle_pt)]:
            if pt is None:
                continue
            key = (round(pt.x, 3), round(pt.y, 3))
            if key not in clo_ref_map:
                clo_ref_map[key] = []
            clo_ref_map[key].append({"clothoid_id": clo.id, "side": side})

    def _lookup_clo_ref(x, y):
        """座標 (x, y) に対応する Clothoid 接点参照を返す。なければ None。"""
        key = (round(x, 3), round(y, 3))
        refs = clo_ref_map.get(key)
        return refs[0] if refs else None

    elem_graph = []    # [{id, type, start, end, plan_length, heights, points_xy,
                       #   start_clo_ref, end_clo_ref}, ...]
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
        heights = []
        if ep:
            for i in range(n_h + 1):
                d   = pl * i / n_h
                elv = ep.elev_at(d)
                heights.append([d, elv])
        else:
            heights = [[0.0, 0.0], [pl, 0.0]]

        # 平面形状点列をサンプリング（要素の種類に応じて正確な曲線形状を生成）
        n_pts = max(4, int(pl * 0.5))
        points_xy = []   # [[x, y], ...] 正順（start→end）
        if isinstance(obj, Segment):
            for i in range(n_pts + 1):
                t = i / n_pts
                x = obj.start.x + (obj.end.x - obj.start.x) * t
                y = obj.start.y + (obj.end.y - obj.start.y) * t
                points_xy.append([x, y])
        elif isinstance(obj, Arc):
            ci = obj.circle
            a0 = obj.angle_start
            span = obj.arc_angle()   # 常に正（CCW）
            for i in range(n_pts + 1):
                ang = a0 + span * i / n_pts
                x = ci.center.x + ci.radius * math.cos(ang)
                y = ci.center.y + ci.radius * math.sin(ang)
                points_xy.append([x, y])
        elif isinstance(obj, Clothoid):
            raw = obj.points   # Vec2 リスト
            if raw:
                cum = [0.0]
                for k in range(1, len(raw)):
                    dx = raw[k].x - raw[k-1].x
                    dy = raw[k].y - raw[k-1].y
                    cum.append(cum[-1] + math.hypot(dx, dy))
                total = cum[-1]
                for i in range(n_pts + 1):
                    target = total * i / n_pts
                    for k in range(len(cum) - 1):
                        if cum[k] <= target <= cum[k+1]:
                            t = ((target - cum[k]) / (cum[k+1] - cum[k])
                                 if cum[k+1] > cum[k] else 0)
                            x = raw[k].x + (raw[k+1].x - raw[k].x) * t
                            y = raw[k].y + (raw[k+1].y - raw[k].y) * t
                            points_xy.append([x, y])
                            break
                    else:
                        points_xy.append([raw[-1].x, raw[-1].y])

        if not points_xy:
            points_xy = [[s.x, s.y], [e.x, e.y]]

        # 端点に対応するClothoid接点参照を取得
        start_clo_ref = _lookup_clo_ref(s.x, s.y)
        end_clo_ref   = _lookup_clo_ref(e.x, e.y)

        elem_graph.append({
            "id":            obj.id,
            "type":          type(obj).__name__,
            "nickname":      scene.get_nickname(obj.id,
                                 "seg" if isinstance(obj, Segment) else
                                 "arc" if isinstance(obj, Arc) else "clothoid"),
            "start":         [s.x, s.y],
            "end":           [e.x, e.y],
            "plan_length":   pl,
            "heights":       heights,
            "points_xy":     points_xy,
            # どのClothoidのどちら側の接点が端点になっているか
            # None: Clothoid接点ではない端点
            # {"clothoid_id": int, "side": "line"|"circle"}: Clothoid接点
            "start_clo_ref": start_clo_ref,
            "end_clo_ref":   end_clo_ref,
        })

    # 走行チェーン先頭要素と方向を記録（オートドライブの起点）
    start_info = None
    if elements:
        first = elements[0]
        pts = _elem_endpoints_xy(first)
        if pts:
            if rev_flags[0]:
                start_info = {"id": first.id, "forward": False}
            else:
                start_info = {"id": first.id, "forward": True}

    return {
        "centerline_3d":    build_centerline(elements, profiles, rev_flags),
        "display_segments": display_segs,
        "elem_graph":       elem_graph,
        "start_info":       start_info,
    }


def launch_viewer(scene: Scene,
                  elements: list,
                  profiles: list,
                  rev_flags: list[bool],
                  all_display: list = None,
                  warp_boundary: float = None):
    """
    設計アプリのメインウィンドウから呼ぶ。別プロセスで Panda3D ウィンドウを起動する。

    Parameters
    ----------
    elements/profiles/rev_flags : 走行チェーン
    all_display : 表示する全要素（線分・円弧・クロソイド）
    warp_boundary : float, optional
        オートドライブのワープ境界 [m]。None のとき RoadViewer.WARP_BOUNDARY(=500m)。
    """
    import subprocess, tempfile, os

    data = prepare_viewer_data(scene, elements, profiles, rev_flags, all_display)

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
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    centerline   = [tuple(p) for p in data["centerline_3d"]]
    display_segs = [[tuple(p) for p in seg]
                    for seg in data.get("display_segments", [])]
    elem_graph   = data.get("elem_graph", None)
    start_info   = data.get("start_info", None)
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
