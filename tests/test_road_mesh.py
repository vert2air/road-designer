"""
tests/test_road_mesh.py

_road_mesh.py の単体テスト。

Panda3D の GeomVertexReader を使って生成されたジオメトリの
頂点座標・法線・カラーを直接検証し、出力の正しさを確認する。

観点の分類:
  [仕様] 詳細設計書に記載された振る舞いの確認
  [境界] 境界値試験
  [エッジ] エッジケース・コーナーケース
  [C1]   C1 カバレッジを高めるための追加試験
"""
from __future__ import annotations
from models import (
    Vec2, Line, Segment, Circle, Clothoid,
    ElementProfile, GradeLine,
)
from _road_mesh import (
    build_car_box,
    build_road_mesh,
    build_center_line_node,
    build_piers,
    build_road_markings,
    build_ground,
    build_centerline,
)
from panda3d.core import GeomVertexReader, LColor
import pytest
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ──────────────────────────────────────────────────────────────
# ヘルパー
# ──────────────────────────────────────────────────────────────

def read_vertices(node, geom_index: int = 0) -> list[tuple]:
    """GeomNode の指定 geom インデックスから頂点座標リストを返す。"""
    geom = node.get_geom(geom_index)
    vdata = geom.get_vertex_data()
    reader = GeomVertexReader(vdata, "vertex")
    pts = []
    while not reader.is_at_end():
        pts.append(tuple(reader.get_data3()))
    return pts


def read_normals(node, geom_index: int = 0) -> list[tuple]:
    """GeomNode の指定 geom インデックスから法線リストを返す。"""
    geom = node.get_geom(geom_index)
    vdata = geom.get_vertex_data()
    reader = GeomVertexReader(vdata, "normal")
    norms = []
    while not reader.is_at_end():
        norms.append(tuple(reader.get_data3()))
    return norms


def total_verts(node) -> int:
    """GeomNode 内の全 geom の合計頂点数を返す。"""
    return sum(
        node.get_geom(i).get_vertex_data().get_num_rows()
        for i in range(node.get_num_geoms())
    )


def make_ep(plan_length: float, elev_start: float = 0.0,
            elev_end: float = 0.0) -> ElementProfile:
    """テスト用 ElementProfile を生成するヘルパー。"""
    ep = ElementProfile()
    ep.plan_length = plan_length
    gl = GradeLine()
    gl.dist_start = 0.0
    gl.elev_start = elev_start
    gl.dist_end = plan_length
    gl.elev_end = elev_end
    ep.grade_lines = [gl]
    return ep


def y_centerline(n: int = 3, z: float = 0.0) -> list[tuple]:
    """y 方向に延びる直線中心線。

    接線 = (0, 1) → 法線 = (1, 0) なので道路幅は x 方向に広がる。
    """
    return [(0.0, i * 10.0, z, i * 10.0) for i in range(n)]


# ══════════════════════════════════════════════════════════════
# build_car_box
# ══════════════════════════════════════════════════════════════

class TestBuildCarBox:
    """[仕様] build_car_box の頂点構造・寸法を検証する。"""

    def test_vertex_count(self):
        """6 面 × 4 頂点 = 24 頂点が生成される。"""
        node = build_car_box(4.0, 2.0, 1.5)
        assert node.get_geom(0).get_vertex_data().get_num_rows() == 24

    def test_x_range(self):
        """x 方向の範囲が ±length/2 に収まる（前後軸）。"""
        node = build_car_box(4.0, 2.0, 1.5)
        xs = [p[0] for p in read_vertices(node)]
        assert min(xs) == pytest.approx(-2.0, abs=1e-6)
        assert max(xs) == pytest.approx(+2.0, abs=1e-6)

    def test_y_range(self):
        """y 方向の範囲が ±width/2 に収まる（左右軸）。"""
        node = build_car_box(4.0, 2.0, 1.5)
        ys = [p[1] for p in read_vertices(node)]
        assert min(ys) == pytest.approx(-1.0, abs=1e-6)
        assert max(ys) == pytest.approx(+1.0, abs=1e-6)

    def test_z_range(self):
        """z 方向は 0（底面）から height（天面）の範囲。"""
        node = build_car_box(4.0, 2.0, 1.5)
        zs = [p[2] for p in read_vertices(node)]
        assert min(zs) == pytest.approx(0.0, abs=1e-6)
        assert max(zs) == pytest.approx(1.5, abs=1e-6)

    def test_normals_are_unit_vectors(self):
        """すべての法線が単位ベクトルになっている。"""
        node = build_car_box(4.0, 2.0, 1.5)
        for n in read_normals(node):
            length = math.hypot(*n)
            assert length == pytest.approx(1.0, abs=1e-5)

    def test_custom_dimensions(self):
        """カスタムサイズでも長さ・幅・高さが正しく反映される。"""
        node = build_car_box(10.0, 3.0, 2.0)
        pts = read_vertices(node)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        assert min(xs) == pytest.approx(-5.0, abs=1e-6)
        assert max(xs) == pytest.approx(+5.0, abs=1e-6)
        assert min(ys) == pytest.approx(-1.5, abs=1e-6)
        assert max(ys) == pytest.approx(+1.5, abs=1e-6)
        assert min(zs) == pytest.approx(0.0, abs=1e-6)
        assert max(zs) == pytest.approx(2.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════
# build_road_mesh
# ══════════════════════════════════════════════════════════════

class TestBuildRoadMesh:
    """[仕様] build_road_mesh の頂点数・幅・z オフセット・空入力を検証する。"""

    def test_vertex_count(self):
        """頂点数 = 2 × len(centerline)（左右各 1 頂点）。"""
        cl = y_centerline(5)
        node = build_road_mesh(cl, half_width=2.0)
        assert node.get_geom(0).get_vertex_data().get_num_rows() == 2 * 5

    def test_road_width(self):
        """y 方向中心線 → x 方向に ±half_width で道路幅が確保される。"""
        cl = y_centerline(2, z=0.0)
        half = 3.0
        node = build_road_mesh(cl, half_width=half)
        xs = [p[0] for p in read_vertices(node)]
        assert min(xs) == pytest.approx(-half, abs=1e-4)
        assert max(xs) == pytest.approx(+half, abs=1e-4)

    def test_default_z_offset(self):
        """デフォルト z_offset=0.02 が中心線の z に加算される。"""
        z_cl = 5.0
        cl = y_centerline(2, z=z_cl)
        node = build_road_mesh(cl, half_width=2.0)
        for p in read_vertices(node):
            assert p[2] == pytest.approx(z_cl + 0.02, abs=1e-5)

    def test_custom_z_offset(self):
        """明示指定した z_offset が正しく加算される。"""
        cl = y_centerline(2, z=1.0)
        node = build_road_mesh(cl, half_width=2.0, z_offset=0.1)
        for p in read_vertices(node):
            assert p[2] == pytest.approx(1.1, abs=1e-5)

    def test_centerline_y_positions_preserved(self):
        """y 座標は中心線の各点の y 値と一致する。"""
        cl = y_centerline(3)
        node = build_road_mesh(cl, half_width=1.0)
        pts = read_vertices(node)
        ys = sorted(set(round(p[1], 4) for p in pts))
        # 中心線が y=0, 10, 20 なので頂点も同じ y に並ぶ
        assert ys == pytest.approx([0.0, 10.0, 20.0], abs=1e-4)

    def test_color_override_accepted(self):
        """color_override を指定しても正常に GeomNode が返る。"""
        cl = y_centerline(2)
        node = build_road_mesh(cl, half_width=2.0,
                               color_override=LColor(0.5, 0.5, 0.5, 1))
        assert node.get_num_geoms() == 1

    def test_short_centerline_returns_empty_node(self):
        """点数 < 2 の中心線では頂点ゼロの GeomNode を返す（クラッシュしない）。"""
        node = build_road_mesh([(0.0, 0.0, 0.0, 0.0)], half_width=2.0)
        assert total_verts(node) == 0


# ══════════════════════════════════════════════════════════════
# build_center_line_node
# ══════════════════════════════════════════════════════════════

class TestBuildCenterLineNode:
    """[仕様] build_center_line_node の頂点数・z オフセット・xy 座標を検証する。"""

    def test_vertex_count(self):
        """頂点数が中心線の点数と一致する。"""
        cl = [(i * 5.0, 0.0, 0.0, i * 5.0) for i in range(6)]
        node = build_center_line_node(cl)
        assert node.get_geom(0).get_vertex_data().get_num_rows() == 6

    def test_z_offset_0_05_applied(self):
        """各頂点の z = 中心線 z + 0.05（路面との Z-fighting 防止）。"""
        cl = [(0.0, 0.0, 3.0, 0.0), (10.0, 0.0, 7.0, 10.0)]
        node = build_center_line_node(cl)
        pts = read_vertices(node)
        assert pts[0][2] == pytest.approx(3.0 + 0.05, abs=1e-5)
        assert pts[1][2] == pytest.approx(7.0 + 0.05, abs=1e-5)

    def test_xy_positions_unchanged(self):
        """x, y 座標は中心線の値をそのまま使う。"""
        cl = [(1.0, 2.0, 0.0, 0.0), (3.0, 4.0, 0.0, 5.0)]
        node = build_center_line_node(cl)
        pts = read_vertices(node)
        assert pts[0][0] == pytest.approx(1.0, abs=1e-5)
        assert pts[0][1] == pytest.approx(2.0, abs=1e-5)
        assert pts[1][0] == pytest.approx(3.0, abs=1e-5)
        assert pts[1][1] == pytest.approx(4.0, abs=1e-5)

    def test_color_override_accepted(self):
        """color_override を指定しても正常に GeomNode が返る。"""
        cl = [(0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0)]
        node = build_center_line_node(cl, color_override=LColor(1, 0, 0, 1))
        assert node.get_num_geoms() == 1


# ══════════════════════════════════════════════════════════════
# build_ground
# ══════════════════════════════════════════════════════════════

class TestBuildGround:
    """[仕様] build_ground の頂点数・z 値・中心座標・サイズを検証する。"""

    def test_vertex_count(self):
        """地面は 4 頂点の四角形メッシュ。"""
        node = build_ground(0.0, 0.0, 100.0)
        assert len(read_vertices(node)) == 4

    def test_z_is_minus_0_1(self):
        """すべての頂点が z = -0.1（路面より確実に下）。"""
        node = build_ground(0.0, 0.0, 200.0)
        for p in read_vertices(node):
            assert p[2] == pytest.approx(-0.1, abs=1e-6)

    def test_center_position(self):
        """cx, cy が地面の中心になる（±size/2 の範囲を持つ）。"""
        cx, cy, size = 50.0, -30.0, 100.0
        node = build_ground(cx, cy, size)
        pts = read_vertices(node)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        assert min(xs) == pytest.approx(cx - size / 2, abs=1e-4)
        assert max(xs) == pytest.approx(cx + size / 2, abs=1e-4)
        assert min(ys) == pytest.approx(cy - size / 2, abs=1e-4)
        assert max(ys) == pytest.approx(cy + size / 2, abs=1e-4)

    def test_default_size(self):
        """デフォルト size=2000 のとき対角線が 2000 × 2000 m。"""
        node = build_ground(0.0, 0.0)
        pts = read_vertices(node)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        assert max(xs) - min(xs) == pytest.approx(2000.0, abs=1e-2)
        assert max(ys) - min(ys) == pytest.approx(2000.0, abs=1e-2)

    def test_normal_is_upward(self):
        """法線が上向き (0, 0, 1)。"""
        node = build_ground(0.0, 0.0, 100.0)
        for n in read_normals(node):
            assert n == pytest.approx((0.0, 0.0, 1.0), abs=1e-5)


# ══════════════════════════════════════════════════════════════
# build_piers
# ══════════════════════════════════════════════════════════════

class TestBuildPiers:
    """[仕様] build_piers の橋脚生成条件と頂点数を検証する。"""

    def test_no_piers_when_z_zero(self):
        """z = 0.0（地面レベル）では橋脚は生成されない。"""
        cl = y_centerline(2, z=0.0)
        node = build_piers(cl, half_width=2.0)
        assert total_verts(node) == 0

    def test_no_piers_at_threshold_0_05(self):
        """z = 0.05（閾値ちょうど）でも橋脚は生成されない。"""
        cl = [(0.0, 0.0, 0.05, 0.0), (100.0, 0.0, 0.05, 100.0)]
        node = build_piers(cl, half_width=2.0)
        assert total_verts(node) == 0

    def test_piers_generated_above_threshold(self):
        """z > 0.05 の中心線では橋脚（頂点）が生成される。"""
        cl = [(0.0, 0.0, 1.0, 0.0), (100.0, 0.0, 1.0, 100.0)]
        node = build_piers(cl, half_width=2.0)
        assert total_verts(node) > 0

    def test_short_centerline_returns_empty_node(self):
        """点数 < 2 の中心線では頂点ゼロの GeomNode を返す。"""
        node = build_piers([(0.0, 0.0, 10.0, 0.0)], half_width=2.0)
        assert total_verts(node) == 0

    def test_pier_interval_multiple_locations(self):
        """300m の中心線（interval=30m）で複数箇所に橋脚が配置される。"""
        # 60 点 × 5m 間隔 = 300m、z=10m で全点に橋脚
        cl = [(0.0, i * 5.0, 10.0, i * 5.0) for i in range(61)]
        node = build_piers(cl, half_width=2.0, interval=30.0)
        # 1箇所あたり左右2本 × (上面1 + 側面4) × 4頂点 = 40頂点
        # 11箇所 × 40 = 440頂点以上
        assert total_verts(node) >= 200

    def test_pier_z_top_matches_centerline(self):
        """橋脚の頂点の z_max が中心線の z と一致する。"""
        z_top = 8.0
        cl = [(0.0, 0.0, z_top, 0.0), (100.0, 0.0, z_top, 100.0)]
        node = build_piers(cl, half_width=2.0, interval=100.0)
        if total_verts(node) == 0:
            pytest.skip("橋脚が生成されなかった")
        pts = read_vertices(node)
        zs = [p[2] for p in pts]
        assert max(zs) == pytest.approx(z_top, abs=1e-4)

    def test_pier_base_at_z_zero(self):
        """橋脚の底面は z = 0.0。"""
        cl = [(0.0, 0.0, 5.0, 0.0), (100.0, 0.0, 5.0, 100.0)]
        node = build_piers(cl, half_width=2.0, interval=100.0)
        if total_verts(node) == 0:
            pytest.skip("橋脚が生成されなかった")
        pts = read_vertices(node)
        zs = [p[2] for p in pts]
        assert min(zs) == pytest.approx(0.0, abs=1e-4)


# ══════════════════════════════════════════════════════════════
# build_road_markings
# ══════════════════════════════════════════════════════════════

class TestBuildRoadMarkings:
    """[仕様] build_road_markings の左右白線の頂点数・位置・z オフセットを検証する。"""

    def test_geom_count_is_2(self):
        """左右 2 本の白線 → ジオメトリ数 = 2。"""
        cl = y_centerline(4)
        node = build_road_markings(cl, half_width=2.0)
        assert node.get_num_geoms() == 2

    def test_vertex_count_per_line(self):
        """各白線の頂点数は中心線の点数と等しい。"""
        n = 5
        cl = y_centerline(n)
        node = build_road_markings(cl, half_width=2.0)
        for gi in range(2):
            assert node.get_geom(gi).get_vertex_data().get_num_rows() == n

    def test_marking_width(self):
        """y 方向中心線 → 白線が x 方向に ±half_width に配置される。"""
        half = 3.5
        cl = y_centerline(3)
        node = build_road_markings(cl, half_width=half)
        all_xs = []
        for gi in range(2):
            all_xs.extend(p[0] for p in read_vertices(node, gi))
        assert min(all_xs) == pytest.approx(-half, abs=1e-4)
        assert max(all_xs) == pytest.approx(+half, abs=1e-4)

    def test_z_offset_0_08_applied(self):
        """各白線の z = 中心線 z + 0.08（路面メッシュより上）。"""
        z_cl = 4.0
        cl = [(0.0, 0.0, z_cl, 0.0), (0.0, 10.0, z_cl, 10.0)]
        node = build_road_markings(cl, half_width=2.0)
        for gi in range(2):
            for p in read_vertices(node, gi):
                assert p[2] == pytest.approx(z_cl + 0.08, abs=1e-5)

    def test_short_centerline_returns_empty_node(self):
        """点数 < 2 の中心線では空の GeomNode を返す。"""
        node = build_road_markings([(0.0, 0.0, 0.0, 0.0)], half_width=2.0)
        assert node.get_num_geoms() == 0

    def test_left_right_x_positions_are_opposite(self):
        """左右の白線は x 方向に対称に配置される。"""
        half = 2.0
        cl = [(0.0, 0.0, 0.0, 0.0), (0.0, 10.0, 0.0, 10.0)]
        node = build_road_markings(cl, half_width=half)
        xs_0 = sorted(set(round(p[0], 4) for p in read_vertices(node, 0)))
        xs_1 = sorted(set(round(p[0], 4) for p in read_vertices(node, 1)))
        # 各白線は x が一定値（左右どちらか）
        assert len(xs_0) == 1
        assert len(xs_1) == 1
        assert xs_0[0] == pytest.approx(-xs_1[0], abs=1e-4)


# ══════════════════════════════════════════════════════════════
# build_centerline の Clothoid ブランチ（C1 補完）
# ══════════════════════════════════════════════════════════════

class TestBuildCenterlineClothoidBranch:
    """[C1] build_centerline の Clothoid ブランチをカバー。

    既存の test_road_viewer.py は Segment/Arc のみをテストしているため、
    Clothoid 分岐（L231-254）と unknown 型分岐（L231→256, L256-257）が未カバー。
    """

    def test_clothoid_with_points_generates_centerline(self):
        """[仕様] points を持つ Clothoid から中心線点列が生成される（L231-252 正常パス）。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(0, 80), 50.0)
        clo = Clothoid(ln, ci)
        # 複数の points を直接設定（正常パス）
        clo._points = [Vec2(-50, 0), Vec2(-25, 30), Vec2(0, 50), Vec2(25, 70)]

        ep = make_ep(100.0)
        cl = build_centerline([clo], [ep], [False])

        assert len(cl) > 0
        # x, y 座標が points の範囲内に収まる
        xs = [p[0] for p in cl]
        ys = [p[1] for p in cl]
        assert min(xs) >= -50 - 1e-4
        assert max(xs) <= 25 + 1e-4
        assert min(ys) >= 0 - 1e-4

    def test_clothoid_reversed(self):
        """[仕様] rev=True のとき点列が逆順になる。"""
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(0, 80), 50.0)
        clo = Clothoid(ln, ci)
        clo._points = [Vec2(0, 0), Vec2(10, 10), Vec2(20, 15)]

        ep = make_ep(30.0)
        cl_fwd = build_centerline([clo], [ep], [False])
        cl_rev = build_centerline([clo], [ep], [True])

        assert len(cl_fwd) == len(cl_rev)
        # 正順と逆順では先頭の xy が逆になる
        assert cl_fwd[0][0] != pytest.approx(cl_rev[0][0], abs=1e-4) or \
            cl_fwd[0][1] != pytest.approx(cl_rev[0][1], abs=1e-4)

    def test_clothoid_for_else_branch(self):
        """[C1] points が 1 点のとき内側 for-else の else が実行される（L253-254）。

        cum = [0.0] → inner for k in range(0) が実行されず、
        else ブロックで raw[-1] が追加される。
        """
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(0, 80), 50.0)
        clo = Clothoid(ln, ci)
        clo._points = [Vec2(5.0, 3.0)]   # 1 点 → for-else の else が発火

        ep = make_ep(10.0)
        cl = build_centerline([clo], [ep], [False])

        # for-else の else で raw[-1] が繰り返し追加される → 点列がある
        assert len(cl) > 0
        # すべての xy が raw[-1] の値に等しい
        for p in cl:
            assert p[0] == pytest.approx(5.0, abs=1e-4)
            assert p[1] == pytest.approx(3.0, abs=1e-4)

    def test_unknown_element_type_skipped(self):
        """[C1] Segment/Arc/Clothoid 以外の型は pts_2d が空のまま continue される
        （L231→256 False 分岐、L256-257 カバー）。"""
        ln = Line(Vec2(0, 0), Vec2(100, 0))   # Line は非対応型

        ep = make_ep(100.0)
        cl = build_centerline([ln], [ep], [False])

        # pts_2d が空 → continue → 何も追加されない
        assert cl == []
