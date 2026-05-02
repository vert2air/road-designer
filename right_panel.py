"""
右パネル (プロパティ・操作パネル)
"""
from __future__ import annotations
import math
from typing import Optional, Callable
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QGroupBox, QScrollArea, QFrame, QLineEdit,
    QCheckBox, QComboBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from models import (Vec2, Line, Segment, Circle, Arc, Clothoid, Scene,
                    SegmentSnap, ArcSnap)


def _make_spinbox(val: float, lo: float = -1e6, hi: float = 1e6,
                  step: float = 0.1, decimals: int = 3) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(val)
    return sb


def _separator() -> QFrame:
    """水平セパレータ線"""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def _style_disabled(btn: QPushButton, disabled: bool):
    """disable 状態を視覚的に明確にする"""
    if disabled:
        btn.setStyleSheet("color: #666666; background-color: #2a2a2a;")
    else:
        btn.setStyleSheet("")


class RightPanel(QWidget):
    request_smooth_connect  = pyqtSignal(object, object)   # line_a, line_b
    request_polyline_connect = pyqtSignal(object, object)
    request_disconnect      = pyqtSignal(object, object)
    request_add_clothoid    = pyqtSignal(object, object)   # line, circle
    request_delete_clothoid = pyqtSignal(object)
    request_flip_clothoid   = pyqtSignal(object)
    request_select          = pyqtSignal(list)
    request_delete          = pyqtSignal(list)   # 削除要求
    scene_changed           = pyqtSignal()

    def __init__(self, scene: Scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._selected: list = []
        self._block = False  # UI → モデル更新の再帰防止

        self.setMinimumWidth(260)
        self.setMaximumWidth(360)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)

        # ── マウス座標表示 ────────────────────────────────────
        coord_group = QGroupBox("マウス座標")
        coord_layout = QHBoxLayout(coord_group)
        self._lbl_mouse_x = QLabel("X: ---")
        self._lbl_mouse_y = QLabel("Y: ---")
        coord_layout.addWidget(self._lbl_mouse_x)
        coord_layout.addWidget(self._lbl_mouse_y)
        root_layout.addWidget(coord_group)

        # ── ニックネームで選択エリア ─────────────────────────
        nick_group = QGroupBox("ニックネームで選択")
        nick_layout = QVBoxLayout(nick_group)

        self._nick_combos: list[QComboBox] = []
        self._nick_combo_area = QVBoxLayout()
        nick_layout.addLayout(self._nick_combo_area)

        # 1行目: +, -, 選択を適用, 図形を削除
        btn_row1 = QHBoxLayout()
        btn_add = QPushButton("+")
        btn_add.setFixedWidth(30)
        btn_add.clicked.connect(self._add_nick_combo)
        btn_rem = QPushButton("-")
        btn_rem.setFixedWidth(30)
        btn_rem.clicked.connect(self._remove_nick_combo)
        btn_apply = QPushButton("選択を適用")
        btn_apply.clicked.connect(self._apply_nick_select)
        btn_del = QPushButton("図形を削除")
        btn_del.clicked.connect(self._delete_selected_objs)
        btn_row1.addWidget(btn_add)
        btn_row1.addWidget(btn_rem)
        btn_row1.addWidget(btn_apply)
        btn_row1.addWidget(btn_del)
        nick_layout.addLayout(btn_row1)

        # 2行目: 再描画
        btn_row2 = QHBoxLayout()
        btn_redraw = QPushButton("再描画（全クロソイド再計算）")
        btn_redraw.clicked.connect(self._redraw)
        btn_row2.addWidget(btn_redraw)
        nick_layout.addLayout(btn_row2)
        root_layout.addWidget(nick_group)

        # 初期コンボ x2
        self._add_nick_combo()
        self._add_nick_combo()

        # ── スクロール可能なプロパティ領域 ─────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._prop_widget = QWidget()
        self._prop_layout = QVBoxLayout(self._prop_widget)
        self._prop_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._prop_widget)
        root_layout.addWidget(scroll, 1)

    def update_mouse_pos(self, x: float, y: float):
        """キャンバス上のマウス座標をリアルタイム表示"""
        self._lbl_mouse_x.setText(f"X: {x:.3f}")
        self._lbl_mouse_y.setText(f"Y: {y:.3f}")

    # ─── ニックネームコンボ ──────────────────────────────────
    def _add_nick_combo(self):
        cb = QComboBox()
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._nick_combos.append(cb)
        self._nick_combo_area.addWidget(cb)
        # 選択変更時に後続コンボの選択肢を更新
        cb.currentIndexChanged.connect(self._on_combo_changed)
        self._refresh_nick_combos()

    def _on_combo_changed(self, idx: int):
        """いずれかのコンボが変更されたら後続コンボの選択肢を再構築"""
        sender = self.sender()
        if sender is not None and idx >= 0:
            text = sender.itemText(idx)
            if not text:  # セパレータはスキップ
                return
        # 最後のコンボに何かが選択されたら1個追加する
        if sender is not None and self._nick_combos:
            last_cb = self._nick_combos[-1]
            if sender is last_cb:
                obj = self._find_by_nick_label(last_cb.currentText())
                if obj is not None:
                    self._add_nick_combo()
                    return  # _add_nick_combo 内で _refresh_nick_combos が呼ばれる
        self._refresh_nick_combos()

    def _remove_nick_combo(self):
        if len(self._nick_combos) > 1:
            cb = self._nick_combos.pop()
            self._nick_combo_area.removeWidget(cb)
            cb.deleteLater()

    # ─── 隣接図形の計算 ──────────────────────────────────────
    SNAP_TOL = 1.0   # m

    def _endpoints_of(self, obj) -> list:
        """図形の端点座標リストを返す（Segment/Arc/Clothoid のみ）"""
        from models import Vec2
        import math as _m
        if isinstance(obj, Segment):
            return [obj.start, obj.end]
        if isinstance(obj, Arc):
            return [obj.start, obj.end]
        if isinstance(obj, Clothoid):
            if obj.is_valid and obj._line_pt and obj._circle_pt:
                return [obj._line_pt, obj._circle_pt]
        return []

    def _adjacent_elements(self, obj, exclude_pt=None) -> list:
        """
        obj の端点に隣接する図形リストを返す。
        exclude_pt が指定された場合、その点と一致する端点は除外して隣接を探す。
        戻り値: [(cand, is_forward), ...]
          is_forward=True  → cand の始点側で接続（順方向）
          is_forward=False → cand の終点側で接続（逆方向）
        """
        import math as _m
        my_pts = self._endpoints_of(obj)
        if exclude_pt is not None:
            my_pts = [p for p in my_pts
                      if _m.hypot(p.x - exclude_pt.x, p.y - exclude_pt.y) > self.SNAP_TOL]
        if not my_pts:
            return []

        result = []
        seen = set()
        all_elems = []
        for ln in self.scene.lines:
            all_elems.extend(ln.segments)
        for ci in self.scene.circles:
            all_elems.extend(ci.arcs)
        all_elems.extend(self.scene.clothoids)

        for cand in all_elems:
            if cand is obj:
                continue
            cand_pts = self._endpoints_of(cand)
            if len(cand_pts) < 2:
                continue
            cand_start = cand_pts[0]
            cand_end   = cand_pts[-1]
            for mp in my_pts:
                matched = False
                if _m.hypot(mp.x - cand_start.x, mp.y - cand_start.y) < self.SNAP_TOL:
                    if id(cand) not in seen:
                        result.append((cand, True))   # 始点で接続 → 順方向
                        seen.add(id(cand))
                    matched = True
                elif _m.hypot(mp.x - cand_end.x, mp.y - cand_end.y) < self.SNAP_TOL:
                    if id(cand) not in seen:
                        result.append((cand, False))  # 終点で接続 → 逆方向
                        seen.add(id(cand))
                    matched = True
                if matched:
                    break
        return result

    def _free_endpoint(self, obj, shared_pt) -> object:
        """
        obj の端点のうち shared_pt と一致しない方を返す。
        """
        import math as _m
        for p in self._endpoints_of(obj):
            if _m.hypot(p.x - shared_pt.x, p.y - shared_pt.y) > self.SNAP_TOL:
                return p
        return None

    def _shared_pt(self, obj_a, obj_b) -> object:
        """obj_a と obj_b の共有端点を返す（なければ None）"""
        import math as _m
        for pa in self._endpoints_of(obj_a):
            for pb in self._endpoints_of(obj_b):
                if _m.hypot(pa.x - pb.x, pa.y - pb.y) < self.SNAP_TOL:
                    return pa
        return None

    def _all_items(self) -> list[str]:
        """全図形のコンボラベルリスト（タイプ別・名称順）"""
        lines_items    = sorted([f"{self.scene.get_nickname(ln.id,'line')} [直線#{ln.id}]"
                                  for ln in self.scene.lines])
        seg_items      = sorted([f"線分#{seg.id} (直線:{self.scene.get_nickname(ln.id,'line')}) [線分#{seg.id}]"
                                  for ln in self.scene.lines for seg in ln.segments])
        circle_items   = sorted([f"{self.scene.get_nickname(ci.id,'circle')} [円#{ci.id}]"
                                  for ci in self.scene.circles])
        arc_items      = sorted([f"円弧#{arc.id} (円:{self.scene.get_nickname(ci.id,'circle')}) [円弧#{arc.id}]"
                                  for ci in self.scene.circles for arc in ci.arcs])
        clothoid_items = sorted([f"{self.scene.get_nickname(clo.id,'clothoid')} [クロソイド#{clo.id}]"
                                  for clo in self.scene.clothoids])
        return ["(なし)"] + lines_items + seg_items + circle_items + arc_items + clothoid_items

    def _compute_next_forward(self, prev_obj, prev_is_fwd, next_obj) -> bool:
        """
        前の図形の出口接線と、次の図形の「共有点→近傍点」ベクトルの内積で判定。
        内積 < 0 → 逆方向（スムーズに繋がる）= [順]
        内積 > 0 → 同方向（逆走）= [逆]
        """
        import math as _m

        prev_pts = self._endpoints_of(prev_obj)
        next_pts = self._endpoints_of(next_obj)
        if not prev_pts or not next_pts:
            return True

        # 前の図形の出口接線
        exit_pt  = prev_pts[-1] if prev_is_fwd else prev_pts[0]
        exit_tan = self._tangent_at(prev_obj, at_end=prev_is_fwd)
        if not prev_is_fwd:
            exit_tan = (-exit_tan[0], -exit_tan[1])

        # 共有点 = 次の図形の始点側か終点側か
        d_start = _m.hypot(exit_pt.x-next_pts[0].x,  exit_pt.y-next_pts[0].y)
        d_end   = _m.hypot(exit_pt.x-next_pts[-1].x, exit_pt.y-next_pts[-1].y)
        connect_at_start = d_start < d_end

        # 次の図形の「共有点→近傍点」ベクトル
        entry_tan = self._entry_tangent(next_obj, connect_at_start)
        if entry_tan is None:
            return True

        dot = exit_tan[0]*entry_tan[0] + exit_tan[1]*entry_tan[1]
        # exit_tan: 前の図形の進行方向（出口での接線）
        # entry_tan: 次の図形の「共有点→近傍点」方向
        # dot > 0 → 同方向（前の図形の向きと次の図形の向きが一致）= [順]
        # dot < 0 → 逆方向（次の図形が逆向き）= [逆]
        return dot >= 0

    def _tangent_at(self, obj, at_end: bool) -> tuple:
        """obj の始点(at_end=False)または終点(at_end=True)での進行方向接線ベクトル"""
        import math as _m
        if isinstance(obj, Segment):
            dx = obj.end.x - obj.start.x
            dy = obj.end.y - obj.start.y
            ln = _m.hypot(dx, dy) or 1
            return (dx/ln, dy/ln)
        elif isinstance(obj, Arc):
            ang = obj.angle_end if at_end else obj.angle_start
            return (-_m.sin(ang), _m.cos(ang))
        elif isinstance(obj, Clothoid):
            raw = obj.points
            if raw and len(raw) >= 2:
                if at_end:
                    dx = raw[-1].x - raw[-2].x
                    dy = raw[-1].y - raw[-2].y
                else:
                    dx = raw[1].x - raw[0].x
                    dy = raw[1].y - raw[0].y
                ln = _m.hypot(dx, dy) or 1
                return (dx/ln, dy/ln)
        return (1, 0)

    def _entry_tangent(self, obj, connect_at_start: bool) -> tuple:
        """
        次の図形の「共有点 → 近傍点」方向ベクトルを返す。
        connect_at_start=True: 共有点が obj の始点
        connect_at_start=False: 共有点が obj の終点
        """
        import math as _m
        if isinstance(obj, Segment):
            if connect_at_start:
                dx = obj.end.x - obj.start.x
                dy = obj.end.y - obj.start.y
            else:
                dx = obj.start.x - obj.end.x
                dy = obj.start.y - obj.end.y
            ln = _m.hypot(dx, dy) or 1
            return (dx/ln, dy/ln)

        elif isinstance(obj, Arc):
            DELTA = _m.radians(0.1)
            if connect_at_start:
                ang0 = obj.angle_start
                ang1 = obj.angle_start + DELTA   # 少し CCW 方向へ
            else:
                ang0 = obj.angle_end
                ang1 = obj.angle_end - DELTA      # 少し CW 方向（終点から戻る方向）
            R  = obj.circle.radius
            cx = obj.circle.center.x
            cy = obj.circle.center.y
            x0 = cx + R * _m.cos(ang0); y0 = cy + R * _m.sin(ang0)
            x1 = cx + R * _m.cos(ang1); y1 = cy + R * _m.sin(ang1)
            dx = x1 - x0; dy = y1 - y0
            ln = _m.hypot(dx, dy) or 1
            return (dx/ln, dy/ln)

        elif isinstance(obj, Clothoid):
            raw = obj.points
            if not raw or len(raw) < 2:
                return None
            if connect_at_start:
                dx = raw[1].x - raw[0].x
                dy = raw[1].y - raw[0].y
            else:
                dx = raw[-2].x - raw[-1].x
                dy = raw[-2].y - raw[-1].y
            ln = _m.hypot(dx, dy) or 1
            return (dx/ln, dy/ln)

        return None

    def _next_is_forward(self, prev_obj, prev_is_fwd, next_obj) -> bool:
        """
        prev_obj → next_obj でチェーンを進むとき、next_obj の is_forward を返す。
        共有点が next_obj の始点側 → is_forward=True（正順）
        共有点が next_obj の終点側 → is_forward=False（逆順）
        """
        import math as _m
        prev_pts = self._endpoints_of(prev_obj)
        next_pts = self._endpoints_of(next_obj)
        if not prev_pts or not next_pts:
            return True
        exit_pt = prev_pts[-1] if prev_is_fwd else prev_pts[0]
        d_start = _m.hypot(exit_pt.x-next_pts[0].x,  exit_pt.y-next_pts[0].y)
        d_end   = _m.hypot(exit_pt.x-next_pts[-1].x, exit_pt.y-next_pts[-1].y)
        return d_start < d_end   # 始点で接続 → 正順(True)

    def _refresh_nick_combos(self):
        """
        コンボボックスの選択肢を更新する。
        1つ目: 全図形
        2つ目以降: 前の図形の出口端点に隣接する図形を先頭
                   隣接が2個以上なら [順]/[逆] を付加
        """
        import math as _m
        all_items = self._all_items()

        selected_objs = []
        for cb in self._nick_combos:
            obj = self._find_by_nick_label(cb.currentText())
            selected_objs.append(obj)

        # 各コンボの is_forward を追跡（チェーン方向の管理）
        is_forward = [True] * len(self._nick_combos)
        for i in range(1, len(selected_objs)):
            prev = selected_objs[i - 1]
            cur  = selected_objs[i]
            if prev is None or cur is None:
                break
            is_forward[i] = self._next_is_forward(prev, is_forward[i-1], cur)

        for i, cb in enumerate(self._nick_combos):
            cur_text = cb.currentText()
            cb.blockSignals(True)
            cb.clear()

            if i == 0:
                cb.addItems(all_items)
            else:
                prev_obj = selected_objs[i - 1]
                if prev_obj is None or not self._endpoints_of(prev_obj):
                    cb.addItems(all_items)
                else:
                    if i == 1:
                        # 2つ目: 1つ目の両端点に隣接する図形すべて
                        adj = self._adjacent_from_obj(prev_obj, excludes=selected_objs)
                        show_dir = len(adj) >= 2
                    else:
                        # 3つ目以降: 前の図形の出口端点のみ
                        prev_pts = self._endpoints_of(prev_obj)
                        exit_pt  = prev_pts[-1] if is_forward[i-1] else prev_pts[0]
                        adj = self._adjacent_from_pt(exit_pt, excludes=selected_objs,
                                                      prev_obj=prev_obj)
                        show_dir = len(adj) >= 2

                    cb.addItem("(なし)")
                    for cand, _ in adj:
                        base_label = self._label_for_obj(cand)
                        if not base_label:
                            continue
                        if show_dir:
                            if i == 1:
                                # 2つ目: cand が prev_obj のどちらの端点側に接続しているかで
                                # prev_is_fwd を決める
                                # 終点側に接続 → prev を正順(True)で通過してきた
                                # 始点側に接続 → prev を逆順(False)で通過してきた
                                prev_exit_fwd = self._prev_is_fwd_for_adj(prev_obj, cand)
                                cand_fwd = self._compute_next_forward(
                                    prev_obj, prev_exit_fwd, cand)
                            else:
                                cand_fwd = self._compute_next_forward(
                                    prev_obj, is_forward[i-1], cand)
                            prefix = "[順] " if cand_fwd else "[逆] "
                            cb.addItem(prefix + base_label)
                        else:
                            cb.addItem(base_label)

                    if adj:
                        cb.insertSeparator(cb.count())
                    for item in all_items:
                        cb.addItem(item)

            # 現在の選択を復元
            # cur_text から base（プレフィックスなし）を取得
            base = cur_text
            for prefix in ("[順] ", "[逆] "):
                if base.startswith(prefix):
                    base = base[len(prefix):]
                    break

            # 検索優先順: そのまま → "[順] base" → "[逆] base" → base
            found = -1
            for search in [cur_text,
                           "[順] " + base,
                           "[逆] " + base,
                           base]:
                found = cb.findText(search)
                if found >= 0:
                    break
            cb.setCurrentIndex(found if found >= 0 else 0)
            cb.blockSignals(False)

    def _prev_is_fwd_for_adj(self, prev_obj, cand) -> bool:
        """
        prev_obj の隣接図形 cand に繋がるとき、prev_obj をどちら向きで通過してきたかを返す。
        - cand が prev_obj の終点側に接続 → prev_obj を正順(True)で通過してきた
        - cand が prev_obj の始点側に接続 → prev_obj を逆順(False)で通過してきた
        """
        import math as _m
        prev_pts = self._endpoints_of(prev_obj)
        cand_pts = self._endpoints_of(cand)
        if not prev_pts or not cand_pts:
            return True

        end_pt   = prev_pts[-1]   # prev_obj の終点
        start_pt = prev_pts[0]    # prev_obj の始点

        # cand の端点が prev_obj の終点に近い → 正順
        for cp in cand_pts:
            if _m.hypot(cp.x - end_pt.x, cp.y - end_pt.y) < self.SNAP_TOL:
                return True

        # cand の端点が prev_obj の始点に近い → 逆順
        for cp in cand_pts:
            if _m.hypot(cp.x - start_pt.x, cp.y - start_pt.y) < self.SNAP_TOL:
                return False

        # Clothoid の line_pt/circle_pt が prev_obj に接続している場合も考慮
        if isinstance(prev_obj, Clothoid) and prev_obj.is_valid:
            if prev_obj._circle_pt:
                for cp in cand_pts:
                    if _m.hypot(cp.x - prev_obj._circle_pt.x,
                                 cp.y - prev_obj._circle_pt.y) < self.SNAP_TOL:
                        return True   # circle_pt 側 = 終点 = 正順で通過

        # prev_obj が Arc で cand が Clothoid の場合
        if isinstance(cand, Clothoid) and cand.is_valid and isinstance(prev_obj, Arc):
            if cand._circle_pt:
                if _m.hypot(cand._circle_pt.x - end_pt.x,
                             cand._circle_pt.y - end_pt.y) < self.SNAP_TOL:
                    return True
                if _m.hypot(cand._circle_pt.x - start_pt.x,
                             cand._circle_pt.y - start_pt.y) < self.SNAP_TOL:
                    return False

        return True  # デフォルト

    def _adjacent_from_obj(self, obj, excludes=None) -> list:
        """
        obj の全端点に隣接する図形をすべて返す（2つ目のコンボ用）。
        - 同じ直線上で端点を共有する線分
        - 同じ円上で端点を共有する円弧
        - obj が接点であるクロソイド
        - 交点を共有する他の直線の線分
        戻り値: [(cand, is_forward), ...] (重複なし)
        """
        import math as _m
        exclude_set = set(id(e) for e in excludes if e is not None) if excludes else set()
        result = []
        seen = set()

        def add(cand, fwd):
            if id(cand) not in exclude_set and id(cand) not in seen:
                result.append((cand, fwd))
                seen.add(id(cand))

        pts = self._endpoints_of(obj)

        # 各端点から隣接を探す
        for pt in pts:
            adj = self._adjacent_from_pt(pt, excludes=excludes, prev_obj=obj)
            for cand, fwd in adj:
                add(cand, fwd)

        # obj が Clothoid の場合、接点に接する線分・円弧を追加で探す
        if isinstance(obj, Clothoid) and obj.is_valid:
            if obj._line_pt:
                adj2 = self._adjacent_from_pt(obj._line_pt, excludes=excludes, prev_obj=obj)
                for cand, fwd in adj2:
                    add(cand, fwd)
            if obj._circle_pt:
                adj3 = self._adjacent_from_pt(obj._circle_pt, excludes=excludes, prev_obj=obj)
                for cand, fwd in adj3:
                    add(cand, fwd)

        # obj が Arc の場合、両端の接点に接するクロソイドも探す
        if isinstance(obj, Arc):
            for clo in self.scene.clothoids:
                if id(clo) in exclude_set or id(clo) in seen:
                    continue
                if not clo.is_valid:
                    continue
                clo_pts = self._endpoints_of(clo)
                for pt in pts:
                    for cp in clo_pts:
                        if _m.hypot(pt.x - cp.x, pt.y - cp.y) < self.SNAP_TOL:
                            fwd = (cp is clo_pts[0])  # line_pt側=True, circle_pt側=False
                            add(clo, fwd)

        # obj が Segment の場合、同じ直線の線分 + クロソイドの接点も探す
        if isinstance(obj, Segment):
            for clo in self.scene.clothoids:
                if id(clo) in exclude_set or id(clo) in seen:
                    continue
                if not clo.is_valid or clo.line is not obj.line:
                    continue
                if clo._line_pt is None:
                    continue
                t = obj.line.project_t(clo._line_pt)
                if obj.t_start - 1e-6 <= t <= obj.t_end + 1e-6:
                    add(clo, True)  # line_pt 側で接続

        return result

    def _adjacent_from_pt(self, pt, excludes=None, prev_obj=None) -> list:
        """
        指定座標 pt に隣接する図形を返す。
        prev_obj がクロソイドで pt が _line_pt の場合、
        その点を含む線分（端点でなくても）も候補に含める。
        excludes: 除外するオブジェクトのリスト（選択済み全図形）
        戻り値: [(cand, is_forward), ...]
        """
        import math as _m
        exclude_set = set(id(e) for e in excludes if e is not None) if excludes else set()
        result = []
        seen = set()
        all_elems = []
        for ln in self.scene.lines:
            all_elems.extend(ln.segments)
        for ci in self.scene.circles:
            all_elems.extend(ci.arcs)
        all_elems.extend(self.scene.clothoids)

        for cand in all_elems:
            if id(cand) in exclude_set:
                continue
            cand_pts = self._endpoints_of(cand)
            if len(cand_pts) < 2:
                continue
            d_start = _m.hypot(pt.x - cand_pts[0].x, pt.y - cand_pts[0].y)
            d_end   = _m.hypot(pt.x - cand_pts[-1].x, pt.y - cand_pts[-1].y)
            if d_start < self.SNAP_TOL:
                if id(cand) not in seen:
                    result.append((cand, True))
                    seen.add(id(cand))
            elif d_end < self.SNAP_TOL:
                if id(cand) not in seen:
                    result.append((cand, False))
                    seen.add(id(cand))

        # クロソイドの _line_pt は線分の内部点の場合がある
        # clo.line と同じ直線上の線分のみを対象に「線分上にあるか」で判定
        if (prev_obj is not None and isinstance(prev_obj, Clothoid)
                and prev_obj._line_pt is not None
                and _m.hypot(pt.x - prev_obj._line_pt.x,
                              pt.y - prev_obj._line_pt.y) < self.SNAP_TOL):
            clo_line = prev_obj.line
            t = clo_line.project_t(prev_obj._line_pt)
            for seg in clo_line.segments:       # ← clo.line の線分のみ
                if id(seg) in exclude_set or id(seg) in seen:
                    continue
                if seg.t_start - 1e-6 <= t <= seg.t_end + 1e-6:
                    if abs(t - seg.t_start) < 1e-4:
                        result.append((seg, True))
                        seen.add(id(seg))
                    elif abs(t - seg.t_end) < 1e-4:
                        result.append((seg, False))
                        seen.add(id(seg))
                    else:
                        result.append((seg, False))
                        result.append((seg, True))
                        seen.add(id(seg))
        return result

    def _redraw(self):
        """シーンを再計算して再描画する"""
        for clo in self.scene.clothoids:
            clo.compute()
        self.scene_changed.emit()

    def _delete_selected_objs(self):
        """コンボボックスで選択中の図形を削除する"""
        from PyQt6.QtWidgets import QMessageBox
        objs = []
        for cb in self._nick_combos:
            obj = self._find_by_nick_label(cb.currentText())
            if obj is not None and obj not in objs:
                objs.append(obj)
        if not objs:
            return
        names = ", ".join(self._label_for_obj(o) or str(o) for o in objs)
        reply = QMessageBox.question(
            self, "図形を削除",
            f"以下の図形を削除しますか？\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.request_delete.emit(objs)

    def _apply_nick_select(self):
        selected = []
        for cb in self._nick_combos:
            txt = cb.currentText()
            obj = self._find_by_nick_label(txt)
            if obj is not None:
                selected.append(obj)
        self.request_select.emit(selected)

    def _find_by_nick_label(self, label: str) -> Optional[object]:
        # [順]/[逆] プレフィックスを除去
        for prefix in ("[順] ", "[逆] "):
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        for ln in self.scene.lines:
            if f"{self.scene.get_nickname(ln.id, 'line')} [直線#{ln.id}]" == label:
                return ln
            for seg in ln.segments:
                if f"線分#{seg.id} (直線:{self.scene.get_nickname(ln.id,'line')}) [線分#{seg.id}]" == label:
                    return seg
        for ci in self.scene.circles:
            if f"{self.scene.get_nickname(ci.id, 'circle')} [円#{ci.id}]" == label:
                return ci
            for arc in ci.arcs:
                if f"円弧#{arc.id} (円:{self.scene.get_nickname(ci.id,'circle')}) [円弧#{arc.id}]" == label:
                    return arc
        for clo in self.scene.clothoids:
            if f"{self.scene.get_nickname(clo.id, 'clothoid')} [クロソイド#{clo.id}]" == label:
                return clo
        return None

    # ─── 選択変更時 ──────────────────────────────────────────
    def update_selection(self, selected: list, scene: Scene):
        self.scene    = scene
        self._selected = selected
        self._refresh_nick_combos()
        self._sync_combos_to_selection(selected)
        self._rebuild_props()

    def _sync_combos_to_selection(self, selected: list):
        """設計画面での選択をコンボボックスに反映する"""
        labels = []
        for obj in selected:
            label = self._label_for_obj(obj)
            if label:
                labels.append(label)

        while len(self._nick_combos) < len(labels):
            self._add_nick_combo()

        for i, cb in enumerate(self._nick_combos):
            if i < len(labels):
                label = labels[i]
                # プレフィックスなし → あり の順で検索
                idx = cb.findText(label)
                if idx < 0:
                    for prefix in ("[順] ", "[逆] "):
                        idx = cb.findText(prefix + label)
                        if idx >= 0:
                            break
                if idx >= 0:
                    cb.blockSignals(True)
                    cb.setCurrentIndex(idx)
                    cb.blockSignals(False)
            else:
                cb.blockSignals(True)
                cb.setCurrentIndex(0)
                cb.blockSignals(False)

    def _label_for_obj(self, obj) -> str:
        """図形オブジェクトからコンボラベル文字列を生成する"""
        if isinstance(obj, Line):
            return f"{self.scene.get_nickname(obj.id, 'line')} [直線#{obj.id}]"
        if isinstance(obj, Segment):
            ln = obj.line
            return f"線分#{obj.id} (直線:{self.scene.get_nickname(ln.id,'line')}) [線分#{obj.id}]"
        if isinstance(obj, Circle):
            return f"{self.scene.get_nickname(obj.id, 'circle')} [円#{obj.id}]"
        if isinstance(obj, Arc):
            ci = obj.circle
            return f"円弧#{obj.id} (円:{self.scene.get_nickname(ci.id,'circle')}) [円弧#{obj.id}]"
        if isinstance(obj, Clothoid):
            return f"{self.scene.get_nickname(obj.id, 'clothoid')} [クロソイド#{obj.id}]"
        return ""

    def _clear_props(self):
        while self._prop_layout.count():
            item = self._prop_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _rebuild_props(self):
        self._clear_props()
        sel = self._selected
        n   = len(sel)

        if n == 0:
            self._prop_layout.addWidget(QLabel("図形を選択してください"))
            return

        if n == 1:
            self._build_single(sel[0])
            return

        # ── 2図形選択 ────────────────────────────────────────
        if n == 2:
            a, b = sel
            # Segment は親 Line として扱う (接続操作のため)
            la = a.line if isinstance(a, Segment) else a
            # 線分 + 線分
            if isinstance(a, Segment) and isinstance(b, Segment) and a is not b:
                self._build_two_segments(a, b)
                return

            # 円弧 + 円弧
            if isinstance(a, Arc) and isinstance(b, Arc) and a is not b:
                self._build_two_arcs(a, b)
                return

            lb = b.line if isinstance(b, Segment) else b

            # 直線 + 直線 (Segment経由も含む)
            if isinstance(la, Line) and isinstance(lb, Line) and la is not lb:
                self._build_two_lines(la, lb)
                return

            # 直線 + 円
            ln = ci = None
            if isinstance(a, Line) and isinstance(b, Circle):
                ln, ci = a, b
            elif isinstance(a, Circle) and isinstance(b, Line):
                ln, ci = b, a
            elif isinstance(a, Segment) and isinstance(b, Circle):
                ln, ci = a.line, b
            elif isinstance(a, Circle) and isinstance(b, Segment):
                ln, ci = b.line, a
            if ln is not None and ci is not None:
                self._build_line_circle(ln, ci)
                return

            # クロソイド選択時は単体プロパティを両方表示
            for obj in sel:
                self._build_single(obj)
            return

        # ── 3図形以上 ─────────────────────────────────────────
        self._prop_layout.addWidget(QLabel(f"{n} 個の図形が選択されています"))
        # それでも各図形のニックネームだけ表示
        for obj in sel:
            oid = getattr(obj, 'id', None)
            if oid:
                prefix = ("line" if isinstance(obj, Line) else
                          "circle" if isinstance(obj, Circle) else
                          "clothoid" if isinstance(obj, Clothoid) else "seg")
                name = self.scene.get_nickname(oid, prefix)
                self._prop_layout.addWidget(QLabel(f"  • {name}"))

    # ─── 単一図形プロパティ ──────────────────────────────────
    def _build_single(self, obj):
        # ニックネーム（ID 表示を含む）
        self._add_nickname_editor(obj)

        if isinstance(obj, Line):
            self._build_line_props(obj)
        elif isinstance(obj, Circle):
            self._build_circle_props(obj)
        elif isinstance(obj, Clothoid):
            self._build_clothoid_props(obj)
        elif isinstance(obj, Segment):
            self._build_segment_props(obj)
        elif isinstance(obj, Arc):
            self._build_arc_props(obj)

        # 関連図形
        self._add_related_objects(obj)

        # 縦断設計情報
        self._add_vertical_profile_info(obj)

    def _add_vertical_profile_info(self, obj):
        """平面線形要素に対応する縦断設計情報（ElementProfile）を表示する"""
        from models import ElementProfile
        oid = getattr(obj, 'id', None)
        if oid is None:
            return
        ep = next((ep for ep in self.scene.element_profiles
                   if ep.element_id == oid), None)
        if ep is None or not ep.grade_lines:
            return

        grp = QGroupBox("縦断設計")
        lay = QVBoxLayout(grp)
        lay.addWidget(QLabel(f"平面長: {ep.plan_length:.3f} m"))
        lay.addWidget(QLabel(f"始端標高: {ep.elev_start:.3f} m"))
        lay.addWidget(QLabel(f"終端標高: {ep.elev_end:.3f} m"))
        lay.addWidget(QLabel(f"勾配直線数: {len(ep.grade_lines)}"))
        # 勾配直線の一覧
        for gl in sorted(ep.grade_lines, key=lambda g: g.dist_start):
            grad = gl.gradient
            lay.addWidget(QLabel(
                f"  {gl.dist_start:.1f}→{gl.dist_end:.1f}m  "
                f"{grad:+.3f}%"))
        if ep.vertical_curves:
            lay.addWidget(QLabel(f"縦断曲線数: {len(ep.vertical_curves)}"))
            for vc in ep.vertical_curves:
                lay.addWidget(QLabel(
                    f"  PVI={vc.pvi_dist:.1f}m  L={vc.length:.1f}m  K={vc.K:.1f}"))
        self._prop_layout.addWidget(grp)

    def _add_nickname_editor(self, obj):
        grp = QGroupBox("ニックネーム / ID")
        lay = QVBoxLayout(grp)

        # ID（読み取り専用、最上部）
        oid = getattr(obj, 'id', None)
        if oid is not None:
            id_row = QHBoxLayout()
            id_row.addWidget(QLabel("ID:"))
            id_val = QLabel(str(oid))
            id_val.setStyleSheet("font-weight: bold;")
            id_row.addWidget(id_val)
            id_row.addStretch()
            lay.addLayout(id_row)

        # ニックネーム入力欄
        edit = QLineEdit()
        if oid is not None:
            edit.setText(self.scene.nicknames.get(oid, ""))
        def on_change(text):
            if oid is not None:
                self.scene.set_nickname(oid, text)
                self._refresh_nick_combos()
                self.scene_changed.emit()
        edit.textChanged.connect(on_change)
        lay.addWidget(edit)
        self._prop_layout.addWidget(grp)

    def _add_related_objects(self, obj):
        related = self.scene.connected_objects(obj)
        if not related:
            return
        grp = QGroupBox("関連図形")
        lay = QVBoxLayout(grp)
        for rel in related:
            rid = getattr(rel, 'id', None)
            prefix = ("line" if isinstance(rel, Line) else
                      "circle" if isinstance(rel, Circle) else "clothoid")
            name = self.scene.get_nickname(rid, prefix) if rid else str(rel)
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            btn_sel = QPushButton("選択")
            btn_sel.clicked.connect(lambda _, r=rel: self.request_select.emit([r]))
            btn_add = QPushButton("選択追加")
            btn_add.clicked.connect(lambda _, r=rel:
                                     self.request_select.emit(self._selected + [r]))
            row.addWidget(btn_sel)
            row.addWidget(btn_add)
            lay.addLayout(row)
        self._prop_layout.addWidget(grp)

    def _build_line_props(self, ln: Line):
        grp = QGroupBox("直線プロパティ")
        lay = QVBoxLayout(grp)

        def add_vec2(label, get_fn, set_fn):
            lay.addWidget(QLabel(label))
            row = QHBoxLayout()
            sbx = _make_spinbox(get_fn().x)
            sby = _make_spinbox(get_fn().y)
            def on_x(v):
                if self._block: return
                old = get_fn()
                set_fn(Vec2(v, old.y))
                self.scene_changed.emit()
            def on_y(v):
                if self._block: return
                old = get_fn()
                set_fn(Vec2(old.x, v))
                self.scene_changed.emit()
            sbx.valueChanged.connect(on_x)
            sby.valueChanged.connect(on_y)
            row.addWidget(QLabel("X:")); row.addWidget(sbx)
            row.addWidget(QLabel("Y:")); row.addWidget(sby)
            lay.addLayout(row)

        add_vec2("参照始点", lambda: ln.ref_start,
                 lambda v: setattr(ln, 'ref_start', v))
        add_vec2("参照終点", lambda: ln.ref_end,
                 lambda v: setattr(ln, 'ref_end', v))

        ang = math.degrees(ln.angle)
        lay.addWidget(QLabel(f"方向角: {ang:.2f}°"))
        self._prop_layout.addWidget(grp)

    def _build_circle_props(self, ci: Circle):
        grp = QGroupBox("円プロパティ")
        lay = QVBoxLayout(grp)

        row_cx = QHBoxLayout()
        sb_cx = _make_spinbox(ci.center.x)
        sb_cy = _make_spinbox(ci.center.y)
        sb_r  = _make_spinbox(ci.radius, 0.001, 1e6, 0.5)

        def on_cx(v):
            if self._block: return
            ci.center = Vec2(v, ci.center.y)
            self.scene_changed.emit()
        def on_cy(v):
            if self._block: return
            ci.center = Vec2(ci.center.x, v)
            self.scene_changed.emit()
        def on_r(v):
            if self._block: return
            ci.radius = max(0.001, v)
            self.scene_changed.emit()

        sb_cx.valueChanged.connect(on_cx)
        sb_cy.valueChanged.connect(on_cy)
        sb_r.valueChanged.connect(on_r)

        row_cx.addWidget(QLabel("中心X:")); row_cx.addWidget(sb_cx)
        row_cx.addWidget(QLabel("Y:"));     row_cx.addWidget(sb_cy)
        lay.addLayout(row_cx)
        row_r = QHBoxLayout()
        row_r.addWidget(QLabel("半径:")); row_r.addWidget(sb_r)
        lay.addLayout(row_r)
        self._prop_layout.addWidget(grp)

    def _build_clothoid_props(self, clo: Clothoid):
        grp = QGroupBox("クロソイドプロパティ")
        lay = QVBoxLayout(grp)

        # 状態表示
        curve_dir = "左カーブ" if clo.is_left_curve else "右カーブ"
        valid_str = "有効" if clo.is_valid else "【無効 - 配置条件不満足】"
        rev_str   = "反転あり" if clo.reversed_flag else "反転なし"
        lbl_info = QLabel(f"方向: {curve_dir}  /  {rev_str}\n状態: {valid_str}")
        lbl_info.setStyleSheet("color: #80e080;" if clo.is_valid else "color: #e08080;")
        lbl_info.setWordWrap(True)
        lay.addWidget(lbl_info)

        if clo.is_valid:
            lay.addWidget(QLabel(f"クロソイドパラメータ A: {clo._A:.4f}"))
            lay.addWidget(QLabel(f"全偏角 τ: {math.degrees(clo._tau):.4f}°"))
            lay.addWidget(_separator())

            # 線側接点
            lp = clo._line_pt
            lay.addWidget(QLabel("線側接点:"))
            lay.addWidget(QLabel(f"  X: {lp.x:.4f}"))
            lay.addWidget(QLabel(f"  Y: {lp.y:.4f}"))

            # 円側接点
            cp = clo._circle_pt
            lay.addWidget(QLabel("円側接点:"))
            lay.addWidget(QLabel(f"  X: {cp.x:.4f}"))
            lay.addWidget(QLabel(f"  Y: {cp.y:.4f}"))

            # 円弧端点との一致確認
            circle = clo.circle
            if circle.arcs:
                arc = circle.arcs[0]
                if clo.is_left_curve:
                    diff = math.hypot(cp.x - arc.start.x, cp.y - arc.start.y)
                    match_str = f"arc.start との距離: {diff:.6f}"
                    match_ok  = diff < 0.01
                else:
                    diff = math.hypot(cp.x - arc.end.x, cp.y - arc.end.y)
                    match_str = f"arc.end との距離: {diff:.6f}"
                    match_ok  = diff < 0.01
                lbl_match = QLabel(f"  ({match_str})")
                lbl_match.setStyleSheet("color: #80e080;" if match_ok else "color: #e08080;")
                lay.addWidget(lbl_match)

        lay.addWidget(_separator())

        # snap チェックボックス
        lay.addWidget(QLabel("snap 設定:"))
        chk_seg = QCheckBox("線分との snap")
        chk_arc = QCheckBox("円弧との snap")
        chk_seg.setChecked(clo.snap_segment)
        chk_arc.setChecked(clo.snap_arc)

        def on_seg(v):
            clo.snap_segment = bool(v)
            clo.compute()
            self.scene_changed.emit()
        def on_arc(v):
            clo.snap_arc = bool(v)
            clo.compute()
            self.scene_changed.emit()

        chk_seg.stateChanged.connect(on_seg)
        chk_arc.stateChanged.connect(on_arc)
        lay.addWidget(chk_seg)
        lay.addWidget(chk_arc)

        lay.addWidget(_separator())

        # 反転ボタン: 同じ直線・円の組に2本ある場合は disable
        siblings = self.scene.clothoids_for(clo.line, clo.circle)
        can_flip = (len(siblings) == 1)
        btn_flip = QPushButton("クロソイドを反転")
        btn_flip.setEnabled(can_flip)
        _style_disabled(btn_flip, not can_flip)
        if not can_flip:
            btn_flip.setToolTip("2本セットのクロソイドは個別に反転できません")
        btn_flip.clicked.connect(lambda: self.request_flip_clothoid.emit(clo))
        lay.addWidget(btn_flip)

        # 削除ボタン
        btn_del = QPushButton("このクロソイドを削除")
        btn_del.setStyleSheet("color: #e08080;")
        btn_del.clicked.connect(lambda: self.request_delete_clothoid.emit(clo))
        lay.addWidget(btn_del)

        self._prop_layout.addWidget(grp)

    def _build_segment_props(self, seg: Segment):
        grp = QGroupBox("線分プロパティ")
        lay = QVBoxLayout(grp)
        ln  = seg.line

        # 親の直線情報（読み取り専用）
        ln_nick = self.scene.get_nickname(ln.id, 'line')
        lbl_ln = QLabel(f"親直線: {ln_nick}  (ID:{ln.id})")
        btn_sel_ln = QPushButton("直線を選択")
        btn_sel_ln.setMaximumWidth(90)
        btn_sel_ln.clicked.connect(lambda checked=False, _ln=ln:
            self.request_select.emit([_ln]))
        row_ln = QHBoxLayout()
        row_ln.addWidget(lbl_ln)
        row_ln.addWidget(btn_sel_ln)
        lay.addLayout(row_ln)

        # 線分長 (読み取り専用)
        lay.addWidget(QLabel(f"長さ: {seg.length():.4f} m"))

        lay.addWidget(_separator())

        # 始点 (t_start から計算)
        def add_endpoint(label, get_t, set_t, other_t_getter):
            lay.addWidget(QLabel(label))
            pt = ln.point_at(get_t())
            row_x = QHBoxLayout()
            row_y = QHBoxLayout()
            sb_x = _make_spinbox(pt.x, step=0.1, decimals=4)
            sb_y = _make_spinbox(pt.y, step=0.1, decimals=4)
            sb_t = _make_spinbox(get_t(), lo=0.0, hi=1.0, step=0.001, decimals=6)
            lbl_t = QLabel(f"割合: {get_t():.6f}")

            def on_x(v):
                if self._block: return
                # 直線上に束縛: t = projection
                from models import Vec2
                current = ln.point_at(get_t())
                t = ln.project_t(Vec2(v, current.y))
                set_t(t)
                self._refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)
                self.scene_changed.emit()

            def on_y(v):
                if self._block: return
                from models import Vec2
                current = ln.point_at(get_t())
                t = ln.project_t(Vec2(current.x, v))
                set_t(t)
                self._refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)
                self.scene_changed.emit()

            def on_t(v):
                if self._block: return
                set_t(v)
                self._refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)
                self.scene_changed.emit()

            sb_x.valueChanged.connect(on_x)
            sb_y.valueChanged.connect(on_y)
            sb_t.valueChanged.connect(on_t)

            row_x.addWidget(QLabel("X:")); row_x.addWidget(sb_x)
            row_y.addWidget(QLabel("Y:")); row_y.addWidget(sb_y)
            lay.addLayout(row_x)
            lay.addLayout(row_y)
            lay.addWidget(lbl_t)

        def set_t_start(v): seg.t_start = v
        def set_t_end(v):   seg.t_end   = v
        add_endpoint("始点", lambda: seg.t_start, set_t_start, lambda: seg.t_end)
        add_endpoint("終点", lambda: seg.t_end,   set_t_end,   lambda: seg.t_start)

        self._prop_layout.addWidget(grp)

    def _refresh_seg_display(self, sb_x, sb_y, sb_t, lbl_t, ln, get_t):
        from models import Vec2
        self._block = True
        pt = ln.point_at(get_t())
        sb_x.setValue(pt.x)
        sb_y.setValue(pt.y)
        sb_t.setValue(get_t())
        lbl_t.setText(f"割合: {get_t():.6f}")
        self._block = False

    def _build_arc_props(self, arc: Arc):
        grp = QGroupBox("円弧プロパティ")
        lay = QVBoxLayout(grp)
        ci  = arc.circle

        # 親の円情報（読み取り専用）
        ci_nick = self.scene.get_nickname(ci.id, 'circle')
        lbl_ci = QLabel(f"親円: {ci_nick}  (ID:{ci.id})")
        btn_sel_ci = QPushButton("円を選択")
        btn_sel_ci.setMaximumWidth(80)
        btn_sel_ci.clicked.connect(lambda checked=False, _ci=ci:
            self.request_select.emit([_ci]))
        row_ci = QHBoxLayout()
        row_ci.addWidget(lbl_ci)
        row_ci.addWidget(btn_sel_ci)
        lay.addLayout(row_ci)

        # 弧長角・弧長 (読み取り専用)
        lbl_span = QLabel(f"弧長角: {math.degrees(arc.arc_angle()):.4f}°")
        lbl_len  = QLabel(f"弧長: {arc.arc_length():.4f} m")
        lay.addWidget(lbl_span)
        lay.addWidget(lbl_len)
        lay.addWidget(_separator())

        def add_arc_endpoint(label, get_angle, set_angle):
            lay.addWidget(QLabel(label))
            ang_deg = math.degrees(get_angle())
            pt      = Vec2(ci.center.x + ci.radius * math.cos(get_angle()),
                           ci.center.y + ci.radius * math.sin(get_angle()))

            row_ang = QHBoxLayout()
            row_x   = QHBoxLayout()
            row_y   = QHBoxLayout()
            sb_ang = _make_spinbox(ang_deg, lo=-360.0, hi=360.0, step=0.1, decimals=4)
            sb_x   = _make_spinbox(pt.x, step=0.1, decimals=4)
            sb_y   = _make_spinbox(pt.y, step=0.1, decimals=4)
            lbl_ang_ro = QLabel(f"  角度: {ang_deg:.4f}°")
            lbl_coord  = QLabel(f"  ({pt.x:.4f}, {pt.y:.4f})")

            def refresh_display():
                self._block = True
                a = get_angle()
                p = Vec2(ci.center.x + ci.radius * math.cos(a),
                         ci.center.y + ci.radius * math.sin(a))
                sb_ang.setValue(math.degrees(a))
                sb_x.setValue(p.x)
                sb_y.setValue(p.y)
                lbl_ang_ro.setText(f"  角度: {math.degrees(a):.4f}°")
                lbl_coord.setText(f"  ({p.x:.4f}, {p.y:.4f})")
                lbl_span.setText(f"弧長角: {math.degrees(arc.arc_angle()):.4f}°")
                lbl_len.setText(f"弧長: {arc.arc_length():.4f} m")
                self._block = False

            def on_ang(v):
                if self._block: return
                set_angle(math.radians(v))
                refresh_display()
                self.scene_changed.emit()

            def on_x(v):
                if self._block: return
                cur_a = get_angle()
                # 円上: x固定でyを2候補から近い方を選ぶ
                dx = v - ci.center.x
                if abs(dx) > ci.radius:
                    return
                dy = math.sqrt(max(0.0, ci.radius**2 - dx**2))
                cur_y = ci.center.y + ci.radius * math.sin(cur_a)
                new_y = ci.center.y + dy if abs(cur_y - (ci.center.y + dy)) < abs(cur_y - (ci.center.y - dy)) else ci.center.y - dy
                a = math.atan2(new_y - ci.center.y, v - ci.center.x)
                set_angle(a)
                refresh_display()
                self.scene_changed.emit()

            def on_y(v):
                if self._block: return
                cur_a = get_angle()
                dy = v - ci.center.y
                if abs(dy) > ci.radius:
                    return
                dx = math.sqrt(max(0.0, ci.radius**2 - dy**2))
                cur_x = ci.center.x + ci.radius * math.cos(cur_a)
                new_x = ci.center.x + dx if abs(cur_x - (ci.center.x + dx)) < abs(cur_x - (ci.center.x - dx)) else ci.center.x - dx
                a = math.atan2(v - ci.center.y, new_x - ci.center.x)
                set_angle(a)
                refresh_display()
                self.scene_changed.emit()

            sb_ang.valueChanged.connect(on_ang)
            sb_x.valueChanged.connect(on_x)
            sb_y.valueChanged.connect(on_y)

            row_ang.addWidget(QLabel("角度(°):")); row_ang.addWidget(sb_ang)
            row_x.addWidget(QLabel("X:"));         row_x.addWidget(sb_x)
            row_y.addWidget(QLabel("Y:"));         row_y.addWidget(sb_y)
            lay.addLayout(row_ang)
            lay.addLayout(row_x)
            lay.addLayout(row_y)
            lay.addWidget(lbl_coord)

        add_arc_endpoint("始点 (angle_start)",
                         lambda: arc.angle_start,
                         lambda v: setattr(arc, 'angle_start', v))
        add_arc_endpoint("終点 (angle_end)",
                         lambda: arc.angle_end,
                         lambda v: setattr(arc, 'angle_end', v))

        self._prop_layout.addWidget(grp)

    # ─── 2線分の接続操作 ─────────────────────────────────────
    # ─── 2線分の結合操作 ─────────────────────────────────────
    def _build_two_segments(self, seg_a: Segment, seg_b: Segment):
        grp = QGroupBox("線分の結合")
        lay = QVBoxLayout(grp)
        la_nick = self.scene.get_nickname(seg_a.line.id, 'line')
        lb_nick = self.scene.get_nickname(seg_b.line.id, 'line')
        lay.addWidget(QLabel(f"線分#{seg_a.id} (直線:{la_nick})"))
        lay.addWidget(QLabel(f"線分#{seg_b.id} (直線:{lb_nick})"))
        lay.addWidget(_separator())

        if seg_a.line is not seg_b.line:
            lay.addWidget(QLabel("異なる直線上の線分は結合できません。"))
            self._prop_layout.addWidget(grp)
            return

        lay.addWidget(QLabel(
            "近接する端点で結合します。\n"
            "一方の線分を削除し、もう一方を延長します。"))
        lay.addWidget(_separator())

        pairs = self._candidate_seg_pairs(seg_a, seg_b)
        if not pairs:
            lay.addWidget(QLabel("※ 近接する端点がありません"))
            self._prop_layout.addWidget(grp)
            return

        combo = QComboBox()
        for p in pairs:
            status = ""
            if p['blocked_a']: status += f"  ★A.{p['end_a']}束縛"
            if p['blocked_b']: status += f"  ★B.{p['end_b']}束縛"
            combo.addItem(p['label'] + status)
        lay.addWidget(combo)

        btn = QPushButton("結合する")
        def do_merge(checked=False, _c=combo, _p=pairs, _a=seg_a, _b=seg_b):
            p = _p[_c.currentIndex()]
            if p['blocked_a'] or p['blocked_b']:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "結合不可",
                    "選択した端点は他の図形に束縛されているため結合できません。")
                return
            self._merge_segments(_a, _b, p['end_a'], p['end_b'])
            self.scene_changed.emit()
        btn.clicked.connect(do_merge)
        lay.addWidget(btn)
        self._prop_layout.addWidget(grp)

    def _seg_end_blocked(self, seg: Segment, end: str) -> bool:
        """線分の端点がクロソイドに束縛されているか確認"""
        for clo in self.scene.clothoids:
            if not clo.is_valid:
                continue
            if clo.snap_segment and clo.line is seg.line and clo._line_pt is not None:
                t_x = clo.line.project_t(clo._line_pt)
                if end == 'end'   and abs(seg.t_end   - t_x) < 1e-4: return True
                if end == 'start' and abs(seg.t_start - t_x) < 1e-4: return True
            if seg.id in clo._split_seg_ids:
                return True
        return False

    def _candidate_seg_pairs(self, seg_a: Segment, seg_b: Segment) -> list:
        candidates = []
        for end_a, pt_a in [('start', seg_a.start), ('end', seg_a.end)]:
            for end_b, pt_b in [('start', seg_b.start), ('end', seg_b.end)]:
                dist = math.hypot(pt_a.x - pt_b.x, pt_a.y - pt_b.y)
                candidates.append({
                    'end_a': end_a, 'end_b': end_b, 'dist': dist,
                    'blocked_a': self._seg_end_blocked(seg_a, end_a),
                    'blocked_b': self._seg_end_blocked(seg_b, end_b),
                    'label': (f"A.{end_a}({pt_a.x:.1f},{pt_a.y:.1f}) ↔ "
                              f"B.{end_b}({pt_b.x:.1f},{pt_b.y:.1f})  d={dist:.1f}m"),
                })
        return sorted(candidates, key=lambda c: c['dist'])

    def _merge_segments(self, seg_a: Segment, seg_b: Segment,
                         end_a: str, end_b: str):
        """
        seg_b を削除し、seg_a の end_a 側を seg_b の反対端まで延長する。
        例: end_a='end', end_b='start' → seg_a.t_end = seg_b.t_end; del seg_b
        """
        far_t = seg_b.t_start if end_b == 'end' else seg_b.t_end
        if end_a == 'end':
            seg_a.t_end = far_t
        else:
            seg_a.t_start = far_t
        ln = seg_a.line
        if seg_b in ln.segments:
            ln.segments.remove(seg_b)

    # ─── 2円弧の結合操作 ─────────────────────────────────────
    def _build_two_arcs(self, arc_a: Arc, arc_b: Arc):
        grp = QGroupBox("円弧の結合")
        lay = QVBoxLayout(grp)
        ca_nick = self.scene.get_nickname(arc_a.circle.id, 'circle')
        cb_nick = self.scene.get_nickname(arc_b.circle.id, 'circle')
        lay.addWidget(QLabel(f"円弧#{arc_a.id} (円:{ca_nick})"))
        lay.addWidget(QLabel(f"円弧#{arc_b.id} (円:{cb_nick})"))
        lay.addWidget(_separator())

        if arc_a.circle is not arc_b.circle:
            lay.addWidget(QLabel("異なる円上の円弧は結合できません。"))
            self._prop_layout.addWidget(grp)
            return

        lay.addWidget(QLabel(
            "近接する端点で結合します。\n"
            "一方の円弧を削除し、もう一方を延長します。"))
        lay.addWidget(_separator())

        pairs = self._candidate_arc_pairs(arc_a, arc_b)
        if not pairs:
            lay.addWidget(QLabel("※ 近接する端点がありません"))
            self._prop_layout.addWidget(grp)
            return

        combo = QComboBox()
        for p in pairs:
            status = ""
            if p['blocked_a']: status += f"  ★A.{p['end_a']}束縛"
            if p['blocked_b']: status += f"  ★B.{p['end_b']}束縛"
            combo.addItem(p['label'] + status)
        lay.addWidget(combo)

        btn = QPushButton("結合する")
        def do_merge(checked=False, _c=combo, _p=pairs, _a=arc_a, _b=arc_b):
            p = _p[_c.currentIndex()]
            if p['blocked_a'] or p['blocked_b']:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "結合不可",
                    "選択した端点は他の図形に束縛されているため結合できません。")
                return
            self._merge_arcs(_a, _b, p['end_a'], p['end_b'])
            self.scene_changed.emit()
        btn.clicked.connect(do_merge)
        lay.addWidget(btn)
        self._prop_layout.addWidget(grp)

    def _arc_end_blocked(self, arc: Arc, end: str) -> bool:
        """円弧の端点がクロソイドに束縛されているか確認"""
        for clo in self.scene.clothoids:
            if not clo.is_valid:
                continue
            if clo.snap_arc and clo.circle is arc.circle and clo._circle_pt is not None:
                import math as _m
                ang = _m.atan2(clo._circle_pt.y - arc.circle.center.y,
                               clo._circle_pt.x - arc.circle.center.x)
                if end == 'start' and abs(arc.angle_start - ang) < 1e-4: return True
                if end == 'end'   and abs(arc.angle_end   - ang) < 1e-4: return True
            if arc.id in clo._split_arc_ids:
                return True
        return False

    def _candidate_arc_pairs(self, arc_a: Arc, arc_b: Arc) -> list:
        candidates = []
        for end_a, ang_a, pt_a in [('start', arc_a.angle_start, arc_a.start),
                                     ('end',   arc_a.angle_end,   arc_a.end)]:
            for end_b, ang_b, pt_b in [('start', arc_b.angle_start, arc_b.start),
                                         ('end',   arc_b.angle_end,   arc_b.end)]:
                dist = math.hypot(pt_a.x - pt_b.x, pt_a.y - pt_b.y)
                candidates.append({
                    'end_a': end_a, 'end_b': end_b, 'dist': dist,
                    'blocked_a': self._arc_end_blocked(arc_a, end_a),
                    'blocked_b': self._arc_end_blocked(arc_b, end_b),
                    'label': (f"A.{end_a}({math.degrees(ang_a):.1f}°) ↔ "
                              f"B.{end_b}({math.degrees(ang_b):.1f}°)  d={dist:.1f}m"),
                })
        return sorted(candidates, key=lambda c: c['dist'])

    def _merge_arcs(self, arc_a: Arc, arc_b: Arc, end_a: str, end_b: str):
        """
        arc_b を削除し、arc_a の end_a 側を arc_b の反対端まで延長する。
        例: end_a='end', end_b='start' → arc_a.angle_end = arc_b.angle_end; del arc_b
        """
        far_angle = arc_b.angle_start if end_b == 'end' else arc_b.angle_end
        if end_a == 'end':
            arc_a.angle_end = far_angle
        else:
            arc_a.angle_start = far_angle
        ci = arc_a.circle
        if arc_b in ci.arcs:
            ci.arcs.remove(arc_b)

    # ─── 2直線 ───────────────────────────────────────────────
    def _build_two_lines(self, a: Line, b: Line):
        grp = QGroupBox("2直線の接続操作")
        lay = QVBoxLayout(grp)

        # 現在の接続状態を表示
        conn = a.connection
        has_conn = (conn is not None and
                    ((conn.line_a is a and conn.line_b is b) or
                     (conn.line_a is b and conn.line_b is a)))
        if has_conn:
            kind_str = "スムーズ接続中" if conn.kind == "smooth" else "折れ線接続中"
            lbl = QLabel(f"状態: {kind_str}")
            lbl.setStyleSheet("color: #80e080; font-weight: bold;")
        else:
            lbl = QLabel("状態: 接続なし")
            lbl.setStyleSheet("color: #a0a0a0;")
        lay.addWidget(lbl)

        lay.addWidget(_separator())

        btn_poly = QPushButton("折れ線接続")
        btn_smoo = QPushButton("スムーズ接続")
        btn_disc = QPushButton("接続解除")

        # 接続解除はこの2直線の接続が存在するときのみ有効
        btn_disc.setEnabled(has_conn)
        _style_disabled(btn_disc, not has_conn)

        btn_poly.clicked.connect(lambda: self.request_polyline_connect.emit(a, b))
        btn_smoo.clicked.connect(lambda: self.request_smooth_connect.emit(a, b))
        btn_disc.clicked.connect(lambda: self.request_disconnect.emit(a, b))

        lay.addWidget(btn_poly)
        lay.addWidget(btn_smoo)
        lay.addWidget(btn_disc)

        # 各直線のプロパティも続けて表示
        self._prop_layout.addWidget(grp)
        self._add_nickname_editor(a)
        self._build_line_props(a)
        self._add_nickname_editor(b)
        self._build_line_props(b)

    # ─── 直線+円 (クロソイド操作) ────────────────────────────
    def _build_line_circle(self, ln: Line, ci: Circle):
        grp = QGroupBox("クロソイド操作（直線 + 円）")
        lay = QVBoxLayout(grp)

        clothoids = self.scene.clothoids_for(ln, ci)
        n = len(clothoids)

        # 現在の状態表示
        if n == 0:
            state_txt = "クロソイドなし"
            state_css = "color: #a0a0a0;"
        elif n == 1:
            clo = clothoids[0]
            curve_dir = "左カーブ" if clo.is_left_curve else "右カーブ"
            valid_str  = "有効" if clo.is_valid else "【無効 - 配置条件不満足】"
            rev_str    = "（反転）" if clo.reversed_flag else ""
            state_txt  = f"クロソイド 1本: {curve_dir}{rev_str}  {valid_str}"
            state_css  = "color: #80e080;" if clo.is_valid else "color: #e08080;"
        else:
            c0, c1 = clothoids[0], clothoids[1]
            state_txt = (f"クロソイド 2本: "
                         f"{'左' if c0.is_left_curve else '右'} / "
                         f"{'左' if c1.is_left_curve else '右'}カーブ")
            state_css = "color: #80e080;"

        lbl_state = QLabel(state_txt)
        lbl_state.setStyleSheet(state_css)
        lbl_state.setWordWrap(True)
        lay.addWidget(lbl_state)

        lay.addWidget(_separator())

        # ── クロソイドを追加 ──────────────────────────────────
        # n=0: 1本目追加(有効), n=1: 反転側を追加(有効), n=2: disable
        btn_add = QPushButton(
            "クロソイドを追加" if n == 0 else
            "クロソイドを追加（反転側）" if n == 1 else
            "クロソイドを追加（上限に達しています）"
        )
        can_add = (n < 2)
        btn_add.setEnabled(can_add)
        _style_disabled(btn_add, not can_add)

        def do_add():
            self.request_add_clothoid.emit(ln, ci)
        btn_add.clicked.connect(do_add)
        lay.addWidget(btn_add)

        # ── クロソイドを削除 ──────────────────────────────────
        # n=1: 有効, n=0 or n=2: disable
        btn_del = QPushButton("クロソイドを削除")
        can_del = (n == 1)
        btn_del.setEnabled(can_del)
        _style_disabled(btn_del, not can_del)

        def do_del():
            if clothoids:
                self.request_delete_clothoid.emit(clothoids[0])
        btn_del.clicked.connect(do_del)
        lay.addWidget(btn_del)

        # ── クロソイドを反転 ──────────────────────────────────
        # n=1: 有効, n=0 or n=2: disable
        btn_flp = QPushButton("クロソイドを反転")
        can_flp = (n == 1)
        btn_flp.setEnabled(can_flp)
        _style_disabled(btn_flp, not can_flp)

        def do_flp():
            if clothoids:
                self.request_flip_clothoid.emit(clothoids[0])
        btn_flp.clicked.connect(do_flp)
        lay.addWidget(btn_flp)

        # ── n=1 のとき: snap チェックボックスも表示 ─────────
        if n == 1:
            clo = clothoids[0]
            lay.addWidget(_separator())
            lay.addWidget(QLabel("snap 設定:"))
            chk_seg = QCheckBox("線分との snap")
            chk_arc = QCheckBox("円弧との snap")
            chk_seg.setChecked(clo.snap_segment)
            chk_arc.setChecked(clo.snap_arc)

            def on_seg(v):
                clo.snap_segment = bool(v)
                clo.compute()
                self.scene_changed.emit()
            def on_arc(v):
                clo.snap_arc = bool(v)
                clo.compute()
                self.scene_changed.emit()

            chk_seg.stateChanged.connect(on_seg)
            chk_arc.stateChanged.connect(on_arc)
            lay.addWidget(chk_seg)
            lay.addWidget(chk_arc)

        self._prop_layout.addWidget(grp)

        # 直線・円それぞれのプロパティも表示
        self._add_nickname_editor(ln)
        self._build_line_props(ln)
        self._add_nickname_editor(ci)
        self._build_circle_props(ci)
