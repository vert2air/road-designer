"""右パネル（プロパティ・操作パネル）モジュール。

Canvas での選択に連動してプロパティ表示・数値入力・接続操作を提供する。
接続操作は request_* シグナル経由で MainWindow に委譲する疎結合構造。

プロパティ UI の構築メソッド群（``_build_*`` 等）は
``_prop_builder.PropBuilderMixin`` として分離している。
"""
from __future__ import annotations
import math
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QScrollArea, QFrame, QSplitter,
    QComboBox,
)
from PySide6.QtCore import Qt, Signal
from models import (Vec2, Line, Segment, Circle, Arc, Clothoid, Scene,
                    tangent_at, entry_tangent, SNAP_TOL, new_id,
                    effective_set)
from _prop_builder import PropBuilderMixin
# backward-compat re-export（テストが right_panel から直接 import するため）
from _prop_builder import (  # noqa: F401
    _encode_point_pair, _decode_point_pair,
    _clipboard_has_point_pair, _copy_point_pair, _paste_point_pair,
    _transform_pair,
)


class RightPanel(QWidget, PropBuilderMixin):
    """右パネル。図形選択コンボ・プロパティ表示・操作ボタンを提供する。

    ``Canvas`` と直接参照し合わず、``request_*`` シグナルを ``MainWindow``
    に送ることで疎結合を保つ。

    Signals
    -------
    request_smooth_connect : Signal(object, object)
        スムーズ接続を要求する。引数: ``(line_a, line_b)``。
    request_polyline_connect : Signal(object, object)
        折れ線接続を要求する。引数: ``(line_a, line_b)``。
    request_disconnect : Signal(object, object)
        接続解除を要求する。引数: ``(line_a, line_b)``。
    request_add_clothoid : Signal(object, object)
        クロソイド追加を要求する。引数: ``(line, circle)``。
    request_delete_clothoid : Signal(object)
        クロソイド削除を要求する。引数: ``clothoid``。
    request_flip_clothoid : Signal(object)
        クロソイド反転を要求する。引数: ``clothoid``。
    request_select : Signal(list)
        選択変更を要求する。引数: 選択図形のリスト。
    request_delete : Signal(list)
        図形削除を要求する。引数: 削除する図形のリスト。
    request_set_offset : Signal(object, object, object)
        オフセット拘束設定を要求する。引数: ``(line, ci_a, ci_b)``。
    request_clear_offset : Signal(object)
        オフセット拘束解除を要求する。引数: ``line``。
    request_add_arcs : Signal(object, list)
        円弧追加を要求する。引数: ``(circle, [Arc, ...])``。
        Arc オブジェクトは arc_start/arc_end が設定済みで
        まだ ci.arcs には追加されていない。
    request_push_undo : Signal()
        プロパティ変更前の Undo スタックへの push を要求する。
        プロパティ編集コールバックの初回呼び出し時に1回だけ発行する。
    scene_changed : Signal()
        シーン変更を通知する。
    """
    request_smooth_connect = Signal(object, object)   # line_a, line_b
    request_polyline_connect = Signal(object, object)
    request_disconnect = Signal(object, object)
    request_add_clothoid = Signal(object, object)   # line, circle
    request_delete_clothoid = Signal(object)
    request_flip_clothoid = Signal(object)
    request_select = Signal(list)
    request_delete = Signal(list)   # 削除要求
    request_set_offset = Signal(object, object, object)  # line, ci_a, ci_b
    request_clear_offset = Signal(object)                  # line
    # ln_a, ln_b, ci
    request_set_two_line_offset = Signal(object, object, object)
    request_clear_two_line_offset = Signal(object, object)  # ln_a, ln_b
    request_add_arcs = Signal(object, list)            # circle, [Arc]
    request_push_undo = Signal()                        # プロパティ変更前の状態保存
    scene_changed = Signal()

    def __init__(self, scene: Scene, parent=None):
        """RightPanel を初期化する。

        コンボボックスエリア・プロパティエリア・ボタン群を構築する。
        ``_block`` フラグは UI 操作によるモデル更新が再帰的に UI を更新する
        ことを防ぐために使用する。

        Parameters
        ----------
        scene : Scene
            初期状態の Scene オブジェクト。
        parent : QWidget, optional
            親ウィジェット。
        """
        super().__init__(parent)
        self.scene = scene
        self._selected: list = []
        self._block = False  # UI → モデル更新の再帰防止
        self._canvas_ref = None  # キャンバスへの直接参照（直接更新用）

        self.setMinimumWidth(260)
        self.setMaximumWidth(360)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)

        # ── マウス座標表示 ────────────────────────────────────
        coord_group = QGroupBox("マウス座標")
        coord_layout = QVBoxLayout(coord_group)
        coord_xy = QHBoxLayout()
        self._lbl_mouse_x = QLabel("X: ---")
        self._lbl_mouse_y = QLabel("Y: ---")
        coord_xy.addWidget(self._lbl_mouse_x)
        coord_xy.addWidget(self._lbl_mouse_y)
        coord_layout.addLayout(coord_xy)
        # 距離測定ラベル（ラバーバンド選択中のみ表示）
        self._lbl_measure_dist = QLabel("")
        self._lbl_measure_dist.setStyleSheet(
            "color: #50c8ff; font-weight: bold;")
        self._lbl_measure_dist.hide()
        coord_layout.addWidget(self._lbl_measure_dist)
        # ホバー中の図形名ラベル（図形がある時のみ表示）
        self._lbl_hovered = QLabel("")
        self._lbl_hovered.setWordWrap(True)
        self._lbl_hovered.setStyleSheet("color: #ccaa00; font-style: italic;")
        self._lbl_hovered.hide()
        coord_layout.addWidget(self._lbl_hovered)
        root_layout.addWidget(coord_group)

        # ── ニックネームで選択エリア ─────────────────────────
        nick_group = QGroupBox("ニックネームで選択")
        # チェックボックス付きタイトルで折りたたみ可能にする
        nick_group.setCheckable(True)
        nick_group.setChecked(True)  # デフォルトは展開

        # 折りたたみ用コンテナ
        nick_content = QWidget()
        nick_layout = QVBoxLayout(nick_content)
        nick_layout.setContentsMargins(0, 0, 0, 0)

        self._nick_combos: list[QComboBox] = []
        # コンボ一覧をスクロール可能なエリアに入れる（大量選択時に画面を圧迫しない）
        nick_combo_widget = QWidget()
        self._nick_combo_area = QVBoxLayout(nick_combo_widget)
        self._nick_combo_area.setContentsMargins(0, 0, 0, 0)
        self._nick_combo_area.setAlignment(Qt.AlignmentFlag.AlignTop)
        nick_scroll = QScrollArea()
        nick_scroll.setWidget(nick_combo_widget)
        nick_scroll.setWidgetResizable(True)
        nick_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nick_scroll.setFrameShape(QFrame.Shape.NoFrame)
        nick_layout.addWidget(nick_scroll)

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

        # コンテナを nick_group の外側レイアウトに追加して折りたたみを接続
        nick_outer = QVBoxLayout(nick_group)
        nick_outer.setContentsMargins(4, 2, 4, 4)
        nick_outer.addWidget(nick_content)
        nick_group.toggled.connect(nick_content.setVisible)

        # 初期コンボ x2
        self._add_nick_combo()
        self._add_nick_combo()

        # ── スクロール可能なプロパティ領域 ─────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 水平スクロールを常に非表示にしてコンテンツを幅に収める
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._prop_widget = QWidget()
        self._prop_layout = QVBoxLayout(self._prop_widget)
        self._prop_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # ウィジェットが scroll のビューポート幅に追従するよう制約を設定
        # SetFixedSize だとリサイズに追従しないので SetMinAndMaxSize を使う
        from PySide6.QtWidgets import QLayout
        self._prop_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinAndMaxSize)
        scroll.setWidget(self._prop_widget)

        # ニックネームエリアとプロパティエリアをスプリッターで結合
        # → ドラッグで高さを自由に調整できる
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(nick_group)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)   # nick_group: 伸縮なし
        splitter.setStretchFactor(1, 1)   # scroll: 残り全体を使う
        splitter.setSizes([200, 400])     # 初期サイズ（ピクセル）
        root_layout.addWidget(splitter, 1)

    def update_mouse_pos(self, x: float, y: float):
        """Canvas.mouse_world_pos シグナルを受け取り、マウス座標ラベルを更新する。

        Parameters
        ----------
        x, y : float
            ワールド座標（小数点以下 3 桁で表示する）。
        """
        self._lbl_mouse_x.setText(f"X: {x:.3f}")
        self._lbl_mouse_y.setText(f"Y: {y:.3f}")

    def update_measure_dist(self, dist: float):
        """Canvas.measure_dist_changed シグナルを受け取り、距離ラベルを更新する。

        Parameters
        ----------
        dist : float
            ラバーバンド対角線のワールド距離 [m]。-1 のとき非表示にする。
        """
        if dist < 0:
            self._lbl_measure_dist.hide()
            self._lbl_measure_dist.setText("")
        else:
            self._lbl_measure_dist.setText(f"距離: {dist:.3f} m")
            self._lbl_measure_dist.show()

    def update_hovered(self, obj):
        """Canvas.hover_changed シグナルを受け取り、ホバー中の図形名を表示する。

        ニックネーム・タイプ#id・親図形情報をまとめて表示する。
        obj が None のとき表示を消す。

        Parameters
        ----------
        obj : Segment | Arc | Clothoid | Line | Circle | None
            ホバー中の図形。None のとき表示を消す。
        """
        if obj is None:
            self._lbl_hovered.hide()
            self._lbl_hovered.setText("")
            return

        from models import Segment, Arc, Clothoid, Line, Circle

        def _fmt(o, _kind, type_label):
            """ニックネームまたは (タイプ#id) 形式の文字列を返す。

            ニックネームが設定されていれば "name (タイプ#id)"、
            未設定なら "(タイプ#id)" を返す。
            """
            if self.scene is None:
                return f"#{o.id}"
            nick = self.scene.get_nickname(o.id)
            base = f"({type_label}#{o.id})"
            return f"{nick} {base}" if nick else base

        lines = []
        if isinstance(obj, Segment):
            lines.append(_fmt(obj, 'seg', '線分'))
            if obj.line is not None:
                lines.append(f"  親: {_fmt(obj.line, 'line', '直線')}")
        elif isinstance(obj, Arc):
            lines.append(_fmt(obj, 'arc', '円弧'))
            if obj.circle is not None:
                lines.append(f"  親: {_fmt(obj.circle, 'circle', '円')}")
        elif isinstance(obj, Clothoid):
            lines.append(_fmt(obj, 'clothoid', 'クロソイド'))
            if obj.line is not None:
                lines.append(f"  直線: {_fmt(obj.line, 'line', '直線')}")
            if obj.circle is not None:
                lines.append(f"  円: {_fmt(obj.circle, 'circle', '円')}")
        elif isinstance(obj, Line):
            lines.append(_fmt(obj, 'line', '直線'))
        elif isinstance(obj, Circle):
            lines.append(_fmt(obj, 'circle', '円'))
        else:
            lines.append(f"#{getattr(obj, 'id', '?')}")

        self._lbl_hovered.setText("\n".join(lines))
        self._lbl_hovered.show()

    # ─── ニックネームコンボ ──────────────────────────────────
    def _add_nick_combo(self):
        """ニックネーム選択コンボボックスを 1 個追加する。

        コンボをウィジェットツリーと ``_nick_combos`` リストに登録し、
        ``currentIndexChanged`` を ``_on_combo_changed`` に接続してから
        :meth:`_refresh_nick_combos` で選択肢を初期化する。
        「+」ボタンと :meth:`_on_combo_changed` （末尾コンボに図形が選択された時）
        から呼ばれる。
        """
        cb = QComboBox()
        cb.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMaximumWidth(240)
        self._nick_combos.append(cb)
        self._nick_combo_area.addWidget(cb)
        cb.currentIndexChanged.connect(self._on_combo_changed)
        self._refresh_nick_combos()

    def _road_follow(self, combo_idx: int):
        """「道なり」ボタンのハンドラ。

        combo_idx 番目のコンボに対して高優先候補から自動選択を試み、
        選べた場合はさらに次のコンボに対しても繰り返す。

        選択ルール（高優先候補 adj に対して）:

        1. adj が 1 件 → それを選ぶ。
        2. adj が複数件で、``[順]`` ラベルの候補が 1 件だけ → それを選ぶ。
        3. それ以外 → 停止。

        Parameters
        ----------
        combo_idx : int
            操作対象のコンボボックスのインデックス（1 以上）。
        """
        from PySide6.QtCore import Qt as _Qt

        i = combo_idx
        while True:
            if i >= len(self._nick_combos):
                break
            cb = self._nick_combos[i]

            # 高優先候補（セパレータより前のアイテム）を収集
            # [道なり] アイテム自体は連鎖の再帰を避けるため除外する
            adj_items = []   # [(item_index, text), ...]
            for j in range(cb.count()):
                t = cb.itemText(j)
                flags = cb.model().flags(cb.model().index(j, 0))
                is_separator = (not t and
                                not bool(flags & _Qt.ItemFlag.ItemIsEnabled))
                if is_separator:
                    break  # セパレータに到達 → 高優先候補はここまで
                if t and t != '(なし)' and not t.startswith('[道なり] '):
                    adj_items.append((j, t))

            if not adj_items:
                break  # 高優先候補なし → 停止

            chosen_idx = None

            if len(adj_items) == 1:
                # ルール1: 候補が1件だけ
                chosen_idx = adj_items[0][0]
            else:
                # ルール2: [順] ラベル付きが1件だけ
                forward_items = [(j, t) for j, t in adj_items
                                 if t.startswith('[順] ')]
                if len(forward_items) == 1:
                    chosen_idx = forward_items[0][0]

            if chosen_idx is None:
                break  # 選べない → 停止

            # 選択を反映（blockSignals してから手動で後続更新）
            cb.blockSignals(True)
            cb.setCurrentIndex(chosen_idx)
            cb.blockSignals(False)

            # _on_combo_changed 相当: 最後のコンボなら新しいコンボを追加
            if i == len(self._nick_combos) - 1:
                chosen_obj = self._find_by_nick_label(cb.currentText())
                if chosen_obj and self._endpoints_of(chosen_obj):
                    self._add_nick_combo()
            else:
                # 後続コンボの選択肢を更新
                self._refresh_nick_combos()

            i += 1

    def _on_combo_changed(self, idx: int):
        """コンボボックス選択変更時のコールバック。

        * ``[道なり]`` プレフィックスのアイテムが選ばれた場合:
          プレフィックスを除いた実際の選択肢に置き換えてから
          :meth:`_road_follow` で連鎖選択を実行する。
        * 最後のコンボに図形が選択された場合は _add_nick_combo で 1 個追加する。
        * その後 _refresh_nick_combos で全コンボの選択肢を更新する。

        Parameters
        ----------
        idx : int
            変更されたコンボボックスのインデックス（現在は使用しない）。
        """
        sender = self.sender()
        if sender is not None and idx >= 0:
            text = sender.itemText(idx)
            if not text:  # セパレータはスキップ
                return

            # [道なり] アイテムが選ばれた場合
            if text.startswith("[道なり] "):
                # プレフィックスを除いた実ラベルに相当するアイテムをコンボから探す
                real_label = text[len("[道なり] "):]
                real_idx = sender.findText(real_label)
                # 実アイテムが見つかれば選択を置き換え
                if real_idx >= 0:
                    sender.blockSignals(True)
                    sender.setCurrentIndex(real_idx)
                    sender.blockSignals(False)
                # このコンボが何番目か特定して連鎖処理
                if sender in self._nick_combos:
                    combo_pos = self._nick_combos.index(sender)
                    # 末尾なら新しいコンボを追加
                    if combo_pos == len(self._nick_combos) - 1:
                        obj = self._find_by_nick_label(sender.currentText())
                        if obj is not None:
                            self._add_nick_combo()
                    else:
                        self._refresh_nick_combos()
                    # 次のコンボから連鎖選択
                    self._road_follow(combo_pos + 1)
                return

        # 最後のコンボに何かが選択されたら1個追加する
        if sender is not None and self._nick_combos:
            last_cb = self._nick_combos[-1]
            if sender is last_cb:
                obj = self._find_by_nick_label(last_cb.currentText())
                if obj is not None:
                    self._add_nick_combo()
                    # _add_nick_combo 内で _refresh_nick_combos が呼ばれる
                    self._trim_trailing_none_combos()
                    return
        self._refresh_nick_combos()
        self._trim_trailing_none_combos()

    def _remove_nick_combo(self):
        """末尾のニックネーム選択コンボボックスを 1 個削除する。

        ``_nick_combos`` が 1 個しかない場合は何もしない（最低 1 個を保持する）。
        「-」ボタンから呼ばれる。
        """
        if len(self._nick_combos) > 1:
            cb = self._nick_combos.pop()
            self._nick_combo_area.removeWidget(cb)
            cb.deleteLater()

    def _trim_trailing_none_combos(self):
        """末尾に「（なし）」が2個以上続く場合、1個になるよう余分を削除する。

        最低1個のコンボは常に保持する。
        """
        while len(self._nick_combos) >= 2:
            if (self._nick_combos[-1].currentText() == "(なし)"
                    and self._nick_combos[-2].currentText() == "(なし)"):
                cb = self._nick_combos.pop()
                self._nick_combo_area.removeWidget(cb)
                cb.deleteLater()
            else:
                break

    # ─── 隣接図形の計算 ──────────────────────────────────────
    SNAP_TOL = SNAP_TOL  # models.SNAP_TOL を参照（= 1.0 m）
    #: 高優先候補の隣接判定閾値 [m]。端点間距離がこれ未満のとき隣接とみなす。
    #: 図形追加時のギャップ防止には SNAP_TOL(1.0m) を使うが、
    #: コンボボックスの高優先候補には厳密な値を使う。
    ADJ_TOL = 0.001

    def _endpoints_of(self, obj) -> list:
        """図形の端点座標リストを返す。

        コンボの隣接判定で共有端点との距離計算に使う。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid or any
            端点を取得する図形。

        Returns
        -------
        list[Vec2]
            [始点, 終点]。Clothoid が無効または非対応型のとき空リスト。
        """
        if isinstance(obj, Segment):
            return [obj.start, obj.end]
        if isinstance(obj, Arc):
            return [obj.start, obj.end]
        if isinstance(obj, Clothoid):
            if obj.is_valid and obj._line_pt and obj._circle_pt:
                return [obj._line_pt, obj._circle_pt]
        return []

    # ── 高優先候補の厳密な隣接判定 ─────────────────────────────────────

    def _directly_connected(self, obj_a, obj_b) -> bool:
        """obj_a と obj_b が「直接接点」を持つかを判定する。

        親図形が異なる場合に高優先候補に含めるかどうかの判定に使う。
        以下のケースを「直接接点あり」とみなす:

        * **クロソイド接点**: obj_a/obj_b の一方が Clothoid で、その
          ``_line_pt`` / ``_circle_pt`` が相手の端点と ADJ_TOL 以内。
        * **折れ線接続**: 一方が Segment で ``line.connection`` が
          ``"polyline"`` であり、共有点が相手の端点と ADJ_TOL 以内。
        * **オフセット拘束の接点**: OffsetConstraint で off_a=0 または
          off_b=0 の場合、直線と円が接している。

        スムーズ接続（``bisector_dir`` がある円経由）は接点でないため除外。
        接点でないオフセット接続（off != 0）も除外。

        Parameters
        ----------
        obj_a, obj_b : Segment or Arc or Clothoid
            判定する 2 つの図形。

        Returns
        -------
        bool
        """
        def pts_close(pa, pb):
            return math.hypot(pa.x - pb.x, pa.y - pb.y) < self.ADJ_TOL

        pts_a = self._endpoints_of(obj_a)
        pts_b = self._endpoints_of(obj_b)

        # クロソイド接点
        for obj, other_pts in [(obj_a, pts_b), (obj_b, pts_a)]:
            if isinstance(obj, Clothoid) and obj.is_valid:
                for cp in [p for p in [obj._line_pt, obj._circle_pt]
                           if p is not None]:
                    for q in other_pts:
                        if pts_close(cp, q):
                            return True

        # 折れ線接続（LineConnection "polyline"）
        for obj, other_pts in [(obj_a, pts_b), (obj_b, pts_a)]:
            if isinstance(obj, Segment):
                conn = getattr(obj.line, 'connection', None)
                if conn and getattr(conn, 'kind', None) == 'polyline':
                    sp = getattr(conn, 'shared_point', None)
                    if sp is not None:
                        for q in other_pts:
                            if pts_close(sp, q):
                                return True

        # オフセット拘束で接点（off=0 → 半径と距離が一致）
        for oc in self.scene.offset_constraints:
            a_line = getattr(oc, 'line', None)
            ca = getattr(oc, 'circle_a', None)
            cb = getattr(oc, 'circle_b', None)
            # off=0 のとき直線と円が接点を持つ
            if abs(oc.off_a) < 1e-9 and ca is not None and a_line is not None:
                segs_a = a_line.segments if a_line else []
                arcs_a = ca.arcs if ca else []
                pair_obj_a = any(obj_a is s for s in segs_a) or any(
                    obj_a is r for r in arcs_a)
                pair_obj_b = any(obj_b is s for s in segs_a) or any(
                    obj_b is r for r in arcs_a)
                if pair_obj_a and pair_obj_b:
                    return True
            if abs(oc.off_b) < 1e-9 and cb is not None and a_line is not None:
                segs_b = a_line.segments if a_line else []
                arcs_b = cb.arcs if cb else []
                pair_obj_a = any(obj_a is s for s in segs_b) or any(
                    obj_a is r for r in arcs_b)
                pair_obj_b = any(obj_b is s for s in segs_b) or any(
                    obj_b is r for r in arcs_b)
                if pair_obj_a and pair_obj_b:
                    return True

        return False

    def _parent_of(self, obj):
        """obj の親図形（Line または Circle）を返す。なければ None。"""
        if isinstance(obj, Segment):
            return obj.line
        if isinstance(obj, Arc):
            return obj.circle
        if isinstance(obj, Clothoid):
            return None  # Clothoid は Line と Circle の両方に跨がる
        return None

    def _adjacent_elements(self, obj, exclude_pt=None) -> list:
        """obj の端点に隣接する図形のリストを返す。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid
            基準となる図形。
        exclude_pt : Vec2, optional
            この座標と SNAP_TOL 以内の obj 端点を検索から除外する。
            2 つ目コンボで「出口端点側だけ」の隣接を取る際に使う。

        Returns
        -------
        list[tuple]
            [(cand, is_forward), ...] のリスト。
            is_forward=True: cand の始点で接続（正順）、False: 終点で接続（逆順）。
        """
        my_pts = self._endpoints_of(obj)
        if exclude_pt is not None:
            my_pts = [
                p for p in my_pts
                if math.hypot(
                    p.x - exclude_pt.x, p.y - exclude_pt.y
                ) > self.SNAP_TOL]
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
            cand_end = cand_pts[-1]
            for mp in my_pts:
                matched = False
                if (math.hypot(
                        mp.x - cand_start.x, mp.y - cand_start.y)
                        < self.ADJ_TOL):
                    if id(cand) not in seen:
                        result.append((cand, True))   # 始点で接続 → 順方向
                        seen.add(id(cand))
                    matched = True
                elif (math.hypot(
                        mp.x - cand_end.x, mp.y - cand_end.y)
                        < self.ADJ_TOL):
                    if id(cand) not in seen:
                        result.append((cand, False))  # 終点で接続 → 逆方向
                        seen.add(id(cand))
                    matched = True
                if matched:
                    break
        return result

    def _free_endpoint(self, obj, shared_pt) -> object:
        """obj の端点のうち shared_pt と一致しない方（自由端点）を返す。

        スムーズ接続の二等分線計算で U/V（X と反対側の端点）を特定するために使う。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid
            対象の図形。
        shared_pt : Vec2
            共有端点（交点 X）の座標。

        Returns
        -------
        Vec2 or None
            X と SNAP_TOL を超えて離れた端点。両端点が共有点の場合は None。
        """
        for p in self._endpoints_of(obj):
            if (math.hypot(p.x - shared_pt.x, p.y - shared_pt.y)
                    > self.SNAP_TOL):
                return p
        return None

    def _shared_pt(self, obj_a, obj_b) -> object:
        """obj_a と obj_b の共有端点を返す。

        全端点ペアを総当たりし、SNAP_TOL 以内の組み合わせを探す。

        Parameters
        ----------
        obj_a, obj_b : Segment or Arc or Clothoid
            共有端点を探す 2 つの図形。

        Returns
        -------
        Vec2 or None
            共有端点の座標。なければ None。
        """
        for pa in self._endpoints_of(obj_a):
            for pb in self._endpoints_of(obj_b):
                if math.hypot(pa.x - pb.x, pa.y - pb.y) < self.SNAP_TOL:
                    return pa
        return None

    def _all_items(self) -> list[str]:
        """Scene 内の全図形のコンボラベルリストを返す。

        タイプ別にグループ化してニックネーム順にソートする。
        先頭に "(なし)" を含む。

        Returns
        -------
        list[str]
            順序: 直線 → 線分 → 円 → 円弧 → クロソイド。
        """
        lines_items = sorted([
            f"{self.scene.display_name(ln.id,'直線')} [直線#{ln.id}]"
            for ln in self.scene.lines])
        seg_items = sorted([
            f"線分#{seg.id}"
            f" (直線:{self.scene.display_name(ln.id,'直線')})"
            f" [線分#{seg.id}]"
            for ln in self.scene.lines for seg in ln.segments])
        circle_items = sorted([
            f"{self.scene.display_name(ci.id,'円')} [円#{ci.id}]"
            for ci in self.scene.circles])
        arc_items = sorted([
            f"円弧#{arc.id}"
            f" (円:{self.scene.display_name(ci.id,'円')})"
            f" [円弧#{arc.id}]"
            for ci in self.scene.circles for arc in ci.arcs])
        clothoid_items = sorted([
            f"{self.scene.display_name(clo.id,'クロソイド')}"
            f" [クロソイド#{clo.id}]"
            for clo in self.scene.clothoids])
        return (["(なし)"] + lines_items + seg_items
                + circle_items + arc_items + clothoid_items)

    def _compute_next_forward(self, prev_obj, prev_is_fwd, next_obj) -> bool:
        """前の図形の出口接線と次の図形の入口方向から [順]/[逆] ラベルを判定する。

        コンボボックスの高優先候補に付ける ``[順]``/``[逆]`` ラベルの決定に使う。

        Parameters
        ----------
        prev_obj : Segment or Arc or Clothoid
            前の選択図形。
        prev_is_fwd : bool
            前の図形を正順（True）/ 逆順（False）で通過したか。
        next_obj : Segment or Arc or Clothoid
            次の選択候補図形。

        Returns
        -------
        bool
            True のとき next_obj を正順（[順]）で通過、
            False のとき逆順（[逆]）で通過すると判定する。

        Notes
        -----
        前の図形の出口接線 exit_tan と next_obj の共有点側入口方向 entry_tan の
        内積を計算し、内積 >= 0 のとき正順（スムーズ接続）、< 0 のとき逆順とみなす。
        """

        prev_pts = self._endpoints_of(prev_obj)
        next_pts = self._endpoints_of(next_obj)
        if not prev_pts or not next_pts:
            return True

        # 前の図形の出口接線
        exit_pt = prev_pts[-1] if prev_is_fwd else prev_pts[0]
        exit_tan = self._tangent_at(prev_obj, at_end=prev_is_fwd)
        if not prev_is_fwd:
            exit_tan = (-exit_tan[0], -exit_tan[1])

        # 共有点 = 次の図形の始点側か終点側か
        d_start = math.hypot(
            exit_pt.x - next_pts[0].x, exit_pt.y - next_pts[0].y)
        d_end = math.hypot(
            exit_pt.x - next_pts[-1].x, exit_pt.y - next_pts[-1].y)
        connect_at_start = d_start < d_end

        # 次の図形の「共有点→近傍点」ベクトル
        entry_tan = self._entry_tangent(next_obj, connect_at_start)
        if entry_tan is None:
            return True

        dot = exit_tan[0] * entry_tan[0] + exit_tan[1] * entry_tan[1]
        # exit_tan: 前の図形の進行方向（出口での接線）
        # entry_tan: 次の図形の「共有点→近傍点」方向
        # dot > 0 → 同方向（前の図形の向きと次の図形の向きが一致）= [順]
        # dot < 0 → 逆方向（次の図形が逆向き）= [逆]
        return dot >= 0

    def _tangent_at(self, obj, at_end: bool) -> tuple:
        """図形端点の接線単位ベクトルを返す（models.tangent_at への委譲）。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid
            接線を求める図形。
        at_end : bool
            False で始点側、True で終点側。

        Returns
        -------
        tuple[float, float]
            単位接線ベクトル (dx, dy)。
        """
        return tangent_at(obj, at_end)

    def _entry_tangent(self, obj, connect_at_start: bool) -> tuple:
        """共有端点→近傍点方向の単位ベクトルを返す（models.entry_tangent への委譲）。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid
            対象の図形。
        connect_at_start : bool
            True のとき共有端点が始点側。

        Returns
        -------
        tuple[float, float] or None
            単位ベクトル。取得不可のとき None。
        """
        return entry_tangent(obj, connect_at_start)

    def _next_is_forward(self, prev_obj, prev_is_fwd, next_obj) -> bool:
        """prev_obj → next_obj でチェーンを進むとき next_obj の通過方向を返す。

        ``_refresh_nick_combos`` が ``is_forward`` 配列を構築する際に使う。
        ``_compute_next_forward`` と異なり接線内積ではなく純粋な端点位置で判定する。

        Parameters
        ----------
        prev_obj : Segment or Arc or Clothoid
            前の選択図形。
        prev_is_fwd : bool
            前の図形を正順（True）/ 逆順（False）で通過したか（現メソッドでは未使用）。
        next_obj : Segment or Arc or Clothoid
            次の選択候補図形。

        Returns
        -------
        bool
            共有点が next_obj の始点側のとき True（正順）、終点側のとき False（逆順）。
        """
        prev_pts = self._endpoints_of(prev_obj)
        next_pts = self._endpoints_of(next_obj)
        if not prev_pts or not next_pts:
            return True
        exit_pt = prev_pts[-1] if prev_is_fwd else prev_pts[0]
        d_start = math.hypot(
            exit_pt.x - next_pts[0].x, exit_pt.y - next_pts[0].y)
        d_end = math.hypot(
            exit_pt.x - next_pts[-1].x, exit_pt.y - next_pts[-1].y)
        return d_start < d_end   # 始点で接続 → 正順(True)

    def _refresh_nick_combos(self):
        """全コンボボックスの選択肢を再構築する。

        先頭コンボは全図形を表示し、2 つ目以降は隣接候補を先頭に
        [順]/[逆] ラベル付きで表示する。選択中テキストをプレフィックス変化を
        考慮して可能な限り復元する。
        """
        all_items = self._all_items()
        selected_objs = [self._find_by_nick_label(cb.currentText())
                         for cb in self._nick_combos]

        # is_forward を追跡（チェーン方向の管理）
        is_forward = [True] * len(self._nick_combos)
        for i in range(1, len(selected_objs)):
            prev, cur = selected_objs[i - 1], selected_objs[i]
            if prev is None or cur is None:
                break
            is_forward[i] = self._next_is_forward(prev, is_forward[i - 1], cur)

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
                        adj = self._adjacent_from_obj(
                            prev_obj, excludes=selected_objs)
                    else:
                        prev_pts = self._endpoints_of(prev_obj)
                        exit_pt = (
                            prev_pts[-1] if is_forward[i - 1]
                            else prev_pts[0])
                        adj = self._adjacent_from_pt(
                            exit_pt, excludes=selected_objs,
                            prev_obj=prev_obj)
                    cb.addItem("(なし)")
                    self._fill_adjacent_items(
                        cb, adj, prev_obj, is_forward[i - 1], is_2nd=(i == 1))
                    if adj:
                        cb.insertSeparator(cb.count())
                    for item in all_items:
                        cb.addItem(item)

            # 現在の選択を復元（[順]/[逆] プレフィックス・距離文字列も考慮）
            import re as _re
            base = cur_text
            for prefix in ("[順] ", "[逆] "):
                if base.startswith(prefix):
                    base = base[len(prefix):]
                    break
            # 末尾の距離文字列を除去
            base = _re.sub(r'\s+[\d.]+\s*m$', '', base)
            found = -1
            for search in [cur_text, "[順] " + base, "[逆] " + base, base]:
                found = cb.findText(search)
                if found >= 0:
                    break
            # 距離付きラベルでの照合（_find_by_nick_label を使う）
            if found < 0:
                target = self._find_by_nick_label(cur_text)
                if target is not None:
                    for j in range(cb.count()):
                        t = cb.itemText(j)
                        if t and self._find_by_nick_label(t) is target:
                            found = j
                            break
            cb.setCurrentIndex(found if found >= 0 else 0)
            cb.blockSignals(False)

    def _fill_adjacent_items(
            self, cb, adj, prev_obj, prev_is_fwd, is_2nd: bool):
        """隣接候補リストをコンボボックスに追加する。

        高優先候補を追加した後、道なり条件を満たす場合は
        ``[道なり] <元の選択肢>`` アイテムも追加する。

        **道なり条件**:

        * 高優先候補が 1 件 → その候補の直後に ``[道なり]`` 版を追加。
        * 高優先候補が複数件で ``[順]`` ラベルが 1 件のみ
          → その ``[順]`` 候補の直後に ``[道なり]`` 版を追加。

        ``[道なり]`` アイテムが選ばれると :meth:`_on_combo_changed` が
        連鎖処理（:meth:`_road_follow_from`）を呼び出す。

        Parameters
        ----------
        cb : QComboBox
            追加先のコンボボックス。
        adj : list[tuple]
            ``(cand, is_forward, distance)`` の隣接候補リスト。
        prev_obj : Segment or Arc or Clothoid
            前のコンボで選択された図形。
        prev_is_fwd : bool
            前の図形をどちらの向きで通過するか。
        is_2nd : bool
            True のとき 2 つ目コンボ用ロジック（_prev_is_fwd_for_adj を使う）。
        """
        show_dir = len(adj) >= 2
        labels = []   # [(label_text, is_road_follow_candidate), ...]

        for item in adj:
            cand, _, dist = item[0], item[1], item[2] if len(item) > 2 else 0.0
            base_label = self._label_for_obj(cand)
            if not base_label:
                continue
            dist_str = f"  {dist:.3f} m"
            if show_dir:
                pef = (self._prev_is_fwd_for_adj(prev_obj, cand)
                       if is_2nd else prev_is_fwd)
                is_fwd = self._compute_next_forward(prev_obj, pef, cand)
                prefix = "[順] " if is_fwd else "[逆] "
                labels.append((prefix + base_label + dist_str, is_fwd))
            else:
                labels.append((base_label + dist_str, True))

        # 高優先候補を追加
        for label, _ in labels:
            cb.addItem(label)

        # 道なり条件を判定して [道なり] アイテムを追加
        road_follow_label = None
        if len(labels) == 1:
            # 候補が1件 → その直後に [道なり] 版
            road_follow_label = "[道なり] " + labels[0][0]
        elif len(labels) > 1:
            # 複数候補で [順] が1件のみ
            fwd_labels = [(ln, f) for ln, f in labels if f]
            if len(fwd_labels) == 1:
                road_follow_label = "[道なり] " + fwd_labels[0][0]

        if road_follow_label:
            cb.addItem(road_follow_label)

    def _prev_is_fwd_for_adj(self, prev_obj, cand) -> bool:
        """2 つ目コンボ専用。cand が prev_obj のどちらの端点で接続しているかを返す。

        cand の端点が prev_obj の終点（pts[-1]）に近ければ True（正順で通過）、
        始点（pts[0]）に近ければ False（逆順で通過）。
        どちらにも一致しない場合は True を返す。

        Returns
        -------
        bool
            prev_obj を正順（True）で通過してきたか、逆順（False）か。
        """
        prev_pts = self._endpoints_of(prev_obj)
        cand_pts = self._endpoints_of(cand)
        if not prev_pts or not cand_pts:
            return True

        end_pt = prev_pts[-1]   # prev_obj の終点
        start_pt = prev_pts[0]    # prev_obj の始点

        # cand の端点が prev_obj の終点に近い → 正順
        for cp in cand_pts:
            if math.hypot(cp.x - end_pt.x, cp.y - end_pt.y) < self.SNAP_TOL:
                return True

        # cand の端点が prev_obj の始点に近い → 逆順
        for cp in cand_pts:
            if (math.hypot(cp.x - start_pt.x, cp.y - start_pt.y)
                    < self.SNAP_TOL):
                return False

        # Clothoid の line_pt/circle_pt が prev_obj に接続している場合も考慮
        if isinstance(prev_obj, Clothoid) and prev_obj.is_valid:
            if prev_obj._circle_pt:
                for cp in cand_pts:
                    if (math.hypot(
                            cp.x - prev_obj._circle_pt.x,
                            cp.y - prev_obj._circle_pt.y)
                            < self.SNAP_TOL):
                        return True   # circle_pt 側 = 終点 = 正順で通過

        # prev_obj が Arc で cand が Clothoid の場合
        if (isinstance(cand, Clothoid) and cand.is_valid
                and isinstance(prev_obj, Arc)):
            if cand._circle_pt:
                if math.hypot(cand._circle_pt.x - end_pt.x,
                              cand._circle_pt.y - end_pt.y) < self.SNAP_TOL:
                    return True
                if math.hypot(cand._circle_pt.x - start_pt.x,
                              cand._circle_pt.y - start_pt.y) < self.SNAP_TOL:
                    return False

        return True  # デフォルト

    def _adjacent_from_obj(self, obj, excludes=None) -> list:
        """obj の全端点に隣接する図形をすべて返す（2 つ目のコンボ用）。

        ``_refresh_nick_combos`` が 2 つ目コンボの高優先候補を生成する際に呼ばれる。
        3 つ目以降のコンボでは出口端点を絞り込んだ :meth:`_adjacent_from_pt` を使う。

        Parameters
        ----------
        obj : Segment or Arc or Clothoid
            基準となる図形。
        excludes : list, optional
            除外するオブジェクトのリスト（選択済み図形を除くために使う）。

        Returns
        -------
        list[tuple[object, bool]]
            ``(cand, is_forward)`` の重複なしリスト。
            ``is_forward=True``: cand の始点で接続（正順）、False: 終点で接続（逆順）。

        Notes
        -----
        以下を隣接とみなす:

        * 同じ直線上で端点を共有する線分（同一親 Line）
        * 同じ円上で端点を共有する円弧（同一親 Circle）
        * obj が接点（_line_pt / _circle_pt）であるクロソイド
        * Arc の端点に _circle_pt で接続するクロソイド
        * Segment の _line_pt に接するクロソイド（直線内部接点を含む）
        """
        exclude_set = (
            set(id(e) for e in excludes if e is not None)
            if excludes else set())
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
            for cand, fwd, *_ in adj:
                add(cand, fwd)

        # obj が Clothoid の場合、接点に接する線分・円弧を追加で探す
        if isinstance(obj, Clothoid) and obj.is_valid:
            if obj._line_pt:
                adj2 = self._adjacent_from_pt(
                    obj._line_pt, excludes=excludes, prev_obj=obj)
                for cand, fwd, *_ in adj2:
                    add(cand, fwd)
            if obj._circle_pt:
                adj3 = self._adjacent_from_pt(
                    obj._circle_pt, excludes=excludes, prev_obj=obj)
                for cand, fwd, *_ in adj3:
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
                        if (math.hypot(pt.x - cp.x, pt.y - cp.y)
                                < self.SNAP_TOL):
                            # line_pt側=True, circle_pt側=False
                            fwd = (cp is clo_pts[0])
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
        """指定座標 pt に隣接する図形を ADJ_TOL で厳密に判定して返す。

        高優先候補の選択に使う。SNAP_TOL(1.0m) より厳密な ADJ_TOL(0.001m) で
        端点距離を判定する。

        **絞り込みルール（親図形が異なる場合）**:

        * クロソイド接点 / 折れ線接続 / オフセット拘束で接点（off=0）のみを含める。
        * スムーズ接続や接点でないオフセット接続は除外する。

        **同一親の複数候補**: 同一親図形の候補が複数ある場合、
        最も pt に近いもの（各方向で1つ）のみを残す。

        Parameters
        ----------
        pt : Vec2
            基点となる座標。
        excludes : list, optional
            除外するオブジェクトのリスト（選択済み全図形）。
        prev_obj : Segment or Arc or Clothoid, optional
            前の選択図形（クロソイドの line_pt 判定に使う）。

        Returns
        -------
        list[tuple[object, bool, float]]
            ``(cand, is_forward, distance)`` のリスト。
            ``is_forward=True``: cand の始点で接続（正順）。
            ``distance``: pt と接続端点の距離 [m]。
        """
        exclude_set = (
            set(id(e) for e in excludes if e is not None)
            if excludes else set())
        result = []

        all_elems = []
        for ln in self.scene.lines:
            all_elems.extend(ln.segments)
        for ci in self.scene.circles:
            all_elems.extend(ci.arcs)
        all_elems.extend(self.scene.clothoids)

        # ── 端点距離 ADJ_TOL での一次候補収集 ──────────────────────────
        raw_candidates = []   # (cand, is_forward, distance)
        for cand in all_elems:
            if id(cand) in exclude_set:
                continue
            cand_pts = self._endpoints_of(cand)
            if len(cand_pts) < 2:
                continue
            d_start = math.hypot(pt.x - cand_pts[0].x, pt.y - cand_pts[0].y)
            d_end = math.hypot(pt.x - cand_pts[-1].x, pt.y - cand_pts[-1].y)
            if d_start < self.ADJ_TOL:
                raw_candidates.append((cand, True, d_start))
            elif d_end < self.ADJ_TOL:
                raw_candidates.append((cand, False, d_end))

        # クロソイドの _line_pt が線分の内部点の場合も収集
        if (prev_obj is not None and isinstance(prev_obj, Clothoid)
                and prev_obj._line_pt is not None
                and math.hypot(pt.x - prev_obj._line_pt.x,
                               pt.y - prev_obj._line_pt.y) < self.ADJ_TOL):
            clo_line = prev_obj.line
            t = clo_line.project_t(prev_obj._line_pt)
            for seg in clo_line.segments:
                if id(seg) in exclude_set:
                    continue
                if seg.t_start - 1e-6 <= t <= seg.t_end + 1e-6:
                    d = math.hypot(pt.x - prev_obj._line_pt.x,
                                   pt.y - prev_obj._line_pt.y)
                    if abs(t - seg.t_start) < 1e-4:
                        raw_candidates.append((seg, True, d))
                    elif abs(t - seg.t_end) < 1e-4:
                        raw_candidates.append((seg, False, d))
                    else:
                        raw_candidates.append((seg, True, d))
                        raw_candidates.append((seg, False, d))

        # ── 親図形が異なる場合の絞り込み ─────────────────────────────
        prev_parent = self._parent_of(
            prev_obj) if prev_obj is not None else None

        filtered = []
        for cand, fwd, dist in raw_candidates:
            cand_parent = self._parent_of(cand)
            same_parent = (prev_obj is not None
                           and prev_parent is not None
                           and cand_parent is not None
                           and prev_parent is cand_parent)
            if same_parent:
                # 同一親 → そのまま通す（後でフィルタ）
                filtered.append((cand, fwd, dist, True))
            elif prev_obj is None:
                # 先頭コンボ（prev なし）→ 全て通す
                filtered.append((cand, fwd, dist, False))
            else:
                # 親が異なる → 直接接点チェック
                if self._directly_connected(prev_obj, cand):
                    filtered.append((cand, fwd, dist, False))

        # ── 同一親・同一方向で最近傍1つだけ残す ─────────────────────
        # prev_parent ごと・fwd ごとに最小 dist のものを採用
        same_parent_best = {}   # key: (id(parent), fwd) → (cand, dist)
        others = []
        for cand, fwd, dist, is_same in filtered:
            if is_same:
                cp = self._parent_of(cand)
                key = (id(cp), fwd)
                if (key not in same_parent_best
                        or dist < same_parent_best[key][1]):
                    same_parent_best[key] = (cand, dist, fwd)
            else:
                others.append((cand, fwd, dist))

        # 同一親の最近傍を結果に追加
        final = []
        for (pid, fwd), (cand, dist, _) in same_parent_best.items():
            final.append((cand, fwd, dist))
        final.extend(others)

        # 重複除去してソート（距離順）
        seen_ids = set()
        result = []
        for cand, fwd, dist in sorted(final, key=lambda x: x[2]):
            if id(cand) not in seen_ids:
                result.append((cand, fwd, dist))
                seen_ids.add(id(cand))

        return result

    def set_canvas(self, canvas) -> None:
        """キャンバスへの直接参照を設定する。

        シグナル経由の描画更新では遅延が生じる場合があるため、
        オフセット変更時など即時更新が必要な箇所でキャンバスを
        直接呼び出すために使う。``MainWindow._connect_signals`` から呼ばれる。
        """
        self._canvas_ref = canvas

    def _canvas_update(self) -> None:
        """キャンバスを即時再描画する。

        ``_canvas_ref`` が設定されていれば ``repaint()`` を呼び出す。
        未設定の場合は ``scene_changed`` シグナルで代替する。
        """
        if self._canvas_ref is not None:
            self._canvas_ref.repaint()
        else:
            self.scene_changed.emit()

    def _redraw(self):
        """全クロソイドを compute() で再計算してキャンバスを即時再描画する。

        数値入力や snap 設定変更後にクロソイドの状態が不整合になった場合の
        手動修復用として「再描画」ボタンから呼ばれる。
        """
        for clo in self.scene.clothoids:
            clo.compute()
        self._canvas_update()

    def _delete_selected_objs(self):
        """コンボボックスで選択中の図形を QMessageBox 確認後に削除する。

        確認ダイアログでキャンセルされた場合は何もしない。
        削除は request_delete シグナル経由で MainWindow に委譲する。
        """
        from PySide6.QtWidgets import QMessageBox
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
        """コンボボックスの現在の選択を Canvas の選択状態に反映する。

        各コンボで選択中の図形を収集し ``request_select`` シグナルで
        MainWindow に委譲する。「選択を適用」ボタンから呼ばれる。
        """
        selected = []
        for cb in self._nick_combos:
            txt = cb.currentText()
            obj = self._find_by_nick_label(txt)
            if obj is not None:
                selected.append(obj)
        self.request_select.emit(selected)

    def _find_by_nick_label(self, label: str) -> Optional[object]:
        """コンボラベル文字列から対応する図形オブジェクトを逆引きする。

        ``[道なり] `` / ``[順] `` / ``[逆] `` プレフィックスと末尾の距離文字列
        （例: ``  0.001 m``）を除去してから Scene 内の全図形と照合する。

        Parameters
        ----------
        label : str
            コンボボックスに表示されているラベル文字列。

        Returns
        -------
        Line or Segment or Circle or Arc or Clothoid or None
            一致する図形。見つからない場合は None。
        """
        # [道なり] / [順] / [逆] プレフィックスを除去
        for prefix in ("[道なり] ", "[順] ", "[逆] "):
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        # 末尾の距離文字列（例: "  0.001 m"）を除去
        import re as _re
        label = _re.sub(r'\s+[\d.]+\s*m$', '', label)
        for ln in self.scene.lines:
            ln_label = (
                f"{self.scene.display_name(ln.id, '直線')} [直線#{ln.id}]")
            if ln_label == label:
                return ln
            for seg in ln.segments:
                seg_label = (
                    f"線分#{seg.id}"
                    f" (直線:{self.scene.display_name(ln.id,'直線')})"
                    f" [線分#{seg.id}]")
                if seg_label == label:
                    return seg
        for ci in self.scene.circles:
            ci_label = (
                f"{self.scene.display_name(ci.id, '円')} [円#{ci.id}]")
            if ci_label == label:
                return ci
            for arc in ci.arcs:
                arc_label = (
                    f"円弧#{arc.id}"
                    f" (円:{self.scene.display_name(ci.id,'円')})"
                    f" [円弧#{arc.id}]")
                if arc_label == label:
                    return arc
        for clo in self.scene.clothoids:
            clo_label = (
                f"{self.scene.display_name(clo.id, 'クロソイド')}"
                f" [クロソイド#{clo.id}]")
            if clo_label == label:
                return clo
        return None

    # ─── 選択変更時 ──────────────────────────────────────────
    def update_selection(self, selected: list, scene: Scene):
        """外部（Canvas）から選択変更を受け取り、パネル全体を更新する。

        処理順は ``_sync_combos_to_selection`` → ``_refresh_nick_combos``
        → ``_rebuild_props`` の順で行う。先にコンボへ選択図形を設定してから
        ``_refresh_nick_combos`` を呼ぶことで、設計画面でのクリック選択でも
        右パネルのコンボ操作でも「手段を問わず 1 個目のコンボが設定された
        直後に 2 個目の高優先候補が更新される」要件を満たす。

        Parameters
        ----------
        selected : list
            新しく選択された図形オブジェクトのリスト。
        scene : Scene
            現在の Scene オブジェクト。
        """
        self.scene = scene
        self._selected = selected
        self._sync_combos_to_selection(selected)  # まず選択図形をコンボに設定
        self._refresh_nick_combos()               # 設定後に次コンボの選択肢を更新
        self._trim_trailing_none_combos()         # 末尾の余分な（なし）を除去
        self._rebuild_props()

    def _sync_combos_to_selection(self, selected: list):
        """Canvas の選択変更をコンボボックスに反映する。

        コンボ数が選択図形数より少ない場合は _add_nick_combo で補充する。
        ラベル検索は [順]/[逆] プレフィックスを考慮する。

        Parameters
        ----------
        selected : list
            Canvas で選択中の図形リスト。
        """
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
                # 距離付きラベル（例: "  0.000 m"）にも対応するため
                # findText が失敗したら全アイテムを走査して _find_by_nick_label で比較
                idx = cb.findText(label)
                if idx < 0:
                    for prefix in ("[順] ", "[逆] "):
                        idx = cb.findText(prefix + label)
                        if idx >= 0:
                            break
                if idx < 0:
                    # 距離付きラベルの可能性: 全アイテムを _find_by_nick_label で照合
                    target = self._find_by_nick_label(label)
                    if target is not None:
                        for j in range(cb.count()):
                            t = cb.itemText(j)
                            if t and self._find_by_nick_label(t) is target:
                                idx = j
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
        """図形オブジェクトからコンボラベル文字列を生成する。

        Parameters
        ----------
        obj : Line or Segment or Circle or Arc or Clothoid or any
            ラベルを生成する図形。

        Returns
        -------
        str
            "{ニックネーム} [種別#{id}]" 形式。非対応型は空文字。
        """
        if isinstance(obj, Line):
            return (
                f"{self.scene.display_name(obj.id, '直線')}"
                f" [直線#{obj.id}]")
        if isinstance(obj, Segment):
            ln = obj.line
            return (
                f"線分#{obj.id}"
                f" (直線:{self.scene.display_name(ln.id,'直線')})"
                f" [線分#{obj.id}]")
        if isinstance(obj, Circle):
            return (
                f"{self.scene.display_name(obj.id, '円')}"
                f" [円#{obj.id}]")
        if isinstance(obj, Arc):
            ci = obj.circle
            return (
                f"円弧#{obj.id}"
                f" (円:{self.scene.display_name(ci.id,'円')})"
                f" [円弧#{obj.id}]")
        if isinstance(obj, Clothoid):
            return (
                f"{self.scene.display_name(obj.id, 'クロソイド')}"
                f" [クロソイド#{obj.id}]")
        return ""

    # ─── ラバーバンド複数選択操作 ─────────────────────────────
    def _is_rubber_select(self, sel) -> bool:
        """選択リストに Segment/Arc とその親 Line/Circle が共存するか判定する。

        ラバーバンド選択では線分→親直線も一緒に選択される仕様のため、
        この状態を検出して複数選択操作パネルを表示するかの判断に使う。
        """
        selected_line_ids = {id(o) for o in sel if isinstance(o, Line)}
        selected_circle_ids = {id(o) for o in sel if isinstance(o, Circle)}
        for o in sel:
            if isinstance(o, Segment) and o.line is not None:
                if id(o.line) in selected_line_ids:
                    return True
            if isinstance(o, Arc) and o.circle is not None:
                if id(o.circle) in selected_circle_ids:
                    return True
        return False

    def _selection_bbox_center(self, effective) -> Vec2:
        """有効図形セットの AABB 中心座標を返す。

        回転・拡大縮小の基準点として使う。

        Parameters
        ----------
        effective : list
            :func:`models.effective_set` で得た図形リスト。

        Returns
        -------
        Vec2
            AABB の中心。有効点がなければ原点 (0, 0)。
        """
        pts = []
        for obj in effective:
            if isinstance(obj, Line):
                for seg in obj.segments:
                    s, e = seg.start, seg.end
                    pts += [(s.x, s.y), (e.x, e.y)]
                if not obj.segments:
                    pts += [(obj.ref_start.x, obj.ref_start.y),
                            (obj.ref_end.x, obj.ref_end.y)]
            elif isinstance(obj, Circle):
                r = obj.radius
                cx, cy = obj.center.x, obj.center.y
                pts += [(cx - r, cy), (cx + r, cy),
                        (cx, cy - r), (cx, cy + r)]
            elif isinstance(obj, Clothoid) and obj.points:
                pts += [(p.x, p.y) for p in obj.points]
        if not pts:
            return Vec2(0, 0)
        xs, ys = zip(*pts)
        return Vec2((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def _recompute_clothoids(self, moved_ids: set):
        """移動した Line/Circle に関連するクロソイドを再計算する。

        Parameters
        ----------
        moved_ids : set[int]
            ``id(obj)`` の集合（移動・変形した Line または Circle）。
        """
        for clo in self.scene.clothoids:
            if id(clo.line) in moved_ids or id(clo.circle) in moved_ids:
                clo.compute()

    def _do_translate(self, dx: float, dy: float):
        """選択図形を (dx, dy) 平行移動する。

        操作後は Undo スタックを push し ``scene_changed`` を emit する。

        Parameters
        ----------
        dx, dy : float
            移動量 [m]。
        """
        effective = effective_set(self._selected)
        self.request_push_undo.emit()
        moved_ids: set = set()
        for obj in effective:
            if isinstance(obj, Line):
                obj.ref_start = Vec2(obj.ref_start.x + dx,
                                     obj.ref_start.y + dy)
                obj.ref_end = Vec2(obj.ref_end.x + dx,
                                   obj.ref_end.y + dy)
                moved_ids.add(id(obj))
            elif isinstance(obj, Circle):
                obj.center = Vec2(obj.center.x + dx, obj.center.y + dy)
                moved_ids.add(id(obj))
        self._recompute_clothoids(moved_ids)
        self.scene_changed.emit()
        self._rebuild_props()

    def _do_rotate(self, angle_deg: float, use_bbox_center: bool):
        """選択図形を指定角度（度数）回転する。

        Parameters
        ----------
        angle_deg : float
            回転角 [°]（正 = 反時計回り）。
        use_bbox_center : bool
            True → AABB 中心を回転基準、False → 原点 (0, 0) を基準。
        """
        effective = effective_set(self._selected)
        center = (self._selection_bbox_center(effective)
                  if use_bbox_center else Vec2(0, 0))
        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        cx, cy = center.x, center.y

        def rot(v: Vec2) -> Vec2:
            dx_r = v.x - cx
            dy_r = v.y - cy
            return Vec2(cx + dx_r * cos_a - dy_r * sin_a,
                        cy + dx_r * sin_a + dy_r * cos_a)

        self.request_push_undo.emit()
        moved_ids: set = set()
        for obj in effective:
            if isinstance(obj, Line):
                obj.ref_start = rot(obj.ref_start)
                obj.ref_end = rot(obj.ref_end)
                moved_ids.add(id(obj))
            elif isinstance(obj, Circle):
                obj.center = rot(obj.center)
                for arc in obj.arcs:
                    arc.angle_start += angle_rad
                    arc.angle_end += angle_rad
                moved_ids.add(id(obj))
        self._recompute_clothoids(moved_ids)
        self.scene_changed.emit()
        self._rebuild_props()

    def _do_scale(self, factor: float, use_bbox_center: bool):
        """選択図形を均等拡大縮小する（Clothoid 保持のため XY 同率）。

        Parameters
        ----------
        factor : float
            倍率（0 以外の正数）。
        use_bbox_center : bool
            True → AABB 中心を基準、False → 原点 (0, 0) を基準。
        """
        if abs(factor) < 1e-9:
            return
        effective = effective_set(self._selected)
        center = (self._selection_bbox_center(effective)
                  if use_bbox_center else Vec2(0, 0))
        cx, cy = center.x, center.y

        def sc(v: Vec2) -> Vec2:
            return Vec2(cx + (v.x - cx) * factor,
                        cy + (v.y - cy) * factor)

        self.request_push_undo.emit()
        moved_ids: set = set()
        for obj in effective:
            if isinstance(obj, Line):
                obj.ref_start = sc(obj.ref_start)
                obj.ref_end = sc(obj.ref_end)
                moved_ids.add(id(obj))
            elif isinstance(obj, Circle):
                obj.center = sc(obj.center)
                obj.radius = obj.radius * factor
                moved_ids.add(id(obj))
        self._recompute_clothoids(moved_ids)
        self.scene_changed.emit()
        self._rebuild_props()

    def _do_copy(self):
        """選択図形を複製し、複製した図形だけを選択状態にする。

        複製後は元の選択を解除して複製物を ``request_select`` で選択する。
        Clothoid については、対応する Line/Circle が複製されていれば
        その複製物を参照するクロソイドを作成し、されていなければ
        元の Line/Circle を参照する。
        縦断線形情報（ElementProfile）も同時に複製する。
        """
        effective = effective_set(self._selected)
        self.request_push_undo.emit()
        id_map: dict = {}       # id(obj_py) → new_obj（Clothoid 解決用）
        elem_id_map: dict = {}  # 旧整数ID → 新整数ID（ElementProfile 複製用）
        new_objs: list = []
        clothoids_to_copy = [o for o in effective
                             if isinstance(o, Clothoid)]
        for obj in effective:
            if isinstance(obj, Clothoid):
                continue
            if isinstance(obj, Line):
                new_line = Line(
                    Vec2(obj.ref_start.x, obj.ref_start.y),
                    Vec2(obj.ref_end.x, obj.ref_end.y))
                new_line.id = new_id()
                for seg in obj.segments:
                    new_seg = Segment(new_line, seg.t_start, seg.t_end)
                    new_seg.id = new_id()
                    elem_id_map[seg.id] = new_seg.id
                    new_line.segments.append(new_seg)
                self.scene.add_line(new_line)
                id_map[id(obj)] = new_line
                new_objs.append(new_line)
            elif isinstance(obj, Circle):
                new_ci = Circle(
                    Vec2(obj.center.x, obj.center.y), obj.radius)
                new_ci.id = new_id()
                for arc in obj.arcs:
                    new_arc = Arc(new_ci, arc.angle_start, arc.angle_end)
                    new_arc.id = new_id()
                    elem_id_map[arc.id] = new_arc.id
                    new_ci.arcs.append(new_arc)
                self.scene.add_circle(new_ci)
                id_map[id(obj)] = new_ci
                new_objs.append(new_ci)
        for clo in clothoids_to_copy:
            new_line = id_map.get(id(clo.line), clo.line)
            new_ci = id_map.get(id(clo.circle), clo.circle)
            new_clo = Clothoid(new_line, new_ci,
                               reversed_flag=clo.reversed_flag,
                               snap_segment=clo.snap_segment,
                               snap_arc=clo.snap_arc)
            new_clo.id = new_id()
            elem_id_map[clo.id] = new_clo.id
            self.scene.add_clothoid(new_clo)
            new_objs.append(new_clo)
        # 縦断線形情報を複製
        self._copy_element_profiles(elem_id_map)
        self.scene_changed.emit()
        self.request_select.emit(new_objs)

    def _copy_element_profiles(self, elem_id_map: dict):
        """旧要素 ID → 新要素 ID のマッピングを使って ElementProfile を複製する。

        GradeLine・VerticalCurve もすべて新しい ID で複製し、
        GradeLine↔VerticalCurve の相互参照（next_curve/prev_curve および
        prev_line_id/next_line_id）も新しい ID 体系で再構築する。

        Parameters
        ----------
        elem_id_map : dict[int, int]
            旧 Segment/Arc/Clothoid の整数 ID → 新要素の整数 ID。
        """
        from vertical_profile import ElementProfile, GradeLine, VerticalCurve

        for ep in list(self.scene.element_profiles):
            if ep.element_id not in elem_id_map:
                continue

            # ── GradeLine を複製 ──────────────────────────────
            gl_id_map: dict = {}   # 旧 GradeLine.id → 新 GradeLine
            new_gls: list = []
            for gl in ep.grade_lines:
                new_gl = GradeLine()
                new_gl.id = new_id()
                new_gl.dist_start = gl.dist_start
                new_gl.elev_start = gl.elev_start
                new_gl.dist_end = gl.dist_end
                new_gl.elev_end = gl.elev_end
                gl_id_map[gl.id] = new_gl
                new_gls.append(new_gl)

            # ── VerticalCurve を複製 ──────────────────────────
            vc_id_map: dict = {}   # 旧 VerticalCurve.id → 新 VerticalCurve
            new_vcs: list = []
            for vc in ep.vertical_curves:
                new_vc = VerticalCurve()
                new_vc.id = new_id()
                new_vc.pvi_dist = vc.pvi_dist
                new_vc.pvi_elev = vc.pvi_elev
                new_vc.g1 = vc.g1
                new_vc.g2 = vc.g2
                new_vc.length = vc.length
                # prev/next_line_id を新 GradeLine の ID に更新
                pgl = gl_id_map.get(vc.prev_line_id)
                ngl = gl_id_map.get(vc.next_line_id)
                new_vc.prev_line_id = pgl.id if pgl else -1
                new_vc.next_line_id = ngl.id if ngl else -1
                vc_id_map[vc.id] = new_vc
                new_vcs.append(new_vc)

            # ── GradeLine の next/prev_curve 参照を再構築 ────
            for gl in ep.grade_lines:
                new_gl = gl_id_map[gl.id]
                if gl.next_curve is not None:
                    new_gl.next_curve = vc_id_map.get(gl.next_curve.id)
                if gl.prev_curve is not None:
                    new_gl.prev_curve = vc_id_map.get(gl.prev_curve.id)

            # ── ElementProfile 本体を複製 ────────────────────
            new_ep = ElementProfile()
            new_ep.id = new_id()
            new_ep.element_id = elem_id_map[ep.element_id]
            new_ep.element_type = ep.element_type
            new_ep.plan_length = ep.plan_length
            new_ep.reversed_flag = ep.reversed_flag
            new_ep.elev_start = ep.elev_start
            new_ep.elev_end = ep.elev_end
            new_ep.grade_lines = new_gls
            new_ep.vertical_curves = new_vcs
            self.scene.element_profiles.append(new_ep)

    def _clear_props(self):
        """プロパティレイアウトの全ウィジェットを即時削除する。

        ``deleteLater()`` はイベントループが回るまで実際の削除が実行されないため、
        直後の ``_rebuild_props`` で ``findChildren`` が古いウィジェットを返す問題がある。
        ``setParent(None)`` でツリーから切り離してから ``deleteLater()`` を呼ぶことで
        ``findChildren`` の検索対象から即座に除外される。
        """
        while self._prop_layout.count():
            item = self._prop_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_props(self):
        """プロパティパネルの内容を選択状態に合わせて一から再構築する。

        :meth:`_clear_props` で既存ウィジェットをすべて削除してから再生成する。
        差分更新は行わない（状態管理の複雑さを避けるためのトレードオフ）。

        選択図形の組み合わせに応じて呼ぶメソッドを切り替える:

        * 0 個: 「図形を選択してください」ラベルを表示
        * 1 個: :meth:`_build_single`
        * 2 個 (Segment + Segment 同一直線): :meth:`_build_two_segments`
        * 2 個 (Arc + Arc 同一円): :meth:`_build_two_arcs`
        * 2 個 (Line + Line): :meth:`_build_two_lines`
        * 2 個 (Line + Circle): :meth:`_build_line_circle`
        * 2 個 その他: 各図形に :meth:`_build_single` を呼ぶ
        * 3 個 (Circle + Circle + Line): :meth:`_build_offset_constraint`
        * 3 個 (Line + Line + Circle): :meth:`_build_two_line_offset_constraint`
        * 3 個以上その他: 図形数とニックネーム一覧を表示
        """
        self._clear_props()
        sel = self._selected
        n = len(sel)

        if n == 0:
            self._prop_layout.addWidget(QLabel("図形を選択してください"))
            return

        if n == 1:
            self._build_single(sel[0])
            return

        # ── 2図形選択 ────────────────────────────────────────
        if n == 2:
            # ラバーバンド選択（Seg+親Line や Arc+親Circle が混在）
            if self._is_rubber_select(sel):
                self._build_multi_select(sel)
                return
            a, b = sel
            # Segment は親 Line として扱う (接続操作のため)
            la = a.line if isinstance(a, Segment) else a
            # 線分 + 線分
            if (isinstance(a, Segment) and isinstance(b, Segment)
                    and a is not b):
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
        # Segment→Line / Arc→Circle に昇格して重複除去した有効オブジェクト列
        def _to_base(o):
            if isinstance(o, Segment):
                return o.line
            if isinstance(o, Arc):
                return o.circle
            return o

        eff_objs = list(dict.fromkeys(_to_base(o) for o in sel))
        eff_circles = [o for o in eff_objs if isinstance(o, Circle)]
        eff_lines = [o for o in eff_objs if isinstance(o, Line)]

        # 2円 + 1直線 → OffsetConstraint
        if (len(eff_circles) == 2
                and len(eff_lines) == 1 and len(eff_objs) == 3):
            self._build_offset_constraint(
                eff_lines[0], eff_circles[0], eff_circles[1])
            return

        # 1円 + 2直線 → TwoLineOffsetConstraint
        if (len(eff_circles) == 1
                and len(eff_lines) == 2 and len(eff_objs) == 3):
            self._build_two_line_offset_constraint(
                eff_lines[0], eff_lines[1], eff_circles[0])
            return

        # ラバーバンド選択または一般的な複数選択 → 操作パネル
        self._build_multi_select(sel)
