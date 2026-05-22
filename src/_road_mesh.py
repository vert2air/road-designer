"""道路 3D メッシュ生成ユーティリティ。

``build_centerline``・``build_road_mesh`` 等の純粋な数値/メッシュ生成関数群。
Panda3D の Geom API を直接使用するため Panda3D が必要。
``road_viewer.py`` から利用される。
"""
from __future__ import annotations
import math
from typing import Optional

# ─── Panda3D ──────────────────────────────────────────────────────────────
from panda3d.core import (
    GeomVertexFormat, GeomVertexData, GeomVertexWriter,
    Geom, GeomTriangles, GeomLinestrips, GeomNode,
    LColor,
)

# ─── 設計モデル ────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, ".")
from models import (
    Segment, Arc, Clothoid, ElementProfile,
)



def _tangent_normal_at(centerline: list, i: int) -> tuple[float, float, float, float]:
    """中心線点列のインデックス i における接線・法線単位ベクトルを返す。

    中差分（両端は前進/後退差分）で接線を計算し、右直交する法線を求める。

    Parameters
    ----------
    centerline : list[tuple]
        ``build_centerline`` が返す [(x, y, z, dist), ...] 形式の点列。
    i : int
        対象インデックス（0 ≦ i < len(centerline)）。

    Returns
    -------
    (tx, ty, nx, ny) : tuple[float, float, float, float]
        接線単位ベクトル (tx, ty) と右法線単位ベクトル (nx, ny)。
    """
    n = len(centerline)
    x, y = centerline[i][0], centerline[i][1]
    if i == 0:
        dx, dy = centerline[1][0] - x, centerline[1][1] - y
    elif i == n - 1:
        dx, dy = x - centerline[n-2][0], y - centerline[n-2][1]
    else:
        dx = centerline[i+1][0] - centerline[i-1][0]
        dy = centerline[i+1][1] - centerline[i-1][1]
    ln = math.hypot(dx, dy)
    if ln < 1e-9:
        dx, dy = 1.0, 0.0
    else:
        dx /= ln; dy /= ln
    return dx, dy, dy, -dx  # (tx, ty, nx, ny)  右法線 = (ty, -tx)


def _elev_at_dist(dist: float, profiles: list,
                  offsets: list) -> float:
    """チェーン累積距離 dist に対する標高を返す（縦断曲線優先）。

    Returns
    -------
    float
        標高 [m]。dist がチェーン全体を超える場合は 0.0。
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
        return ep.elev_at(rel)
    return 0.0




def build_car_box(length: float = 4.0, width: float = 2.0,
                  height: float = 1.5) -> GeomNode:
    """車を表す直方体の GeomNode を返す。

    Panda3D の座標系（Y が前方）を前提とする。
    原点は車底面の中央。

    Parameters
    ----------
    length, width, height : float
        車体の長さ・幅・高さ [m]。

    Returns
    -------
    GeomNode
    """
    fmt  = GeomVertexFormat.get_v3n3c4()
    vdata = GeomVertexData("car_box", fmt, Geom.UH_static)
    vdata.setNumRows(24)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")

    hl, hw, hh = length / 2, width / 2, height
    # 面ごとに法線と色を変える（6面 × 4頂点 = 24頂点）
    faces = [
        # (4頂点リスト, 法線, 色)
        ([(-hl,-hw,0),( hl,-hw,0),( hl, hw,0),(-hl, hw,0)],  (0,0,-1), LColor(0.7,0.1,0.1,1)),  # 底
        ([(-hl,-hw,hh),( hl,-hw,hh),( hl, hw,hh),(-hl, hw,hh)], (0,0,1), LColor(0.9,0.2,0.2,1)),  # 天井
        ([(-hl,-hw,0),(-hl,-hw,hh),( hl,-hw,hh),( hl,-hw,0)],  (0,-1,0), LColor(0.8,0.15,0.15,1)),  # 前
        ([( hl, hw,0),( hl, hw,hh),(-hl, hw,hh),(-hl, hw,0)],  (0, 1,0), LColor(0.8,0.15,0.15,1)),  # 後
        ([( hl,-hw,0),( hl, hw,0),( hl, hw,hh),( hl,-hw,hh)],  (1,0,0), LColor(0.75,0.12,0.12,1)), # 右
        ([(-hl, hw,0),(-hl,-hw,0),(-hl,-hw,hh),(-hl, hw,hh)], (-1,0,0), LColor(0.75,0.12,0.12,1)), # 左
    ]
    tris = GeomTriangles(Geom.UH_static)
    vi = 0
    for verts, normal, color in faces:
        for v in verts:
            vw.addData3(*v); nw.addData3(*normal); cw.addData4(color)
        tris.addVertices(vi, vi+1, vi+2)
        tris.addVertices(vi, vi+2, vi+3)
        vi += 4

    geom = Geom(vdata); geom.addPrimitive(tris)
    node = GeomNode("car_box"); node.addGeom(geom)
    return node


def _elem_endpoints_xy(obj):
    """obj の始点・終点の Vec2 タプルを返す。取得できない場合は None。"""
    if isinstance(obj, Segment):
        return obj.start, obj.end
    if isinstance(obj, Arc):
        return obj.start, obj.end
    if isinstance(obj, Clothoid):
        if obj.is_valid and obj._line_pt and obj._circle_pt:
            return obj._line_pt, obj._circle_pt
    return None


def build_centerline(elements: list, profiles: list[ElementProfile],
                     rev_flags: list[bool],
                     n_per_m: float = 0.5) -> list[tuple]:
    """平面線形要素チェーンから 3D 中心線点列を生成する。

    Parameters
    ----------
    elements : list[Segment | Arc | Clothoid]
        チェーン順に並んだ平面線形要素のリスト。
    profiles : list[ElementProfile]
        各要素に対応する縦断データのリスト（elements と同じ順序・長さ）。
    rev_flags : list[bool]
        各要素を逆順で使うかどうかのフラグのリスト。
    n_per_m : float, optional
        1m あたりの出力点数（デフォルト 0.5 = 2m 間隔）。

    Returns
    -------
    list[tuple[float, float, float, float]]
        [(x, y, z, dist), ...] 形式の点列。
        x, y: ワールド座標、z: 標高 [m]、dist: チェーン始端からの累積距離 [m]。

    Notes
    -----
    各要素の先頭点（境界点）は前の要素の末端高さを継承する（段差防止）。
    plan_length < 0.001 の要素はスキップする。
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
                z = ep.elev_at(dist - offset if not rev else L - (dist - offset))
            points.append((wx, wy, z, dist))

    return points


# ══════════════════════════════════════════════════════════════
#   道路メッシュの生成
# ══════════════════════════════════════════════════════════════

def build_road_mesh(centerline: list[tuple],
                    half_width: float = 4.0,
                    color_override: LColor = None,
                    z_offset: float = 0.02) -> GeomNode:
    """中心線に沿った帯状三角形メッシュ（路面）を生成する。

    Parameters
    ----------
    centerline : list[tuple]
        `build_centerline` が返す [(x, y, z, dist), ...] 形式の点列。
    half_width : float, optional
        道路の半幅 [m]（デフォルト 4.0）。全幅 = half_width * 2。
    color_override : LColor, optional
        頂点カラー。None のとき暗いグレー LColor(0.25, 0.25, 0.25, 1)。
    z_offset : float, optional
        地面との Z-fighting を防ぐための高さオフセット [m]（デフォルト 0.02）。
        路面メッシュを地面より確実に上に描画するために必要。

    Returns
    -------
    GeomNode
        Panda3D の GeomNode。表面と裏面の両方向の三角形を含む（両面描画）。
    """
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
        _, _, nx_v, ny_v = _tangent_normal_at(centerline, i)

        for side in (-1, 1):
            px = x + side * half_width * nx_v
            py = y + side * half_width * ny_v
            vw.add_data3(px, py, z + z_offset)  # 地面より z_offset だけ上
            nw.add_data3(0, 0, 1)
            cw.add_data4(road_color)

    for i in range(n - 1):
        bl = i*2; br = i*2+1; tl = (i+1)*2; tr = (i+1)*2+1
        tris.add_vertices(bl, tl, tr)
        tris.add_vertices(bl, tr, br)
        # 裏面も追加（カリングなしで両面表示）
        tris.add_vertices(bl, tr, tl)
        tris.add_vertices(bl, br, tr)

    geom = Geom(vdata)
    geom.add_primitive(tris)
    node = GeomNode("road")
    node.add_geom(geom)
    return node


def build_center_line_node(centerline: list[tuple],
                            color_override: LColor = None) -> GeomNode:
    """センターラインを GeomNode として返す"""

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


def build_piers(centerline: list[tuple], half_width: float,
                interval: float = 30.0) -> GeomNode:
    """道路中心線に沿って約 interval m おきに橋脚を生成する。

    橋脚は道路端（half_width）からさらに OUTER=0.5m 外側の左右に配置する
    ため、路面メッシュの下に橋脚が来ない。

    Parameters
    ----------
    centerline : list[tuple]
        `build_centerline` が返す [(x, y, z, dist), ...] 形式の点列。
    half_width : float
        道路の半幅 [m]。橋脚の外側オフセット計算に使う。
    interval : float, optional
        橋脚の目安間隔 [m]（デフォルト 30.0）。
        dist が次の目標値を超えた最初の点に配置する。

    Returns
    -------
    GeomNode
        橋脚の直方体メッシュを含む GeomNode。
        z_top <= 0.05 の位置では橋脚を生成しない。
    """
    fmt   = GeomVertexFormat.get_v3n3c4()
    vdata = GeomVertexData("piers", fmt, Geom.UH_static)
    vw    = GeomVertexWriter(vdata, "vertex")
    nw    = GeomVertexWriter(vdata, "normal")
    cw    = GeomVertexWriter(vdata, "color")
    tris  = GeomTriangles(Geom.UH_static)

    col   = LColor(0.75, 0.75, 0.78, 1)  # 明るいグレー（コンクリート色）
    PW    = 0.4   # 橋脚の幅（m）
    OUTER = half_width + 0.5   # 道路端からさらに外側に出す距離

    n     = len(centerline)
    if n < 2:
        return GeomNode("piers")

    next_dist = 0.0  # 次の橋脚を打つ目標距離

    def add_quad(pts, normal):
        """4頂点の四角形を2三角形で追加"""
        base = vdata.get_num_rows()
        for p in pts:
            vw.add_data3(*p)
            nw.add_data3(*normal)
            cw.add_data4(col)
        tris.add_vertices(base, base+1, base+2)
        tris.add_vertices(base, base+2, base+3)

    def add_pier(cx, cy, z_top, nx_v, ny_v):
        """1本の橋脚（直方体）を追加"""
        if z_top <= 0.05:
            return  # 地面と同じ高さなら不要
        # 道路外側オフセット方向
        for side in (-1, 1):
            ox = cx + side * OUTER * nx_v
            oy = cy + side * OUTER * ny_v
            # 橋脚の4隅（横断方向に PW、縦断方向に PW）
            tx_v, ty_v = -ny_v, nx_v  # 縦断方向（接線）
            hw = PW / 2
            # 底面4点
            b = [(ox + dx*nx_v*hw + dy*tx_v*hw, oy + dx*ny_v*hw + dy*ty_v*hw, 0.0)
                 for dx, dy in [(-1,-1),( 1,-1),( 1, 1),(-1, 1)]]
            # 上面4点
            t = [(x, y, z_top) for x, y, _ in b]

            # 上面
            add_quad(t, (0, 0, 1))
            # 4側面
            sides = [(0,1),(1,2),(2,3),(3,0)]
            normals = [(-ty_v, tx_v, 0), (nx_v, ny_v, 0),
                       ( ty_v,-tx_v, 0), (-nx_v,-ny_v, 0)]
            for (a, bb_), nm in zip(sides, normals):
                add_quad([b[a], b[bb_], t[bb_], t[a]], nm)

    for i in range(n):
        x, y, z, dist = centerline[i]
        if dist < next_dist - 0.001:
            continue

        # 接線・法線
        _, _, nx_v, ny_v = _tangent_normal_at(centerline, i)

        add_pier(x, y, z, nx_v, ny_v)
        next_dist = dist + interval

    geom = Geom(vdata)
    geom.add_primitive(tris)
    node = GeomNode("piers")
    node.add_geom(geom)
    return node


def build_road_markings(centerline: list[tuple],
                        half_width: float) -> GeomNode:
    """左右の路肩白線（LineStrips）を生成する。

    メッシュでなく LineStrips を使うのは、白線は視覚的に細く面でなく線として
    描く方が実装がシンプルなため。白線の z = centerline[i][2] + 0.08m で
    路面より上に描き、路面メッシュとの Z-fighting を防ぐ。

    Parameters
    ----------
    centerline : list[tuple]
        `build_centerline` が返す [(x, y, z, dist), ...] 形式の点列。
    half_width : float
        道路の半幅 [m]。白線は中心から ±half_width の位置に描く。

    Returns
    -------
    GeomNode
        左右 2 本の LineStrips を含む GeomNode。
    """


    fmt = GeomVertexFormat.get_v3c4()

    n = len(centerline)
    if n < 2:
        return GeomNode("markings")

    white  = LColor(1, 1, 1, 1)
    EDGE_Z = 0.08  # 路面より少し上に描く

    node = GeomNode("markings")

    # 左右を別々に追加
    for side_idx, side in enumerate((-1, 1)):
        vdata2 = GeomVertexData(f"marking_{side_idx}", fmt, Geom.UH_static)
        vw2    = GeomVertexWriter(vdata2, "vertex")
        cw2    = GeomVertexWriter(vdata2, "color")
        ls2    = GeomLinestrips(Geom.UH_static)
        for i, (x, y, z, _) in enumerate(centerline):
            _, _, nx_v, ny_v = _tangent_normal_at(centerline, i)
            px = x + side * half_width * nx_v
            py = y + side * half_width * ny_v
            vw2.add_data3(px, py, z + EDGE_Z)
            cw2.add_data4(white)
            ls2.add_vertex(i)
        ls2.close_primitive()
        g2 = Geom(vdata2)
        g2.add_primitive(ls2)
        node.add_geom(g2)

    return node


def build_ground(cx: float, cy: float, size: float = 2000) -> GeomNode:
    """地面の平板メッシュを生成する。

    全表示要素の AABB 重心を中心に size×size m の緑色平板（z=-0.1m）を配置する。
    z=-0.1m にすることで路面メッシュ（z+0.02m）との Z-fighting を防ぐ。

    Parameters
    ----------
    cx, cy : float
        平板の中心座標（ワールド座標）。
    size : float, optional
        平板の一辺の長さ [m]（デフォルト 2000）。

    Returns
    -------
    GeomNode
        緑色（0.3, 0.5, 0.25, 1）の平板メッシュを含む GeomNode。
    """
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

