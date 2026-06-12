"""
要求仕様書 第5章「右パネル」適合確認テスト (GUI)。

実行方法:
    uv run pytest -m spec tests/test_spec_gui_ch5.py -v

CI では -m 'not spec' により除外されるため、開発者が手動で実行する。
各テストクラスの docstring に対応する仕様書の節番号と条文を引用する。
"""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

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


# ─── 5.7 図形を削除ボタン ────────────────────────────────────────

class TestSpec5_7_DeleteButton:
    """5.7 図形を削除ボタン

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

    def test_delete_button_shows_confirmation_dialog(
            self, make_panel_qt, monkeypatch):
        """[5.7] 「図形を削除」ボタンを押すと確認ダイアログが表示される。"""
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

        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(mock_question))
        panel._delete_selected_objs()

        assert question_called, "確認ダイアログが表示されなかった"

    def test_no_answer_cancels_deletion(self, make_panel_qt, monkeypatch):
        """[5.7] 確認ダイアログで「いいえ」を選ぶと図形が削除されない。"""
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
        """[5.7] 確認ダイアログで「はい」を選ぶと request_delete シグナルが発行される。"""
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

    def test_no_selection_in_combo_does_nothing(
            self, make_panel_qt, monkeypatch):
        """[5.7] コンボに図形が選択されていないとき削除ボタンを押しても何もしない。"""
        from PySide6.QtWidgets import QMessageBox
        from models import Scene
        panel, _ = make_panel_qt(scene=Scene())

        question_called = []
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(
                lambda *a, **kw: (
                    question_called.append(True)
                    or QMessageBox.StandardButton.No
                )))

        panel._delete_selected_objs()   # 何も選択されていない状態
        assert not question_called, "選択なしのとき確認ダイアログが出てはいけない"


# ─── 5.9 ニックネーム管理 ────────────────────────────────────────

class TestSpec5_9_Nickname:
    """5.9 ニックネーム管理

    仕様書より:
        各図形（直線・円・クロソイド）に任意のニックネームを設定できる。
        ニックネームはファイル保存・読み込みに対応し、
        縦断線形ウィンドウのカラーバーラベルとしても使用される。
    """

    def test_set_nickname_is_stored_in_scene(self):
        """[5.9] scene.set_nickname() で設定したニックネームが scene.nicknames に保存される。"""
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        scene.add_line(ln)

        scene.set_nickname(ln.id, 'テスト直線A')
        assert scene.get_nickname(ln.id) == 'テスト直線A'

    def test_nickname_can_be_changed(self):
        """[5.9] ニックネームを変更すると get_nickname で新しい値が返る。"""
        from models import Circle, Vec2, Scene
        scene = Scene()
        ci = Circle(Vec2(0, 0), 50)
        scene.add_circle(ci)

        scene.set_nickname(ci.id, '交差点A')
        assert scene.get_nickname(ci.id) == '交差点A'

        scene.set_nickname(ci.id, '交差点B')
        assert scene.get_nickname(ci.id) == '交差点B'

    def test_unset_nickname_returns_falsy_or_id_format(self):
        """[5.9] 未設定の場合 get_nickname は None を返し、
        display_name は id 形式の文字列を返す。"""
        from models import Line, Vec2, Scene
        scene = Scene()
        ln = Line(Vec2(0, 0), Vec2(50, 0))
        scene.add_line(ln)

        assert scene.get_nickname(ln.id) is None, "未設定は None を返すべき"
        name = scene.display_name(ln.id, '直線')
        assert isinstance(name, str), "display_name は str を返すべき"
        assert str(ln.id) in name, "display_name は id を含むべき"

    def test_nickname_is_reflected_in_combo_label(self, make_panel_qt):
        """[5.9] ニックネームを設定するとコンボボックスのラベルに反映される。"""
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
        """[5.9] _label_for_obj() が返すラベルにニックネームが含まれる。"""
        from models import Circle, Vec2, Scene
        scene = Scene()
        ci = Circle(Vec2(0, 0), 30)
        scene.add_circle(ci)
        scene.set_nickname(ci.id, '丸山')

        panel, _ = make_panel_qt(scene=scene)
        label = panel._label_for_obj(ci)
        assert '丸山' in label, f"ラベル {label!r} にニックネームが含まれるべき"

    def test_nickname_serialized_and_deserialized(self):
        """[5.9] Scene を to_dict / from_dict でシリアライズするとニックネームが保持される。"""
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


# ─── 5.1 ホバー情報表示 ──────────────────────────────────────────

class TestSpec5_1_HoverInfo:
    """5.1 マウス座標・ホバー情報表示 — ホバー中の図形情報

    仕様書より:
        カーソルが図形の上にある（ホバー中）場合、座標の直下にその図形の
        情報を表示する。表示形式: {ニックネーム} ({タイプ}#{id})
        （ニックネーム未設定の場合は ({タイプ}#{id}) のみ）。
        線分・円弧については親図形のニックネームも表示する。
    """

    def test_hover_shows_type_and_id(self, make_window_qt):
        """[5.1] ニックネーム未設定の線分は (線分#id) と親直線を表示。"""
        from models import Line, Segment, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        w.scene.add_line(ln)
        w._canvas.hover_changed.emit(seg)
        text = w._right_panel._lbl_hovered.text()
        assert f"(線分#{seg.id})" in text
        assert f"(直線#{ln.id})" in text   # 親図形情報

    def test_hover_shows_nickname_when_set(self, make_window_qt):
        """[5.1] ニックネーム設定済みなら名前も表示される。"""
        from models import Line, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        w.scene.set_nickname(ln.id, "国道1号")
        w._canvas.hover_changed.emit(ln)
        text = w._right_panel._lbl_hovered.text()
        assert "国道1号" in text

    def test_hover_none_hides_label(self, make_window_qt):
        """[5.1] ホバー解除（None）で表示が消える。"""
        from models import Line, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        w.scene.add_line(ln)
        w._canvas.hover_changed.emit(ln)
        w._canvas.hover_changed.emit(None)
        assert w._right_panel._lbl_hovered.text() == ""

    def test_mouse_move_over_figure_updates_hover(
            self, make_window_qt, qtbot):
        """[5.1] 実際のマウス移動で図形上に来るとホバー情報が出る。"""
        from models import Line, Segment, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        c = w._canvas
        ln = Line(Vec2(0, 0), Vec2(100, 0))
        seg = Segment(ln, 0.0, 1.0)
        ln.segments.append(seg)
        w.scene.add_line(ln)
        w.show()
        qtbot.waitExposed(c)
        # ワールド (50,0) = スクリーン (550,500) へ移動
        QTest.mouseMove(c, QPoint(549, 500))
        QTest.mouseMove(c, QPoint(550, 500))
        qtbot.wait(50)
        assert w._right_panel._lbl_hovered.text() != ""


# ─── 5.2 [道なり] アイテム ───────────────────────────────────────

class TestSpec5_2_RoadFollow:
    """5.2 図形選択コンボボックス — [道なり] アイテム

    仕様書より:
        高優先候補が1件だけ（または [順] 判定の候補がちょうど1件）の
        場合、その候補の直後に [道なり] <図形ラベル> アイテムを自動追加
        する。選択されると以降のコンボボックスに対して連鎖的に選択を
        進める。
    """

    @staticmethod
    def _three_chain_scene(w):
        """同一直線上で連続する 3 線分のシーン。

        親図形が異なる場合は折れ線接続・クロソイド接点などの
        「直接接点」がないと高優先候補に入らないため、
        同一親の連続線分（常に高優先候補になる）でチェーンを作る。
        """
        from models import Line, Segment, Vec2
        ln = Line(Vec2(0, 0), Vec2(300, 0))
        segs = []
        for i in range(3):
            seg = Segment(ln, i / 3, (i + 1) / 3)
            ln.segments.append(seg)
            segs.append(seg)
        w.scene.add_line(ln)
        return segs

    def test_michinari_item_appears_for_single_candidate(
            self, make_window_qt):
        """[5.2] 隣接候補が1件 → 2個目コンボに [道なり] が出る。"""
        w = make_window_qt()
        w._set_right_panel_visible(True)
        segs = self._three_chain_scene(w)
        rp = w._right_panel
        rp.update_selection([segs[0]], w.scene)
        cb2 = rp._nick_combos[1]
        items = [cb2.itemText(i) for i in range(cb2.count())]
        assert any(t.startswith("[道なり]") for t in items)

    def test_michinari_chains_to_chain_end(self, make_window_qt):
        """[5.2] [道なり] を選ぶと後続のコンボが連鎖的に埋まる。"""
        w = make_window_qt()
        w._set_right_panel_visible(True)
        segs = self._three_chain_scene(w)
        rp = w._right_panel
        rp.update_selection([segs[0]], w.scene)
        cb2 = rp._nick_combos[1]
        idx = next(i for i in range(cb2.count())
                   if cb2.itemText(i).startswith("[道なり]"))
        cb2.setCurrentIndex(idx)
        # 連鎖の結果、3 個目以降のコンボにも図形が選択されている
        selected_texts = [cb.currentText() for cb in rp._nick_combos]
        filled = [t for t in selected_texts
                  if t and t != "(なし)"]
        assert len(filled) >= 3


# ─── 5.3 Copy / Paste ボタン ─────────────────────────────────────

class TestSpec5_3_CopyPaste:
    """5.3 図形のプロパティ表示・編集 — Copy / Paste ボタン

    仕様書より:
        ⧉ Copy: 現在の始点・終点ペアをクリップボードにコピー。
        ⧈ Paste: クリップボードの始点・終点ペアを貼り付け
        （左クリック: そのまま貼り付け）。
    """

    @staticmethod
    def _find_btn(panel, label):
        from PySide6.QtWidgets import QPushButton
        return [b for b in panel.findChildren(QPushButton)
                if label in b.text()]

    def test_copy_then_paste_transfers_ref_points(self, make_window_qt):
        """[5.3] 直線 A を Copy → 直線 B に Paste で参照点が転写される。"""
        from models import Line, Segment, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        rp = w._right_panel
        la = Line(Vec2(1, 2), Vec2(31, 42))
        la.segments.append(Segment(la, 0.0, 1.0))
        lb = Line(Vec2(0, 0), Vec2(10, 0))
        lb.segments.append(Segment(lb, 0.0, 1.0))
        w.scene.add_line(la)
        w.scene.add_line(lb)

        rp.update_selection([la], w.scene)
        copy_btns = self._find_btn(rp, "Copy")
        assert copy_btns, "Copy ボタンが表示されていない"
        copy_btns[0].click()

        rp.update_selection([lb], w.scene)
        paste_btns = self._find_btn(rp, "Paste")
        assert paste_btns, "Paste ボタンが表示されていない"
        paste_btns[0].click()
        assert (lb.ref_start.x, lb.ref_start.y) == (1, 2)
        assert (lb.ref_end.x, lb.ref_end.y) == (31, 42)

    def test_paste_is_undoable(self, make_window_qt):
        """[5.3/4.8] Paste は Undo に記録される。"""
        from models import Line, Segment, Vec2
        w = make_window_qt()
        w._set_right_panel_visible(True)
        rp = w._right_panel
        la = Line(Vec2(1, 2), Vec2(31, 42))
        la.segments.append(Segment(la, 0.0, 1.0))
        lb = Line(Vec2(0, 0), Vec2(10, 0))
        lb.segments.append(Segment(lb, 0.0, 1.0))
        w.scene.add_line(la)
        w.scene.add_line(lb)
        rp.update_selection([la], w.scene)
        self._find_btn(rp, "Copy")[0].click()
        rp.update_selection([lb], w.scene)
        self._find_btn(rp, "Paste")[0].click()
        w._canvas.undo()
        restored = w.scene.lines[1]
        assert (restored.ref_start.x, restored.ref_start.y) == (0, 0)


# ─── 5.6 複数図形選択時の操作パネル ──────────────────────────────

class TestSpec5_6_MultiSelectPanel:
    """5.6 複数図形選択時の操作パネル

    仕様書より:
        実効的な選択図形が 2 個以上のとき、右パネルにコピー・平行移動・
        回転・拡大縮小の操作グループが表示される。コピーは選択図形を
        複製し、元の選択を外して複製した図形のみ選択状態にする。
    """

    @staticmethod
    def _select_three_lines(w):
        """専用パネル（接続・拘束）に該当しない 3 直線を選択する。

        2 図形の Line+Circle はクロソイド操作パネル、
        Line+Line+Circle は TwoLineOffsetConstraint パネルに
        ディスパッチされるため、複数選択パネルは 3 直線で確認する。
        """
        from models import Line, Segment, Vec2
        lines = []
        for i in range(3):
            ln = Line(Vec2(0, i * 20), Vec2(10, i * 20))
            ln.segments.append(Segment(ln, 0.0, 1.0))
            w.scene.add_line(ln)
            lines.append(ln)
        w._right_panel.update_selection(lines, w.scene)
        return lines

    def test_panel_shown_for_three_lines(self, make_window_qt):
        """[5.6] 3 図形選択でコピー・適用ボタンが表示される。"""
        from PySide6.QtWidgets import QPushButton
        w = make_window_qt()
        w._set_right_panel_visible(True)
        self._select_three_lines(w)
        texts = [b.text() for b in
                 w._right_panel.findChildren(QPushButton)]
        assert any("コピー" in t for t in texts)
        assert any("適用" in t for t in texts)

    def test_copy_button_duplicates_and_selects_copies(
            self, make_window_qt, qtbot):
        """[5.6] コピー実行で複製のみが選択状態になる（Canvas 連動）。"""
        from PySide6.QtWidgets import QPushButton
        w = make_window_qt()
        w._set_right_panel_visible(True)
        lines = self._select_three_lines(w)
        btns = [b for b in w._right_panel.findChildren(QPushButton)
                if "コピー" in b.text()]
        btns[0].click()
        assert len(w.scene.lines) == 6
        # request_select → MainWindow → Canvas.set_selection の配線確認
        assert all(ln not in w._canvas._selected for ln in lines)
        assert len(w._canvas._selected) == 3
