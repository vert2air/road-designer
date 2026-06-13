"""
要求仕様書 第4章「メイン編集画面」適合確認テスト (GUI)。

実行方法:
    uv run pytest -m spec tests/test_spec_gui_ch4.py -v

CI では -m 'not spec' により除外されるため、開発者が手動で実行する。
各テストクラスの docstring に対応する仕様書の節番号と条文を引用する。
"""
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

pytestmark = pytest.mark.spec


# ─── ヘルパー ────────────────────────────────────────────────────

def _add_line(scene, x0=0.0, y0=0.0, x1=100.0, y1=0.0):
    """シーンに直線と線分を1本追加して (line, seg) を返す。"""
    from models import Line, Segment, Vec2
    ln = Line(Vec2(x0, y0), Vec2(x1, y1))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    scene.add_line(ln)
    return ln, seg


# ─── 4.2 モード切替 ─────────────────────────────────────────────

class TestSpec4_2_ModeSwitch:
    """4.2 モード切替

    仕様書より:
        | キー | モード     |
        |------|-----------|
        | `S`  | 選択モード |
        | `L`  | 直線モード |
        | `C`  | 円モード   |
    """

    def test_s_action_activates_select_mode(self, make_window_qt):
        """[4.2] S アクション（ショートカット）を trigger すると選択モードになる。"""
        w = make_window_qt()
        w._act_line.trigger()                   # 先に直線モードへ
        assert w._canvas.mode == "line"

        w._act_select.trigger()
        assert w._canvas.mode == "select"

    def test_l_action_activates_line_mode(self, make_window_qt):
        """[4.2] L アクション（ショートカット）を trigger すると直線モードになる。"""
        w = make_window_qt()
        assert w._canvas.mode == "select"       # 初期は select

        w._act_line.trigger()
        assert w._canvas.mode == "line"

    def test_c_action_activates_circle_mode(self, make_window_qt):
        """[4.2] C アクション（ショートカット）を trigger すると円モードになる。"""
        w = make_window_qt()
        w._act_circle.trigger()
        assert w._canvas.mode == "circle"

    def test_mode_toggle_sequence(self, make_window_qt):
        """[4.2] S → L → C → S の順に切り替えられる。"""
        w = make_window_qt()
        for mode, action in [
            ("line", w._act_line),
            ("circle", w._act_circle),
            ("select", w._act_select),
        ]:
            action.trigger()
            assert w._canvas.mode == mode


# ─── 4.3 直線モード ───────────────────────────────────────────────

class TestSpec4_3_LineMode:
    """4.3 直線モード

    仕様書より:
        マウスを左クリックするたびに折れ線を描く。
        1回目のクリック位置を記憶し、2回目以降のクリックで直線を追加・折れ線接続する。
        ラバー線により次の直線の予定位置を表示する。
        `Esc` キーで連続入力をリセット。
    """

    def test_first_click_sets_line_first_pt(self, make_window_qt, qtbot):
        """[4.3] 直線モードで1回目のクリックを行うと始点が記録される。"""
        w = make_window_qt()
        w._act_line.trigger()
        c = w._canvas

        assert c._line_first_pt is None
        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))
        assert c._line_first_pt is not None

    def test_first_click_does_not_add_line_to_scene(
            self, make_window_qt, qtbot):
        """[4.3] 1回目のクリックではシーンに直線が追加されない。"""
        w = make_window_qt()
        w._act_line.trigger()
        c = w._canvas

        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(300, 500))
        assert len(w.scene.lines) == 0

    def test_second_click_adds_line_to_scene(self, make_window_qt, qtbot):
        """[4.3] 2回目のクリックで直線がシーンに追加される。"""
        w = make_window_qt()
        w._act_line.trigger()
        c = w._canvas

        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(300, 500))
        assert len(w.scene.lines) == 0          # まだ追加されていない

        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(700, 500))
        assert len(w.scene.lines) == 1          # 2回目で追加

    def test_esc_resets_line_first_pt(self, make_window_qt, qtbot):
        """[4.3] Esc キーで直線の始点（_line_first_pt）がリセットされる。"""
        w = make_window_qt()
        w._act_line.trigger()
        c = w._canvas

        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))
        assert c._line_first_pt is not None

        qtbot.keyClick(c, Qt.Key.Key_Escape)
        assert c._line_first_pt is None

    def test_esc_does_not_delete_already_added_lines(
            self, make_window_qt, qtbot):
        """[4.3] Esc キーは追加済みの直線を削除しない。"""
        w = make_window_qt()
        w._act_line.trigger()
        c = w._canvas

        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(300, 500))
        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(700, 500))
        assert len(w.scene.lines) == 1

        qtbot.keyClick(c, Qt.Key.Key_Escape)
        assert len(w.scene.lines) == 1          # Esc で削除されない


# ─── 4.4 円モード ─────────────────────────────────────────────────

class TestSpec4_4_CircleMode:
    """4.4 円モード

    仕様書より:
        マウスの左クリックで中心を決め、ドラッグで半径を仮表示し、
        左ボタンを離すことで半径を確定する。
    """

    def test_press_sets_circle_center(self, make_window_qt, qtbot):
        """[4.4] 円モードで左ボタンを押すと中心座標が記録される。"""
        w = make_window_qt()
        w._act_circle.trigger()
        c = w._canvas

        assert c._circle_center is None
        qtbot.mousePress(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))
        assert c._circle_center is not None
        qtbot.mouseRelease(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))

    def test_drag_release_adds_circle_to_scene(self, make_window_qt, qtbot):
        """[4.4] 円モードでドラッグ後にリリースすると円がシーンに追加される。"""
        w = make_window_qt()
        w._act_circle.trigger()
        c = w._canvas

        # 押し込み → 移動（半径を設定）→ リリース
        qtbot.mousePress(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))
        QTest.mouseMove(c, QPoint(600, 500))        # 100px 離れた位置へ移動
        qtbot.mouseRelease(c, Qt.MouseButton.LeftButton, pos=QPoint(600, 500))

        assert len(w.scene.circles) == 1

    def test_zero_radius_does_not_add_circle(self, make_window_qt, qtbot):
        """[4.4] 押してその場で離した場合（半径ゼロ）は円が追加されない。"""
        w = make_window_qt()
        w._act_circle.trigger()
        c = w._canvas

        # 同じ位置でプレス＆リリース → radius ≈ 0
        qtbot.mousePress(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))
        qtbot.mouseRelease(c, Qt.MouseButton.LeftButton, pos=QPoint(500, 500))

        assert len(w.scene.circles) == 0


# ─── 4.5 選択モードでの図形操作 ──────────────────────────────────

class TestSpec4_5_DeleteAndMultiSelect:
    """4.5 選択モードでの図形操作

    仕様書より:
        - 左クリックで選択、`Shift` + クリックで複数選択
        - `Del` キーで削除（直線・円を削除すると関連クロソイドも削除）
    """

    def test_del_key_deletes_selected_line(self, make_window_qt, qtbot):
        """[4.5] Del キーで選択中の直線が削除される。"""
        w = make_window_qt()
        ln, seg = _add_line(w.scene)
        assert len(w.scene.lines) == 1

        c = w._canvas
        c.set_selection([ln])
        qtbot.keyClick(c, Qt.Key.Key_Delete)
        assert len(w.scene.lines) == 0

    def test_del_key_deletes_selected_circle(self, make_window_qt, qtbot):
        """[4.5] Del キーで選択中の円が削除される。"""
        from models import Circle, Vec2
        w = make_window_qt()
        ci = Circle(Vec2(0, 0), 50)
        w.scene.add_circle(ci)
        assert len(w.scene.circles) == 1

        c = w._canvas
        c.set_selection([ci])
        qtbot.keyClick(c, Qt.Key.Key_Delete)
        assert len(w.scene.circles) == 0

    def test_del_line_also_removes_related_clothoids(
            self, make_window_qt, qtbot):
        """[4.5] 直線を削除すると関連するクロソイドも削除される。"""
        from models import Circle, Clothoid, Vec2
        w = make_window_qt()
        ln, seg = _add_line(w.scene, x0=0.0, y0=0.0, x1=100.0, y1=0.0)
        ci = Circle(Vec2(50, 50), 30)
        w.scene.add_circle(ci)
        clo = Clothoid(ln, ci, reversed_flag=False)
        w.scene.add_clothoid(clo)
        assert len(w.scene.clothoids) == 1

        c = w._canvas
        c.set_selection([ln])
        qtbot.keyClick(c, Qt.Key.Key_Delete)
        assert len(w.scene.lines) == 0
        assert len(w.scene.clothoids) == 0, "直線に関連するクロソイドも削除されるべき"

    def test_del_circle_also_removes_related_clothoids(
            self, make_window_qt, qtbot):
        """[4.5] 円を削除すると関連するクロソイドも削除される。"""
        from models import Circle, Clothoid, Vec2
        w = make_window_qt()
        ln, seg = _add_line(w.scene)
        ci = Circle(Vec2(50, 50), 30)
        w.scene.add_circle(ci)
        clo = Clothoid(ln, ci, reversed_flag=False)
        w.scene.add_clothoid(clo)
        assert len(w.scene.clothoids) == 1

        c = w._canvas
        c.set_selection([ci])
        qtbot.keyClick(c, Qt.Key.Key_Delete)
        assert len(w.scene.circles) == 0
        assert len(w.scene.clothoids) == 0, "円に関連するクロソイドも削除されるべき"

    def test_shift_click_adds_second_object_to_selection(
            self, make_window_qt, qtbot):
        """[4.5] Shift+クリックで2つ目の図形を選択に追加できる。

        Canvas の scale=1.0, offset=(500,500) のとき:
          スクリーン (550, 500) → ワールド (50, 0)  ← seg1 の中点
          スクリーン (750, 500) → ワールド (250, 0) ← seg2 の中点
        """
        from PySide6.QtTest import QTest as _QTest
        w = make_window_qt()
        c = w._canvas
        # Canvas は make_window_qt で scale=1.0, offset=(500,500) に設定済み

        # seg1: world (0,0)–(100,0)  → 中点スクリーン (550, 500)
        _add_line(w.scene, x0=0.0, y0=0.0, x1=100.0, y1=0.0)
        # seg2: world (200,0)–(300,0) → 中点スクリーン (750, 500)
        _add_line(w.scene, x0=200.0, y0=0.0, x1=300.0, y1=0.0)

        # 1本目をクリックで選択（modifier を位置引数で渡す）
        _QTest.mouseClick(c, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier, QPoint(550, 500))
        assert len(c._selected) == 1

        # 2本目を Shift+クリックで追加選択（QTest.mouseClick を直接使用）
        _QTest.mouseClick(c, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.ShiftModifier, QPoint(750, 500))
        assert len(c._selected) == 2, "Shift+クリックで複数選択になるべき"

    def test_click_empty_area_clears_selection(self, make_window_qt, qtbot):
        """[4.5] 何もない場所をクリックすると選択が解除される。"""
        w = make_window_qt()
        ln, seg = _add_line(w.scene)
        c = w._canvas
        c.set_selection([ln])
        assert len(c._selected) == 1

        # Canvas の遠隅（図形のないエリア）をクリック（パン→リリース時に選択解除）
        qtbot.mousePress(c, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        qtbot.mouseRelease(c, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        assert len(c._selected) == 0, "空の場所クリックで選択解除されるべき"


# ─── 4.8 Undo ────────────────────────────────────────────────────

class TestSpec4_8_Undo:
    """4.8 Undo

    仕様書より:
        `Ctrl+Z` で最大 500 手順まで遡ることができる。
        シーン全体を JSON でシリアライズしてスタックに積む方式。
    """

    def test_undo_stack_max_capacity_is_500(self, make_window_qt):
        """[4.8] Undo スタックの最大容量が 500 である。"""
        w = make_window_qt()
        assert w._canvas._undo_stack.maxlen == 500

    def test_ctrl_z_undoes_line_addition(self, make_window_qt, qtbot):
        """[4.8] 直線追加後に Ctrl+Z を押すと元に戻る（直線がなくなる）。"""
        w = make_window_qt()
        c = w._canvas

        # push_undo してから直線を追加
        c.push_undo()
        _add_line(w.scene)
        assert len(w.scene.lines) == 1

        qtbot.keyClick(c, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(w.scene.lines) == 0

    def test_ctrl_z_in_line_mode_undoes_line_addition(
            self, make_window_qt, qtbot):
        """[4.8] 直線モードで2クリックして追加した直線を Ctrl+Z で元に戻せる。"""
        w = make_window_qt()
        w._act_line.trigger()
        c = w._canvas

        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(300, 500))
        qtbot.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(700, 500))
        assert len(w.scene.lines) == 1

        qtbot.keyClick(c, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(w.scene.lines) == 0

    def test_undo_multiple_steps(self, make_window_qt, qtbot):
        """[4.8] Undo を複数回押すと、その都度1操作ずつ戻る。"""
        w = make_window_qt()
        c = w._canvas

        # 2本の直線を追加（それぞれ push_undo あり）
        c.push_undo()
        _add_line(w.scene, x0=0, y0=0, x1=100, y1=0)
        assert len(w.scene.lines) == 1

        c.push_undo()
        _add_line(w.scene, x0=200, y0=0, x1=300, y1=0)
        assert len(w.scene.lines) == 2

        # 1回目の Undo → 1本に戻る
        qtbot.keyClick(c, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(w.scene.lines) == 1

        # 2回目の Undo → 0本に戻る
        qtbot.keyClick(c, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(w.scene.lines) == 0

    def test_undo_empty_stack_is_noop(self, make_window_qt, qtbot):
        """[4.8] スタックが空の状態で Ctrl+Z を押してもエラーにならない。"""
        w = make_window_qt()
        c = w._canvas
        assert len(c._undo_stack) == 0

        # エラーなく実行できることを確認
        qtbot.keyClick(c, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(w.scene.lines) == 0


# ─── 4.5 ラバーバンド選択（Shift + 左ドラッグ） ─────────────────

class TestSpec4_5_RubberBandSelect:
    """4.5 選択モードでの図形操作 — ラバーバンド選択

    仕様書より:
        選択モードで Shift を押しながら何もない場所をドラッグすると、
        矩形による一括選択ができる。矩形に完全に含まれる図形のみ
        選択する。線分・円弧が選択されるとき、その親の直線・円も
        一緒に選択される。ドラッグ中は対角線のワールド距離が右パネルに
        表示される（簡易測距ツールを兼ねる）。Esc キーでキャンセル。
    """

    def test_shift_drag_selects_enclosed_figure_and_parent(
            self, make_window_qt, qtbot):
        """[4.5] Shift+ドラッグで囲んだ線分とその親直線が選択される。"""
        w = make_window_qt()
        c = w._canvas
        ln, seg = _add_line(w.scene, 0, 0, 100, 0)
        c.show()
        # 図形から離れた点 (=ワールド(-200,200)) からドラッグ開始
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier,
                         QPoint(300, 300))
        QTest.mouseMove(c, QPoint(610, 510))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ShiftModifier,
                           QPoint(610, 510))
        assert seg in c._selected
        assert ln in c._selected

    def test_partially_enclosed_figure_not_selected(
            self, make_window_qt, qtbot):
        """[4.5] 矩形に完全に含まれない図形は選択されない。"""
        w = make_window_qt()
        c = w._canvas
        _add_line(w.scene, 0, 0, 100, 0)
        c.show()
        # 線分の右半分だけを囲む（x=50..110 のみ）
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier,
                         QPoint(550, 300))
        QTest.mouseMove(c, QPoint(610, 510))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ShiftModifier,
                           QPoint(610, 510))
        assert c._selected == []

    def test_measure_distance_shown_in_right_panel(
            self, make_window_qt, qtbot):
        """[4.5/5.1] ドラッグ中に対角距離が右パネルに表示され、
        終了で消える。"""
        w = make_window_qt()
        w._set_right_panel_visible(True)
        c = w._canvas
        rp = w._right_panel
        c.show()
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier,
                         QPoint(300, 300))
        # ワールド距離 100（(-200,200)→(-100,200)）の移動
        QTest.mouseMove(c, QPoint(400, 300))
        assert "100.000" in rp._lbl_measure_dist.text()
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ShiftModifier,
                           QPoint(400, 300))
        assert rp._lbl_measure_dist.text() == ""

    def test_esc_cancels_rubber_band(self, make_window_qt, qtbot):
        """[4.5] Esc キーでドラッグ中のラバーバンド選択をキャンセル。"""
        w = make_window_qt()
        c = w._canvas
        c.show()
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier,
                         QPoint(300, 300))
        QTest.mouseMove(c, QPoint(400, 400))
        assert c._rubber_select_start is not None
        QTest.keyClick(c, Qt.Key.Key_Escape)
        assert c._rubber_select_start is None


# ─── 4.5 複数図形選択時の AABB 操作 ──────────────────────────────

class TestSpec4_5_AabbOperations:
    """4.5 選択モードでの図形操作 — 複数図形選択時の AABB 操作

    仕様書より:
        実効的な選択図形が 2 個以上のとき、選択範囲を囲む AABB 枠線と
        操作ハンドルを表示する。辺=平行移動、頂点=XY 等率拡大縮小、
        対角線=回転。ドラッグ完了時に Undo スタックに記録される。
    """

    @staticmethod
    def _two_figures(w):
        from models import Circle, Vec2
        ln, seg = _add_line(w.scene, 0, 0, 10, 0)
        ci = Circle(Vec2(100, 0), 50.0)
        w.scene.add_circle(ci)
        w._canvas._selected = [ln, ci]
        return ln, ci

    def test_edge_drag_translates_all(self, make_window_qt, qtbot):
        """[4.5] 辺ドラッグで全選択図形が平行移動する。"""
        w = make_window_qt()
        c = w._canvas
        ln, ci = self._two_figures(w)
        c.show()
        # AABB(0,-50)-(150,50) の上辺中点 (575,450) → (575,440)
        # = ワールド +10 上へ
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(575, 450))
        QTest.mouseMove(c, QPoint(575, 440))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier,
                           QPoint(575, 440))
        assert ln.ref_start.y == pytest.approx(10)
        assert ci.center.y == pytest.approx(10)

    def test_aabb_drag_recorded_in_undo(self, make_window_qt, qtbot):
        """[4.5] AABB ドラッグ後に Ctrl+Z で元の位置に戻る。"""
        w = make_window_qt()
        c = w._canvas
        ln, ci = self._two_figures(w)
        c.show()
        QTest.mousePress(c, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(575, 450))
        QTest.mouseMove(c, QPoint(575, 440))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier,
                           QPoint(575, 440))
        QTest.keyClick(c, Qt.Key.Key_Z,
                       Qt.KeyboardModifier.ControlModifier)
        restored_ln = w.scene.lines[0]
        restored_ci = w.scene.circles[0]
        assert restored_ln.ref_start.y == pytest.approx(0)
        assert restored_ci.center.y == pytest.approx(0)


# ─── 4.6 / 5.10.2 TwoLineOffsetConstraint（2直線+1円） ──────────

class TestSpec4_6_TwoLineOffsetPanel:
    """4.6 2図形選択時の操作 — 2 直線 + 1 円が選択された場合

    仕様書より:
        右パネルに TwoLineOffsetConstraint パネルが表示される。
        「オフセット拘束を設定」で拘束を登録し、直線が動くと円の中心が
        追従する。「オフセット拘束を解除」で解除する。
    """

    @staticmethod
    def _setup(w):
        from models import Line, Circle, Segment, Vec2
        la = Line(Vec2(0, 0), Vec2(10, 0))
        la.segments.append(Segment(la, 0.0, 1.0))
        lb = Line(Vec2(0, 0), Vec2(0, 10))
        lb.segments.append(Segment(lb, 0.0, 1.0))
        ci = Circle(Vec2(13, 12), 10.0)
        w.scene.add_line(la)
        w.scene.add_line(lb)
        w.scene.add_circle(ci)
        return la, lb, ci

    def test_set_button_creates_constraint_and_circle_follows(
            self, make_window_qt, qtbot):
        """[4.6] 設定ボタン → 拘束が登録され、直線移動に円が追従。"""
        from PySide6.QtWidgets import QPushButton
        from models import Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        la, lb, ci = self._setup(w)
        w._right_panel.update_selection([la, lb, ci], w.scene)
        btns = [b for b in w._right_panel.findChildren(QPushButton)
                if b.text() == "オフセット拘束を設定"]
        assert btns, "設定ボタンが表示されていない"
        btns[0].click()
        assert len(w.scene.two_line_offset_constraints) == 1

        # 直線 A を y=5 に移動 → 円中心が (13,17) に追従するはず
        la.ref_start = Vec2(0, 5)
        la.ref_end = Vec2(10, 5)
        w._canvas.propagate_from_line(la)
        assert ci.center.y == pytest.approx(17.0)
        assert ci.center.x == pytest.approx(13.0)

    def test_clear_button_removes_constraint(self, make_window_qt, qtbot):
        """[4.6] 解除ボタン → 拘束が削除される。"""
        from PySide6.QtWidgets import QPushButton
        from models import TwoLineOffsetConstraint
        w = make_window_qt()
        w._set_right_panel_visible(True)
        la, lb, ci = self._setup(w)
        oc = TwoLineOffsetConstraint()
        oc.line_a, oc.line_b, oc.circle = la, lb, ci
        oc.calc_offsets_from_current()
        w.scene.two_line_offset_constraints.append(oc)
        w._right_panel.update_selection([la, lb, ci], w.scene)
        btns = [b for b in w._right_panel.findChildren(QPushButton)
                if b.text() == "オフセット拘束を解除"]
        assert btns, "解除ボタンが表示されていない"
        btns[0].click()
        assert w.scene.two_line_offset_constraints == []


# ─── 4.8 Undo の対象操作（追加分） ───────────────────────────────

class TestSpec4_8_UndoNewTargets:
    """4.8 Undo — 全削除・マージ・オフセット拘束設定の Undo 対応

    仕様書より:
        Undo の対象操作: …全削除…追加で読み込む（マージ）…
        オフセット拘束の設定・解除（両種類）。
    """

    def test_clear_all_is_undoable(self, make_window_qt):
        """[4.8] 全削除 → Ctrl+Z でシーンが復元される。"""
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        w = make_window_qt()
        _add_line(w.scene, 0, 0, 100, 0)
        with patch.object(QMessageBox, 'question',
                          return_value=QMessageBox.StandardButton.Yes):
            w._clear_all()
        assert w.scene.lines == []
        w._canvas.undo()
        assert len(w.scene.lines) == 1

    def test_merge_is_undoable(self, make_window_qt, tmp_path):
        """[4.8] マージ → Ctrl+Z で追加前に戻る。"""
        import json
        from unittest.mock import patch
        from models import Scene, Line, Vec2
        w = make_window_qt()
        src = Scene()
        src.add_line(Line(Vec2(0, 100), Vec2(100, 100)))
        path = tmp_path / "m.rdjson"
        path.write_text(json.dumps(src.to_dict()), encoding='utf-8')
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',
                   return_value=(str(path), '')):
            w._merge()
        assert len(w.scene.lines) == 1
        w._canvas.undo()
        assert w.scene.lines == []

    def test_two_line_constraint_set_is_undoable(self, make_window_qt):
        """[4.8] 2直線+1円拘束の設定 → Ctrl+Z で解除される。"""
        from models import Line, Circle, Vec2
        w = make_window_qt()
        la = Line(Vec2(0, 0), Vec2(10, 0))
        lb = Line(Vec2(0, 0), Vec2(0, 10))
        ci = Circle(Vec2(13, 12), 10.0)
        w.scene.add_line(la)
        w.scene.add_line(lb)
        w.scene.add_circle(ci)
        w._do_set_two_line_offset_constraint(la, lb, ci)
        assert len(w.scene.two_line_offset_constraints) == 1
        w._canvas.undo()
        assert w.scene.two_line_offset_constraints == []


# ─── 4.5 / 4.7 AABB・ラバーバンドの描画 ──────────────────────────

class TestSpec4_7_MultiSelectRendering:
    """4.7 図形の色分け — AABB 枠線・ラバーバンド矩形の描画

    仕様書より:
        AABB 枠線・対角線（複数選択時）: 青色（半透明）。
        AABB 頂点ハンドル: 青色。
        （4.5）ドラッグ中は矩形が青系の破線枠 + 半透明塗りで表示される。

    実際に描画した画像のピクセル色で検証する。
    """

    @staticmethod
    def _grab(c):
        return c.grab().toImage()

    def test_aabb_vertex_handle_painted_blue(self, make_window_qt, qtbot):
        """[4.7] 複数選択時、AABB 頂点位置に青系ハンドルが描かれる。"""
        from models import Circle, Vec2
        w = make_window_qt()
        c = w._canvas
        ln, _ = _add_line(w.scene, 0, 0, 10, 0)
        ci = Circle(Vec2(100, 0), 50.0)
        w.scene.add_circle(ci)
        c._selected = [ln, ci]
        w.show()
        qtbot.waitExposed(c)
        img = self._grab(c)
        # AABB TL 頂点 = スクリーン (500, 450)
        px = img.pixelColor(500, 450)
        assert px.blue() > px.red(), f"頂点が青系でない: {px.name()}"
        # AABB 中心 (575, 500) 付近に十字（背景色ではない）
        center_px = img.pixelColor(575, 500)
        bg = img.pixelColor(50, 50)
        assert center_px != bg

    def test_single_selection_has_no_aabb(self, make_window_qt, qtbot):
        """[4.7] 単一選択では AABB ハンドルは描かれない。"""
        from models import Circle, Vec2
        w = make_window_qt()
        c = w._canvas
        ci = Circle(Vec2(100, 0), 50.0)
        w.scene.add_circle(ci)
        c._selected = [ci]
        w.show()
        qtbot.waitExposed(c)
        img = self._grab(c)
        # 単一選択の AABB 相当位置（円の左上外側）は背景色のまま
        px = img.pixelColor(545, 445)
        bg = img.pixelColor(50, 50)
        assert px == bg

    def test_rubber_band_rect_painted(self, make_window_qt, qtbot):
        """[4.5] ラバーバンド矩形が半透明塗り＋対角線で描かれる。"""
        from models import Vec2
        w = make_window_qt()
        c = w._canvas
        w.show()
        qtbot.waitExposed(c)
        c._rubber_select_start = Vec2(400, 400)
        c._rubber_select_end = Vec2(600, 600)
        c.repaint()
        img = self._grab(c)
        inside = img.pixelColor(500, 480)    # 矩形内（対角線を避ける）
        outside = img.pixelColor(200, 200)   # 矩形外
        assert inside != outside, "半透明塗りが描かれていない"
        # 対角線（始点→終点、y=x 上）の中点付近
        diag = img.pixelColor(500, 500)
        assert diag.blue() > diag.red(), f"対角線が青系でない: {diag.name()}"
