# 道路設計アプリ 基本設計書

（平面線形・縦断線形・3D走行ビューア）

---

## 目次

1. [システム概要](#1-システム概要)
2. [アーキテクチャ](#2-アーキテクチャ)
3. [データモデル](#3-データモデル)
4. [平面線形の設計](#4-平面線形の設計)
5. [縦断線形の設計](#5-縦断線形の設計)
6. [UIコンポーネント設計](#6-uiコンポーネント設計)
7. [3D走行ビューア設計](#7-3d走行ビューア設計)
8. [ユーティリティ関数](#8-ユーティリティ関数)
9. [resolve_chain アルゴリズム](#9-resolve_chain-アルゴリズム)
10. [テスト設計方針](#10-テスト設計方針)

---

## 1. システム概要

### 1.1 目的

道路の平面線形（直線・円弧・クロソイド）と縦断線形（勾配直線・縦断曲線）を設計し、3D 走行シミュレーションで確認するためのデスクトップアプリケーション。

### 1.2 技術スタック

| 項目 | 内容 |
|------|------|
| 言語 | Python 3.11+ |
| UI フレームワーク | PySide6 |
| 3D 描画 | Panda3D（別プロセスで起動） |
| ファイル形式 | `.rdjson`（JSON 形式） |
| 数値計算 | 標準ライブラリのみ（scipy / numpy 不使用） |

### 1.3 座標系

数学座標系（ワールド座標）を採用する。

- **x 軸**: 画面右方向が正
- **y 軸**: 画面上方向が正
- **有向角の正方向**: 反時計回り（CCW）

GUI 描画時のみ `w2s()` でスクリーン座標（y 軸下向き）に変換する。3D ビューアへは `(x右, y奥, z上)` の Panda3D 座標系に変換して渡す。

---

## 2. アーキテクチャ

### 2.1 ディレクトリ構成

すべてのソースファイルを `src/` 配下に配置する。起動コマンドは `python src/main.py`。

```
road_designer/
  README.md
  docs/
    road_design_spec.md
    road_design_basic_design.md
    road_design_detail_design.md
  src/
    main.py                # エントリーポイント
    models.py              # データモデル・ユーティリティ（vertical_profile を再エクスポート）
    vertical_profile.py    # 縦断線形クラス群（ElementProfile / GradeLine 等）
    canvas.py              # メイン編集キャンバス
    right_panel.py         # 右パネル
    _prop_builder.py       # プロパティパネル UI 構築 Mixin（PropBuilderMixin）
    main_window.py         # メインウィンドウ
    vertical_window.py     # 縦断線形設計ウィンドウ
    road_viewer.py         # 3D走行ビューア（別プロセス起動）
    _road_mesh.py          # 3D道路メッシュ生成関数群（road_viewer から分離）
```

### 2.2 モジュール構成

| モジュール | 役割・概要 |
|---|---|
| `src/main.py` | エントリーポイント。`MainWindow` を生成して起動 |
| `src/models.py` | データモデル・ビジネスロジック・ユーティリティ関数（クロソイド計算、`resolve_chain` 等）。`vertical_profile` のクラス群を後方互換のために再エクスポート |
| `src/vertical_profile.py` | 縦断線形データモデル（`ElementProfile`・`GradeLine`・`VerticalCurve`・`VerticalAlignment`・`plan_length_of`・`make_empty_profile`）。`models.py` から循環インポートで参照される |
| `src/canvas.py` | メイン編集キャンバス。描画・マウス操作・ハンドル管理 |
| `src/right_panel.py` | 右パネル。図形選択コンボ・プロパティ表示・操作ボタン。`PropBuilderMixin` を継承 |
| `src/_prop_builder.py` | プロパティパネル UI 構築 Mixin（`PropBuilderMixin`）。`right_panel.py` が継承して使用 |
| `src/vertical_window.py` | 縦断線形設計ウィンドウ（`ProfileCanvas` + `VerticalAlignmentWindow`） |
| `src/main_window.py` | メインウィンドウ。メニュー・ファイル操作・モジュール間シグナル接続 |
| `src/road_viewer.py` | 3D 走行ビューア（Panda3D、別プロセス起動）。中心線生成・走行シミュレーション |
| `src/_road_mesh.py` | 3D 道路メッシュ生成関数群（`build_road_mesh`・`build_piers` 等）。`road_viewer.py` から利用 |

### 2.3 コンポーネント間の依存関係

同一 `src/` 内のファイル同士は通常の `import` で参照する。`models.py` と `vertical_profile.py` の間にのみ制御された循環インポートが存在する（下記参照）。

```
src/main.py
  └─ main_window.py
       ├─ canvas.py               ← models.py
       ├─ right_panel.py          ← models.py, _prop_builder.py
       ├─ _prop_builder.py        ← models.py
       ├─ vertical_window.py      ← models.py, vertical_profile.py, _prop_builder.py
       └─ road_viewer.py          ← models.py, _road_mesh.py  （別プロセス）
            └─ _road_mesh.py      ← models.py

models.py  ←→  vertical_profile.py  （後方互換再エクスポートのための循環インポート）
```

**循環インポートの解決**: `vertical_profile.py` は `models.py` から `Segment`・`Arc`・`Clothoid`・`new_id` をインポートする。`models.py` はこれらのクラスを定義した**後**に `from vertical_profile import ...` で再エクスポートする。Python はモジュールの部分的な初期化状態を許容するため、`Segment`/`Arc`/`Clothoid` が定義済みの時点で `vertical_profile.py` のインポートが始まり、循環が安全に解決される。

### 2.4 シグナル設計

コンポーネント間の通知は PySide6 シグナルを使用し、直接参照を避ける。

| シグナル | 発行元 | 接続先（スロット） |
|---|---|---|
| `selection_changed(list)` | `Canvas` | `MainWindow._on_selection_changed` / `RightPanel.update_selection` |
| `scene_changed()` | `Canvas` / `RightPanel` | `MainWindow._on_scene_changed` |
| `mouse_world_pos(float, float)` | `Canvas` | `RightPanel.update_mouse_pos` |
| `hover_changed(object)` | `Canvas` | `RightPanel.update_hovered`（ホバー中図形の情報表示。`None` で消去） |
| `measure_dist_changed(float)` | `Canvas` | `RightPanel.update_measure_dist`（ラバーバンド対角距離の表示。`-1` で消去） |
| `request_smooth_connect(Line, Line)` | `RightPanel` | `MainWindow._do_smooth_connect` |
| `request_polyline_connect(Line, Line)` | `RightPanel` | `MainWindow._do_polyline_connect` |
| `request_disconnect(Line, Line)` | `RightPanel` | `MainWindow._do_disconnect` |
| `request_add_clothoid(Line, Circle)` | `RightPanel` | `MainWindow._do_add_clothoid` |
| `request_delete_clothoid(Clothoid)` | `RightPanel` | `MainWindow._do_delete_clothoid` |
| `request_flip_clothoid(Clothoid)` | `RightPanel` | `MainWindow._do_flip_clothoid` |
| `request_select(list)` | `RightPanel` | `Canvas.set_selection` |
| `request_delete(list)` | `RightPanel` | `MainWindow._do_delete_objects` |
| `request_set_offset(Line, Circle, Circle)` | `RightPanel` | `MainWindow._do_set_offset_constraint` |
| `request_clear_offset(Line)` | `RightPanel` | `MainWindow._do_clear_offset_constraint` |
| `request_set_two_line_offset(Line, Line, Circle)` | `RightPanel` | `MainWindow._do_set_two_line_offset_constraint` |
| `request_clear_two_line_offset(Line, Line)` | `RightPanel` | `MainWindow._do_clear_two_line_offset_constraint` |
| `request_add_arcs(Circle, list)` | `RightPanel` | `MainWindow._do_add_arcs` |
| `request_push_undo()` | `RightPanel` | `Canvas.push_undo` |

シグナルに加えて、`MainWindow._connect_signals()` が `RightPanel.set_canvas(canvas)` でキャンバスへの直接参照も渡す。これはオフセット拘束のスピンボックス変更など即時の `repaint()` が必要な場面で使う限定的なバイパスであり、通常の通知はシグナル経由を原則とする。

---

## 3. データモデル

### 3.1 クラス一覧

| クラス / 関数 | 定義モジュール | 分類 | 説明 |
|---|---|---|---|
| `Vec2` | `models.py` | 基本型 | 2次元ベクトル。`dot` / `cross` / `normalized` / `perp` 等の演算を持つ |
| `Line` | `models.py` | 平面線形 | 参照始点・参照終点で定義される有向直線。`segments: list[Segment]` を保持 |
| `Segment` | `models.py` | 平面線形 | 直線の部分区間。`t_start` / `t_end`（0.0〜1.0）で位置を管理 |
| `LineConnection` | `models.py` | 接続情報 | 2直線の折れ線/スムーズ接続を管理。`kind: "polyline" \| "smooth"` |
| `Circle` | `models.py` | 平面線形 | 中心と半径で定義される円。`arcs: list[Arc]` を保持 |
| `Arc` | `models.py` | 平面線形 | 円の部分区間。`angle_start` / `angle_end`（ラジアン、CCW）で管理 |
| `Clothoid` | `models.py` | 平面線形 | 直線と円で定義されるクロソイド曲線。`compute()` で接点・点列を計算 |
| `OffsetConstraint` | `models.py` | 平面線形 | 2 円 A・B と直線 S のオフセット拘束。円が動くと直線が追従（`Circle → Line`）。`solve()` で直線を再計算 |
| `TwoLineOffsetConstraint` | `models.py` | 平面線形 | 2 直線 A・B と円 C のオフセット拘束。直線が動くと円中心が追従（`Line → Circle`）。`solve()` で 2×2 連立方程式を解く |
| `ElementProfile` | `vertical_profile.py` | 縦断線形 | 平面要素1つに対応する縦断データ。`grade_lines` + `vertical_curves` を保持 |
| `GradeLine` | `vertical_profile.py` | 縦断線形 | 勾配直線。`dist_start` / `dist_end` ・ `elev_start` / `elev_end` で定義 |
| `VerticalCurve` | `vertical_profile.py` | 縦断線形 | 縦断曲線（放物線）。`pvi_dist` / `pvi_elev` ・ `g1` ・ `g2` ・ `length` で定義 |
| `make_empty_profile()` | `vertical_profile.py` | 縦断線形 | `GradeLine` / `VerticalCurve` を持たない空の `ElementProfile` を生成するファクトリ関数 |
| `Scene` | `models.py` | 集約 | 全図形・`ElementProfile`・ニックネームを管理。`to_dict` / `from_dict` でシリアライズ |

> `ElementProfile`・`GradeLine`・`VerticalCurve`・`plan_length_of`・`make_empty_profile` は `vertical_profile.py` で定義されるが、`models.py` からも後方互換のために再エクスポートされる（`from models import ElementProfile` は引き続き動作する）。

### 3.2 Scene の構造

```
Scene
  lines:                        list[Line]
    segments:                   list[Segment]
  circles:                      list[Circle]
    arcs:                       list[Arc]
  clothoids:                    list[Clothoid]
  offset_constraints:           list[OffsetConstraint]
  two_line_offset_constraints:  list[TwoLineOffsetConstraint]
  element_profiles:             list[ElementProfile]
    grade_lines:                list[GradeLine]
    vertical_curves:            list[VerticalCurve]
  vertical_alignments:          list[VerticalAlignment]  # 旧フォーマット互換用（読み込み専用）
  nicknames:                    dict[int, str]            # id → nickname（未設定図形のキーは存在しない）
```

### 3.3 ID 管理

- 全図形（`Line`・`Segment`・`Circle`・`Arc`・`Clothoid`・`OffsetConstraint`・`TwoLineOffsetConstraint`・`GradeLine`・`VerticalCurve`）の ID はタイプを通じてグローバルにユニーク
- `new_id()` でスレッドセーフに採番。`_id_counter` をグローバルに管理
- **保存時**: `to_dict()` の呼び出し前に `_fix_duplicate_ids()` が走り、メモリ上の ID 重複を検出して自動修正する。これにより保存ファイルに ID 重複が混入しない
- **読み込み時**: `_resolve_id()` で衝突を検出し、後から現れた ID を振り直す。ID が振り直された場合でも、`lines_by_id`・`circles_by_id` に「元の ID でも同じオブジェクトを引けるフォールバックエントリ」を保持し、クロソイドやオフセット拘束の参照が失われない
- 読み込み後は全 ID の最大値 + 1 から採番を再開（`_reset_id_counter_after()`）
- **ID 振り直し**: `Scene.renumber_ids()` で全図形の ID を 1 から連番で付け直す。メモリ上のクロソイド・オフセット拘束はオブジェクト直接参照なので更新不要だが、`Segment`/`Arc` が持つクロソイド整数参照（`clothoid_start`/`clothoid_end`）とニックネーム辞書のキーは追従して更新される。この操作は Undo 非対応（実行前に確認ダイアログを表示）
- **マージ読み込み**: `Scene.merge_from_dict(d)` で既存シーンに JSON データを追記する。既存 ID との衝突は `_resolve_id()` で解決し（`id_remap` でニックネームも転記）、追加した `Line`/`Circle`/`Clothoid` のリストを返す。クロソイドは保存済みの `split_seg_ids`/`split_arc_ids` を設定してから `compute()` を再実行することで、余分な再分割を防ぐ。`element_profiles` はマージ対象外
- **ニックネームのデフォルト**: なし。`get_nickname(id)` は未設定のとき `None` を返す。表示が必要なときは `display_name(id, type_label)` で `(type_label#id)` 形式の文字列を生成する（ファイル保存不要）

### 3.4 ファイル形式（.rdjson）

JSON 形式。各図形の `id` フィールドの直後に `nickname` を埋め込む。

```json
{
  "lines":    [{ "id": 1, "nickname": "my_line", "ref_start": {...}, "segments": [...] }],
  "circles":  [{ "id": 3, "nickname": "my_circle", "center": {...}, "arcs": [...] }],
  "clothoids":[{ "id": 5, "nickname": "clo_1", "line_id": 1, "circle_id": 3, ... }],
  "offset_constraints": [{ "id": 7, "line_id": 1, "ca_id": 3, "cb_id": 4, "off_a": 10.0, "off_b": 5.0 }],
  "two_line_offset_constraints": [{ "id": 8, "la_id": 1, "lb_id": 2, "circle_id": 3, "off_a": 5.0, "off_b": 5.0 }],
  "element_profiles": [{ "id": 10, "element_id": 5, "plan_length": 66.3, ... }]
}
```

---

## 4. 平面線形の設計

### 4.1 直線と線分

`Line` は参照始点・参照終点（参照点）と方向ベクトル（`direction`）を持つ有向直線。`Segment` は `t_start` / `t_end`（参照始点=0、参照終点=1）で直線上の区間を表す。

**Line の主要メソッド**:

| メソッド | 説明 |
|---|---|
| `project_t(p)` | 点 `p` の直線上のパラメータ t を返す |
| `point_at(t)` | パラメータ t の座標を返す |
| `signed_dist(p)` | 符号付き距離（左側が正） |
| `intersect(other)` | 2直線の交点を返す（平行なら `None`） |
| `left_normal` | `direction` を CCW に 90° 回転した左法線ベクトル |

### 4.2 クロソイド

#### 4.2.1 数式

クロソイドパラメータ `A`、円半径 `R`、曲線長 `L`、全偏角 `τ` の関係:

```
A² = R · L
L  = 2 · R · τ
```

弧長 `s` での曲率:

```
κ(s) = s / A²
```

#### 4.2.2 接点計算（`compute` メソッド）

以下の変数を使う:

- `d`: 円の中心から直線への垂直距離（`d = |signed_dist(circle.center)|`）
- `τ`: Fresnel 条件 `ye(τ) = d − R·cos(τ)` を二分法（80 回）で求めた全偏角
- `xe`: `∫₀ᴸ cos(s²/2A²) ds`（中点則、n=500 ステップ）
- `proj_center`: 円心を直線に正射影した点

```python
# 円側接点
cc = proj_center + direction * R*sin(τ) + left_normal * sign * (d - R*cos(τ))
# 線側接点
lc = proj_center + direction * (R*sin(τ) - xe)
```

#### 4.2.3 点列生成

等接線角度変化方式。`θᵢ = i·τ/n_steps` に対応する弧長 `sᵢ = √(2·A²·θᵢ)` の点を、内部積分（`n_int = max(n_steps*8, 800)` ステップの中点則）で取り出す。

#### 4.2.4 snap 機能

**デフォルト動作**: `snap_segment=False`, `snap_arc=False`（デフォルト off）。
直接生成した Clothoid は線分・円弧を接点で分割して管理する。
スムーズ接続（`Canvas.smooth_connect`）で自動生成されるクロソイドのみ両側 `True` で生成する。

| snap 設定 | 動作 |
|---|---|
| `snap_segment=True` | 線側接点に最も近い線分の端点を接点に一致させる（`reversed_flag` に応じて終点/始点） |
| `snap_segment=False` | 線側接点 X で最も近い線分 AB を AX/XB に分割。`_split_seg_ids` で追跡・復元 |
| `snap_arc=True` | 円側接点に最も近い円弧の端点を接点に一致させる（左カーブ→始点、右カーブ→終点） |
| `snap_arc=False` | 円側接点で円弧を分割。`_split_arc_ids` で追跡・復元 |

### 4.3 接続操作

#### 4.3.1 折れ線接続（polyline）

2直線の交点を共有参照点として `LineConnection(kind="polyline")` を生成する。

**追従動作**: 接続中の一方の直線が動いて共有端点がずれた場合、`Canvas._follow_polyline_connection()` が相手直線を**平行移動**（方向は変えない）して共有端点を追従させる。`conn.shared_point` を先に更新してから相手を動かすため、相互の伝播が無限再帰しない（差分がゼロになった時点で停止する）。

#### 4.3.2 スムーズ接続（smooth）

以下の変数を使う:

- `X`: 直線 A と直線 B の交点
- `bisect`: 折れ角の二等分線方向（`normalize(XU + XV)`）
- `J`, `K`: X を挟む2方向の実効直線

手順:

1. 折れ線接続で X を確定する
2. `bisect` 方向にデフォルト距離（`1.5R`）で円 C を配置する
3. 直線 J と円 C で左カーブのクロソイド E を生成（`snap_segment=True`, `snap_arc=True`）
4. 直線 K と円 C で右カーブのクロソイド F を生成（`snap_segment=True`, `snap_arc=True`）

スムーズ接続中、円の中心は `bisect` 上に束縛される。

### 4.4 オフセット拘束

オフセット拘束には2種類ある。

**循環依存の検出**: `OffsetConstraint`（`Circle → Line`）と `TwoLineOffsetConstraint`（`Line → Circle`）が連鎖してループを作ると解が収束しない。このため拘束の**設定時**に `models.detect_constraint_cycle(scene, inputs, outputs)` が新拘束の出力ノードから既存拘束グラフを BFS で辿り、入力ノードに到達できる（= ループが生まれる）場合は警告ダイアログを表示して登録を拒否する。設定時に拒否しているため、実行時の伝播チェーンは必ず有限で停止する。

#### 4.4.1 OffsetConstraint（Circle → Line）

円 A・円 B と直線 S の 3 図形に対して設定する。円が動くと直線が追従する。スムーズ接続で生成された円（`bisector_dir` が設定された円）は設定不可。

**`solve()` の数式**（直線の方程式を `n·x = c`、`n`: 法線単位ベクトル）:

```
距離拘束:
  |n · ca.center - c| = ra = ca.radius + off_a
  |n · cb.center - c| = rb = cb.radius + off_b

n · (cb.center - ca.center) = ε_b · rb + ε_a · ra
```

`ε_a = -sign(signed_dist(circle_a))`、`ε_b = sign(signed_dist(circle_b))` は設定時点で固定し、法線方向（直線が 2 円の間か外側か）を維持する。

**feasible フラグ**: `solve()` 成功で `True`、距離拘束が矛盾（2 円が近すぎる）で `False`。`False` のとき直線は変更せず、条件が回復次第追従を再開する。

**伝播**: `Canvas._propagate_circle(ci)` から呼ばれる。円の変形時は **TwoLineOffsetConstraint を先に解いて `ci.center` を確定させてから**（半径変化時に 2 直線の縁からの距離を維持するため）、`circle_a is ci` または `circle_b is ci` に該当する全 `OffsetConstraint` で `solve()` を実行し、`_propagate_line(oc.line)` で関連クロソイドも追従させる。

#### 4.4.2 TwoLineOffsetConstraint（Line → Circle）

直線 A・直線 B と円 C の 3 図形に対して設定する。直線が動くと円の中心が追従する。

**`solve()` の数式**（各直線の左法線 `n`、切片 `c = n · ref_start` を使った 2×2 連立方程式）:

```
n_a · P = c_a + ε_a · (C.radius + off_a)
n_b · P = c_b + ε_b · (C.radius + off_b)

det = n_ax * n_by - n_ay * n_bx
P = (行列式で解く)
```

`det ≈ 0`（2 直線が平行）のとき `feasible = False`。`ε_a`・`ε_b` は設定時点の円中心の `signed_dist` 符号で固定する。

**伝播**: 直線の移動時は `Canvas._propagate_line(ln)` の末尾から `_propagate_two_line_oc_for_line(ln)` が呼ばれ、`line_a is ln` または `line_b is ln` に該当する全 `TwoLineOffsetConstraint` で `solve()` を実行し、さらに `_propagate_offset_constraints(oc.circle)` で連鎖する `OffsetConstraint` も追従させる。円の半径変更時は `_propagate_two_line_offset_constraints(ci)`（円側エントリー）が `circle is ci` の拘束を解いて中心を追従させる。循環は設定時に拒否済みのため伝播は有限で停止する。

---

## 5. 縦断線形の設計

### 5.1 データ構造

各平面線形要素（`Segment` / `Arc` / `Clothoid`）に `ElementProfile` が 1 対 1 で対応する。`grade_lines` ・ `vertical_curves` の距離は要素内の相対距離（始端=0、終端=`plan_length`）で管理する。

### 5.2 GradeLine

| フィールド | 説明 |
|---|---|
| `dist_start`, `dist_end` | 勾配直線の始端・終端距離（相対）[m] |
| `elev_start`, `elev_end` | 始端・終端標高 [m] |

勾配 [%] = `(elev_end - elev_start) / (dist_end - dist_start) * 100`

### 5.3 VerticalCurve（縦断曲線）

| フィールド | 説明 |
|---|---|
| `pvi_dist`, `pvi_elev` | PVI（Point of Vertical Intersection）の距離・標高。勾配直線の終点と一致 |
| `g1`, `g2` | 前勾配・後勾配 [%] |
| `length` | 曲線長 L [m] |

派生値（読み取り専用プロパティ）:

```python
vpc_dist = pvi_dist - L / 2        # VPC（曲線始点）の距離
vpt_dist = pvi_dist + L / 2        # VPT（曲線終点）の距離
vpc_elev = pvi_elev - g1 / 100 * L / 2
```

標高の放物線式（`x`: VPC からの局所距離）:

```python
y(x) = vpc_elev + (g1 / 100) * x + ((g2 - g1) / (200 * L)) * x²
```

K 値 = `L / |g2 - g1|`

### 5.4 標高計算の優先順位

`ElementProfile.elev_at(rel)` の優先順位:

1. `VPC ≤ rel ≤ VPT` の `VerticalCurve` が存在する → 放物線式の値を使用
2. 該当する `GradeLine` が存在する → 線形補間
3. 見つからない → `0.0` を返す

### 5.5 隣接スナップ（`_snap_grade_lines`）

勾配直線の追加・ドラッグ・数値入力の後に実行し、隣接する `GradeLine` の端点を強制一致させる。

| 引数 | 動作 |
|---|---|
| `'end'` | 前→後方向に伝播。変更した終端値を次の始端へ |
| `'start'` | 後→前方向に伝播 |
| `'both'` | 両方向（縦断線形ウィンドウを開く際に実行して境界標高を揃える） |

### 5.6 チェーン統合と保存

縦断線形ウィンドウを開くと `set_plan_elements()` がチェーン全体の `grade_lines` を累積距離で統合して表示する。ウィンドウを閉じると `save_to_profiles()` が各要素の距離範囲に切り出して `ElementProfile` に書き戻す。

---

## 6. UI コンポーネント設計

### 6.1 Canvas

メイン編集キャンバス（`canvas.py`）。`QWidget` を継承し、`paintEvent` でシーン全体を描画する。

#### 6.1.1 描画モード

| モード | 動作 |
|---|---|
| 選択モード（`S`） | クリックで図形を選択。ハンドルを表示し、ドラッグで変形 |
| 直線モード（`L`） | 左クリックで折れ線を連続入力 |
| 円モード（`C`） | 左クリック＆ドラッグで中心と半径を指定 |

#### 6.1.2 ハンドル種別

| ハンドル | 色 | 動作 |
|---|---|---|
| 参照点（直線） | 灰色 | ドラッグで参照点を移動。関連クロソイドを自動再計算 |
| 端点（線分/円弧） | 赤色 | ドラッグで端点を移動（直線上/円周上に束縛） |
| 半径ハンドル | 緑色 | ドラッグで半径を変更 |
| 共有参照点 | 橙色 | 折れ線/スムーズ接続時。ドラッグで両直線が追従 |
| snap 済み端点 | — | ハンドルでなく接点マーカー（菱形）を表示 |
| AABB 頂点ハンドル（複数選択時） | 青色 | ドラッグで AABB 中心基点の XY 等率拡大縮小 |
| AABB 辺（複数選択時） | 青色（枠線） | ドラッグで全選択図形を平行移動 |
| AABB 対角線（複数選択時） | 青色（破線） | ドラッグで AABB 中心を回転中心とした回転 |

**AABB ドラッグの実装方針**: ドラッグ開始時に `_snapshot_selected()` で全選択図形のジオメトリをスナップショット保存し、`_bbox_drag_aabb` として開始時の AABB を固定する。毎フレームはスナップショットから変換を再計算して適用する（累積誤差なし）。ヒット判定の優先順位は頂点 → 対角線 → 辺。

#### 6.1.2b ラバーバンド選択（Shift+ドラッグ）

選択モードで `Shift` を押しながら空白部分をドラッグすると矩形選択（ラバーバンド選択）になる。

- 矩形に**完全に含まれる**図形のみ選択する（Clothoid: 全描画点、Arc: 約 10° 刻みのサンプル点全部、Circle: 上下左右 4 点、Segment: 両端点）
- `Segment`/`Arc` が含まれるとき親 `Line`/`Circle` も一緒に選択する。右パネルはこの「子+親の共存」パターン（`_is_rubber_select()`）を検出して複数選択操作パネルを表示する
- ドラッグ中は始点〜現在点のワールド距離を `measure_dist_changed` シグナルで右パネルに通知する（**簡易測距ツール**を兼ねる）
- 矩形サイズが 4px 未満ならクリック扱い（選択なし）

#### 6.1.3 色分け

| 図形 | 色 |
|---|---|
| 直線（参照線） | 灰色（破線） |
| 線分 | 青色 |
| 円（円弧なし） | 紫色（実線） |
| 円（円弧あり） | 薄紫色（点線） |
| 円弧 | 紫色（太い実線） |
| クロソイド | 緑色 |
| 線側接点マーカー（菱形） | 黄色 |
| 円側接点マーカー（菱形） | 橙色 |
| 選択中の図形 | 黄橙色（ハイライト） |
| ホバー中の図形 | 黄色（ハイライト） |

#### 6.1.4 Undo

`push_undo()` で `Scene` 全体を JSON シリアライズして `deque(maxlen=500)` のスタックに積む。最大 500 手順（`maxlen` で自動的に古い履歴を破棄）。`Ctrl+Z` で `undo()` を呼びリストアする。

**Undo に記録される操作**:
- 図形の追加・削除・全削除
- ハンドルのドラッグ（`mousePressEvent` でハンドルヒット時に `push_undo()` を呼ぶ）
- 複数選択時の AABB ドラッグ（ドラッグ開始時に `push_undo()` を呼ぶ）
- 右パネルからのプロパティ変更（X/Y 座標・半径・角度等の数値入力。同一編集セッション中の連続変更は1手順にまとめる）
- 右パネルからの複数選択操作（コピー・平行移動・回転・拡大縮小）と Paste（始点/終点ペアの貼り付け）
- 接続操作（折れ線接続・スムーズ接続・解除）
- クロソイドの追加・削除・反転
- オフセット拘束の設定・解除（両種類）
- マージ読み込み（`Ctrl+Shift+O`）

**Undo に記録されない操作**: ニックネーム変更、オフセット量スピンボックスのリアルタイム編集、ID 振り直し（確認ダイアログで代替）。

### 6.2 RightPanel

右パネル（`right_panel.py`）。`QWidget` を継承。

#### 6.2.1 図形選択コンボボックス

複数のコンボボックスで平面線形要素をチェーン状に選択する。

- **1つ目**: 全図形を一覧表示
- **2つ目**: 1つ目の両端点に隣接する図形を先頭に表示（`[順]`/`[逆]` 付き）
- **3つ目以降**: 前の図形の出口端点に隣接する図形を先頭に表示
- 最後のコンボに図形が選択されると自動で1個追加

**コンボボックスの即時更新**: 1つ目のコンボに図形が設定されたとき（設計画面でのクリック選択・コンボ直接操作のいずれでも）、直ちに2つ目の高優先候補（隣接図形）が更新される。これは `update_selection` の処理順を「`_sync_combos_to_selection()` → `_refresh_nick_combos()`」とすることで実現する（先に選択図形をコンボに設定してから次のコンボの選択肢を更新する）。

**`[道なり]` 自動選択**: 高優先候補が 1 件、または `[順]` 判定の候補がちょうど 1 件のとき、コンボに `[道なり]` アイテムが追加される。選択すると `_road_follow()` が同じ条件で後続コンボの選択を連鎖的に進め、一本道のチェーンをワンクリックで末端まで選択できる。連鎖中は `[道なり]` 自身を候補から除外して無限ループを防ぐ。末尾の「(なし)」コンボは `_trim_trailing_none_combos()` で常に 1 個に保たれる。

**ホバー情報・測距表示**: コンボ群の上のマウス座標エリアには、`hover_changed` シグナル経由でホバー中図形の情報（`ニックネーム (型#id)` + 親図形）、`measure_dist_changed` シグナル経由でラバーバンドの対角距離も表示される。

#### 6.2.2 `[順]`/`[逆]` の判定

前の図形の出口接線ベクトル（`exit_tan`）と次の候補図形の「共有端点→近傍点」ベクトル（`entry_tan`）の内積で判定する。

```
dot = exit_tan · entry_tan
dot ≥ 0 → [順]（同方向、スムーズに繋がる）
dot < 0 → [逆]（逆方向）
```

各図形の近傍点の求め方:

| 図形 | 近傍点 |
|---|---|
| 線分 | 共有端点からもう一方の端点への方向ベクトル |
| 円弧 | 共有端点が始点なら `+0.1°`、終点なら `−0.1°` の円周上の点 |
| クロソイド | 点列 `points` で共有端点の隣の点 |

#### 6.2.3 プロパティ変更の Undo 対応

各プロパティコールバック（`on_x` / `on_y` / `on_r` / `on_t` / `on_ang` 等）は `request_push_undo` シグナルを発行し、`MainWindow` 経由で `Canvas.push_undo()` を呼ぶ。同一編集セッション中の最初の変更のみ push する（`_undo_pushed` フラグで制御）。

ハンドルドラッグ完了時（`mouseReleaseEvent` でドラッグ検出）に `selection_changed.emit()` を発行し、右パネルのプロパティを即座に更新する。

#### 6.2.4 シグナル一覧

| シグナル | 引数 | 用途 |
|---|---|---|
| `request_smooth_connect` | `Line, Line` | スムーズ接続 |
| `request_polyline_connect` | `Line, Line` | 折れ線接続 |
| `request_disconnect` | `Line, Line` | 接続解除 |
| `request_add_clothoid` | `Line, Circle` | クロソイド追加 |
| `request_delete_clothoid` | `Clothoid` | クロソイド削除 |
| `request_flip_clothoid` | `Clothoid` | クロソイド反転 |
| `request_select` | `list` | 選択変更 |
| `request_delete` | `list` | 図形削除 |
| `request_set_offset` | `Line, Circle, Circle` | OffsetConstraint 設定 |
| `request_clear_offset` | `Line` | OffsetConstraint 解除 |
| `request_set_two_line_offset` | `Line, Line, Circle` | TwoLineOffsetConstraint 設定 |
| `request_clear_two_line_offset` | `Line, Line` | TwoLineOffsetConstraint 解除 |
| `request_add_arcs` | `Circle, list[Arc]` | 円弧を追加 |
| `request_push_undo` | — | Undo スタックへの push |
| `scene_changed` | — | シーン変更通知 |

#### 6.2.5 オフセット拘束パネル

選択図形の組み合わせに応じて2種類のパネルを表示する。

**OffsetConstraint パネル**（円 2 個 + 直線 1 本を選択時、`_build_offset_constraint()` が呼ばれる）:
- スムーズ接続で生成された円が含まれる場合は警告を表示して設定不可
- 拘束未設定: `off_a`・`off_b` スピンボックス（初期値 0）+ 「オフセット拘束を設定」ボタン
- 拘束設定済み: `off_a`・`off_b` スピンボックス（リアルタイム編集）+ 現在距離の情報表示 + 「オフセット拘束を解除」ボタン

**TwoLineOffsetConstraint パネル**（直線 2 本 + 円 1 個を選択時、`_build_two_line_offset_constraint()` が呼ばれる）:
- 拘束未設定: `off_a`・`off_b` スピンボックス（初期値 0）+ 「オフセット拘束を設定」ボタン
- 拘束設定済み: `off_a`・`off_b` スピンボックス（リアルタイム編集）+ 現在距離の情報表示 + 「オフセット拘束を解除」ボタン

`off_a`・`off_b` の変更は即座にジオメトリへ反映される（Undo 非対応、設定・解除は Undo 対応）。

#### 6.2.6 複数選択時の操作パネル

`effective_set(selected)` が 2 個以上のとき（ラバーバンド選択による「子+親の共存」選択を含む）`_build_multi_select()` が呼ばれ、以下を表示する。各操作の実体は `RightPanel` の `_do_copy` / `_do_translate` / `_do_rotate` / `_do_scale` が担う。

- **コピー**（`_do_copy`）: 選択図形を複製し、複製した図形のみ選択状態にする。クロソイドは参照先の Line/Circle が同時に複製されていればその複製物を参照する。対応する `ElementProfile`（GradeLine・VerticalCurve・相互参照を含む）も複製する
- **平行移動**（`_do_translate`）: ΔX・ΔY を数値入力して「適用」ボタンで移動
- **回転**（`_do_rotate`）: 角度（度数）+ 基準点（AABB 中心 / 原点）を指定して「適用」。円の円弧角度も回転角分シフトする
- **拡大縮小（XY 同率）**（`_do_scale`）: 倍率 + 基準点を指定して「適用」。クロソイドのパラメータ整合のため XY 同率のみ

#### 6.2.7 FocusSpinBox / _FlexSpinBox

`_prop_builder.py` に定義された `FocusSpinBox(QDoubleSpinBox)` を全プロパティスピンボックスで使用する。フォーカスポリシーを `StrongFocus` に変更し、`wheelEvent` で `hasFocus()` のときのみ値を変更する（ホバー状態でのホイール操作では値が変わらず、イベントは親に伝播してスクロールになる）。実際に生成されるのはサブクラス `_FlexSpinBox` で、`minimumSizeHint`/`sizeHint` を小さくオーバーライドして右パネルの水平スクロール発生を防ぐ。

#### 6.2.8 その他のパネル要素

- **Copy / Paste ボタン**（直線・線分のプロパティ）: 始点・終点ペアを JSON でクリップボードに保存・復元する。Paste の右クリックメニューから原点基準の回転（90°/180°/−90°）・線対称（y=0 / x=0 / y=x / y=−x）変換を選んで貼り付けられる。Paste ボタンの有効/無効はクリップボード内容に自動追従する
- **子図形リスト**: 直線選択時は所属線分の一覧（`_build_child_segments_list`）、円選択時は所属円弧の一覧（`_build_child_arcs_list`）を表示し、各行から選択できる
- **円弧追加**: 円の空き区間（円弧がない部分）を `_calc_free_arc_intervals()` で計算し、`request_add_arcs` シグナル経由で追加する。クロソイド接点がある場合はその角度で区間を区切る
- **関連拘束一覧**（`_add_related_constraints`）: 選択図形が関与するオフセット拘束（両種類）を一覧表示し、「選択」ボタンで拘束の全構成図形を選択してパネルを切り替えられる

### 6.3 ProfileCanvas（縦断線形）

縦断線形設計ウィンドウ内のキャンバス（`vertical_window.py`）。

#### 6.3.1 座標変換

```python
screen_x =  dist * scale_x + offset.x
screen_y = -elev * scale_y + offset.y   # y 軸反転
```

#### 6.3.2 描画モード

| モード | 動作 |
|---|---|
| 選択モード（`S`） | 勾配直線・縦断曲線をクリックで選択。数値入力で精密編集 |
| 勾配直線モード（`G`） | 左クリックで始点・終点を指定。重複区間は自動置換 |

---

## 7. 3D 走行ビューア設計

### 7.1 起動方式

`main_window.py` の `launch_viewer()` が `tempfile` に JSON を書き出し、`subprocess.Popen` で `road_viewer.py` を別プロセスとして起動する。I/O を伴わない計算部分は `prepare_viewer_data()` に分離されており単体テスト可能。

### 7.2 中心線生成（`build_centerline`）

引数: `elements`（平面線形要素リスト）、`profiles`（`ElementProfile` リスト）、`rev_flags`（逆順フラグリスト）、`n_per_m`（点密度、デフォルト 0.5 点/m）

各要素の 2D 中心線を生成し標高を付与する:

| 要素 | 中心線生成方法 |
|---|---|
| `Segment` | 始端→終端を n 等分した線形補間 |
| `Arc` | `angle_start` から CCW に n 等分した角度補間 |
| `Clothoid` | `elem.points` を累積弧長でリサンプリングして n 点取得 |

**境界点の高さ継承**: 各要素先頭点（境界点）は前の要素の末端高さを `ep.elev_at()` を呼ばずそのまま継承する（段差防止）。

### 7.3 道路表示

| 要素 | 仕様 |
|---|---|
| 路面メッシュ | 全幅 3.5m（半幅 1.75m）、`z + 0.02m` で地面より上、両面描画 |
| センターライン | 走行チェーン=黄色、背景=グレー |
| 白線（路肩ライン） | 道路端、路面より 0.08m 上 |
| 橋脚 | 約 30m おきに道路端外側 0.5m に左右 1 本ずつ。断面 0.4m×0.4m、地面から道路面まで |
| 地面 | 2000m×2000m の緑色平板 |

### 7.4 RoadViewer クラス（Panda3D ShowBase 継承）

`__init__(centerline, display_segs=None, elem_graph=None, start_info=None, warp_boundary=None)`

| メソッド/グループ | 役割 |
|---|---|
| `_build_scene()` | 路面・白線・橋脚・地面・HUD・キー設定と周囲車両（`_init_traffic()`）を構築 |
| `_move_task(task)` | 毎フレーム呼ばれる走行タスク。オートドライブ / 通常ループを切り替え、自車・カメラ・周囲車両を更新 |
| `_ad_step(dt)` / `_ad_advance(overflow)` | オートドライブ: チェーン末端超過時に `elem_graph` から次の要素をランダム選択して遷移。候補なしのときワープ |
| `_ad_start_elem()` / `_ad_warp()` | オートドライブ走行開始 / パックマン式ワープ（境界超過軸の符号を反転） |
| `_ad_history_push()` / `_rewind()` / `_forward()` | 走行履歴スタック（最大 10 件）。`←` で過去要素を復元、`→` で最新に戻る |
| `_init_traffic()` / `_add_traffic_car()` / `_step_traffic_car()` | 周囲車両の初期化・追加・フレーム更新（個別速度係数付き） |
| `_update_car_pose_cl()` / `_update_camera_cl()` | 自車・カメラ位置姿勢の更新（follow / onboard / overview / overview_fixed の 4 モード） |
| `_overview_pan()` / `_overview_zoom_in()` / `_overview_zoom_out()` | 固定俯瞰視点のマウスパン・ズーム |
| `_toggle_surface()` / `_apply_surface_visible()` | 路面メッシュ（`_surface_nodes`）の表示/非表示を切り替え |
| `_interp_cl()` / `_make_elem_cl()` / `_find_next_candidates()` / `_bearing_str()` | モジュールレベル純粋関数への薄いラッパー |

---

## 8. ユーティリティ関数（models.py）

| 関数 | 定義モジュール | 説明 |
|---|---|---|
| `tangent_at(obj, at_end)` | `models.py` | `Segment` / `Arc` / `Clothoid` の始点/終点での接線単位ベクトルを返す |
| `entry_tangent(obj, connect_at_start)` | `models.py` | 「共有端点→近傍点」方向の単位ベクトルを返す |
| `resolve_chain(elems, element_profiles=None)` | `models.py` | 要素リストからチェーン順序と `reversed_flags` を解決して返す。`SNAP_TOL=1.0m`、貪欲法 |
| `detect_constraint_cycle(scene, inputs, outputs)` | `models.py` | 新しいオフセット拘束を追加すると拘束グラフにループが生まれるかを BFS で検査する。拘束設定前に `MainWindow` が呼ぶ |
| `plan_length_of(obj)` | `vertical_profile.py` | `Segment` / `Arc` / `Clothoid` の平面長を計算して返す（`models.py` から再エクスポート） |
| `make_empty_profile()` | `vertical_profile.py` | `GradeLine` / `VerticalCurve` を持たない空の `ElementProfile` を生成する（`models.py` から再エクスポート） |
| `interp_cl(cl, dist)` | `road_viewer.py` | 中心線点列上の累積距離に対応する位置・方向・右ベクトルを線形補間（Panda3D 不要、テスト可能） |
| `bearing_str(fwd_x, fwd_y)` | `road_viewer.py` | 進行方向ベクトルを 8 方位文字列に変換（Panda3D 不要、テスト可能） |
| `make_elem_cl(elem, forward)` | `road_viewer.py` | 要素辞書から 3D 中心線を生成して `(cl, total)` を返す（Panda3D 不要、テスト可能） |
| `find_next_candidates(graph, cur_id, ex, ey, exit_clo_ref)` | `road_viewer.py` | 隣接走行候補要素を検索して `[(elem, forward), ...]` を返す（Panda3D 不要、テスト可能） |
| `prepare_viewer_data(...)` | `road_viewer.py` | 3D 中心線・表示セグメント・`elem_graph`・`start_info` を計算して `dict` で返す（I/O なし、テスト可能） |
| `OffsetConstraint.solve()` | `models.py` | `off_a`・`off_b`・`_eps_a`・`_eps_b` から直線 S の参照点を再計算する |
| `OffsetConstraint.calc_offsets_from_current()` | `models.py` | 現在の直線と 2 円の位置関係から `off_a`・`off_b`・`_eps_a`・`_eps_b` を算出して設定する |
| `TwoLineOffsetConstraint.solve()` | `models.py` | 2 直線の法線方程式から 2×2 連立方程式を解き、円 C の中心を再計算する |
| `TwoLineOffsetConstraint.calc_offsets_from_current()` | `models.py` | 現在の 2 直線と円の位置関係から `off_a`・`off_b`・`_eps_a`・`_eps_b` を算出して設定する |
| `Scene._fix_duplicate_ids()` | `models.py` | `to_dict()` の前に全図形の ID 重複を検出して振り直す |
| `Scene.renumber_ids()` | `models.py` | 全図形の ID を 1 から連番で付け直す。`Segment`/`Arc` のクロソイド整数参照とニックネームキーも追従更新 |
| `Scene.merge_from_dict(d)` | `models.py` | 既存シーンに JSON 辞書をマージ追記する。ID 衝突は `_resolve_id()` で解決。追加した図形のリストを返す |
| `Scene.get_nickname(id)` | `models.py` | 図形のニックネームを返す。未設定のとき `None` を返す |
| `Scene.display_name(id, type_label)` | `models.py` | ニックネーム設定済みならその値、未設定なら `(type_label#id)` 形式の文字列を返す（画面表示専用） |
| `effective_set(selected)` | `models.py` | 選択リストから代表の `Line`/`Circle`/`Clothoid` を `id()` 重複排除して返す。`Segment` → 親 `Line`、`Arc` → 親 `Circle` に昇格する |

---

## 9. resolve_chain アルゴリズム

平面線形要素のリストから走行チェーンの順序と向きを解決する。

**手順:**

1. 各要素の端点 `(start_pt, end_pt)` を `_elem_endpoints()` で取得する

2. 孤立端点（他のどの要素の端点とも `SNAP_TOL=1.0m` 以内にない端点）を持つ要素をチェーン先頭候補とする
   - 始点が孤立 → 正順（`rev=False`）で先頭
   - 終点が孤立 → 逆順（`rev=True`）で先頭

3. 既存 `ElementProfile` の `reversed_flag` と一致する候補を優先して先頭に選ぶ

4. 貪欲法でチェーンを構築する
   - 現在の末尾要素の出口端点から `SNAP_TOL*10` 以内で最も近い残り要素を次に追加
   - 見つからない場合は残り先頭を強制追加

---

## 10. テスト設計方針

### 10.1 テスト可能な範囲

以下のモジュール・関数は UI や外部 I/O に依存せず、単体テストが可能。

| 対象 | テスト内容 |
|---|---|
| `Vec2`（演算子・メソッド） | `dot` / `cross` / `normalized` / `perp` の計算結果 |
| `Line`（各メソッド） | `project_t` / `point_at` / `signed_dist` / `intersect` の計算 |
| `Arc`（各プロパティ） | `start` / `end` / `arc_angle` / `arc_length` の計算 |
| `Clothoid.compute()` | 接点座標・点列の生成（既知データとの比較） |
| `OffsetConstraint.solve()` | 距離拘束の充足・法線方向の維持・`feasible` フラグの変化 |
| `OffsetConstraint.calc_offsets_from_current()` | `off_a`・`off_b`・`_eps_a`・`_eps_b` の正確な算出 |
| `TwoLineOffsetConstraint.solve()` | 連立方程式による円中心の再計算・平行判定（`feasible=False`）・法線方向の維持 |
| `Scene.renumber_ids()` | ID の連番付け直し・クロソイド整数参照・ニックネームキーの追従 |
| `detect_constraint_cycle()` | 循環なし・OffsetConstraint→TwoLineOC の単純ループ・多段ループの検出 |
| `Scene.merge_from_dict()` | 追記後の ID 重複回避・追加図形リストの返却 |
| `Scene.display_name()` | ニックネーム設定済み/未設定の両ケース |
| `effective_set()` | Segment→Line/Arc→Circle の昇格・重複排除 |
| `ElementProfile.elev_at()` | 縦断曲線優先・勾配直線補間・範囲外の返り値 |
| `resolve_chain()` | 単一要素・複数要素・逆順要素の各ケース |
| `tangent_at()` / `entry_tangent()` | 各図形タイプでの接線ベクトル方向 |
| `Scene.to_dict()` / `from_dict()` | 往復シリアライズ・ID 衝突の自動修正 |
| `Scene._fix_duplicate_ids()` | メモリ上の ID 重複を検出・修正できること |
| `interp_cl()` | 空リスト・中間点・z 補間・境界値・末尾超過 |
| `bearing_str()` | N/NE/E/SE/S/SW/W/NW 全 8 方位 |
| `make_elem_cl()` | pts_xy あり/なし・forward/reverse・高さ補間・空 heights・末尾超過 |
| `find_next_candidates()` | 座標一致・Clothoid ref 一致・許容誤差外・複数候補 |
| `prepare_viewer_data()` | 中心線点数・標高の連続性（段差 < 0.01m） |
| `VerticalCurve.elevation_at()` | VPC〜VPT 内の放物線値・範囲外の NaN 返却 |

### 10.2 I/O 依存部分（モック必要）

| 処理 | 依存先 |
|---|---|
| `_write_file()` / `_open()` | `open()` / `json.load` / `QFileDialog`（PySide6 UI） |
| `launch_viewer()` | `subprocess.Popen` / `tempfile` |
| `Canvas` の描画 | `QPainter`（PySide6） |
| `RoadViewer` の描画 | Panda3D `ShowBase` |

### 10.3 仕様適合テスト（GUI・手動実行）

要求仕様書との適合を確認する GUI テスト群。`pytest.mark.spec` マーカーを付与し、CI では除外（`-m 'not spec'`）。ディスプレイのある環境で開発者が手動実行する。

| ファイル | 対象仕様書章 | 件数 |
|---|---|---|
| `test_spec_gui_ch4.py` | 第4章 平面線形編集（モード切替・直線/円追加・削除・Undo） | 23件 |
| `test_spec_gui_ch5.py` | 第5章 右パネル（マウス座標・プロパティ表示・削除ダイアログ・ニックネーム） | 21件 |
| `test_spec_gui_ch6.py` | 第6章 縦断線形ウィンドウ（モード切替・Undo/Redo） | 20件 |

実行方法:

```bash
uv run pytest -m spec tests/test_spec_gui_ch4.py tests/test_spec_gui_ch5.py tests/test_spec_gui_ch6.py -v
```

### 10.4 C1 カバレッジ達成の方針

- `models.py` の全クラス・ユーティリティ関数を優先的にカバーする（I/O 依存なし）
- `Clothoid.compute()` は τ の存在条件（`d > R` の場合・`d ≤ R` の場合）を両方テストする
- `resolve_chain()` は要素数 1・2・3以上・孤立端点なし（環状）の各ケースをカバーする
- `ElementProfile.elev_at()` は縦断曲線範囲内・範囲外・`GradeLine` のみ・両方なし の 4 ケースをカバーする
- `Scene.from_dict()` の ID 衝突ケース（`_resolve_id`）を専用テストでカバーする
- `OffsetConstraint.solve()` は成功ケース・距離拘束矛盾（`feasible=False`）・法線方向維持（2 円の間 vs 外側）の各ケースをカバーする
- `TwoLineOffsetConstraint.solve()` は成功ケース・2 直線が平行（`feasible=False`）・法線方向維持の各ケースをカバーする
- `effective_set()` は Segment→Line 昇格・Arc→Circle 昇格・重複排除の各ケースをカバーする
- `Scene.from_dict()` で `_resolve_id` による ID 振り直し後でも `lines_by_id` / `circles_by_id` のフォールバック参照でクロソイドが消えないことをテストする（ID 重複を含むファイルを細工したデータでロードするテスト）
