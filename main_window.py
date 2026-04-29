"""
道路設計アプリ メインウィンドウ
"""
from __future__ import annotations
import json
import os
from typing import Optional
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QToolBar,
    QSplitter, QFileDialog, QMessageBox, QLabel, QCheckBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QKeySequence, QIcon, QAction, QActionGroup

from models import Scene, Line, Circle, Clothoid, Segment, Arc, Vec2
from canvas import Canvas
from right_panel import RightPanel
from vertical_window import VerticalAlignmentWindow


class MainWindow(QMainWindow):
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
        """常に canvas.scene と同じ参照を返す"""
        return self._canvas.scene

    @scene.setter
    def scene(self, s: Scene):
        self._canvas.scene = s

    def _build_ui(self):
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

    def _build_toolbar(self):
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
        rp.scene_changed.connect(self._on_scene_changed)

    # ─── イベントハンドラ ─────────────────────────────────────
    def _on_selection_changed(self, selected: list):
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
        if self._filepath:
            self._write_file(self._filepath)
        else:
            self._save_as()

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "名前を付けて保存", "", "Road Design JSON (*.rdjson);;JSON (*.json)")
        if path:
            self._filepath = path
            self._write_file(path)

    def _write_file(self, path: str):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.scene.to_dict(), f, indent=2, ensure_ascii=False)
            self.setWindowTitle(f"道路設計アプリ - {os.path.basename(path)}")
            self._status_label.setText("保存完了")
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))

    def _open(self):
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
        self._canvas.smooth_connect(a, b)
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_polyline_connect(self, a, b):
        self._canvas.push_undo()
        self._canvas._connect_polyline(a, b)
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_disconnect(self, a, b):
        self._canvas.disconnect_lines(a, b)
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_add_clothoid(self, ln, ci):
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
        self._canvas.push_undo()
        self.scene.remove_clothoid(clo)
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    def _do_flip_clothoid(self, clo):
        self._canvas.push_undo()
        clo.reversed_flag = not clo.reversed_flag
        clo.compute()
        self._canvas.scene_changed.emit()
        self._canvas.update()
        self._right_panel.update_selection(self._canvas._selected, self.scene)

    # ─── 縦断線形 ────────────────────────────────────────────
    def _open_vertical_window(self):
        from models import ElementProfile, plan_length_of
        import math as _math

        # 選択中の平面線形要素を収集
        raw_elements = [obj for obj in self._canvas._selected
                        if isinstance(obj, (Segment, Arc, Clothoid))]
        if not raw_elements:
            return

        # ── チェーンの順序と向きを解決 ──────────────────────────
        # 各要素の端点（始点・終点のワールド座標）を取得
        def endpoints(obj):
            """(start_pt, end_pt) を Vec2 で返す"""
            from models import Vec2, Segment, Arc, Clothoid
            if isinstance(obj, Segment):
                return obj.start, obj.end
            if isinstance(obj, Arc):
                return obj.start, obj.end
            if isinstance(obj, Clothoid):
                if obj.is_valid and obj._line_pt and obj._circle_pt:
                    return obj._line_pt, obj._circle_pt
            return None, None

        def pt_dist(a, b):
            if a is None or b is None:
                return float('inf')
            return _math.hypot(a.x - b.x, a.y - b.y)

        def resolve_chain(elems):
            """
            要素リストから (順序付きリスト, reversed_flags) を返す。
            共有端点（SNAP_TOL 以内）を検出してチェーンの順序と向きを決定する。
            既存の ElementProfile に reversed_flag が保存されている場合はそれを優先する。
            """
            if len(elems) == 1:
                ep = next((ep for ep in self.scene.element_profiles
                           if ep.element_id == elems[0].id), None)
                rev = ep.reversed_flag if ep else False
                return list(elems), [rev]

            pts      = {id(e): endpoints(e) for e in elems}
            SNAP_TOL = 1.0

            def connects_to_other(pt, exclude_elem):
                for e in elems:
                    if e is exclude_elem: continue
                    s, ep_ = pts[id(e)]
                    if pt_dist(pt, s) < SNAP_TOL or pt_dist(pt, ep_) < SNAP_TOL:
                        return True
                return False

            # チェーンの真の末端要素を探す
            # 「片方の端点が孤立している」要素が先頭候補
            candidates = []
            for cand in elems:
                s, e = pts[id(cand)]
                s_iso = s is not None and not connects_to_other(s, cand)
                e_iso = e is not None and not connects_to_other(e, cand)
                if s_iso and not e_iso:
                    candidates.append((cand, False))   # 正順で先頭
                elif e_iso and not s_iso:
                    candidates.append((cand, True))    # 逆順で先頭

            # 既存データがある場合、reversed_flag と一致する候補を優先
            # 具体的には「最初の要素が rev=False（正順の先頭）」となる候補を優先
            if candidates:
                # ep.reversed_flag が False の要素を正順先頭として優先
                best_first = None
                for cand, cand_rev in candidates:
                    ep_existing = next((ep for ep in self.scene.element_profiles
                                        if ep.element_id == cand.id), None)
                    saved_rev = ep_existing.reversed_flag if ep_existing else None
                    if saved_rev is not None and saved_rev == cand_rev:
                        best_first = (cand, cand_rev)
                        break
                if best_first is None:
                    best_first = candidates[0]
                first, first_rev = best_first
            else:
                first, first_rev = elems[0], False

            # 貪欲にチェーンを構築
            remaining = list(elems)
            chain     = [first]
            rev_flags = [first_rev]
            remaining.remove(first)

            while remaining:
                last_elem = chain[-1]
                last_rev  = rev_flags[-1]
                ls, le    = pts[id(last_elem)]
                cur_end   = le if not last_rev else ls

                best = None; best_rev = False; best_d = float('inf')
                for cand in remaining:
                    cs, ce = pts[id(cand)]
                    d_fwd = pt_dist(cur_end, cs)
                    d_rev = pt_dist(cur_end, ce)
                    if d_fwd < best_d:
                        best_d = d_fwd; best = cand; best_rev = False
                    if d_rev < best_d:
                        best_d = d_rev; best = cand; best_rev = True

                if best is None or best_d > SNAP_TOL * 10:
                    best = remaining[0]; best_rev = False

                chain.append(best)
                rev_flags.append(best_rev)
                remaining.remove(best)

            return chain, rev_flags

        elements, rev_flags = resolve_chain(raw_elements)

        # 各要素に対応する ElementProfile を取得または新規作成
        def get_or_create_ep(obj) -> ElementProfile:
            ep = next((ep for ep in self.scene.element_profiles
                       if ep.element_id == obj.id), None)
            if ep is None:
                ep = ElementProfile()
                ep.element_id   = obj.id
                ep.element_type = (
                    'segment'  if isinstance(obj, Segment)  else
                    'arc'      if isinstance(obj, Arc)       else
                    'clothoid')
                self.scene.element_profiles.append(ep)
            ep.plan_length  = plan_length_of(obj)
            ep.reversed_flag = rev_flags[elements.index(obj)]
            return ep

        profiles = [get_or_create_ep(obj) for obj in elements]

        # 隣接する ElementProfile 間の接点標高を同期
        for i in range(len(profiles) - 1):
            ep_cur  = profiles[i]
            ep_next = profiles[i + 1]
            if ep_cur.grade_lines:
                last_gl = max(ep_cur.grade_lines, key=lambda g: g.dist_end)
                shared_elev = last_gl.elev_end
                ep_cur.elev_end    = shared_elev
                ep_next.elev_start = shared_elev
            elif ep_next.grade_lines:
                first_gl = min(ep_next.grade_lines, key=lambda g: g.dist_start)
                shared_elev = first_gl.elev_start
                ep_cur.elev_end    = shared_elev
                ep_next.elev_start = shared_elev

        self._vertical_window = VerticalAlignmentWindow(
            self.scene, profiles, elements, rev_flags, parent=None)
        self._vertical_window.show()

    # ─── デモデータ ──────────────────────────────────────────
    def _add_demo(self):
        """起動時のデモ図形"""
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
