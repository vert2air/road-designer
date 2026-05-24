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
            ("line",   w._act_line),
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

    def test_first_click_does_not_add_line_to_scene(self, make_window_qt, qtbot):
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

    def test_esc_does_not_delete_already_added_lines(self, make_window_qt, qtbot):
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

    def test_del_line_also_removes_related_clothoids(self, make_window_qt, qtbot):
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

    def test_del_circle_also_removes_related_clothoids(self, make_window_qt, qtbot):
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

    def test_shift_click_adds_second_object_to_selection(self, make_window_qt, qtbot):
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
        from models import Line, Vec2
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

    def test_ctrl_z_in_line_mode_undoes_line_addition(self, make_window_qt, qtbot):
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
