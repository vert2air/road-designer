"""プロパティパネルの UI 構築メソッド群。

右パネル（``RightPanel``）に mixin として組み込まれる ``PropBuilderMixin``
クラスと、それが使用するユーティリティ関数・ウィジェットを定義する。

``PropBuilderMixin`` のメソッドは ``self.scene``・``self._prop_layout``・
``self.request_*`` シグナル等が存在することを前提とする。
"""
from __future__ import annotations
import math
import json as _json
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QDoubleSpinBox, QGroupBox, QFrame, QLineEdit,
    QCheckBox, QComboBox, QSizePolicy, QMenu, QApplication,
    QSpinBox,
)
from PySide6.QtCore import Qt
from models import (Vec2, Line, Segment, Circle, Arc, Clothoid, Scene)


# ── クリップボード: 始点/終点ペア ─────────────────────────────────────────
_CLIPBOARD_MIME = "application/x-road-designer-point-pair"


def _encode_point_pair(start, end) -> str:
    """始点・終点ペアを JSON 文字列にエンコードする。"""
    return _json.dumps({"sx": start.x, "sy": start.y,
                        "ex": end.x,   "ey": end.y})


def _decode_point_pair(text: str):
    """JSON 文字列から (start_Vec2, end_Vec2) を返す。None: 解析失敗。"""
    try:
        d = _json.loads(text)
        from models import Vec2
        return Vec2(d["sx"], d["sy"]), Vec2(d["ex"], d["ey"])
    except Exception:
        return None


def _clipboard_has_point_pair() -> bool:
    """クリップボードに始点/終点ペアが設定されているか判定する。"""
    cb = QApplication.clipboard()
    return _decode_point_pair(cb.text()) is not None


def _copy_point_pair(start, end) -> None:
    """始点・終点ペアをクリップボードにコピーする。"""
    QApplication.clipboard().setText(_encode_point_pair(start, end))


def _paste_point_pair():
    """クリップボードから (start_Vec2, end_Vec2) を取り出す。None: 失敗。"""
    return _decode_point_pair(QApplication.clipboard().text())


def _transform_pair(start, end, mode: str):
    """始点・終点ペアを変換して返す。

    Parameters
    ----------
    mode : str
        "rot90" / "rot180" / "rot270" / "flip_y" / "flip_x" /
        "flip_yx" / "flip_y_neg_x"
    """
    from models import Vec2
    import math

    def tr(v):
        x, y = v.x, v.y
        if mode == "rot90":
            return Vec2(-y, x)
        if mode == "rot180":
            return Vec2(-x, -y)
        if mode == "rot270":
            return Vec2(y, -x)
        if mode == "flip_y":     # y=0 で線対称
            return Vec2(x, -y)
        if mode == "flip_x":     # x=0 で線対称
            return Vec2(-x, y)
        if mode == "flip_yx":    # y=x で線対称
            return Vec2(y, x)
        if mode == "flip_y_neg_x":  # y=-x で線対称
            return Vec2(-y, -x)
        return Vec2(x, y)

    return tr(start), tr(end)


def _add_copy_paste_buttons(lay, get_start, get_end,
                             set_start, set_end,
                             on_change, push_undo):
    """Copy / Paste ボタン行を lay に追加するヘルパー。

    Parameters
    ----------
    lay : QVBoxLayout
        ボタンを追加するレイアウト。
    get_start : callable
        始点の Vec2 を返す。
    get_end : callable
        終点の Vec2 を返す。
    set_start : callable
        始点 Vec2 を設定する。
    set_end : callable
        終点 Vec2 を設定する。
    on_change : callable
        座標変更後に呼ぶコールバック（scene_changed 等）。
    push_undo : callable
        Undo スタックへの push を要求するコールバック。
    """
    from PySide6.QtCore import Qt

    row = QHBoxLayout()

    # ── Copy ─────────────────────────────────────────────────────
    btn_copy = QPushButton("⧉ Copy")
    btn_copy.setToolTip("始点・終点ペアをクリップボードにコピー")
    btn_copy.setMaximumWidth(80)

    def do_copy():
        _copy_point_pair(get_start(), get_end())

    btn_copy.clicked.connect(do_copy)

    # ── Paste ────────────────────────────────────────────────────
    btn_paste = QPushButton("⧈ Paste")
    btn_paste.setToolTip(
        "左クリック: そのままペースト\n"
        "右クリック: 回転・対称変換してペースト"
    )
    btn_paste.setMaximumWidth(80)

    _PASTE_MODES = [
        ("rot90",        "原点で 90° 回転してペースト"),
        ("rot180",       "原点で 180° 回転してペースト"),
        ("rot270",       "原点で -90° 回転してペースト"),
        ("flip_y",       "y=0 で線対称してペースト"),
        ("flip_x",       "x=0 で線対称してペースト"),
        ("flip_yx",      "y=x で線対称してペースト"),
        ("flip_y_neg_x", "y=-x で線対称してペースト"),
    ]

    def do_paste(mode=None):
        pair = _paste_point_pair()
        if pair is None:
            return
        s, e = pair
        if mode is not None:
            s, e = _transform_pair(s, e, mode)
        push_undo()
        set_start(s)
        set_end(e)
        on_change()

    def on_paste_left_click():
        do_paste(None)

    def on_paste_right_click(pos):
        menu = QMenu()
        for mode, label in _PASTE_MODES:
            act = menu.addAction(label)
            act.setData(mode)
        menu.addSeparator()
        menu.addAction("キャンセル")
        chosen = menu.exec(btn_paste.mapToGlobal(pos))
        if chosen and chosen.data() in [m for m, _ in _PASTE_MODES]:
            do_paste(chosen.data())

    btn_paste.clicked.connect(on_paste_left_click)
    btn_paste.setContextMenuPolicy(
        Qt.ContextMenuPolicy.CustomContextMenu)
    btn_paste.customContextMenuRequested.connect(on_paste_right_click)

    def refresh_paste_enabled():
        # btn_paste が既に C++ 側で破棄されていれば何もしない
        try:
            btn_paste.setEnabled(_clipboard_has_point_pair())
        except RuntimeError:
            pass

    cb = QApplication.clipboard()
    cb.dataChanged.connect(refresh_paste_enabled)

    # ウィジェット破棄時にシグナル接続を切断（RuntimeError の根本対策）
    btn_paste.destroyed.connect(lambda: cb.dataChanged.disconnect(refresh_paste_enabled))

    refresh_paste_enabled()

    row.addStretch()
    row.addWidget(btn_copy)
    row.addWidget(btn_paste)
    lay.addLayout(row)

class _FlexSpinBox(QDoubleSpinBox):
    """パネル幅に追従する QDoubleSpinBox。

    デフォルト実装の minimumSizeHint が約 120px を主張するため、
    右パネルで水平スクロールが発生する問題を防ぐためにオーバーライドする。
    """

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        from PySide6.QtCore import QSize
        return QSize(40, sh.height())

    def sizeHint(self):
        sh = super().sizeHint()
        from PySide6.QtCore import QSize
        return QSize(60, sh.height())


def _make_spinbox(val: float, lo: float = -1e6, hi: float = 1e6,
                  step: float = 0.1, decimals: int = 3) -> QDoubleSpinBox:
    """設定済みの _FlexSpinBox を生成して返すファクトリ関数。

    Parameters
    ----------
    val : float
        初期値。
    lo, hi : float, optional
        最小・最大値。
    step : float, optional
        単一ステップ量（デフォルト 0.1）。
    decimals : int, optional
        小数点以下桁数（デフォルト 3）。

    Returns
    -------
    QDoubleSpinBox
        設定済みのスピンボックス（実体は _FlexSpinBox）。
    """
    sb = _FlexSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(val)
    # 内側の QLineEdit の sizeHint(≈123px) が GroupBox 幅を押し広げないよう
    # 最大幅を設定して物理的にサイズを制限する
    sb.setMaximumWidth(120)
    return sb


def _separator() -> QFrame:
    """右パネル内の水平区切り線（HLine）を返す。"""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def _style_disabled(btn: QPushButton, disabled: bool):
    """ボタンの disabled 状態をスタイルで視覚的に明示する。

    Parameters
    ----------
    btn : QPushButton
        スタイルを適用するボタン。
    disabled : bool
        True のときグレーアウトスタイルを適用する。
    """
    if disabled:
        btn.setStyleSheet("color: #666666; background-color: #2a2a2a;")
    else:
        btn.setStyleSheet("")



class PropBuilderMixin:
    """``RightPanel`` に組み込む図形プロパティ UI ビルダー群。

    このクラスは単独では使用しない。``RightPanel(QWidget, PropBuilderMixin)``
    として多重継承し、``self.scene``・``self._prop_layout``・``self._selected``・
    ``self._block``・``self.request_*`` シグナル等を RightPanel 側から受け取る。
    """

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
        """対応する ElementProfile が存在すれば縦断情報を右パネルに追加する。

        表示内容: 平面長・始終端標高・GradeLine 一覧・VerticalCurve 一覧。
        ElementProfile が存在しない場合は何も表示しない。
        """
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
            # ニックネームを上段、ボタンを下段にして幅を節約
            lay.addWidget(QLabel(name))
            btn_row = QHBoxLayout()
            btn_sel = QPushButton("選択")
            btn_sel.setFixedWidth(44)
            btn_sel.clicked.connect(lambda _, r=rel: self.request_select.emit([r]))
            btn_add = QPushButton("選択追加")
            btn_add.setFixedWidth(66)
            btn_add.clicked.connect(lambda _, r=rel:
                                     self.request_select.emit(self._selected + [r]))
            btn_row.addStretch()
            btn_row.addWidget(btn_sel)
            btn_row.addWidget(btn_add)
            lay.addLayout(btn_row)
        self._prop_layout.addWidget(grp)

    def _build_line_props(self, ln: Line):
        """直線プロパティパネルを構築して ``_prop_layout`` に追加する。

        参照始点・参照終点の X/Y スピンボックスと方向角（読み取り専用）を表示する。
        各スピンボックスの初回変更時に ``request_push_undo`` を発行し、
        同一編集セッション中の連続変更は 1 手順として Undo に記録される。

        Parameters
        ----------
        ln : Line
            プロパティを表示・編集する直線。
        """
        grp = QGroupBox("直線プロパティ")
        lay = QVBoxLayout(grp)

        def add_vec2(label, get_fn, set_fn):
            """Vec2 入力フォーム（X/Y スピンボックス）を _prop_layout に追加する。

            Parameters
            ----------
            label : str
                グループラベル（例: "参照始点"）。
            get_fn : callable
                現在値を Vec2 で返すゲッター関数。
            set_fn : callable
                Vec2 を受け取るセッター関数。
            """
            lay.addWidget(QLabel(label))
            row = QHBoxLayout()
            sbx = _make_spinbox(get_fn().x)
            sby = _make_spinbox(get_fn().y)
            _undo_pushed = [False]
            def on_x(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
                old = get_fn()
                set_fn(Vec2(v, old.y))
                self.scene_changed.emit()
            def on_y(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
                old = get_fn()
                set_fn(Vec2(old.x, v))
                self.scene_changed.emit()
            sbx.valueChanged.connect(on_x)
            sby.valueChanged.connect(on_y)
            row_x = QHBoxLayout(); row_x.addWidget(QLabel("X:")); row_x.addWidget(sbx)
            row_y = QHBoxLayout(); row_y.addWidget(QLabel("Y:")); row_y.addWidget(sby)
            lay.addLayout(row_x)
            lay.addLayout(row_y)

        add_vec2("参照始点", lambda: ln.ref_start,
                 lambda v: setattr(ln, 'ref_start', v))
        add_vec2("参照終点", lambda: ln.ref_end,
                 lambda v: setattr(ln, 'ref_end', v))

        # ── Copy / Paste ボタン ────────────────────────────────────
        _add_copy_paste_buttons(
            lay,
            get_start=lambda: ln.ref_start,
            get_end=lambda: ln.ref_end,
            set_start=lambda v: setattr(ln, 'ref_start', v),
            set_end=lambda v: setattr(ln, 'ref_end', v),
            on_change=lambda: self.scene_changed.emit(),
            push_undo=lambda: self.request_push_undo.emit(),
        )

        ang = math.degrees(ln.angle)
        lay.addWidget(QLabel(f"方向角: {ang:.2f}°"))
        self._prop_layout.addWidget(grp)

        # ── 子線分リスト ──────────────────────────────────────────────
        if ln.segments:
            self._build_child_segments_list(ln)

    def _build_child_segments_list(self, ln: 'Line'):
        """直線に属する線分を始点順に一覧表示するパネルを構築する。

        各行にニックネーム・始点/終点座標・長さを表示し、
        「選択」ボタンで線分を選択できる。ラベルは折り返して
        ボタンが常にパネル右端に収まるよう配置する。

        Parameters
        ----------
        ln : Line
            親直線。
        """
        segs = sorted(ln.segments, key=lambda s: s.t_start)
        grp = QGroupBox(f"線分一覧 ({len(segs)} 本)")
        lay = QVBoxLayout(grp)
        lay.setSpacing(4)
        for seg in segs:
            start = seg.start
            end   = seg.end
            nick  = self.scene.get_nickname(seg.id, 'seg')

            # 外側: ボタンを右端に固定、ラベルは残り幅を使う
            row = QHBoxLayout()
            row.setSpacing(4)
            row.setContentsMargins(0, 0, 0, 0)

            # ラベル部（折り返しあり・幅制限なし）
            lbl = QLabel(
                f"<b>{nick}</b><br>"
                f"始: ({start.x:.2f}, {start.y:.2f})<br>"
                f"終: ({end.x:.2f}, {end.y:.2f})<br>"
                f"長: {seg.length():.3f} m"
            )
            lbl.setWordWrap(True)
            lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred)

            btn_sel = QPushButton("選択")
            btn_sel.setFixedWidth(44)
            btn_sel.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed)
            btn_sel.clicked.connect(
                lambda _, s=seg: self.request_select.emit([s]))

            btn_add = QPushButton("選択追加")
            btn_add.setFixedWidth(66)
            btn_add.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed)
            btn_add.clicked.connect(
                lambda _, s=seg: self.request_select.emit(self._selected + [s]))

            # ラベルを上段、ボタンを下段右寄せに配置
            lay.addWidget(lbl)
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(btn_sel)
            btn_row.addWidget(btn_add)
            lay.addLayout(btn_row)

        self._prop_layout.addWidget(grp)

    def _build_circle_props(self, ci: Circle):
        """円プロパティパネルを構築して ``_prop_layout`` に追加する。

        中心 X/Y・半径のスピンボックスを表示する。
        各スピンボックスの初回変更時に ``request_push_undo`` を発行し、
        同一編集セッション中の連続変更は 1 手順として Undo に記録される。
        変更後は ``Canvas._propagate_circle`` を経由してクロソイドや
        オフセット拘束への伝播が行われる。

        Parameters
        ----------
        ci : Circle
            プロパティを表示・編集する円。
        """
        grp = QGroupBox("円プロパティ")
        lay = QVBoxLayout(grp)

        row_cx = QHBoxLayout()
        sb_cx = _make_spinbox(ci.center.x)
        sb_cy = _make_spinbox(ci.center.y)
        sb_r  = _make_spinbox(ci.radius, 0.001, 1e6, 0.5)

        _undo_pushed = [False]
        def on_cx(v):
            if self._block: return
            if not _undo_pushed[0]:
                self.request_push_undo.emit(); _undo_pushed[0] = True
            ci.center = Vec2(v, ci.center.y)
            self.scene_changed.emit()
        def on_cy(v):
            if self._block: return
            if not _undo_pushed[0]:
                self.request_push_undo.emit(); _undo_pushed[0] = True
            ci.center = Vec2(ci.center.x, v)
            self.scene_changed.emit()
        def on_r(v):
            if self._block: return
            if not _undo_pushed[0]:
                self.request_push_undo.emit(); _undo_pushed[0] = True
            ci.radius = max(0.001, v)
            self.scene_changed.emit()

        sb_cx.valueChanged.connect(on_cx)
        sb_cy.valueChanged.connect(on_cy)
        sb_r.valueChanged.connect(on_r)

        row_cx.addWidget(QLabel("中心X:")); row_cx.addWidget(sb_cx)
        row_cy = QHBoxLayout()
        row_cy.addWidget(QLabel("中心Y:")); row_cy.addWidget(sb_cy)
        lay.addLayout(row_cx)
        lay.addLayout(row_cy)
        row_r = QHBoxLayout()
        row_r.addWidget(QLabel("半径:")); row_r.addWidget(sb_r)
        lay.addLayout(row_r)

        # ── 円弧追加ボタン ────────────────────────────────────────
        free_arcs = self._calc_free_arc_intervals(ci)
        if free_arcs:
            btn_row = QHBoxLayout()
            btn_row.addStretch()

            # 「円弧を追加」: 空き区間の中で中心角最大の1本だけ
            btn_one = QPushButton("円弧を追加")
            btn_one.setToolTip("空き区間の中で中心角が最大の円弧を1本追加する")
            largest = max(free_arcs, key=lambda a: a.arc_angle())
            btn_one.clicked.connect(
                lambda _, c=ci, a=largest: (
                    self.request_push_undo.emit(),
                    self.request_add_arcs.emit(c, [a]),
                ))
            btn_row.addWidget(btn_one)

            # 「円弧を全追加」: 空き区間すべて
            btn_all = QPushButton("円弧を全追加")
            btn_all.setToolTip("空き区間すべてに円弧を追加する（接点で区切る）")
            btn_all.clicked.connect(
                lambda _, c=ci, aa=free_arcs: (
                    self.request_push_undo.emit(),
                    self.request_add_arcs.emit(c, list(aa)),
                ))
            btn_row.addWidget(btn_all)
            lay.addLayout(btn_row)

        self._prop_layout.addWidget(grp)

        # ── 子円弧リスト ──────────────────────────────────────────────
        if ci.arcs:
            self._build_child_arcs_list(ci)

    def _calc_free_arc_intervals(self, ci: 'Circle') -> list:
        """円 ci の空き区間（円弧がない部分）を Arc オブジェクトのリストで返す。

        クロソイドの接点（``_circle_pt``）がある場合はその角度で区切る。
        既存の弧が全円周を覆っている場合は空リストを返す。

        Parameters
        ----------
        ci : Circle
            対象の円。

        Returns
        -------
        list[Arc]
            追加候補の :class:`Arc` オブジェクトのリスト（まだ ci.arcs には含まれない）。
            中心角 (``arc_angle()``) が 0 の区間は除外する。
        """
        from models import Arc as _Arc
        TWO_PI = 2 * math.pi
        EPS    = 1e-9

        # 既存弧の占有区間を (start, span) で収集（start ∈ [0, 2π), span > 0）
        occupied = []          # [(start, span), ...]
        for arc in ci.arcs:
            s    = arc.angle_start % TWO_PI
            span = arc.arc_angle()   # 常に正
            occupied.append((s, span))

        # 接点角度を収集
        tangent_angles = set()
        for clo in self.scene.clothoids:
            if not clo.is_valid or clo.circle is not ci:
                continue
            if clo._circle_pt is not None:
                cp  = clo._circle_pt
                ang = math.atan2(cp.y - ci.center.y,
                                 cp.x - ci.center.x) % TWO_PI
                tangent_angles.add(ang)

        # occupied の境界角度 + 接点角度 を合わせた境界点集合
        boundaries = set()
        for s, span in occupied:
            boundaries.add(s)
            boundaries.add((s + span) % TWO_PI)
        boundaries |= tangent_angles

        def is_covered(angle):
            """angle が既存弧のいずれかに含まれるか判定（環状）。"""
            a = angle % TWO_PI
            for s, span in occupied:
                if span >= TWO_PI - EPS:
                    return True        # 全円周を覆う弧
                end = (s + span) % TWO_PI
                if end > s:            # 折り返しなし
                    if s - EPS < a < end + EPS:
                        return True
                else:                  # 折り返しあり（s > end）
                    if a > s - EPS or a < end + EPS:
                        return True
            return False

        # 弧なし・接点なし → 全円周
        if not occupied and not boundaries:
            # angle_end = angle_start + 2π - eps で全円周を表現
            # (arc_angle() = (end - start) % 2π = 0 を避けるため)
            return [_Arc(ci, 0.0, TWO_PI - 1e-12)]

        # 全円周を覆っているか確認
        if occupied and all(span >= TWO_PI - EPS for _, span in occupied):
            return []

        # 境界点が1点だけの場合は 0 も加える
        if len(boundaries) == 0:
            return []
        if len(boundaries) == 1:
            boundaries.add(0.0)

        sorted_bounds = sorted(boundaries)
        n = len(sorted_bounds)

        free_arcs = []
        for i in range(n):
            seg_s = sorted_bounds[i]
            seg_e = sorted_bounds[(i + 1) % n] if i < n - 1 else sorted_bounds[0] + TWO_PI

            span = seg_e - seg_s
            if span < EPS:
                continue

            # 区間の中点が覆われているか確認
            mid = (seg_s + span / 2) % TWO_PI
            if is_covered(mid):
                continue

            a_s  = seg_s % TWO_PI
            # arc_angle() = (end - start) % 2π が 0 にならないよう span を制限
            span = min(span, TWO_PI - 1e-12)
            new_arc = _Arc(ci, a_s, a_s + span)
            free_arcs.append(new_arc)

        return free_arcs

    def _build_child_arcs_list(self, ci: 'Circle'):
        """円に属する円弧を始点角度順に一覧表示するパネルを構築する。

        各行にニックネーム・始点/終点角度・弧長を表示し、
        「選択」ボタンで円弧を選択できる。ラベルは折り返して
        ボタンが常にパネル右端に収まるよう配置する。

        Parameters
        ----------
        ci : Circle
            親円。
        """
        arcs = sorted(ci.arcs, key=lambda a: a.angle_start)
        grp = QGroupBox(f"円弧一覧 ({len(arcs)} 本)")
        lay = QVBoxLayout(grp)
        lay.setSpacing(4)
        for arc in arcs:
            nick    = self.scene.get_nickname(arc.id, 'arc')
            ang_s   = math.degrees(arc.angle_start)
            ang_e   = math.degrees(arc.angle_end)
            arc_len = arc.arc_length()

            lbl = QLabel(
                f"<b>{nick}</b><br>"
                f"始: {ang_s:.2f}°<br>"
                f"終: {ang_e:.2f}°<br>"
                f"弧長: {arc_len:.3f} m"
            )
            lbl.setWordWrap(True)
            lbl.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred)

            btn_sel = QPushButton("選択")
            btn_sel.setFixedWidth(44)
            btn_sel.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed)
            btn_sel.clicked.connect(
                lambda _, a=arc: self.request_select.emit([a]))

            btn_add = QPushButton("選択追加")
            btn_add.setFixedWidth(66)
            btn_add.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed)
            btn_add.clicked.connect(
                lambda _, a=arc: self.request_select.emit(self._selected + [a]))

            # ラベルを上段、ボタンを下段右寄せに配置
            lay.addWidget(lbl)
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(btn_sel)
            btn_row.addWidget(btn_add)
            lay.addLayout(btn_row)

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
        """線分プロパティパネルを構築して ``_prop_layout`` に追加する。

        始点・終点の X/Y 座標と割合 t のスピンボックスを表示する。
        X/Y 入力は直線上に束縛され ``Line.project_t`` で t 値に変換される。
        各スピンボックスの初回変更時に ``request_push_undo`` を発行する。

        Parameters
        ----------
        seg : Segment
            プロパティを表示・編集する線分。
        """
        grp = QGroupBox("線分プロパティ")
        lay = QVBoxLayout(grp)
        ln  = seg.line

        # 親の直線情報（読み取り専用）
        ln_nick = self.scene.get_nickname(ln.id, 'line')
        lbl_ln = QLabel(f"親直線: {ln_nick}  (ID:{ln.id})")
        lbl_ln.setWordWrap(True)
        btn_sel_ln = QPushButton("直線を選択")
        btn_sel_ln.setFixedWidth(80)
        btn_sel_ln.clicked.connect(lambda checked=False, _ln=ln:
            self.request_select.emit([_ln]))
        row_ln = QHBoxLayout()
        row_ln.addWidget(lbl_ln, 1)
        row_ln.addWidget(btn_sel_ln)
        lay.addLayout(row_ln)

        # 線分長 (読み取り専用)
        lay.addWidget(QLabel(f"長さ: {seg.length():.4f} m"))

        lay.addWidget(_separator())

        # 始点 (t_start から計算)
        def add_endpoint(label, get_t, set_t, other_t_getter):
            """線分端点の X/Y/t 入力フォームを生成する。

            Parameters
            ----------
            label : str
                グループラベル（"始点" または "終点"）。
            get_t : callable
                現在の t 値を返すゲッター。
            set_t : callable
                t 値を設定するセッター。
            other_t_getter : callable
                反対端の t 値を返すゲッター（縮退防止の比較に使う）。
            """
            lay.addWidget(QLabel(label))
            pt = ln.point_at(get_t())
            row_x = QHBoxLayout()
            row_y = QHBoxLayout()
            sb_x = _make_spinbox(pt.x, step=0.1, decimals=4)
            sb_y = _make_spinbox(pt.y, step=0.1, decimals=4)
            sb_t = _make_spinbox(get_t(), lo=0.0, hi=1.0, step=0.001, decimals=6)
            lbl_t = QLabel(f"割合: {get_t():.6f}")

            _undo_pushed = [False]

            def on_x(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
                from models import Vec2
                current = ln.point_at(get_t())
                t = ln.project_t(Vec2(v, current.y))
                set_t(t)
                self._refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)
                self.scene_changed.emit()

            def on_y(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
                from models import Vec2
                current = ln.point_at(get_t())
                t = ln.project_t(Vec2(current.x, v))
                set_t(t)
                self._refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)
                self.scene_changed.emit()

            def on_t(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
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

        # ── Copy / Paste ボタン ────────────────────────────────────
        _add_copy_paste_buttons(
            lay,
            get_start=lambda: seg.start,
            get_end=lambda: seg.end,
            set_start=lambda v: setattr(seg, 't_start', seg.line.project_t(v)),
            set_end=lambda v: setattr(seg, 't_end',   seg.line.project_t(v)),
            on_change=lambda: self.scene_changed.emit(),
            push_undo=lambda: self.request_push_undo.emit(),
        )

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
        """円弧プロパティパネルを構築して ``_prop_layout`` に追加する。

        始点・終点の角度（度数）と X/Y 座標のスピンボックスを表示する。
        X/Y 入力は円上に束縛され ``atan2`` で角度に変換される。
        各スピンボックスの初回変更時に ``request_push_undo`` を発行する。

        Parameters
        ----------
        arc : Arc
            プロパティを表示・編集する円弧。
        """
        grp = QGroupBox("円弧プロパティ")
        lay = QVBoxLayout(grp)
        ci  = arc.circle

        # 親の円情報（読み取り専用）
        ci_nick = self.scene.get_nickname(ci.id, 'circle')
        lbl_ci = QLabel(f"親円: {ci_nick}  (ID:{ci.id})")
        lbl_ci.setWordWrap(True)
        btn_sel_ci = QPushButton("円を選択")
        btn_sel_ci.setFixedWidth(66)
        btn_sel_ci.clicked.connect(lambda checked=False, _ci=ci:
            self.request_select.emit([_ci]))
        row_ci = QHBoxLayout()
        row_ci.addWidget(lbl_ci, 1)
        row_ci.addWidget(btn_sel_ci)
        lay.addLayout(row_ci)

        # 弧長角・弧長 (読み取り専用)
        lbl_span = QLabel(f"弧長角: {math.degrees(arc.arc_angle()):.4f}°")
        lbl_len  = QLabel(f"弧長: {arc.arc_length():.4f} m")
        lay.addWidget(lbl_span)
        lay.addWidget(lbl_len)
        lay.addWidget(_separator())

        def add_arc_endpoint(label, get_angle, set_angle):
            """円弧端点の角度・X/Y 入力フォームを生成する。

            Parameters
            ----------
            label : str
                グループラベル（"始点" または "終点"）。
            get_angle : callable
                現在の角度（ラジアン）を返すゲッター。
            set_angle : callable
                角度（ラジアン）を設定するセッター。
            """
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

            _undo_pushed = [False]

            def on_ang(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
                set_angle(math.radians(v))
                refresh_display()
                self.scene_changed.emit()

            def on_x(v):
                if self._block: return
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
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
                if not _undo_pushed[0]:
                    self.request_push_undo.emit(); _undo_pushed[0] = True
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

        _lbl_merge = QLabel("近接する端点で結合します。\n一方の線分を削除し、もう一方を延長します。")
        _lbl_merge.setWordWrap(True)
        lay.addWidget(_lbl_merge)
        lay.addWidget(_separator())

        pairs = self._candidate_seg_pairs(seg_a, seg_b)
        if not pairs:
            lay.addWidget(QLabel("※ 近接する端点がありません"))
            self._prop_layout.addWidget(grp)
            return

        combo = QComboBox()
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMaximumWidth(240)
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
                from PySide6.QtWidgets import QMessageBox
                # blocked でないペアがあるか確認
                unblocked = [q for q in _p if not q['blocked_a'] and not q['blocked_b']]
                hint = (f"\n\n「{unblocked[0]['label']}」を選んで試してください。"
                        if unblocked else "")
                QMessageBox.warning(self, "結合不可",
                    "選択した端点は他の図形に束縛されているため結合できません。" + hint)
                return
            self._merge_segments(_a, _b, p['end_a'], p['end_b'])
            self.scene_changed.emit()
        btn.clicked.connect(do_merge)
        lay.addWidget(btn)
        self._prop_layout.addWidget(grp)

    def _seg_end_blocked(self, seg: Segment, end: str) -> bool:
        """線分の指定端点がクロソイドに束縛されているか確認する。

        結合操作（_build_two_segments）で束縛端点を除外するために使う。

        Parameters
        ----------
        seg : Segment
            確認対象の線分。
        end : str
            'start' または 'end'。

        Returns
        -------
        bool
            束縛されているとき True。
            条件 1: ``snap_segment=True`` のクロソイドの接点が端点と一致する。
            条件 2: ``snap_segment=True`` のクロソイドの ``_split_seg_ids`` に
            seg.id が含まれる。

        Note
        ----
        ``snap_segment=False`` のクロソイドの ``_split_seg_ids`` は無視する。
        """
        for clo in self.scene.clothoids:
            if not clo.is_valid:
                continue
            if not clo.snap_segment:
                continue
            if clo.line is seg.line and clo._line_pt is not None:
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
        return sorted(candidates, key=lambda c: (c['blocked_a'] or c['blocked_b'], c['dist']))

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

        _lbl_merge = QLabel("近接する端点で結合します。\n一方の円弧を削除し、もう一方を延長します。")
        _lbl_merge.setWordWrap(True)
        lay.addWidget(_lbl_merge)
        lay.addWidget(_separator())

        pairs = self._candidate_arc_pairs(arc_a, arc_b)
        if not pairs:
            lay.addWidget(QLabel("※ 近接する端点がありません"))
            self._prop_layout.addWidget(grp)
            return

        combo = QComboBox()
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMaximumWidth(240)
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
                from PySide6.QtWidgets import QMessageBox
                unblocked = [q for q in _p if not q['blocked_a'] and not q['blocked_b']]
                hint = (f"\n\n「{unblocked[0]['label']}」を選んで試してください。"
                        if unblocked else "")
                QMessageBox.warning(self, "結合不可",
                    "選択した端点は他の図形に束縛されているため結合できません。" + hint)
                return
            self._merge_arcs(_a, _b, p['end_a'], p['end_b'])
            self.scene_changed.emit()
        btn.clicked.connect(do_merge)
        lay.addWidget(btn)
        self._prop_layout.addWidget(grp)

    def _arc_end_blocked(self, arc: Arc, end: str) -> bool:
        """円弧の指定端点がクロソイドに束縛されているか確認する。

        結合操作（_build_two_arcs）で束縛端点を除外するために使う。

        Parameters
        ----------
        arc : Arc
            確認対象の円弧。
        end : str
            'start' または 'end'。

        Returns
        -------
        bool
            束縛されているとき True。

            条件 1: ``snap_arc=True`` のクロソイドの接点角度が端点角度と
            ``1e-4 rad`` 以内で一致する。
            条件 2: ``snap_arc=True`` のクロソイドの ``_split_arc_ids`` に
            arc.id が含まれる（接点で分割管理されている弧）。

        Note
        ----
        ``snap_arc=False`` のクロソイドの ``_split_arc_ids`` は無視する。
        snap が off のときは接点拘束が解除されており、結合を妨げる理由がない。
        """
        for clo in self.scene.clothoids:
            if not clo.is_valid:
                continue
            if not clo.snap_arc:
                continue
            if clo.circle is arc.circle and clo._circle_pt is not None:
                ang = math.atan2(clo._circle_pt.y - arc.circle.center.y,
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
        return sorted(candidates, key=lambda c: (c['blocked_a'] or c['blocked_b'], c['dist']))

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
    def _build_offset_constraint(self, ln: 'Line',
                                  ci_a: 'Circle', ci_b: 'Circle'):
        """2 円 + 1 直線が選択されたときのオフセット拘束パネルを構築する。

        スムーズ接続で生成された円（``bisector_dir`` が設定された円）は
        設定不可として警告ラベルを表示して早期リターンする。

        既存の ``OffsetConstraint`` がある場合（設定済み）:

        * ``off_a``・``off_b`` のスピンボックス（``valueChanged`` でリアルタイム反映）
        * 直線から各円の中心への現在距離と期待値（``R + off``）の情報ラベル
        * 「オフセット拘束を解除」ボタン → ``request_clear_offset.emit(ln)``

        既存の拘束がない場合（未設定）:

        * ``off_a``・``off_b`` のスピンボックス（初期値 0）
        * 「オフセット拘束を設定」ボタン → ``request_set_offset.emit(ln, ci_a, ci_b)``

        Parameters
        ----------
        ln : Line
            拘束する直線 S。
        ci_a : Circle
            円 A（スムーズ接続の円は不可）。
        ci_b : Circle
            円 B（スムーズ接続の円は不可）。
        """
        from models import OffsetConstraint

        self._prop_layout.addWidget(QLabel("─ オフセット拘束 ─"))

        # スムーズ接続の円は不可
        for ci, label in ((ci_a, "円 A"), (ci_b, "円 B")):
            if ci.bisector_dir is not None:
                self._prop_layout.addWidget(
                    QLabel(f"⚠ {label} はスムーズ接続の円です（設定不可）"))
                return

        # 既存の拘束を検索
        existing = next(
            (oc for oc in self.scene.offset_constraints
             if oc.line is ln
             and {oc.circle_a, oc.circle_b} == {ci_a, ci_b}),
            None
        )

        grp = QGroupBox("オフセット拘束")
        form = QFormLayout(grp)

        nick_ln = self.scene.get_nickname(ln.id,   "line")
        nick_a  = self.scene.get_nickname(ci_a.id, "circle")
        nick_b  = self.scene.get_nickname(ci_b.id, "circle")
        form.addRow("直線:",  QLabel(nick_ln))
        form.addRow("円 A:", QLabel(nick_a))
        form.addRow("円 B:", QLabel(nick_b))

        off_a_init = existing.off_a if existing else 0.0
        off_b_init = existing.off_b if existing else 0.0
        sb_a = _make_spinbox(off_a_init, lo=-1000, hi=1000, step=0.1, decimals=3)
        sb_b = _make_spinbox(off_b_init, lo=-1000, hi=1000, step=0.1, decimals=3)
        form.addRow("off_a [m]:", sb_a)
        form.addRow("off_b [m]:", sb_b)
        self._prop_layout.addWidget(grp)

        def on_off_changed():
            if existing is not None and not self._block:
                self._block = True
                existing.off_a = sb_a.value()
                existing.off_b = sb_b.value()
                existing.solve()
                self._block = False
                self.scene_changed.emit()

        sb_a.valueChanged.connect(on_off_changed)
        sb_b.valueChanged.connect(on_off_changed)

        if existing is None:
            btn_set = QPushButton("オフセット拘束を設定")
            btn_set.clicked.connect(
                lambda: self.request_set_offset.emit(ln, ci_a, ci_b))
            self._prop_layout.addWidget(btn_set)
        else:
            btn_clr = QPushButton("オフセット拘束を解除")
            btn_clr.clicked.connect(
                lambda: self.request_clear_offset.emit(ln))
            self._prop_layout.addWidget(btn_clr)

            da = ln.distance_to(ci_a.center)
            db = ln.distance_to(ci_b.center)
            self._prop_layout.addWidget(
                QLabel(f"現在距離 A: {da:.3f} m  "
                       f"(R+off={ci_a.radius + existing.off_a:.3f})"))
            self._prop_layout.addWidget(
                QLabel(f"現在距離 B: {db:.3f} m  "
                       f"(R+off={ci_b.radius + existing.off_b:.3f})"))

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
