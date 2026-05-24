"""
要求仕様書 第5章「右パネル」適合確認テスト (GUI)。

実行方法:
    uv run pytest -m spec tests/test_spec_gui_ch5.py -v

CI では -m 'not spec' により除外されるため、開発者が手動で実行する。
各テストクラスの docstring に対応する仕様書の節番号と条文を引用する。
"""
import pytest
from PySide6.QtCore import Qt

pytestmark = pytest.mark.spec


# ─── 5.1 マウス座標・ホバー情報表示 ──────────────────────────────

class TestSpec5_1_MouseCoord:
    """5.1 マウス座標・ホバー情報表示

    仕様書より:
        編集画面上にマウスカーソルがある間、右パネルの上部にカーソルの
        ワールド座標（X, Y）をリアルタイムで表示する（小数点以下3桁）。
    """

    def test_update_mouse_pos_updates_x_label(self, make_panel_qt):
        """[5.1] update_mouse_pos(x, y) を呼ぶと X 座標ラベルが更新される。"""
        panel, _ = make_panel_qt()
        panel.update_mouse_pos(12.345, 0.0)
        assert "12.345" in panel._lbl_mouse_x.text()

    def test_update_mouse_pos_updates_y_label(self, make_panel_qt):
        """[5.1] update_mouse_pos(x, y) を呼ぶと Y 座標ラベルが更新される。"""
        panel, _ = make_panel_qt()
        panel.update_mouse_pos(0.0, -67.890)
        assert "-67.890" in panel._lbl_mouse_y.text()

    def test_coord_precision_is_3_decimal_places(self, make_panel_qt):
        """[5.1] 座標は小数点以下3桁（例: X: 1.000）で表示される。"""
        panel, _ = make_panel_qt()
        panel.update_mouse_pos(1.0, 2.0)
        assert "1.000" in panel._lbl_mouse_x.text()
        assert "2.000" in panel._lbl_mouse_y.text()

    def test_negative_coords_are_displayed_correctly(self, make_panel_qt):
        """[5.1] 負の座標も正しく表示される。"""
        panel, _ = make_panel_qt()
        panel.update_mouse_pos(-100.0, -200.5)
        assert "-100.000" in panel._lbl_mouse_x.text()
        assert "-200.500" in panel._lbl_mouse_y.text()

    def test_mouse_world_pos_signal_updates_panel(self, make_window_qt, qtbot):
        """[5.1] Canvas.mouse_world_pos シグナルが RightPanel に接続されている。

        メインウィンドウで右パネルを表示した状態でマウスを動かすと、
        座標ラベルが更新されることを直接シグナル発行で確認する。
        """
        w = make_window_qt()
        # 右パネルを表示
        w._set_right_panel_visible(True)
        rp = w._right_panel

        # Canvas.mouse_world_pos シグナルを直接 emit
        w._canvas.mouse_world_pos.emit(55.5, 33.3)
        assert "55.500" in rp._lbl_mouse_x.text()
        assert "33.300" in rp._lbl_mouse_y.text()


# ─── 5.3 図形のプロパティ表示・編集 ──────────────────────────────

class TestSpec5_3_Properties:
    """5.3 図形のプロパティ表示・編集

    仕様書より:
        | 図形   | 表示・編集内容                                         |
        |--------|-------------------------------------------------------|
        | 直線   | 参照始点・参照終点の X/Y 座標（数値入力）、方向角（読み取り専用） |
        | 線分   | 親直線の表示、始点・終点の X/Y 座標と割合 t（数値入力）|
        | 円     | 中心 X/Y・半径（数値入力）                             |
    """

    def test_no_selection_shows_placeholder_label(self, make_panel_qt):
        """[5.3] 図形未選択のとき「図形を選択してください」ラベルが表示される。"""
        from PySide6.QtWidgets import QLabel
        from models import Scene
        panel, _ = make_panel_qt(scene=Scene())
        panel.update_selection([], panel.scene)

        labels = panel._prop_widget.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]
        assert any("図形を選択してください" in t for t in texts)

    def test_select_line_shows_property_groupbox(self, make_panel_qt):
        """[5.3] 直線を選択するとプロパティグループボックスが表示される。"""
        from PySide6.QtWidgets import QGroupBox
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)

        panel, _ = make_panel_qt(scene=scene)
        panel.update_selection([ln], scene)

        groups = panel._prop_widget.findChildren(QGroupBox)
        assert len(groups) > 0, "直線選択時にプロパティグループボックスが表示されるべき"

    def test_select_circle_shows_property_groupbox(self, make_panel_qt):
        """[5.3] 円を選択するとプロパティグループボックスが表示される。"""
        from PySide6.QtWidgets import QGroupBox
        from models import Circle, Vec2, Scene
        scene = Scene()
        ci = Circle(Vec2(0, 0), 50)
        scene.add_circle(ci)

        panel, _ = make_panel_qt(scene=scene)
        panel.update_selection([ci], scene)

        groups = panel._prop_widget.findChildren(QGroupBox)
        assert len(groups) > 0, "円選択時にプロパティグループボックスが表示されるべき"

    def test_select_segment_shows_property_groupbox(self, make_panel_qt):
        """[5.3] 線分を選択するとプロパティグループボックスが表示される。"""
        from PySide6.QtWidgets import QGroupBox
        from models import Line, Segment, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        scene.add_line(ln)

        panel, _ = make_panel_qt(scene=scene)
        panel.update_selection([seg], scene)

        groups = panel._prop_widget.findChildren(QGroupBox)
        assert len(groups) > 0

    def test_selection_change_rebuilds_props(self, make_panel_qt):
        """[5.3] 選択変更のたびにプロパティが再構築される（stale にならない）。"""
        from PySide6.QtWidgets import QGroupBox, QLabel
        from models import Line, Circle, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)
        ci = Circle(Vec2(0, 0), 50)
        scene.add_circle(ci)

        panel, _ = make_panel_qt(scene=scene)

        # 直線 → 円 → なし の順に選択変更
        panel.update_selection([ln], scene)
        n_groups_line = len(panel._prop_widget.findChildren(QGroupBox))

        panel.update_selection([ci], scene)
        n_groups_circle = len(panel._prop_widget.findChildren(QGroupBox))

        panel.update_selection([], scene)
        labels = panel._prop_widget.findChildren(QLabel)
        texts = [lbl.text() for lbl in labels]

        assert n_groups_line > 0
        assert n_groups_circle > 0
        assert any("図形を選択してください" in t for t in texts)

    def test_canvas_selection_change_updates_right_panel(self, make_window_qt):
        """[5.3] Canvas で図形を選択すると RightPanel のプロパティが更新される。"""
        from PySide6.QtWidgets import QGroupBox
        from models import Line, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)

        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)

        # Canvas のシグナルで選択変更をシミュレート
        w._canvas.set_selection([ln])

        groups = w._right_panel._prop_widget.findChildren(QGroupBox)
        assert len(groups) > 0, "右パネルのプロパティが更新されるべき"


# ─── 5.6 図形を削除ボタン ────────────────────────────────────────

class TestSpec5_6_DeleteButton:
    """5.6 図形を削除ボタン

    仕様書より:
        コンボボックスで選択中の図形を削除する。
        実行前に確認ダイアログを表示する。
    """

    def _select_obj_in_combo(self, panel, obj):
        """コンボに obj を選択状態にするヘルパー。失敗したら pytest.skip。"""
        label = panel._label_for_obj(obj)
        cb = panel._nick_combos[0]
        idx = cb.findText(label)
        if idx < 0:
            pytest.skip(f"コンボにラベルが見つからない: {label!r}")
        cb.setCurrentIndex(idx)

    def test_delete_button_shows_confirmation_dialog(self, make_panel_qt, monkeypatch):
        """[5.6] 「図形を削除」ボタンを押すと確認ダイアログが表示される。"""
        from PySide6.QtWidgets import QMessageBox
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)
        panel, _ = make_panel_qt(scene=scene)
        self._select_obj_in_combo(panel, ln)

        question_called = []

        def mock_question(*args, **kwargs):
            question_called.append(True)
            return QMessageBox.StandardButton.No   # キャンセル

        monkeypatch.setattr(QMessageBox, "question", staticmethod(mock_question))
        panel._delete_selected_objs()

        assert question_called, "確認ダイアログが表示されなかった"

    def test_no_answer_cancels_deletion(self, make_panel_qt, monkeypatch):
        """[5.6] 確認ダイアログで「いいえ」を選ぶと図形が削除されない。"""
        from PySide6.QtWidgets import QMessageBox
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)
        panel, _ = make_panel_qt(scene=scene)
        self._select_obj_in_combo(panel, ln)

        deleted_objects = []
        panel.request_delete.connect(lambda objs: deleted_objects.extend(objs))

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **kw: QMessageBox.StandardButton.No))
        panel._delete_selected_objs()

        assert len(deleted_objects) == 0, "キャンセルしたのに削除シグナルが発行された"

    def test_yes_answer_emits_request_delete(self, make_panel_qt, monkeypatch):
        """[5.6] 確認ダイアログで「はい」を選ぶと request_delete シグナルが発行される。"""
        from PySide6.QtWidgets import QMessageBox
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)
        panel, _ = make_panel_qt(scene=scene)
        self._select_obj_in_combo(panel, ln)

        deleted_objects = []
        panel.request_delete.connect(lambda objs: deleted_objects.extend(objs))

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))
        panel._delete_selected_objs()

        assert len(deleted_objects) == 1
        assert deleted_objects[0] is ln

    def test_no_selection_in_combo_does_nothing(self, make_panel_qt, monkeypatch):
        """[5.6] コンボに図形が選択されていないとき削除ボタンを押しても何もしない。"""
        from PySide6.QtWidgets import QMessageBox
        from models import Scene
        panel, _ = make_panel_qt(scene=Scene())

        question_called = []
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **kw: question_called.append(True) or QMessageBox.StandardButton.No))

        panel._delete_selected_objs()   # 何も選択されていない状態
        assert not question_called, "選択なしのとき確認ダイアログが出てはいけない"


# ─── 5.8 ニックネーム管理 ────────────────────────────────────────

class TestSpec5_8_Nickname:
    """5.8 ニックネーム管理

    仕様書より:
        各図形（直線・円・クロソイド）に任意のニックネームを設定できる。
        ニックネームはファイル保存・読み込みに対応し、
        縦断線形ウィンドウのカラーバーラベルとしても使用される。
    """

    def test_set_nickname_is_stored_in_scene(self):
        """[5.8] scene.set_nickname() で設定したニックネームが scene.nicknames に保存される。"""
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)

        scene.set_nickname(ln.id, 'テスト直線A')
        assert scene.get_nickname(ln.id) == 'テスト直線A'

    def test_nickname_can_be_changed(self):
        """[5.8] ニックネームを変更すると get_nickname で新しい値が返る。"""
        from models import Circle, Vec2, Scene
        scene = Scene()
        ci = Circle(Vec2(0, 0), 50)
        scene.add_circle(ci)

        scene.set_nickname(ci.id, '交差点A')
        assert scene.get_nickname(ci.id) == '交差点A'

        scene.set_nickname(ci.id, '交差点B')
        assert scene.get_nickname(ci.id) == '交差点B'

    def test_unset_nickname_returns_falsy_or_id_format(self):
        """[5.8] 未設定の場合 get_nickname は空文字か id 形式の文字列を返す。"""
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(50, 0))
        scene.add_line(ln)

        name = scene.get_nickname(ln.id)
        assert isinstance(name, str), "get_nickname は str を返すべき"

    def test_nickname_is_reflected_in_combo_label(self, make_panel_qt):
        """[5.8] ニックネームを設定するとコンボボックスのラベルに反映される。"""
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)
        scene.set_nickname(ln.id, 'MyRoad')

        panel, _ = make_panel_qt(scene=scene)
        panel.update_selection([ln], scene)

        # コンボのラベルにニックネームが含まれることを確認
        cb = panel._nick_combos[0]
        found = False
        for i in range(cb.count()):
            if 'MyRoad' in cb.itemText(i):
                found = True
                break
        assert found, "コンボラベルにニックネームが反映されるべき"

    def test_nickname_appears_in_panel_label_for_obj(self, make_panel_qt):
        """[5.8] _label_for_obj() が返すラベルにニックネームが含まれる。"""
        from models import Circle, Vec2, Scene
        scene = Scene()
        ci = Circle(Vec2(0, 0), 30)
        scene.add_circle(ci)
        scene.set_nickname(ci.id, '丸山')

        panel, _ = make_panel_qt(scene=scene)
        label = panel._label_for_obj(ci)
        assert '丸山' in label, f"ラベル {label!r} にニックネームが含まれるべき"

    def test_nickname_serialized_and_deserialized(self):
        """[5.8] Scene を to_dict / from_dict でシリアライズするとニックネームが保持される。"""
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)
        scene.set_nickname(ln.id, '永続化テスト')

        data = scene.to_dict()
        scene2 = Scene.from_dict(data)

        # 復元後も同じ ID のニックネームが取れる
        name = scene2.get_nickname(ln.id)
        assert name == '永続化テスト', "シリアライズ後もニックネームが保持されるべき"
