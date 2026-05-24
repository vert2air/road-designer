"""
要求仕様書 第6章「縦断線形設計ウィンドウ」適合確認テスト (GUI)。

実行方法:
    uv run pytest -m spec tests/test_spec_gui_ch6.py -v

CI では -m 'not spec' により除外されるため、開発者が手動で実行する。
各テストクラスの docstring に対応する仕様書の節番号と条文を引用する。
"""
import pytest
from PySide6.QtCore import Qt

pytestmark = pytest.mark.spec


# ─── ヘルパー ────────────────────────────────────────────────────

def _make_vw(qtbot, n_grade_lines=0):
    """テスト用の VerticalAlignmentWindow を生成して返す。

    Parameters
    ----------
    n_grade_lines : int
        生成直後にキャンバスへ追加する勾配直線の本数（undo テスト用）。
    """
    from models import Scene, Line, Segment, Vec2, GradeLine
    from vertical_window import VerticalAlignmentWindow

    # シンプルな平面線形: 長さ 100m の線分 1 本
    scene = Scene()
    ln = Line(Vec2(0, 0), Vec2(100, 0))
    seg = Segment(ln, 0.0, 1.0)
    ln.segments.append(seg)
    scene.add_line(ln)

    # ElementProfile は models からインポート
    from models import ElementProfile
    ep = ElementProfile()
    ep.element_id = seg.id
    ep.element_type = 'segment'
    ep.plan_length = 100.0      # 100m
    ep.grade_lines = []
    ep.vertical_curves = []

    vw = VerticalAlignmentWindow(scene, [ep], [seg], [False])
    qtbot.addWidget(vw)
    vw.show()

    canvas = vw._canvas
    # 必要に応じて勾配直線を追加（Undo テスト用）
    if n_grade_lines > 0:
        for i in range(n_grade_lines):
            gl = GradeLine(dist_start=float(i * 20),
                           elev_start=10.0 + i,
                           dist_end=float(i * 20 + 10),
                           elev_end=11.0 + i)
            canvas._grade_lines.append(gl)

    return vw, canvas


# ─── 6.2 モード切替 ─────────────────────────────────────────────

class TestSpec6_2_ModeSwitch:
    """6.2 モード切替

    仕様書より:
        | キー  | モード                                       |
        |-------|---------------------------------------------|
        | `S`   | 選択モード（勾配直線・縦断曲線をクリックで選択）|
        | `G`   | 勾配直線モード（左クリックで始点→終点を指定）  |
        | `Esc` | 連続入力のリセット                           |
    """

    def test_initial_mode_is_select(self, qtbot):
        """[6.2] ウィンドウ起動時のモードは選択モード（select）である。"""
        vw, canvas = _make_vw(qtbot)
        assert canvas._mode == "select"

    def test_g_key_activates_grade_mode(self, qtbot):
        """[6.2] G キーを押すと勾配直線モード（grade）になる。"""
        vw, canvas = _make_vw(qtbot)
        assert canvas._mode == "select"

        qtbot.keyClick(vw, Qt.Key.Key_G)
        assert canvas._mode == "grade"

    def test_s_key_activates_select_mode_from_grade(self, qtbot):
        """[6.2] 勾配直線モードのときに S キーを押すと選択モード（select）になる。"""
        vw, canvas = _make_vw(qtbot)
        vw._set_grade_mode()
        assert canvas._mode == "grade"

        qtbot.keyClick(vw, Qt.Key.Key_S)
        assert canvas._mode == "select"

    def test_g_then_s_toggles_mode(self, qtbot):
        """[6.2] G → S → G の順にモード切替ができる。"""
        vw, canvas = _make_vw(qtbot)

        qtbot.keyClick(vw, Qt.Key.Key_G)
        assert canvas._mode == "grade"

        qtbot.keyClick(vw, Qt.Key.Key_S)
        assert canvas._mode == "select"

        qtbot.keyClick(vw, Qt.Key.Key_G)
        assert canvas._mode == "grade"

    def test_esc_resets_grade_first_point(self, qtbot):
        """[6.2] 勾配直線モードで始点を設定後、Esc キーで入力がリセットされる。"""
        vw, canvas = _make_vw(qtbot)
        vw._set_grade_mode()

        # 始点を手動で設定（クリック不要）
        canvas._grade_first = (10.0, 5.0)
        assert canvas._grade_first is not None

        qtbot.keyClick(vw, Qt.Key.Key_Escape)
        assert canvas._grade_first is None

    def test_esc_in_select_mode_is_harmless(self, qtbot):
        """[6.2] 選択モードで Esc を押してもエラーにならない。"""
        vw, canvas = _make_vw(qtbot)
        assert canvas._mode == "select"

        qtbot.keyClick(vw, Qt.Key.Key_Escape)   # エラーなく通過すれば OK
        assert canvas._mode == "select"

    def test_mode_button_s_sets_select(self, qtbot):
        """[6.2] 右パネルの [S] 選択ボタンをクリックすると選択モードになる。"""
        vw, canvas = _make_vw(qtbot)
        vw._set_grade_mode()
        assert canvas._mode == "grade"

        vw._btn_sel.click()
        assert canvas._mode == "select"

    def test_mode_button_g_sets_grade(self, qtbot):
        """[6.2] 右パネルの [G] 勾配直線ボタンをクリックすると勾配直線モードになる。"""
        vw, canvas = _make_vw(qtbot)
        assert canvas._mode == "select"

        vw._btn_grade.click()
        assert canvas._mode == "grade"


# ─── 6.7 Undo / Redo ────────────────────────────────────────────

class TestSpec6_7_UndoRedo:
    """6.7 Undo / Redo

    仕様書より:
        | ショートカット             | 動作                |
        |--------------------------|---------------------|
        | `Ctrl+Z`                 | Undo（最大 50 手順） |
        | `Ctrl+Y` / `Ctrl+Shift+Z` | Redo               |
    """

    def test_undo_stack_max_capacity_is_50(self, qtbot):
        """[6.7] ProfileCanvas の Undo スタックの最大容量が 50 である。"""
        vw, canvas = _make_vw(qtbot)
        assert canvas._undo_stack.maxlen == 50

    def test_undo_stack_is_independent_of_main_canvas(
            self, make_window_qt, qtbot):
        """[6.7] 縦断線形の Undo スタックはメイン画面のスタックとは独立している。"""
        vw, canvas = _make_vw(qtbot)
        w = make_window_qt()

        # 双方のスタックは別オブジェクト
        assert canvas._undo_stack is not w._canvas._undo_stack

    def test_ctrl_z_undoes_grade_line_addition(self, qtbot):
        """[6.7] 勾配直線追加後に Ctrl+Z を押すと元に戻る（勾配直線がなくなる）。"""
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        # 勾配直線を push_undo 後に追加
        canvas._push_undo()
        gl = GradeLine(dist_start=0.0, elev_start=10.0,
                       dist_end=100.0, elev_end=15.0)
        canvas._grade_lines.append(gl)
        assert len(canvas._grade_lines) == 1

        qtbot.keyClick(vw, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(canvas._grade_lines) == 0

    def test_ctrl_z_multiple_steps(self, qtbot):
        """[6.7] Ctrl+Z を複数回押すとその回数分ずつ戻る。"""
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        # 勾配直線を2本追加（それぞれ push_undo）
        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(0.0, 10.0, 50.0, 12.0))
        assert len(canvas._grade_lines) == 1

        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(50.0, 12.0, 100.0, 14.0))
        assert len(canvas._grade_lines) == 2

        # 1回目の Undo
        qtbot.keyClick(vw, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(canvas._grade_lines) == 1

        # 2回目の Undo
        qtbot.keyClick(vw, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(canvas._grade_lines) == 0

    def test_ctrl_z_empty_stack_is_noop(self, qtbot):
        """[6.7] Undo スタックが空のときに Ctrl+Z を押してもエラーにならない。"""
        vw, canvas = _make_vw(qtbot)
        assert len(canvas._undo_stack) == 0

        qtbot.keyClick(vw, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        # エラーなく通過すれば OK
        assert len(canvas._grade_lines) == 0

    def test_undo_api_directly(self, qtbot):
        """[6.7] ProfileCanvas._undo() を直接呼ぶと Undo が実行される。"""
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(0.0, 10.0, 100.0, 15.0))
        assert len(canvas._grade_lines) == 1

        canvas._undo()
        assert len(canvas._grade_lines) == 0

    def test_redo_api_directly(self, qtbot):
        """[6.7] ProfileCanvas._redo() を直接呼ぶと Redo が実行される。"""
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(0.0, 10.0, 100.0, 15.0))
        canvas._undo()
        assert len(canvas._grade_lines) == 0

        canvas._redo()
        assert len(canvas._grade_lines) == 1

    def test_ctrl_y_redoes_grade_line_addition(self, qtbot):
        """[6.7] Ctrl+Z で取り消した操作を Ctrl+Y でやり直せる。

        仕様: Ctrl+Y → Redo

        注意: 現在の実装（v0.1）では keyPressEvent の elif 条件に ShiftModifier が
        必要なため、Ctrl+Y（Shift なし）は Redo をトリガしない実装バグがある。
        このテストが失敗する場合は vertical_window.keyPressEvent を修正すること。
        """
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(0.0, 10.0, 100.0, 15.0))

        # Undo してから Ctrl+Y で Redo
        qtbot.keyClick(vw, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(canvas._grade_lines) == 0

        qtbot.keyClick(vw, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        assert len(canvas._grade_lines) == 1, (
            "Ctrl+Y で Redo されるべき（失敗する場合は実装バグあり: "
            "keyPressEvent の elif に ShiftModifier 条件を削除してください）")

    def test_ctrl_shift_z_redoes_grade_line_addition(self, qtbot):
        """[6.7] Ctrl+Z で取り消した操作を Ctrl+Shift+Z でやり直せる。

        仕様: Ctrl+Shift+Z → Redo

        注意: 現在の実装（v0.1）では Ctrl+Shift+Z が最初の if ブランチ
        （Ctrl+Z=Undo）に捕捉されるため Redo にならない実装バグがある。
        このテストが失敗する場合は vertical_window.keyPressEvent を修正すること。
        """
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(0.0, 10.0, 100.0, 15.0))

        # Undo してから Ctrl+Shift+Z で Redo
        qtbot.keyClick(vw, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert len(canvas._grade_lines) == 0

        qtbot.keyClick(vw, Qt.Key.Key_Z,
                       Qt.KeyboardModifier.ControlModifier |
                       Qt.KeyboardModifier.ShiftModifier)
        assert len(canvas._grade_lines) == 1, (
            "Ctrl+Shift+Z で Redo されるべき（失敗する場合は実装バグあり: "
            "keyPressEvent で Ctrl+Shift+Z を先に if チェックしてください）")

    # ─── 追加: Undo スタックが ProfileCanvas._push_undo で蓄積されることの確認

    def test_push_undo_increments_stack(self, qtbot):
        """[6.7] _push_undo() を呼ぶたびに Undo スタックが増える。"""
        vw, canvas = _make_vw(qtbot)
        assert len(canvas._undo_stack) == 0

        canvas._push_undo()
        assert len(canvas._undo_stack) == 1

        canvas._push_undo()
        assert len(canvas._undo_stack) == 2

    def test_push_undo_clears_redo_stack(self, qtbot):
        """[6.7] _push_undo() を呼ぶと Redo スタックがクリアされる。"""
        from models import GradeLine
        vw, canvas = _make_vw(qtbot)

        # Undo → Redo スタックに何かある状態を作る
        canvas._push_undo()
        canvas._grade_lines.append(GradeLine(0.0, 10.0, 100.0, 15.0))
        canvas._undo()                      # Redo スタックに積まれる
        assert len(canvas._redo_stack) == 1

        # 新しい操作の push_undo → Redo スタックがクリアされるべき
        canvas._push_undo()
        assert len(canvas._redo_stack) == 0, "新操作後は Redo スタックがクリアされるべき"

    def test_undo_stack_max_50_overflow_drops_oldest(self, qtbot):
        """[6.7] Undo スタックが 50 を超えると古いものが捨てられる。"""
        vw, canvas = _make_vw(qtbot)

        # 51 回 push する
        for _ in range(51):
            canvas._push_undo()

        assert len(canvas._undo_stack) == 50, "50 を超えた分は古い方から破棄されるべき"
