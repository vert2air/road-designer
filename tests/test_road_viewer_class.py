"""tests/test_road_viewer_class.py

ShowBase.__init__ をモックして RoadViewer の純 Python メソッドを検証する。
Panda3D の表示ウィンドウは不要。

カバレッジ目標: road_viewer.py 26% → ~70%
"""
from __future__ import annotations
import sys
import os
import math
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ═══════════════════════════════════════════════════════════════
#   ヘルパー
# ═══════════════════════════════════════════════════════════════

def _cl(n=10, z=0.0):
    """y 方向に進む直線中心線 [(0,0,z,0), (0,10,z,10), ...]"""
    return [(0.0, float(i) * 10.0, z, float(i) * 10.0) for i in range(n)]


def _elem(eid=1, start=(0.0, 0.0), end=(0.0, 100.0), pl=100.0,
          start_clo=None, end_clo=None):
    """elem_graph 用の要素辞書を生成する。"""
    pts = [[start[0] + (end[0] - start[0]) * i / 10,
            start[1] + (end[1] - start[1]) * i / 10] for i in range(11)]
    return {
        "id": eid,
        "type": "Segment",
        "nickname": f"seg{eid}",
        "start": list(start),
        "end": list(end),
        "plan_length": pl,
        "heights": [[0.0, 0.0], [pl, 0.0]],
        "points_xy": pts,
        "start_clo_ref": start_clo,
        "end_clo_ref": end_clo,
    }


def _make_viewer(
        cl=None, elem_graph=None, start_info=None, warp_boundary=None):
    """ShowBase.__init__ をモックして RoadViewer インスタンスを返す。"""
    from road_viewer import RoadViewer
    from direct.showbase.ShowBase import ShowBase

    if cl is None:
        cl = _cl()

    with patch.object(ShowBase, '__init__', return_value=None), \
            patch('road_viewer.OnscreenText'), \
            patch('road_viewer.LineSegs'):
        v = RoadViewer.__new__(RoadViewer)
        v.render = MagicMock()
        v.camera = MagicMock()
        v.taskMgr = MagicMock()
        v.accept = MagicMock()
        v.disableMouse = MagicMock()
        v.mouseWatcherNode = MagicMock()
        v.aspect2d = MagicMock()
        kw = {}
        if elem_graph is not None:
            kw['elem_graph'] = elem_graph
        if start_info is not None:
            kw['start_info'] = start_info
        if warp_boundary is not None:
            kw['warp_boundary'] = warp_boundary
        v.__init__(cl, **kw)

    return v


# ═══════════════════════════════════════════════════════════════
#   モジュールレベルの純粋関数テスト
# ═══════════════════════════════════════════════════════════════

class TestInterpCl:
    def test_empty_returns_defaults(self):
        from road_viewer import interp_cl
        pos, fwd, right = interp_cl([], 0.0)
        assert pos == (0, 0, 0)
        assert fwd == (1, 0, 0)

    def test_single_point_returns_that_point(self):
        from road_viewer import interp_cl
        cl = [(1.0, 2.0, 3.0, 0.0)]
        pos, fwd, right = interp_cl(cl, 5.0)
        assert pos == (1.0, 2.0, 3.0)

    def test_midpoint_interpolation(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, fwd, right = interp_cl(cl, 5.0)
        assert pos[0] == pytest.approx(5.0, abs=1e-6)
        assert fwd[0] == pytest.approx(1.0, abs=1e-6)

    def test_past_end_returns_last_point(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, fwd, right = interp_cl(cl, 999.0)
        assert pos == (10.0, 0.0, 0.0)

    def test_z_interpolation(self):
        from road_viewer import interp_cl
        cl = [(0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 10.0, 10.0)]
        pos, fwd, right = interp_cl(cl, 5.0)
        assert pos[2] == pytest.approx(5.0, abs=1e-6)

    def test_right_vector_perpendicular(self):
        from road_viewer import interp_cl
        # x方向に進む → right = (fwd[1], -fwd[0], 0) = (0, -1, 0)
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, fwd, right = interp_cl(cl, 5.0)
        assert abs(right[0] * fwd[0] + right[1] * fwd[1]) < 1e-6  # 直交


class TestBearingStr:
    def test_north(self):
        from road_viewer import bearing_str
        assert bearing_str(0.0, 1.0) == "N"

    def test_east(self):
        from road_viewer import bearing_str
        assert bearing_str(1.0, 0.0) == "E"

    def test_south(self):
        from road_viewer import bearing_str
        assert bearing_str(0.0, -1.0) == "S"

    def test_west(self):
        from road_viewer import bearing_str
        assert bearing_str(-1.0, 0.0) == "W"

    def test_northeast(self):
        from road_viewer import bearing_str
        assert bearing_str(1.0, 1.0) == "NE"

    def test_southwest(self):
        from road_viewer import bearing_str
        assert bearing_str(-1.0, -1.0) == "SW"


class TestElemFwdVec:
    def test_with_points_forward(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [[0.0, 0.0], [1.0, 0.0]],
                "start": [0.0, 0.0], "end": [1.0, 0.0]}
        dx, dy = _elem_fwd_vec(elem, True)
        assert dx == pytest.approx(1.0, abs=1e-6)
        assert dy == pytest.approx(0.0, abs=1e-6)

    def test_with_points_backward(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [[0.0, 0.0], [1.0, 0.0]],
                "start": [0.0, 0.0], "end": [1.0, 0.0]}
        dx, dy = _elem_fwd_vec(elem, False)
        assert dx == pytest.approx(-1.0, abs=1e-6)

    def test_without_points_forward(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [], "start": [0.0, 0.0], "end": [0.0, 10.0]}
        dx, dy = _elem_fwd_vec(elem, True)
        assert dy == pytest.approx(1.0, abs=1e-6)

    def test_without_points_backward(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [], "start": [0.0, 0.0], "end": [0.0, 10.0]}
        dx, dy = _elem_fwd_vec(elem, False)
        assert dy == pytest.approx(-1.0, abs=1e-6)

    def test_zero_length_no_crash(self):
        from road_viewer import _elem_fwd_vec
        elem = {"points_xy": [[5.0, 5.0], [5.0, 5.0]],
                "start": [5.0, 5.0], "end": [5.0, 5.0]}
        dx, dy = _elem_fwd_vec(elem, True)  # ZeroDivision しないこと


class TestMakeElemCl:
    def test_with_points_forward(self):
        from road_viewer import make_elem_cl
        elem = {"plan_length": 10.0,
                "points_xy": [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]],
                "start": [0.0, 0.0], "end": [10.0, 0.0]}
        cl, total = make_elem_cl(elem, True)
        assert total == pytest.approx(10.0)
        assert cl[0][0] == pytest.approx(0.0, abs=1e-4)
        assert cl[-1][0] == pytest.approx(10.0, abs=1e-4)

    def test_with_points_backward(self):
        from road_viewer import make_elem_cl
        elem = {"plan_length": 10.0,
                "points_xy": [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]],
                "start": [0.0, 0.0], "end": [10.0, 0.0]}
        cl, total = make_elem_cl(elem, False)
        assert cl[0][0] == pytest.approx(10.0, abs=1e-4)

    def test_without_points_linear(self):
        from road_viewer import make_elem_cl
        elem = {"plan_length": 10.0, "start": [0.0, 0.0], "end": [0.0, 10.0]}
        cl, total = make_elem_cl(elem, True)
        assert total == pytest.approx(10.0)
        assert len(cl) >= 2

    def test_heights_interpolated(self):
        from road_viewer import make_elem_cl
        elem = {"plan_length": 10.0, "heights": [[0.0, 0.0], [10.0, 5.0]],
                "start": [0.0, 0.0], "end": [10.0, 0.0]}
        cl, total = make_elem_cl(elem, True)
        assert cl[-1][2] == pytest.approx(5.0, abs=0.5)


class TestFindNextCandidates:
    def test_forward_connection(self):
        from road_viewer import find_next_candidates
        eg = [{"id": 1, "start": [0.0, 0.0], "end": [10.0, 0.0],
               "start_clo_ref": None, "end_clo_ref": None},
              {"id": 2, "start": [10.0, 0.0], "end": [20.0, 0.0],
               "start_clo_ref": None, "end_clo_ref": None}]
        cands = find_next_candidates(eg, 1, 10.0, 0.0, None)
        assert len(cands) == 1
        assert cands[0][0]["id"] == 2
        assert cands[0][1] is True

    def test_backward_connection(self):
        from road_viewer import find_next_candidates
        eg = [{"id": 1, "start": [0.0, 0.0], "end": [10.0, 0.0],
               "start_clo_ref": None, "end_clo_ref": None},
              {"id": 2, "start": [20.0, 0.0], "end": [10.0, 0.0],
               "start_clo_ref": None, "end_clo_ref": None}]
        cands = find_next_candidates(eg, 1, 10.0, 0.0, None)
        assert len(cands) == 1
        assert cands[0][1] is False

    def test_skip_current_element(self):
        from road_viewer import find_next_candidates
        eg = [{"id": 1, "start": [0.0, 0.0], "end": [10.0, 0.0],
               "start_clo_ref": None, "end_clo_ref": None}]
        cands = find_next_candidates(eg, 1, 10.0, 0.0, None)
        assert cands == []

    def test_clothoid_ref_start_match(self):
        from road_viewer import find_next_candidates
        exit_ref = {"clothoid_id": 99, "side": "line"}
        eg = [{"id": 1, "start": [0.0, 0.0], "end": [10.0, 0.0],
               "start_clo_ref": {"clothoid_id": 99, "side": "line"},
               "end_clo_ref": None},
              {"id": 2, "start": [0.0, 50.0], "end": [10.0, 50.0],
               "start_clo_ref": None, "end_clo_ref": None}]
        cands = find_next_candidates(eg, 99, 10.0, 0.0, exit_ref)
        assert len(cands) == 1
        assert cands[0][0]["id"] == 1

    def test_clothoid_ref_end_match(self):
        from road_viewer import find_next_candidates
        exit_ref = {"clothoid_id": 99, "side": "circle"}
        eg = [{"id": 1, "start": [0.0, 0.0], "end": [10.0, 0.0],
               "start_clo_ref": None,
               "end_clo_ref": {"clothoid_id": 99, "side": "circle"}}]
        cands = find_next_candidates(eg, 0, 10.0, 0.0, exit_ref)
        assert len(cands) == 1
        assert cands[0][1] is False  # end 側一致 → 逆順


# ═══════════════════════════════════════════════════════════════
#   RoadViewer 初期化
# ═══════════════════════════════════════════════════════════════

class TestViewerInit:
    def test_basic_attributes(self):
        v = _make_viewer()
        assert v.speed == pytest.approx(30.0)
        assert v.view_mode == "follow"
        assert v.paused is False
        assert v._auto_drive is False

    def test_total_is_last_dist(self):
        cl = _cl(n=5)   # dist 0, 10, 20, 30, 40
        v = _make_viewer(cl=cl)
        assert v._total == pytest.approx(40.0)

    def test_warp_boundary_custom(self):
        v = _make_viewer(warp_boundary=200.0)
        assert v._warp_boundary == pytest.approx(200.0)

    def test_warp_boundary_default(self):
        from road_viewer import RoadViewer
        v = _make_viewer()
        assert v._warp_boundary == pytest.approx(RoadViewer.WARP_BOUNDARY)

    def test_auto_drive_with_elem_graph(self):
        eg = [_elem()]
        si = {"id": 1, "forward": True}
        v = _make_viewer(elem_graph=eg, start_info=si)
        assert v._auto_drive is True
        assert v._ad_cur_id == 1
        assert v._ad_forward is True

    def test_taskMgr_add_called(self):
        v = _make_viewer()
        v.taskMgr.add.assert_called()

    def test_disableMouse_called(self):
        v = _make_viewer()
        v.disableMouse.assert_called_once()

    def test_traffic_created_with_elem_graph(self):
        eg = [_elem(pl=100.0)]
        si = {"id": 1, "forward": True}
        v = _make_viewer(elem_graph=eg, start_info=si)
        # _init_traffic が traffic 台数を生成する
        assert len(v._traffic) > 0


# ═══════════════════════════════════════════════════════════════
#   トグル・スピード系
# ═══════════════════════════════════════════════════════════════

class TestTogglePause:
    def test_false_to_true(self):
        v = _make_viewer()
        v._toggle_pause()
        assert v.paused is True

    def test_toggle_twice_restores(self):
        v = _make_viewer()
        v._toggle_pause()
        v._toggle_pause()
        assert v.paused is False


class TestToggleView:
    def test_follow_to_onboard(self):
        v = _make_viewer()
        v.view_mode = "follow"
        v._toggle_view()
        assert v.view_mode == "onboard"

    def test_onboard_to_follow(self):
        v = _make_viewer()
        v.view_mode = "onboard"
        v._toggle_view()
        assert v.view_mode == "follow"

    def test_other_to_follow(self):
        v = _make_viewer()
        v.view_mode = "overview"
        v._toggle_view()
        assert v.view_mode == "follow"


class TestToggleOverview:
    def test_follow_to_overview(self):
        v = _make_viewer()
        v.view_mode = "follow"
        v._toggle_overview()
        assert v.view_mode == "overview"

    def test_onboard_to_overview(self):
        v = _make_viewer()
        v.view_mode = "onboard"
        v._toggle_overview()
        assert v.view_mode == "overview"

    def test_overview_to_fixed(self):
        v = _make_viewer()
        v.view_mode = "overview"
        v._toggle_overview()
        assert v.view_mode == "overview_fixed"

    def test_fixed_to_follow(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        v._toggle_overview()
        assert v.view_mode == "follow"

    def test_saves_current_pos(self):
        # 1点だと build_center_line_node が失敗するので2点以上使う
        cl = [(5.0, 3.0, 0.0, 0.0), (5.0, 13.0, 0.0, 10.0)]
        v = _make_viewer(cl=cl)
        v.view_mode = "follow"
        v._toggle_overview()
        assert v._overview_pos[0] == pytest.approx(5.0)
        assert v._overview_pos[1] == pytest.approx(3.0)


class TestToggleAutoDrive:
    def test_off_to_on(self):
        v = _make_viewer()
        v._auto_drive = False
        v._toggle_auto_drive()
        assert v._auto_drive is True

    def test_on_to_off(self):
        eg = [_elem()]
        si = {"id": 1, "forward": True}
        v = _make_viewer(elem_graph=eg, start_info=si)
        v._toggle_auto_drive()
        assert v._auto_drive is False

    def test_on_with_start_info_resets_dist(self):
        eg = [_elem()]
        si = {"id": 1, "forward": True}
        v = _make_viewer(elem_graph=eg, start_info=si)
        v._auto_drive = False
        v.dist = 42.0
        v._toggle_auto_drive()
        assert v._auto_drive is True
        assert v._ad_dist == pytest.approx(42.0)
        assert v._ad_cur_id == 1


class TestChangeSpeed:
    def test_increase(self):
        v = _make_viewer()
        v.speed = 30.0
        v._change_speed(10.0)
        assert v.speed == pytest.approx(40.0)

    def test_decrease(self):
        v = _make_viewer()
        v.speed = 30.0
        v._change_speed(-10.0)
        assert v.speed == pytest.approx(20.0)

    def test_clamp_at_one(self):
        v = _make_viewer()
        v.speed = 5.0
        v._change_speed(-100.0)
        assert v.speed == pytest.approx(1.0)


class TestToggleSurface:
    def test_flag_flips(self):
        v = _make_viewer()
        initial = v.ROAD_SURFACE
        v._toggle_surface()
        assert v.ROAD_SURFACE != initial

    def test_apply_show(self):
        v = _make_viewer()
        mock_np = MagicMock()
        v._surface_nodes = [mock_np]
        v._apply_surface_visible(True)
        mock_np.show.assert_called_once()

    def test_apply_hide(self):
        v = _make_viewer()
        mock_np = MagicMock()
        v._surface_nodes = [mock_np]
        v._apply_surface_visible(False)
        mock_np.hide.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#   俯瞰ズーム
# ═══════════════════════════════════════════════════════════════

class TestOverviewZoom:
    def test_zoom_in_reduces_height(self):
        v = _make_viewer()
        v.view_mode = "overview"
        old = v.CAM_OVERVIEW_H
        v._overview_zoom_in()
        assert v.CAM_OVERVIEW_H < old

    def test_zoom_in_clamp_at_10(self):
        v = _make_viewer()
        v.view_mode = "overview"
        v.CAM_OVERVIEW_H = 10.0
        v._overview_zoom_in()
        assert v.CAM_OVERVIEW_H == pytest.approx(10.0)

    def test_zoom_out_increases_height(self):
        v = _make_viewer()
        v.view_mode = "overview"
        old = v.CAM_OVERVIEW_H
        v._overview_zoom_out()
        assert v.CAM_OVERVIEW_H > old

    def test_zoom_out_clamp_at_5000(self):
        v = _make_viewer()
        v.view_mode = "overview"
        v.CAM_OVERVIEW_H = 5000.0
        v._overview_zoom_out()
        assert v.CAM_OVERVIEW_H == pytest.approx(5000.0)

    def test_no_effect_in_follow_mode(self):
        v = _make_viewer()
        v.view_mode = "follow"
        old = v.CAM_OVERVIEW_H
        v._overview_zoom_in()
        v._overview_zoom_out()
        assert v.CAM_OVERVIEW_H == pytest.approx(old)

    def test_zoom_in_overview_fixed(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        old = v.CAM_OVERVIEW_H
        v._overview_zoom_in()
        assert v.CAM_OVERVIEW_H < old


# ═══════════════════════════════════════════════════════════════
#   俯瞰パン (_overview_pan)
# ═══════════════════════════════════════════════════════════════

class TestOverviewPan:
    def test_no_mouse_resets_prev(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        v.mouseWatcherNode.hasMouse.return_value = False
        v._pan_prev_mouse = (0.5, 0.5)
        v._overview_pan()
        assert v._pan_prev_mouse is None

    def test_no_button_resets_prev(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        v.mouseWatcherNode.hasMouse.return_value = True
        v.mouseWatcherNode.getMouseX.return_value = 0.1
        v.mouseWatcherNode.getMouseY.return_value = 0.2
        v.mouseWatcherNode.isButtonDown.return_value = False
        v._pan_prev_mouse = (0.0, 0.0)
        v._overview_pan()
        assert v._pan_prev_mouse is None

    def test_first_frame_stores_pos(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        v.mouseWatcherNode.hasMouse.return_value = True
        v.mouseWatcherNode.getMouseX.return_value = 0.3
        v.mouseWatcherNode.getMouseY.return_value = 0.4
        v.mouseWatcherNode.isButtonDown.return_value = True
        v._pan_prev_mouse = None
        v._overview_pan()
        assert v._pan_prev_mouse == (0.3, 0.4)

    def test_drag_moves_pos(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        v._overview_pos = (0.0, 0.0)
        v.mouseWatcherNode.hasMouse.return_value = True
        v.mouseWatcherNode.getMouseX.return_value = 0.1
        v.mouseWatcherNode.getMouseY.return_value = 0.2
        v.mouseWatcherNode.isButtonDown.return_value = True
        v._pan_prev_mouse = (0.0, 0.0)
        v._overview_pan()
        ox, oy = v._overview_pos
        assert ox != 0.0 or oy != 0.0


# ═══════════════════════════════════════════════════════════════
#   補間・方位デリゲートメソッド
# ═══════════════════════════════════════════════════════════════

class TestInterpMethods:
    def test_interp_cl_delegate(self):
        v = _make_viewer()
        cl = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 10.0)]
        pos, fwd, _ = v._interp_cl(cl, 5.0)
        assert pos[0] == pytest.approx(5.0, abs=1e-6)

    def test_interp_uses_self_cl(self):
        cl = [(1.0, 2.0, 3.0, 0.0), (11.0, 2.0, 3.0, 10.0)]
        v = _make_viewer(cl=cl)
        pos, fwd, _ = v._interp(5.0)
        assert pos[0] == pytest.approx(6.0, abs=1e-6)

    def test_bearing_str_static(self):
        from road_viewer import RoadViewer
        assert RoadViewer._bearing_str(0.0, 1.0) == "N"
        assert RoadViewer._bearing_str(1.0, 0.0) == "E"

    def test_make_elem_cl_delegate(self):
        v = _make_viewer()
        e = _elem(pl=20.0)
        cl, total = v._make_elem_cl(e, True)
        assert total == pytest.approx(20.0)

    def test_find_next_candidates_delegate(self):
        eg = [_elem(eid=2, start=(0.0, 90.0), end=(0.0, 190.0))]
        v = _make_viewer(elem_graph=eg)
        cands = v._find_next_candidates(1, 0.0, 90.0, None)
        assert len(cands) == 1


# ═══════════════════════════════════════════════════════════════
#   オートドライブ履歴
# ═══════════════════════════════════════════════════════════════

class TestAdHistoryPush:
    def test_push_adds_entry(self):
        v = _make_viewer()
        v._ad_history_idx = -1
        v._ad_history_push()
        assert len(v._ad_history) == 1

    def test_push_during_review_skips(self):
        v = _make_viewer()
        v._ad_history_idx = 0
        v._ad_history_push()
        assert len(v._ad_history) == 0

    def test_push_max_enforced(self):
        v = _make_viewer()
        v._ad_history_idx = -1
        for _ in range(v._AD_HISTORY_MAX + 5):
            v._ad_history_push()
        assert len(v._ad_history) <= v._AD_HISTORY_MAX

    def test_push_snapshot_content(self):
        v = _make_viewer()
        v._ad_history_idx = -1
        v._ad_dist = 42.0
        v._ad_cur_id = 7
        v._ad_history_push()
        snap = v._ad_history[-1]
        assert snap["dist"] == pytest.approx(42.0)
        assert snap["cur_id"] == 7


# ═══════════════════════════════════════════════════════════════
#   _rewind / _forward
# ═══════════════════════════════════════════════════════════════

class TestRewindForward:
    def test_rewind_normal_100m(self):
        v = _make_viewer()
        v._auto_drive = False
        v.dist = 200.0
        v._rewind()
        assert v.dist == pytest.approx(100.0)

    def test_rewind_normal_clamp(self):
        v = _make_viewer()
        v._auto_drive = False
        v.dist = 50.0
        v._rewind()
        assert v.dist == pytest.approx(0.0)

    def test_forward_normal_100m(self):
        v = _make_viewer()
        v._auto_drive = False
        v._total = 500.0
        v.dist = 100.0
        v._forward()
        assert v.dist == pytest.approx(200.0)

    def test_forward_normal_clamp(self):
        v = _make_viewer()
        v._auto_drive = False
        v._total = 150.0
        v.dist = 100.0
        v._forward()
        assert v.dist == pytest.approx(150.0)

    def test_rewind_auto_within_chain(self):
        v = _make_viewer()
        v._auto_drive = True
        v._ad_dist = 200.0
        v._rewind()
        assert v._ad_dist == pytest.approx(100.0)

    def test_rewind_auto_triggers_history(self):
        v = _make_viewer()
        v._auto_drive = True
        v._ad_dist = 50.0
        snap_cl = _cl(n=5)
        v._ad_history = [{"cl": snap_cl, "total": 40.0, "dist": 10.0,
                          "cur_id": 99, "forward": False}]
        v._ad_history_idx = -1
        v._rewind()
        assert v._ad_history_idx == 0
        assert v._ad_cur_id == 99

    def test_forward_auto_no_history(self):
        v = _make_viewer()
        v._auto_drive = True
        v._ad_history_idx = -1
        v._ad_total = 500.0
        v._ad_dist = 100.0
        v._forward()
        assert v._ad_dist == pytest.approx(200.0)

    def test_forward_auto_history_advance(self):
        v = _make_viewer()
        v._auto_drive = True
        snap_cl = _cl(n=5)
        v._ad_history = [
            {"cl": snap_cl, "total": 40.0, "dist": 0.0,
                "cur_id": 1, "forward": True},
            {"cl": snap_cl, "total": 40.0, "dist": 0.0,
                "cur_id": 2, "forward": True},
        ]
        v._ad_history_idx = 0
        v._forward()
        assert v._ad_history_idx == 1
        assert v._ad_cur_id == 2

    def test_forward_auto_history_reaches_end(self):
        v = _make_viewer()
        v._auto_drive = True
        snap_cl = _cl(n=5)
        v._ad_history = [{"cl": snap_cl, "total": 40.0, "dist": 0.0,
                          "cur_id": 1, "forward": True}]
        v._ad_history_idx = 0
        v._forward()
        assert v._ad_history_idx == -1  # リアルタイムに戻る

    def test_rewind_auto_history_idx_decrements(self):
        v = _make_viewer()
        v._auto_drive = True
        v._ad_dist = 10.0
        snap_cl = _cl(n=5)
        snaps = [
            {"cl": snap_cl, "total": 40.0, "dist": 0.0,
             "cur_id": i, "forward": True}
            for i in range(3)
        ]
        v._ad_history = snaps
        v._ad_history_idx = 2
        v._rewind()
        assert v._ad_history_idx == 1


# ═══════════════════════════════════════════════════════════════
#   _ad_step
# ═══════════════════════════════════════════════════════════════

class TestAdStep:
    def test_within_chain(self):
        v = _make_viewer()
        v._ad_total = 100.0
        v._ad_dist = 0.0
        v.speed = 10.0
        v._ad_step(1.0)
        assert v._ad_dist == pytest.approx(10.0)

    def test_zero_total_no_op(self):
        v = _make_viewer()
        v._ad_total = 0.0
        v._ad_dist = 0.0
        v._ad_step(1.0)
        assert v._ad_dist == pytest.approx(0.0)

    def test_overflow_triggers_advance(self):
        """末端超過 → _ad_advance → 候補なし → ワープ → cur_id=None"""
        v = _make_viewer()
        v._elem_graph = []
        v._ad_total = 1.0
        v._ad_dist = 0.8
        v.speed = 1.0
        v._ad_step(0.5)   # 0.8 + 0.5 > 1.0 → advance → warp
        assert v._ad_cur_id is None


# ═══════════════════════════════════════════════════════════════
#   _ad_warp
# ═══════════════════════════════════════════════════════════════

class TestAdWarp:
    def test_x_beyond_boundary_flips(self):
        v = _make_viewer()
        v._ad_cl = _cl()
        v._ad_warp(600.0, 0.0, 1.0, 0.0, 5.0)
        assert v._ad_cl[0][0] == pytest.approx(-600.0, abs=1e-3)
        assert v._ad_cur_id is None

    def test_y_beyond_boundary_flips(self):
        v = _make_viewer()
        v._ad_cl = _cl()
        v._ad_warp(0.0, -600.0, 0.0, -1.0, 0.0)
        assert v._ad_cl[0][1] == pytest.approx(600.0, abs=1e-3)

    def test_within_boundary_no_flip(self):
        v = _make_viewer()
        v._ad_cl = _cl()
        v._ad_warp(10.0, 10.0, 1.0, 0.0, 0.0)
        assert v._ad_cl[0][0] == pytest.approx(10.0, abs=1e-3)

    def test_overflow_applied(self):
        v = _make_viewer()
        v._ad_cl = _cl()
        v._ad_warp(0.0, 0.0, 1.0, 0.0, 7.0)
        assert v._ad_dist == pytest.approx(7.0)

    def test_total_reset_to_100(self):
        v = _make_viewer()
        v._ad_cl = _cl()
        v._ad_warp(0.0, 0.0, 1.0, 0.0, 0.0)
        assert v._ad_total == pytest.approx(100.0)


# ═══════════════════════════════════════════════════════════════
#   _ad_start_elem
# ═══════════════════════════════════════════════════════════════

class TestAdStartElem:
    def test_forward_with_pts(self):
        v = _make_viewer()
        e = _elem(eid=5, pl=100.0)
        v._ad_start_elem(e, True, 0.0)
        assert v._ad_cur_id == 5
        assert v._ad_forward is True
        assert v._ad_total == pytest.approx(100.0)

    def test_backward_with_pts(self):
        v = _make_viewer()
        e = _elem(eid=6, pl=50.0)
        v._ad_start_elem(e, False, 0.0)
        assert v._ad_cur_id == 6
        assert v._ad_forward is False

    def test_overflow_applied(self):
        v = _make_viewer()
        v._ad_start_elem(_elem(pl=100.0), True, 15.0)
        assert v._ad_dist == pytest.approx(15.0)

    def test_overflow_clamped_to_plan_length(self):
        v = _make_viewer()
        v._ad_start_elem(_elem(pl=10.0), True, 999.0)
        assert v._ad_dist == pytest.approx(10.0)

    def test_without_pts_uses_linear(self):
        v = _make_viewer()
        e = {"id": 7, "plan_length": 20.0,
             "start": [0.0, 0.0], "end": [20.0, 0.0]}
        v._ad_start_elem(e, True, 0.0)
        assert len(v._ad_cl) >= 2

    def test_heights_at_endpoint(self):
        v = _make_viewer()
        e = {"id": 8, "plan_length": 10.0,
             "heights": [[0.0, 0.0], [10.0, 5.0]],
             "points_xy": [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]],
             "start": [0.0, 0.0], "end": [10.0, 0.0]}
        v._ad_start_elem(e, True, 0.0)
        assert v._ad_cl[-1][2] == pytest.approx(5.0, abs=0.5)


# ═══════════════════════════════════════════════════════════════
#   _ad_advance
# ═══════════════════════════════════════════════════════════════

class TestAdAdvance:
    def test_no_candidates_triggers_warp(self):
        v = _make_viewer()
        v._elem_graph = []
        v._ad_cl = _cl()
        v._ad_cur_id = None
        v._ad_advance(0.0)
        assert v._ad_cur_id is None

    def test_with_candidate_transitions(self):
        """隣接要素がある → _ad_start_elem → cur_id 更新"""
        v = _make_viewer()
        eg = [_elem(eid=2, start=(0.0, 90.0), end=(0.0, 190.0), pl=100.0)]
        v._elem_graph = eg
        v._ad_cl = _cl()     # 末端 (0, 90)
        v._ad_cur_id = None
        v._ad_forward = True
        v._ad_advance(0.0)
        assert v._ad_cur_id == 2

    def test_advance_pushes_history(self):
        v = _make_viewer()
        v._elem_graph = []
        v._ad_cl = _cl()
        v._ad_history_idx = -1
        v._ad_history_push()   # 1 件積んでおく
        before = len(v._ad_history)
        v._ad_advance(0.0)
        assert len(v._ad_history) == before + 1

    def test_with_clo_ref_exit_matches(self):
        """exit_clo_ref がある → 接点マッチで候補選択"""
        v = _make_viewer()
        exit_ref = {"clothoid_id": 42, "side": "line"}
        eg = [_elem(eid=3, start=(0.0, 90.0), end=(0.0, 190.0), pl=100.0,
                    start_clo={"clothoid_id": 42, "side": "line"})]
        v._elem_graph = eg
        # 現在要素を elem_graph に入れて end_clo_ref を設定
        cur = _elem(eid=10, start=(0.0, 0.0), end=(0.0, 90.0), pl=90.0,
                    end_clo=exit_ref)
        v._elem_graph = [cur, eg[0]]
        v._ad_cl = _cl()
        v._ad_cur_id = 10
        v._ad_forward = True
        v._ad_advance(0.0)
        assert v._ad_cur_id == 3


# ═══════════════════════════════════════════════════════════════
#   _update_hud
# ═══════════════════════════════════════════════════════════════

class TestUpdateHud:
    def _setup(self, **kw):
        v = _make_viewer(**kw)
        v._cur_pos = (1.0, 2.0, 3.0)
        v._cur_fwd = (1.0, 0.0, 0.0)
        return v

    def test_normal_mode_no_crash(self):
        v = self._setup()
        v._update_hud()
        v.hud.setText.assert_called()

    def test_paused_shows_paused(self):
        v = self._setup()
        v.paused = True
        v._update_hud()
        text = v.hud.setText.call_args[0][0]
        assert "PAUSED" in text

    def test_auto_mode_shows_auto(self):
        eg = [_elem()]
        si = {"id": 1, "forward": True}
        v = self._setup(elem_graph=eg, start_info=si)
        v._update_hud()
        text = v.hud.setText.call_args[0][0]
        assert "AUTO" in text

    def test_auto_warp_shows_warp(self):
        eg = [_elem()]
        si = {"id": 1, "forward": True}
        v = self._setup(elem_graph=eg, start_info=si)
        v._ad_cur_id = None
        v._update_hud()
        text = v.hud.setText.call_args[0][0]
        assert "warp" in text

    def test_history_mode_shows_history(self):
        eg = [_elem()]
        si = {"id": 1, "forward": True}
        v = self._setup(elem_graph=eg, start_info=si)
        v._ad_history_idx = 0
        v._ad_history = [{"cl": _cl(), "total": 90.0, "dist": 0.0,
                          "cur_id": 1, "forward": True}]
        v._update_hud()
        text = v.hud.setText.call_args[0][0]
        assert "History" in text

    def test_non_ascii_nickname_fallback(self):
        eg = [{"id": 1, "type": "Segment", "nickname": "日本語",
               "start": [0.0, 0.0], "end": [0.0, 100.0], "plan_length": 100.0,
               "heights": [[0.0, 0.0], [100.0, 0.0]], "points_xy": None,
               "start_clo_ref": None, "end_clo_ref": None}]
        si = {"id": 1, "forward": True}
        v = self._setup(elem_graph=eg, start_info=si)
        v._update_hud()
        text = v.hud.setText.call_args[0][0]
        assert "#1" in text


# ═══════════════════════════════════════════════════════════════
#   カメラ・自車更新
# ═══════════════════════════════════════════════════════════════

class TestUpdateCameraAndCar:
    def test_car_pose_no_crash(self):
        v = _make_viewer()
        v._update_car_pose(5.0)
        v.car_np.set_pos.assert_called()
        v.car_np.set_hpr.assert_called()

    def test_camera_follow(self):
        v = _make_viewer()
        v.view_mode = "follow"
        v._update_camera_cl(v.cl, 5.0)
        v.camera.set_pos.assert_called()
        v.camera.look_at.assert_called()

    def test_camera_overview(self):
        v = _make_viewer()
        v.view_mode = "overview"
        v._update_camera_cl(v.cl, 5.0)
        v.camera.set_pos.assert_called()
        v.camera.set_hpr.assert_called()

    def test_camera_overview_fixed(self):
        v = _make_viewer()
        v.view_mode = "overview_fixed"
        v._update_camera_cl(v.cl, 5.0)
        v.camera.set_pos.assert_called()

    def test_camera_onboard(self):
        v = _make_viewer()
        v.view_mode = "onboard"
        v._update_camera_cl(v.cl, 5.0)
        v.camera.set_pos.assert_called()
        v.camera.look_at.assert_called()


# ═══════════════════════════════════════════════════════════════
#   トラフィック
# ═══════════════════════════════════════════════════════════════

class TestTrafficMethods:
    def test_remove_one_removes_last(self):
        v = _make_viewer()
        mock_np = MagicMock()
        car = {"np": mock_np, "cl": _cl(), "total": 90.0, "dist": 0.0,
               "cur_id": None, "forward": True, "speed_mul": 1.0}
        v._traffic = [car]
        v._remove_one_traffic()
        assert len(v._traffic) == 0
        mock_np.removeNode.assert_called_once()

    def test_remove_empty_no_crash(self):
        v = _make_viewer()
        v._traffic = []
        v._remove_one_traffic()

    def test_step_within_total(self):
        v = _make_viewer()
        car_cl = [(0.0, 0.0, 0.0, 0.0), (0.0, 100.0, 0.0, 100.0)]
        car = {"np": MagicMock(), "cl": car_cl, "total": 100.0, "dist": 10.0,
               "cur_id": None, "forward": True, "speed_mul": 1.0}
        v.speed = 30.0
        v._step_traffic_car(car, 1.0)   # 10 + 30 = 40 < 100
        assert car["dist"] == pytest.approx(40.0)

    def test_step_overflow_no_cands_warps(self):
        v = _make_viewer()
        v._elem_graph = []
        car_cl = [(0.0, 0.0, 0.0, 0.0), (0.0, 10.0, 0.0, 10.0)]
        car = {"np": MagicMock(), "cl": car_cl, "total": 10.0, "dist": 9.5,
               "cur_id": None, "forward": True, "speed_mul": 1.0}
        v.speed = 1.0
        v._step_traffic_car(car, 1.0)   # 9.5 + 1 > 10 → warp
        assert car["total"] == pytest.approx(100.0)

    def test_step_overflow_with_cands_transitions(self):
        eg1 = _elem(eid=1, start=(0.0, 0.0), end=(0.0, 10.0), pl=10.0)
        eg2 = _elem(eid=2, start=(0.0, 10.0), end=(0.0, 110.0), pl=100.0)
        v = _make_viewer()
        v._elem_graph = [eg1, eg2]
        car_cl = [(0.0, 0.0, 0.0, 0.0), (0.0, 10.0, 0.0, 10.0)]
        car = {"np": MagicMock(), "cl": car_cl, "total": 10.0, "dist": 9.5,
               "cur_id": 1, "forward": True, "speed_mul": 1.0}
        v.speed = 1.0
        v._step_traffic_car(car, 1.0)
        assert car["cur_id"] == 2

    def test_update_pose_no_crash(self):
        v = _make_viewer()
        car = {"np": MagicMock(), "cl": _cl(), "dist": 5.0}
        v._update_traffic_car_pose(car)
        car["np"].setPos.assert_called()
        car["np"].setHpr.assert_called()

    def test_add_one_traffic_no_crash(self):
        v = _make_viewer()
        v._traffic = []
        v._auto_drive = False
        v.dist = 0.0
        v._add_one_traffic()
        # render が MagicMock なので内部で _add_traffic_car が走ってもクラッシュしない
        assert len(v._traffic) == 1

    def test_add_traffic_car_negative_offset_no_name_error(self):
        """負オフセット時の while init_dist < 0 ループで _elem_fwd_vec が正しく呼ばれる。

        修正前は _fwd_vec（未定義）が使われており NameError が発生していた（バグ修正確認）。
        """
        eg1 = _elem(eid=1, start=(0.0, 0.0), end=(0.0, 100.0), pl=100.0)
        eg2 = _elem(eid=2, start=(0.0, -100.0), end=(0.0, 0.0), pl=100.0)
        v = _make_viewer(elem_graph=eg1 and [eg1, eg2])
        v._elem_graph = [eg1, eg2]
        v._ad_cl = [(0.0, 0.0, 0.0, 0.0), (0.0, 100.0, 0.0, 100.0)]
        v._ad_total = 100.0
        v._ad_dist = 0.0
        v._ad_cur_id = 1
        v._ad_forward = True
        # 負オフセットを渡して while init_dist < 0 ループに入る
        # NameError が出なければ修正済み
        v._add_traffic_car(offset=-10.0)   # 0.0 + (-10.0) = -10 < 0 → ループ突入


# ═══════════════════════════════════════════════════════════════
#   prepare_viewer_data
# ═══════════════════════════════════════════════════════════════

class TestPrepareViewerData:
    def _simple_scene(self):
        from models import Scene, Vec2, Line, Segment, ElementProfile
        sc = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        sc.add_line(ln)
        ep = ElementProfile()
        ep.element_id = seg.id
        ep.plan_length = 100.0
        sc.element_profiles.append(ep)
        return sc, seg, ep

    def test_returns_centerline(self):
        from road_viewer import prepare_viewer_data
        sc, seg, ep = self._simple_scene()
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        assert len(result["centerline_3d"]) > 0

    def test_returns_elem_graph(self):
        from road_viewer import prepare_viewer_data
        sc, seg, ep = self._simple_scene()
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        assert len(result["elem_graph"]) > 0

    def test_start_info_forward(self):
        from road_viewer import prepare_viewer_data
        sc, seg, ep = self._simple_scene()
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        assert result["start_info"]["forward"] is True

    def test_start_info_reversed(self):
        from road_viewer import prepare_viewer_data
        sc, seg, ep = self._simple_scene()
        result = prepare_viewer_data(sc, [seg], [ep], [True])
        assert result["start_info"]["forward"] is False

    def test_empty_elements(self):
        from road_viewer import prepare_viewer_data
        from models import Scene
        result = prepare_viewer_data(Scene(), [], [], [])
        assert result["centerline_3d"] == []
        assert result["start_info"] is None

    def test_all_display_adds_segments(self):
        from road_viewer import prepare_viewer_data
        sc, seg, ep = self._simple_scene()
        result = prepare_viewer_data(sc, [], [], [], all_display=[seg])
        assert len(result["display_segments"]) > 0

    def test_arc_in_elem_graph(self):
        from road_viewer import prepare_viewer_data
        from models import Scene, Vec2, Circle, Arc, ElementProfile
        sc = Scene()
        ci = Circle(Vec2(0, 0), 50.0)
        arc = Arc(ci, 0.0, math.pi / 2)
        ci.arcs.append(arc)
        sc.add_circle(ci)
        ep = ElementProfile()
        ep.element_id = arc.id
        ep.plan_length = 50.0 * math.pi / 2
        sc.element_profiles.append(ep)
        result = prepare_viewer_data(sc, [], [], [])
        arc_entries = [e for e in result["elem_graph"] if e["type"] == "Arc"]
        assert len(arc_entries) >= 1

    def test_clothoid_in_elem_graph(self):
        from road_viewer import prepare_viewer_data
        from models import (
            Scene, Vec2, Line, Segment, Circle, Clothoid, ElementProfile,
        )
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(0, 80), 50.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci)
        sc.add_clothoid(clo)
        ep = ElementProfile()
        ep.element_id = seg.id
        ep.plan_length = 200.0
        sc.element_profiles.append(ep)
        result = prepare_viewer_data(sc, [], [], [])
        if clo.is_valid:
            clo_entries = [e for e in result["elem_graph"]
                           if e["type"] == "Clothoid"]
            assert len(clo_entries) >= 1

    def test_segment_points_xy_in_elem_graph(self):
        from road_viewer import prepare_viewer_data
        sc, seg, ep = self._simple_scene()
        result = prepare_viewer_data(sc, [seg], [ep], [False])
        entries = [e for e in result["elem_graph"] if e["type"] == "Segment"]
        assert len(entries) >= 1
        assert entries[0]["points_xy"] is not None
        assert len(entries[0]["points_xy"]) >= 2

    def test_clo_ref_map_in_elem_graph(self):
        """Clothoid 接点を持つ要素に start_clo_ref / end_clo_ref が設定される"""
        from road_viewer import prepare_viewer_data
        from models import (
            Scene, Vec2, Line, Segment, Circle, Clothoid, ElementProfile,
        )
        sc = Scene()
        ln = Line(Vec2(-100, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        ci = Circle(Vec2(0, 80), 50.0)
        sc.add_line(ln)
        sc.add_circle(ci)
        clo = Clothoid(ln, ci)
        sc.add_clothoid(clo)
        ep = ElementProfile()
        ep.element_id = seg.id
        ep.plan_length = 200.0
        sc.element_profiles.append(ep)
        result = prepare_viewer_data(sc, [], [], [])
        if clo.is_valid:
            # Clothoid接点に対応するセグメントに clo_ref が付いているはず
            has_ref = any(
                e.get("start_clo_ref") or e.get("end_clo_ref")
                for e in result["elem_graph"]
            )
            assert has_ref


# ═══════════════════════════════════════════════════════════════
#   _curvature_at（符号付き曲率の純粋計算）
# ═══════════════════════════════════════════════════════════════

class TestCurvatureAt:
    """[仕様] 左曲がりを正・右曲がりを負とする符号付き曲率 [1/m]。

    期待値は円弧の幾何（曲率 = 1/半径）から手計算する。
    """

    @staticmethod
    def _circle_cl(radius=50.0, left=True, n=50, dtheta=0.04):
        """進行方向 +x から始まる半径 radius の円弧中心線。

        left=True なら反時計回り（左カーブ）。
        x = R·sinθ, y = ±R·(1−cosθ), dist = R·θ
        """
        cl = []
        for i in range(n + 1):
            th = i * dtheta
            x = radius * math.sin(th)
            y = radius * (1.0 - math.cos(th))
            if not left:
                y = -y
            cl.append((x, y, 0.0, radius * th))
        return cl

    def test_straight_line_curvature_zero(self):
        from road_viewer import RoadViewer
        cl = _cl(n=20)   # y 方向直線
        assert RoadViewer._curvature_at(cl, 50.0) == pytest.approx(
            0.0, abs=1e-9)

    def test_left_circle_positive_inverse_radius(self):
        from road_viewer import RoadViewer
        cl = self._circle_cl(radius=50.0, left=True)
        kappa = RoadViewer._curvature_at(cl, 50.0)
        assert kappa == pytest.approx(1.0 / 50.0, rel=0.05)

    def test_right_circle_negative_inverse_radius(self):
        from road_viewer import RoadViewer
        cl = self._circle_cl(radius=50.0, left=False)
        kappa = RoadViewer._curvature_at(cl, 50.0)
        assert kappa == pytest.approx(-1.0 / 50.0, rel=0.05)

    def test_tighter_circle_larger_curvature(self):
        from road_viewer import RoadViewer
        cl_small = self._circle_cl(radius=20.0, left=True)
        cl_large = self._circle_cl(radius=100.0, left=True)
        k_small = RoadViewer._curvature_at(cl_small, 20.0)
        k_large = RoadViewer._curvature_at(cl_large, 100.0)
        assert k_small > k_large > 0

    def test_too_few_points_returns_zero(self):
        from road_viewer import RoadViewer
        assert RoadViewer._curvature_at([], 0.0) == 0.0
        assert RoadViewer._curvature_at(
            [(0, 0, 0, 0), (1, 0, 0, 1)], 0.5) == 0.0
