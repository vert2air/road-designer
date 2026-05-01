"""
road_viewer.py  ―  Panda3D による道路 3D 走行ビューア

平面線形（Segment / Arc / Clothoid）と縦断線形（ElementProfile）から
3D 中心線を生成し、道路メッシュを表示して車が走る。

座標系変換:
  設計アプリ  (x右, y上, ワールド) → Panda3D (x右, y奥, z上)
  変換: P3D.x = world.x,  P3D.y = world.y,  P3D.z = height
"""
from __future__ import annotations
import math, sys, json
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
    plan_length_of,
)


# ══════════════════════════════════════════════════════════════
#   3D 中心線の生成
# ══════════════════════════════════════════════════════════════

def _ep_elev(ep: 'ElementProfile', rel: float) -> float:
    """EP 内の相対距離 rel での高さを返す（縦断曲線優先）"""
    rel = max(0.0, min(rel, ep.plan_length))
    for vc in ep.vertical_curves:
        if vc.vpc_dist - 0.001 <= rel <= vc.vpt_dist + 0.001:
            e = vc.elevation_at(rel)
            if not math.isnan(e):
                return e
    for gl in sorted(ep.grade_lines, key=lambda g: g.dist_start):
        if gl.dist_start - 0.001 <= rel <= gl.dist_end + 0.001:
            t = ((rel - gl.dist_start) / (gl.dist_end - gl.dist_start)
                 if abs(gl.dist_end - gl.dist_start) > 1e-9 else 0)
            return gl.elev_start + (gl.elev_end - gl.elev_start) * t
    return 0.0


def _elev_at_dist(dist: float, profiles: list,
                  offsets: list) -> float:
    """
    チェーン累積距離 dist に対する標高を返す。
    縦断曲線（VPC〜VPT）の範囲では縦断曲線の値を優先し、
    それ以外は勾配直線から補間する。
    """
    n = len(profiles)
    for i, (ep, off) in enumerate(zip(profiles, offsets)):
        d_end = off + ep.plan_length
        is_last = (i == n - 1)
        if dist >= d_end - 1e-9 and not is_last:
            continue
        if dist > d_end + 1e-9:
            continue
        rel = max(0.0, min(dist - off, ep.plan_length))
        return _ep_elev(ep, rel)
    return 0.0


def build_centerline(elements: list, profiles: list[ElementProfile],
                     rev_flags: list[bool],
                     n_per_m: float = 0.5) -> list[tuple]:
    """
    平面線形要素チェーンから 3D 中心線点列を生成する。
    戻り値: [(x, y, z, dist), ...]  ← Panda3D 座標 (x右, y奥, z上)
    """
    # 累積オフセット計算
    offsets = []
    acc = 0.0
    for ep in profiles:
        offsets.append(acc)
        acc += ep.plan_length

    points = []

    for elem, ep, offset, rev in zip(elements, profiles, offsets, rev_flags):
        L = ep.plan_length
        if L < 0.001:
            continue
        n = max(2, int(L * n_per_m))
        pts_2d = []  # [(x, y), ...]  正順

        if isinstance(elem, Segment):
            s = elem.start
            e = elem.end
            for i in range(n + 1):
                t = i / n
                pts_2d.append((s.x + (e.x - s.x) * t,
                               s.y + (e.y - s.y) * t))

        elif isinstance(elem, Arc):
            ci = elem.circle
            a0 = elem.angle_start
            a1 = elem.angle_end
            span = (a1 - a0) % (2 * math.pi)  # CCW
            for i in range(n + 1):
                ang = a0 + span * i / n
                pts_2d.append((ci.center.x + ci.radius * math.cos(ang),
                               ci.center.y + ci.radius * math.sin(ang)))

        elif isinstance(elem, Clothoid):
            raw = elem.points  # Vec2 リスト（既にワールド座標）
            if not raw:
                continue
            # raw を n 点にリサンプリング
            cum = [0.0]
            for k in range(1, len(raw)):
                dx = raw[k].x - raw[k-1].x
                dy = raw[k].y - raw[k-1].y
                cum.append(cum[-1] + math.hypot(dx, dy))
            total = cum[-1]
            for i in range(n + 1):
                target = total * i / n
                # 線形補間
                for k in range(len(cum) - 1):
                    if cum[k] <= target <= cum[k+1]:
                        t = ((target - cum[k]) / (cum[k+1] - cum[k])
                             if cum[k+1] > cum[k] else 0)
                        x = raw[k].x + (raw[k+1].x - raw[k].x) * t
                        y = raw[k].y + (raw[k+1].y - raw[k].y) * t
                        pts_2d.append((x, y))
                        break
                else:
                    pts_2d.append((raw[-1].x, raw[-1].y))

        if not pts_2d:
            continue

        if rev:
            pts_2d = list(reversed(pts_2d))

        for i, (wx, wy) in enumerate(pts_2d):
            dist = offset + L * i / n
            # 各要素の先頭点（i=0）は前の要素の末端と座標が重複する
            # 前の要素の末端高さをそのまま継承して段差を防ぐ
            if i == 0 and points:
                z = points[-1][2]
            else:
                z = _ep_elev(ep, dist - offset if not rev else L - (dist - offset))
            points.append((wx, wy, z, dist))

    return points


# ══════════════════════════════════════════════════════════════
#   道路メッシュの生成
# ══════════════════════════════════════════════════════════════

def build_road_mesh(centerline: list[tuple],
                    half_width: float = 4.0,
                    color_override: LColor = None) -> GeomNode:
    """中心線から道路帯状メッシュを生成して GeomNode を返す"""
    fmt  = GeomVertexFormat.get_v3n3c4()
    vdata = GeomVertexData("road", fmt, Geom.UH_static)
    vw    = GeomVertexWriter(vdata, "vertex")
    nw    = GeomVertexWriter(vdata, "normal")
    cw    = GeomVertexWriter(vdata, "color")

    tris = GeomTriangles(Geom.UH_static)

    road_color = color_override if color_override else LColor(0.25, 0.25, 0.25, 1)

    n = len(centerline)
    if n < 2:
        return GeomNode("road")

    for i in range(n):
        x, y, z, _ = centerline[i]
        if i == 0:
            tx = centerline[1][0] - x; ty = centerline[1][1] - y
        elif i == n - 1:
            tx = x - centerline[n-2][0]; ty = y - centerline[n-2][1]
        else:
            tx = centerline[i+1][0] - centerline[i-1][0]
            ty = centerline[i+1][1] - centerline[i-1][1]
        length = math.hypot(tx, ty)
        if length < 1e-9: tx, ty = 1, 0
        else: tx /= length; ty /= length
        nx_v, ny_v = ty, -tx

        for side in (-1, 1):
            px = x + side * half_width * nx_v
            py = y + side * half_width * ny_v
            vw.add_data3(px, py, z)
            nw.add_data3(0, 0, 1)
            cw.add_data4(road_color)

    for i in range(n - 1):
        bl = i*2; br = i*2+1; tl = (i+1)*2; tr = (i+1)*2+1
        tris.add_vertices(bl, tl, tr)
        tris.add_vertices(bl, tr, br)

    geom = Geom(vdata)
    geom.add_primitive(tris)
    node = GeomNode("road")
    node.add_geom(geom)
    return node


def build_center_line_node(centerline: list[tuple],
                            color_override: LColor = None) -> GeomNode:
    """センターラインを GeomNode として返す"""
    from panda3d.core import GeomLinestrips
    fmt   = GeomVertexFormat.get_v3c4()
    vdata = GeomVertexData("cl", fmt, Geom.UH_static)
    vw    = GeomVertexWriter(vdata, "vertex")
    cw    = GeomVertexWriter(vdata, "color")
    ls    = GeomLinestrips(Geom.UH_static)
    color = color_override if color_override else LColor(1, 0.9, 0.1, 1)

    for i, (x, y, z, _) in enumerate(centerline):
        vw.add_data3(x, y, z + 0.05)
        cw.add_data4(color)
        ls.add_vertex(i)
    ls.close_primitive()

    geom = Geom(vdata)
    geom.add_primitive(ls)
    node = GeomNode("centerline")
    node.add_geom(geom)
    return node


def build_ground(cx: float, cy: float, size: float = 2000) -> GeomNode:
    """地面の平板メッシュ"""
    fmt   = GeomVertexFormat.get_v3n3c4()
    vdata = GeomVertexData("ground", fmt, Geom.UH_static)
    vw    = GeomVertexWriter(vdata, "vertex")
    nw    = GeomVertexWriter(vdata, "normal")
    cw    = GeomVertexWriter(vdata, "color")
    col   = LColor(0.3, 0.5, 0.25, 1)
    hs    = size / 2
    for dx, dy in [(-hs,-hs),( hs,-hs),( hs, hs),(-hs, hs)]:
        vw.add_data3(cx+dx, cy+dy, -0.1)
        nw.add_data3(0, 0, 1)
        cw.add_data4(col)
    tris = GeomTriangles(Geom.UH_static)
    tris.add_vertices(0, 1, 2)
    tris.add_vertices(0, 2, 3)
    geom = Geom(vdata)
    geom.add_primitive(tris)
    node = GeomNode("ground")
    node.add_geom(geom)
    return node


# ══════════════════════════════════════════════════════════════
#   Panda3D アプリ
# ══════════════════════════════════════════════════════════════

class RoadViewer(ShowBase):
    SPEED_DEFAULT = 30.0   # m/s
    CAM_BEHIND    = 20.0   # 外部視点: 後方距離
    CAM_ABOVE     = 6.0    # 外部視点: 高さ
    CAM_EYE_H    = 1.5    # 車載視点: 目の高さ

    def __init__(self, centerline: list[tuple],
                 display_segs: list[list[tuple]] = None):
        ShowBase.__init__(self)
        self.cl          = centerline
        self.disp_segs   = display_segs or []
        self.dist        = 0.0
        self.speed       = self.SPEED_DEFAULT
        self.view_mode   = "follow"
        self.paused      = False
        self._total      = centerline[-1][3] if centerline else 0.0

        self._build_scene()
        self._setup_hud()
        self._setup_lighting()
        self.taskMgr.add(self._move_task, "move")
        self._setup_keys()

        # マウス無効化（デフォルトのカメラ操作を切る）
        self.disableMouse()

    # ─── シーン構築 ──────────────────────────────────────────
    def _build_scene(self):
        # 全要素の背景道路メッシュ（要素ごとに独立して生成）
        for seg_cl in self.disp_segs:
            if len(seg_cl) < 2:
                continue
            bg_node = build_road_mesh(seg_cl, half_width=4.0,
                                      color_override=LColor(0.3, 0.3, 0.3, 1))
            self.render.attachNewNode(bg_node)
            bg_cl = build_center_line_node(seg_cl,
                                           color_override=LColor(0.55, 0.55, 0.55, 1))
            self.render.attachNewNode(bg_cl)

        # 走行チェーンの道路メッシュ（明るく強調）
        road_node = build_road_mesh(self.cl, half_width=4.0)
        self.render.attachNewNode(road_node)
        cl_node = build_center_line_node(self.cl)
        self.render.attachNewNode(cl_node)

        # 地面（全表示要素の重心を中心に）
        all_pts = []
        for seg in self.disp_segs:
            all_pts.extend(seg)
        all_pts.extend(self.cl)
        if not all_pts:
            all_pts = self.cl
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
        gnd = build_ground(cx, cy)
        self.render.attachNewNode(gnd)

        # 車ダミー
        self.car_np = self.render.attachNewNode("car")
        cm = CardMaker("car_body")
        cm.set_frame(-1.0, 1.0, 0, 1.5)
        body = self.car_np.attachNewNode(cm.generate())
        body.set_p(-90)
        self._update_car_pose(0.0)

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
        self.accept("escape",  sys.exit)
        self.accept("v",       self._toggle_view)
        self.accept("space",   self._toggle_pause)
        self.accept("arrow_up",    lambda: self._change_speed(+10))
        self.accept("arrow_down",  lambda: self._change_speed(-10))
        self.accept("arrow_left",  self._rewind)
        self.accept("arrow_right", self._forward)

    # ─── 走行処理 ────────────────────────────────────────────
    def _move_task(self, task):
        if not self.paused and self._total > 0:
            dt = globalClock.get_dt()
            self.dist = (self.dist + self.speed * dt) % self._total

        self._update_car_pose(self.dist)
        self._update_camera()
        self._update_hud()
        return Task.cont

    def _update_car_pose(self, dist: float):
        """距離 dist に対応する位置・姿勢を車のノードに設定"""
        pos, fwd, _ = self._interp(dist)
        self.car_np.set_pos(pos)
        # 進行方向を向く (Panda3D: H=ヨー, P=ピッチ, R=ロール)
        heading = math.degrees(math.atan2(-fwd[0], fwd[1]))  # Panda3D の H
        pitch   = math.degrees(math.atan2(fwd[2], math.hypot(fwd[0], fwd[1])))
        self.car_np.set_hpr(heading, pitch, 0)

    def _update_camera(self):
        pos, fwd, _ = self._interp(self.dist)
        if self.view_mode == "follow":
            # 後方上方から追従
            back = (-fwd[0] * self.CAM_BEHIND,
                    -fwd[1] * self.CAM_BEHIND,
                    self.CAM_ABOVE)
            cam_pos = LPoint3(pos[0]+back[0], pos[1]+back[1], pos[2]+back[2])
            self.camera.set_pos(cam_pos)
            self.camera.look_at(LPoint3(*pos))
        else:
            # 車載視点
            eye = LPoint3(pos[0], pos[1], pos[2] + self.CAM_EYE_H)
            look = LPoint3(pos[0] + fwd[0]*5,
                           pos[1] + fwd[1]*5,
                           pos[2] + fwd[2]*5 + self.CAM_EYE_H)
            self.camera.set_pos(eye)
            self.camera.look_at(look)

    def _update_hud(self):
        mode_str = "Follow" if self.view_mode == "follow" else "Onboard"
        pause_str = "[PAUSED]\n" if self.paused else ""
        self.hud.setText(
            f"{pause_str}"
            f"Dist: {self.dist:.0f} / {self._total:.0f} m\n"
            f"Speed: {self.speed:.0f} m/s ({self.speed*3.6:.0f} km/h)\n"
            f"View: {mode_str} [V]\n"
            f"Up/Down:Speed  Left/Right:Jump  Space:Pause  Esc:Quit")

    # ─── 補間 ────────────────────────────────────────────────
    def _interp(self, dist: float):
        """
        累積距離 dist に対する (位置, 前方ベクトル, 右ベクトル) を返す
        位置は (x, y, z) タプル
        """
        cl = self.cl
        n  = len(cl)
        # 対応セグメントを探す
        for i in range(n - 1):
            d0 = cl[i][3]
            d1 = cl[i+1][3]
            if d0 <= dist <= d1:
                t = (dist - d0) / (d1 - d0) if d1 > d0 else 0
                x = cl[i][0] + (cl[i+1][0] - cl[i][0]) * t
                y = cl[i][1] + (cl[i+1][1] - cl[i][1]) * t
                z = cl[i][2] + (cl[i+1][2] - cl[i][2]) * t
                dx = cl[i+1][0] - cl[i][0]
                dy = cl[i+1][1] - cl[i][1]
                dz = cl[i+1][2] - cl[i][2]
                ln = math.hypot(dx, dy, dz) or 1
                fwd = (dx/ln, dy/ln, dz/ln)
                right = (fwd[1], -fwd[0], 0)
                return (x, y, z), fwd, right
        # 末端
        x, y, z, _ = cl[-1]
        return (x, y, z), (1, 0, 0), (0, -1, 0)

    # ─── 操作 ────────────────────────────────────────────────
    def _toggle_view(self):
        self.view_mode = "onboard" if self.view_mode == "follow" else "follow"

    def _toggle_pause(self):
        self.paused = not self.paused

    def _change_speed(self, delta: float):
        self.speed = max(1.0, self.speed + delta)

    def _rewind(self):
        self.dist = max(0, self.dist - 100)

    def _forward(self):
        self.dist = min(self._total, self.dist + 100)


# ══════════════════════════════════════════════════════════════
#   エントリーポイント：設計アプリから呼ばれる
# ══════════════════════════════════════════════════════════════

def launch_viewer(scene: Scene,
                  elements: list,
                  profiles: list[ElementProfile],
                  rev_flags: list[bool],
                  all_display: list = None):
    """
    設計アプリのメインウィンドウから呼ぶ。
    elements/profiles/rev_flags: 走行チェーン
    all_display: 表示する全要素（線分・円弧・クロソイド）
    """
    import subprocess, tempfile, os

    # all_display 用の中心線（走行なし・背景表示のみ）
    # 各要素を独立した点列として管理する（繋げない）
    display_segs = []   # list of list[tuple] — 要素ごとの独立点列
    if all_display:
        for obj in all_display:
            ep_dummy = ElementProfile()
            ep_dummy.plan_length = plan_length_of(obj)
            if ep_dummy.plan_length < 0.001:
                continue
            cl = build_centerline([obj], [ep_dummy], [False], n_per_m=0.5)
            if cl:
                display_segs.append(cl)

    data = {
        "centerline_3d":     build_centerline(elements, profiles, rev_flags),
        "display_segments":  display_segs,   # 要素ごとの独立点列
    }
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

    if not centerline:
        print("No centerline data.")
        return

    app = RoadViewer(centerline, display_segs)
    app.run()


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        _main_from_file(sys.argv[1])
    else:
        # テスト用: 単純な直線コースを走る
        centerline = [(i * 2.0, 0.0, 0.0, i * 2.0) for i in range(200)]
        app = RoadViewer(centerline)
        app.run()
