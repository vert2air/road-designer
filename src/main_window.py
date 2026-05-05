"""道路設計アプリ メインウィンドウモジュール。

Canvas・RightPanel・VerticalAlignmentWindow・road_viewer を統合し、
コンポーネント間のシグナルを配線するハブ。Canvas と RightPanel は互いを
直接参照せず、request_* シグナルを MainWindow が受けて対応する処理を実行する。
"""
from __future__ import annotations
import json
import os
from typing import Optional
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QToolBar,
    QSplitter, QFileDialog, QMessageBox, QLabel, QCheckBox
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QKeySequence, QIcon, QAction, QActionGroup

from models import Scene, Line, Circle, Clothoid, Segment, Arc, Vec2, resolve_chain, SNAP_TOL
from canvas import Canvas
from right_panel import RightPanel
from vertical_window import VerticalAlignmentWindow


class MainWindow(QMainWindow):
    """道路設計アプリのメインウィンドウ。

    全コンポーネント（Canvas・RightPanel・VerticalAlignmentWindow・road_viewer）を
    統合するハブ。_connect_signals で各コンポーネントのシグナルを接続する。

    _get_or_create_ep と _collect_all_display は縦断線形ウィンドウと
    3D ビューアの両方で使われる共通ヘルパーとして MainWindow に集約している。
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("道路設計アプリ")
        self.resize(1400, 800)

        self._filepath: Optional[str] = None
        self._vertical_window: Optional[VerticalAlignmentWindow] = None

        self._build_ui()  # self._canvas が作られる（scene を持つ）
        self._build_menu()
        self._build_toolbar()
        self._connect_signals()

        self._add_demo()

    @property
    def scene(self) -> Scene:
        """現在の Scene への参照（canvas.scene と同一オブジェクト）。

        MainWindow 全体から self.scene で一貫してアクセスするためのプロパティ。

        Returns
        -------
        Scene
            _canvas.scene と同一の Scene オブジェクト。
        """
        return self._canvas.scene

    @scene.setter
    def scene(self, s: Scene):
        self._canvas.scene = s

    def _build_ui(self):
        """Canvas・RightPanel を QSplitter で左右分割した UI を構築する。"""
        central = QWidget()
        self.setCentralWidget(central)
        h_lay = QHBoxLayout(central)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        h_lay.addWidget(self._splitter)

        self._canvas = Canvas(Scene(), self)   # canvas が scene を所有
        self._splitter.addWidget(self._canvas)

        self._right_panel = RightPanel(self.scene, self)
        self._right_panel.setVisible(False)
        self._splitter.addWidget(self._right_panel)
        self._splitter.setSizes([1100, 300])

    def _build_menu(self):
        """メニューバー（ファイル・表示・ウィンドウ）を構築する。"""
        mb = self.menuBar()

        # ── ファイル ──────────────────────────────────────────
        file_menu = mb.addMenu("ファイル(&F)")

        act_save = QAction("上書き保存(&S)", self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self._save)
        file_menu.addAction(act_save)

        act_save_as = QAction("名前を付けて保存(&A)...", self)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self._save_as)
        file_menu.addAction(act_save_as)

        act_open = QAction("開く(&O)...", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self._open)
        file_menu.addAction(act_open)

        file_menu.addSeparator()

        act_clear = QAction("全削除", self)
        act_clear.triggered.connect(self._clear_all)
        file_menu.addAction(act_clear)

        # ── 編集 ──────────────────────────────────────────────
        edit_menu = mb.addMenu("編集(&E)")

        act_undo = QAction("元に戻す(&Z)", self)
        act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        act_undo.triggered.connect(self._canvas.undo)
        edit_menu.addAction(act_undo)

        act_fit = QAction("全体表示(&0)", self)
        act_fit.setShortcut(QKeySequence("Ctrl+0"))
        act_fit.triggered.connect(self._canvas.fit_all)
        edit_menu.addAction(act_fit)

        # ── 表示 ──────────────────────────────────────────────
        view_menu = mb.addMenu("表示(&V)")
        self._act_right_panel = QAction("右パネルを表示", self)
        self._act_right_panel.setCheckable(True)
        self._act_right_panel.setChecked(False)
        self._act_right_panel.triggered.connect(self._toggle_right_panel)
        view_menu.addAction(self._act_right_panel)

        # ── 縦断線形 ─────────────────────────────────────────
        vert_menu = mb.addMenu("縦断線形(&V)")
        act_vert = QAction("縦断線形ウィンドウを開く", self)
        act_vert.setShortcut(QKeySequence("Ctrl+Shift+V"))
        act_vert.triggered.connect(self._open_vertical_window)
        vert_menu.addAction(act_vert)

        # ── 3D 走行ビューア ───────────────────────────────────
        view3d_menu = mb.addMenu("3Dビューア(&3)")
        act_3d = QAction("選択要素で 3D 走行ビューアを開く", self)
        act_3d.setShortcut(QKeySequence("Ctrl+Shift+3"))
        act_3d.triggered.connect(self._open_3d_viewer)
        view3d_menu.addAction(act_3d)

    def _build_toolbar(self):
        """ツールバー（選択/直線/円 モードボタン）を構築する。"""
        tb = QToolBar("ツールバー")
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # モードボタン
        ag = QActionGroup(self)
        ag.setExclusive(True)

        self._act_select = QAction("選択 [S]", self)
        self._act_select.setCheckable(True)
        self._act_select.setChecked(True)
        self._act_select.setShortcut(QKeySequence("S"))
        self._act_select.triggered.connect(lambda: self._canvas.set_mode(Canvas.MODE_SELECT))
        ag.addAction(self._act_select)
        tb.addAction(self._act_select)

        self._act_line = QAction("直線 [L]", self)
        self._act_line.setCheckable(True)
        self._act_line.setShortcut(QKeySequence("L"))
        self._act_line.triggered.connect(lambda: self._canvas.set_mode(Canvas.MODE_LINE))
        ag.addAction(self._act_line)
        tb.addAction(self._act_line)

        self._act_circle = QAction("円 [C]", self)
        self._act_circle.setCheckable(True)
        self._act_circle.setShortcut(QKeySequence("C"))
        self._act_circle.triggered.connect(lambda: self._canvas.set_mode(Canvas.MODE_CIRCLE))
        ag.addAction(self._act_circle)
        tb.addAction(self._act_circle)

        tb.addSeparator()

        # 右パネル toggle
        self._chk_right = QCheckBox("右パネル")
        self._chk_right.setChecked(False)
        self._chk_right.stateChanged.connect(
            lambda s: self._set_right_panel_visible(bool(s)))
        tb.addWidget(self._chk_right)

        tb.addSeparator()

        # ステータスラベル
        self._status_label = QLabel("準備完了")
        tb.addWidget(self._status_label)

    def _connect_signals(self):
        """Canvas / RightPanel のシグナルを MainWindow のスロットに接続する。

        __init__ から分離しているのは読みやすさのため。接続は初期化時に 1 度だけ行う。
        """
        self._canvas.selection_changed.connect(self._on_selection_changed)
        self._canvas.scene_changed.connect(self._on_scene_changed)
        self._canvas.mouse_world_pos.connect(self._right_panel.update_mouse_pos)

        rp = self._right_panel
        rp.request_smooth_connect.connect(self._do_smooth_connect)
        rp.request_polyline_connect.connect(self._do_polyline_connect)
        rp.request_disconnect.connect(self._do_disconnect)
        rp.request_add_clothoid.connect(self._do_add_clothoid)
        rp.request_delete_clothoid.connect(self._do_delete_clothoid)
        rp.request_flip_clothoid.connect(self._do_flip_clothoid)
        rp.request_select.connect(self._canvas.set_selection)
        rp.request_delete.connect(self._do_delete_objects)
        rp.scene_changed.connect(self._on_scene_changed)

    # ─── イベントハンドラ ─────────────────────────────────────
    def _on_selection_changed(self, selected: list):
        """Canvas.selection_changed シグナルを受けて RightPanel のプロパティを更新する。

        Parameters
        ----------
        selected : list
            Canvas で選択中の図形リスト。MainWindow 自体は選択状態を保持しない。
        """
        self._right_panel.update_selection(selected, self.scene)
        n = len(selected)
        if n == 0:
            self._status_label.setText("選択なし")
        elif n == 1:
            obj = selected[0]
            t = type(obj).__name__
            self._status_label.setText(f"選択: {t}")
        else:
            self._status_label.setText(f"{n} 個選択")

    def _on_scene_changed(self):
        """Canvas.scene_changed シグナルを受けてウィンドウタイトルに * を付ける。

        プロパティパネルの更新は行わない（selection_changed 経由で _on_selection_changed が担当）。
        """
        self._canvas.update()
        # ニックネームコンボボックスの選択肢を常に最新に保つ
        self._right_panel.scene = self.scene
        self._right_panel._refresh_nick_combos()

    # ─── ツールバー/メニュー操作 ─────────────────────────────
    def _toggle_right_panel(self):
        visible = self._act_right_panel.isChecked()
        self._set_right_panel_visible(visible)

    def _set_right_panel_visible(self, visible: bool):
        self._right_panel.setVisible(visible)
        self._chk_right.setChecked(visible)
        self._act_right_panel.setChecked(visible)

    # ─── ファイル操作 ─────────────────────────────────────────
    def _save(self):
        """上書き保存。_filepath 未設定のとき _save_as に委譲する。"""
        if self._filepath:
            self._write_file(self._filepath)
        else:
            self._save_as()

    def _save_as(self):
        """名前を付けて保存ダイアログを表示してファイルに書き出す。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "名前を付けて保存", "", "Road Design JSON (*.rdjson);;JSON (*.json)")
        if path:
            self._filepath = path
            self._write_file(path)

    def _write_file(self, path: str):
        """Scene を JSON 形式でファイルに書き出す。

        Parameters
        ----------
        path : str
            書き出し先のファイルパス（.rdjson）。
            書き出し失敗時は QMessageBox.critical でエラーを表示する。
        """
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.scene.to_dict(), f, indent=2, ensure_ascii=False)
            self.setWindowTitle(f"道路設計アプリ - {os.path.basename(path)}")
            self._status_label.setText("保存完了")
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

    def _open(self):
        """ファイルを開くダイアログを表示して Scene を読み込む。

        読み込み成功後に Canvas をリセット（選択・ハンドルのクリア）して fit_all() を呼ぶ。
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "開く", "", "Road Design JSON (*.rdjson);;JSON (*.json)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._canvas.scene = Scene.from_dict(data)
                self._canvas._selected.clear()
                self._canvas._handles.clear()
                self._canvas.scene_changed.emit()
                self._canvas.selection_changed.emit([])
                self._filepath = path
                self.setWindowTitle(f"道路設計アプリ - {os.path.basename(path)}")
                self._canvas.fit_all()
            except Exception as e:
                QMessageBox.critical(self, "読み込みエラー", str(e))

    def _clear_all(self):
        r = QMessageBox.question(self, "確認", "全データを削除しますか？",
                                  QMessageBox.StandardButton.Yes |
                                  QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self._canvas.push_undo()
            self._canvas.scene = Scene()
            self._canvas._selected.clear()
            self._canvas._handles.clear()
            self._canvas.scene_changed.emit()
            self._canvas.selection_changed.emit([])

    # ─── クロソイド操作 ──────────────────────────────────────
    def _do_smooth_connect(self, a, b):
        """RightPanel.request_smooth_connect シグナルを受けて Canvas.smooth_connect を呼ぶ。"""
        self._canvas.smooth_connect(a, b)
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_polyline_connect(self, a, b):
        """RightPanel.request_polyline_connect シグナルを受けて折れ線接続を実行する。"""
        self._canvas.push_undo()
        self._canvas._connect_polyline(a, b)
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_disconnect(self, a, b):
        """RightPanel.request_disconnect シグナルを受けて Canvas.disconnect_lines を呼ぶ。"""
        self._canvas.disconnect_lines(a, b)
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_add_clothoid(self, ln, ci):
        """RightPanel.request_add_clothoid シグナルを受けて Clothoid を生成・追加する。

        Parameters
        ----------
        ln : Line
            クロソイドを接続する直線。
        ci : Circle
            クロソイドを接続する円。
        """
        self._canvas.push_undo()
        existing = self.scene.clothoids_for(ln, ci)
        rev = (len(existing) == 1 and not existing[0].reversed_flag)
        # デフォルトは snap なし（ユーザーが右パネルから個別に on にする）
        clo = Clothoid(ln, ci, reversed_flag=rev,
                       snap_segment=False, snap_arc=False)
        self.scene.add_clothoid(clo)
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_delete_clothoid(self, clo):
        """RightPanel.request_delete_clothoid シグナルを受けて Clothoid を削除する。"""
        self._canvas.push_undo()
        self.scene.remove_clothoid(clo)
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_delete_objects(self, objs: list):
        """右パネルの request_delete シグナルを受けて図形を削除する。

        push_undo() 後に各図形を型に応じて削除する
        （Line / Circle / Clothoid / Segment / Arc）。

        Parameters
        ----------
        objs : list
            削除する図形のリスト。
        """
        from models import Segment, Arc, Clothoid, Line, Circle
        if not objs:
            return
        self._canvas.push_undo()
        for obj in objs:
            if isinstance(obj, Clothoid):
                self.scene.remove_clothoid(obj)
            elif isinstance(obj, Segment):
                # 線分を Line から削除。Line が空になれば Line ごと削除
                ln = obj.line
                if obj in ln.segments:
                    ln.segments.remove(obj)
                if not ln.segments:
                    self.scene.remove_line(ln)
                else:
                    # 関連クロソイドを再計算
                    for clo in self.scene.clothoids:
                        if clo.line is ln:
                            clo.compute()
            elif isinstance(obj, Arc):
                # 円弧を Circle から削除。Circle が空になれば Circle ごと削除
                ci = obj.circle
                if obj in ci.arcs:
                    ci.arcs.remove(obj)
                if not ci.arcs:
                    self.scene.remove_circle(ci)
                else:
                    for clo in self.scene.clothoids:
                        if clo.circle is ci:
                            clo.compute()
            elif isinstance(obj, Line):
                self.scene.remove_line(obj)
            elif isinstance(obj, Circle):
                self.scene.remove_circle(obj)
        # 削除した図形が選択中だったら選択解除
        remaining = [o for o in self._canvas._selected if o not in objs]
        self._canvas._selected = remaining
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(remaining, self.scene)

    def _do_flip_clothoid(self, clo):
        """RightPanel.request_flip_clothoid シグナルを受けて reversed_flag を切り替える。"""
        self._canvas.push_undo()
        clo.reversed_flag = not clo.reversed_flag
        clo.compute()
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    # ─── 縦断線形 ────────────────────────────────────────────
    def _get_or_create_ep(self, obj, rev: bool):
        """obj に対応する ElementProfile を取得または新規作成して返す。

        element_type・plan_length・reversed_flag は常に最新値で上書きする。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid
            ElementProfile を取得する平面線形要素。
        rev : bool
            チェーン上での逆順フラグ（ElementProfile.reversed_flag に設定する）。

        Returns
        -------
        ElementProfile
            取得または新規作成した ElementProfile。
        """
        from models import ElementProfile, plan_length_of
        ep = next((e for e in self.scene.element_profiles
                   if e.element_id == obj.id), None)
        if ep is None:
            ep = ElementProfile()
            ep.element_id = obj.id
            self.scene.element_profiles.append(ep)
        ep.element_type  = ('segment'  if isinstance(obj, Segment)  else
                             'arc'      if isinstance(obj, Arc)       else
                             'clothoid')
        ep.plan_length   = plan_length_of(obj)
        ep.reversed_flag = rev
        return ep

    def _collect_all_display(self):
        """シーン内の全線分・全円弧・全クロソイドをフラットなリストで返す。

        3D ビューアの背景表示と _open_3d_viewer の走行対象（未選択時）に使う。

        Returns
        -------
        list[Segment | Arc | Clothoid]
            全線分 + 全円弧 + 全クロソイドのリスト。
        """
        result = []
        for ln in self.scene.lines:
            result.extend(ln.segments)
        for ci in self.scene.circles:
            result.extend(ci.arcs)
        result.extend(self.scene.clothoids)
        return result

    def _open_vertical_window(self):
        """縦断線形ウィンドウを開く。選択中の平面線形要素をチェーンとして渡す。

        選択要素がない場合は何もしない。
        resolve_chain でチェーン順序を決定し、各要素の ElementProfile を
        取得または生成して VerticalAlignmentWindow に渡す。
        """
        # 選択中の平面線形要素を収集
        raw = [o for o in self._canvas._selected
               if isinstance(o, (Segment, Arc, Clothoid))]
        if not raw:
            return

        elements, rev_flags = resolve_chain(raw, self.scene.element_profiles)
        profiles = [self._get_or_create_ep(obj, rev)
                    for obj, rev in zip(elements, rev_flags)]

        # 隣接 ElementProfile 間の境界標高を同期
        for i in range(len(profiles) - 1):
            cur, nxt = profiles[i], profiles[i + 1]
            if cur.grade_lines:
                elev = max(cur.grade_lines, key=lambda g: g.dist_end).elev_end
            elif nxt.grade_lines:
                elev = min(nxt.grade_lines, key=lambda g: g.dist_start).elev_start
            else:
                continue
            cur.elev_end   = elev
            nxt.elev_start = elev

        self._vertical_window = VerticalAlignmentWindow(
            self.scene, profiles, elements, rev_flags, parent=None)
        self._vertical_window.show()

    def _open_3d_viewer(self):
        """3D 走行ビューアを起動する。

        選択中の要素をチェーンとして走行する。未選択時は全要素を走行対象にする。
        prepare_viewer_data で中心線・背景データを計算し、launch_viewer で
        別プロセス（Panda3D）を起動する。
        """
        from road_viewer import launch_viewer

        # 走行対象要素を収集（未選択なら全要素）
        selected = [o for o in self._canvas._selected
                    if isinstance(o, (Segment, Arc, Clothoid))]
        if not selected:
            selected = self._collect_all_display()
        if not selected:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "3Dビューア", "表示できる図形がありません。")
            return

        ride_elems, rev_flags = resolve_chain(selected, self.scene.element_profiles)
        profiles = [self._get_or_create_ep(obj, rev)
                    for obj, rev in zip(ride_elems, rev_flags)]

        launch_viewer(self.scene, ride_elems, profiles, rev_flags,
                      all_display=self._collect_all_display())

    # ─── デモデータ ──────────────────────────────────────────
    def _add_demo(self):
        """アプリ起動時にデモ図形（直線・線分）を Scene に追加する。"""
        # 直線 A
        la = Line(Vec2(-200, 0), Vec2(-50, 0))
        seg_a = Segment(la, 0.2, 0.9)
        la.segments.append(seg_a)
        self.scene.add_line(la)

        # 直線 B
        lb = Line(Vec2(50, -150), Vec2(200, 0))
        seg_b = Segment(lb, 0.1, 0.85)
        lb.segments.append(seg_b)
        self.scene.add_line(lb)

        # 円
        ci = Circle(Vec2(0, -80), 60)
        self.scene.add_circle(ci)

        self._canvas.fit_all()
        self._canvas.scene_changed.emit()  # right_panel のコンボを初期化
        self._canvas.update()
