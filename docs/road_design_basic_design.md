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
| UI フレームワーク | PyQt6 |
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
  src/
    main.py             # エントリーポイント
    models.py           # データモデル・ユーティリティ
    canvas.py           # メイン編集キャンバス
    right_panel.py      # 右パネル
    main_window.py      # メインウィンドウ
    vertical_window.py  # 縦断線形設計ウィンドウ
    road_viewer.py      # 3D走行ビューア（別プロセス起動）
```

### 2.2 モジュール構成

| モジュール | 役割・概要 |
|---|---|
| `src/main.py` | エントリーポイント。`MainWindow` を生成して起動 |
| `src/models.py` | データモデル・ビジネスロジック・ユーティリティ関数（クロソイド計算、`resolve_chain` 等） |
| `src/canvas.py` | メイン編集キャンバス。描画・マウス操作・ハンドル管理 |
| `src/right_panel.py` | 右パネル。図形選択コンボ・プロパティ表示・操作ボタン |
| `src/vertical_window.py` | 縦断線形設計ウィンドウ（`ProfileCanvas` + `VerticalAlignmentWindow`） |
| `src/main_window.py` | メインウィンドウ。メニュー・ファイル操作・モジュール間シグナル接続 |
| `src/road_viewer.py` | 3D 走行ビューア（Panda3D、別プロセス起動）。中心線・道路メッシュ生成 |

### 2.3 コンポーネント間の依存関係

同一 `src/` 内のファイル同士は通常の `import` で参照する。循環依存は存在しない。

```
src/main.py
  └─ main_window.py
       ├─ canvas.py          ← models.py
       ├─ right_panel.py     ← models.py
       ├─ vertical_window.py ← models.py
       └─ road_viewer.py     ← models.py  （別プロセス）
```

### 2.4 シグナル設計

コンポーネント間の通知は PyQt6 シグナルを使用し、直接参照を避ける。

| シグナル | 発行元 | 接続先（スロット） |
|---|---|---|
| `selection_changed(list)` | `Canvas` | `MainWindow._on_selection_changed` / `RightPanel.update_selection` |
| `scene_changed()` | `Canvas` / `RightPanel` | `MainWindow._on_scene_changed` |
| `mouse_world_pos(float, float)` | `Canvas` | `RightPanel.update_mouse_pos` |
| `request_smooth_connect(Line, Line)` | `RightPanel` | `MainWindow._do_smooth_connect` |
| `request_polyline_connect(Line, Line)` | `RightPanel` | `MainWindow._do_polyline_connect` |
| `request_disconnect(Line, Line)` | `RightPanel` | `MainWindow._do_disconnect` |
| `request_add_clothoid(Line, Circle)` | `RightPanel` | `MainWindow._do_add_clothoid` |
| `request_delete_clothoid(Clothoid)` | `RightPanel` | `MainWindow._do_delete_clothoid` |
| `request_flip_clothoid(Clothoid)` | `RightPanel` | `MainWindow._do_flip_clothoid` |
| `request_select(list)` | `RightPanel` | `Canvas.set_selection` |
| `request_delete(list)` | `RightPanel` | `MainWindow._do_delete_objects` |

---

## 3. データモデル

### 3.1 クラス一覧

| クラス | 分類 | 説明 |
|---|---|---|
| `Vec2` | 基本型 | 2次元ベクトル。`dot` / `cross` / `normalized` / `perp` 等の演算を持つ |
| `Line` | 平面線形 | 参照始点・参照終点で定義される有向直線。`segments: list[Segment]` を保持 |
| `Segment` | 平面線形 | 直線の部分区間。`t_start` / `t_end`（0.0〜1.0）で位置を管理 |
| `LineConnection` | 接続情報 | 2直線の折れ線/スムーズ接続を管理。`kind: "polyline" \| "smooth"` |
| `Circle` | 平面線形 | 中心と半径で定義される円。`arcs: list[Arc]` を保持 |
| `Arc` | 平面線形 | 円の部分区間。`angle_start` / `angle_end`（ラジアン、CCW）で管理 |
| `Clothoid` | 平面線形 | 直線と円で定義されるクロソイド曲線。`compute()` で接点・点列を計算 |
| `ElementProfile` | 縦断線形 | 平面要素1つに対応する縦断データ。`grade_lines` + `vertical_curves` を保持 |
| `GradeLine` | 縦断線形 | 勾配直線。`dist_start` / `dist_end` ・ `elev_start` / `elev_end` で定義 |
| `VerticalCurve` | 縦断線形 | 縦断曲線（放物線）。`pvi_dist` / `pvi_elev` ・ `g1` ・ `g2` ・ `length` で定義 |
| `Scene` | 集約 | 全図形・`ElementProfile`・ニックネームを管理。`to_dict` / `from_dict` でシリアライズ |

### 3.2 Scene の構造

```
Scene
  lines:             list[Line]
    segments:        list[Segment]
  circles:           list[Circle]
    arcs:            list[Arc]
  clothoids:         list[Clothoid]
  element_profiles:  list[ElementProfile]
    grade_lines:     list[GradeLine]
    vertical_curves: list[VerticalCurve]
  nicknames:         dict[int, str]    # id → nickname
```

### 3.3 ID 管理

- 全図形（`Line`・`Segment`・`Circle`・`Arc`・`Clothoid`・`GradeLine`・`VerticalCurve`）の ID はタイプを通じてグローバルにユニーク
- `new_id()` でスレッドセーフに採番。`_id_counter` をグローバルに管理
- ファイル読み込み時は `_resolve_id()` で衝突を検出し、後から現れた ID を振り直す
- 読み込み後は全 ID の最大値 + 1 から採番を再開（`_reset_id_counter_after()`）

### 3.4 ファイル形式（.rdjson）

JSON 形式。各図形の `id` フィールドの直後に `nickname` を埋め込む。

```json
{
  "lines":    [{ "id": 1, "nickname": "my_line", "ref_start": {...}, "segments": [...] }],
  "circles":  [{ "id": 3, "nickname": "my_circle", "center": {...}, "arcs": [...] }],
  "clothoids":[{ "id": 5, "nickname": "clo_1", "line_id": 1, "circle_id": 3, ... }],
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

`push_undo()` で `Scene` 全体を JSON シリアライズしてスタックに積む。最大 500 手順。`Ctrl+Z` で `pop_undo()` を呼びリストアする。

### 6.2 RightPanel

右パネル（`right_panel.py`）。`QWidget` を継承。

#### 6.2.1 図形選択コンボボックス

複数のコンボボックスで平面線形要素をチェーン状に選択する。

- **1つ目**: 全図形を一覧表示
- **2つ目**: 1つ目の両端点に隣接する図形を先頭に表示（`[順]`/`[逆]` 付き）
- **3つ目以降**: 前の図形の出口端点に隣接する図形を先頭に表示
- 最後のコンボに図形が選択されると自動で1個追加

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

| メソッド | 役割 |
|---|---|
| `__init__` | 中心線・表示セグメントを受け取り `_build_scene()` を呼ぶ |
| `_build_scene()` | 路面・白線・橋脚・地面・HUD・キー設定を構築 |
| `_move_task(task)` | 毎フレーム呼ばれる走行タスク。`dist` を更新して `_update_car_pose()` を呼ぶ |
| `_update_car_pose(dist)` | `dist` の位置・姿勢を点列から補間してカメラ・車を配置 |
| `_toggle_surface()` | 路面メッシュ（`_surface_nodes`）の表示/非表示を切り替え |

---

## 8. ユーティリティ関数（models.py）

| 関数 | 説明 |
|---|---|
| `tangent_at(obj, at_end)` | `Segment` / `Arc` / `Clothoid` の始点/終点での接線単位ベクトルを返す |
| `entry_tangent(obj, connect_at_start)` | 「共有端点→近傍点」方向の単位ベクトルを返す |
| `resolve_chain(elems, eps)` | 要素リストからチェーン順序と `reversed_flags` を解決して返す。`SNAP_TOL=1.0m`、貪欲法 |
| `plan_length_of(obj)` | `Segment` / `Arc` / `Clothoid` の平面長を計算して返す |
| `prepare_viewer_data(...)` | 3D 中心線と表示セグメントを計算して `dict` で返す（I/O なし、テスト可能） |

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
| `ElementProfile.elev_at()` | 縦断曲線優先・勾配直線補間・範囲外の返り値 |
| `resolve_chain()` | 単一要素・複数要素・逆順要素の各ケース |
| `tangent_at()` / `entry_tangent()` | 各図形タイプでの接線ベクトル方向 |
| `Scene.to_dict()` / `from_dict()` | 往復シリアライズ・ID 衝突の自動修正 |
| `prepare_viewer_data()` | 中心線点数・標高の連続性（段差 < 0.01m） |
| `VerticalCurve.elevation_at()` | VPC〜VPT 内の放物線値・範囲外の NaN 返却 |

### 10.2 I/O 依存部分（モック必要）

| 処理 | 依存先 |
|---|---|
| `_write_file()` / `_open()` | `open()` / `json.load` / `QFileDialog`（PyQt6 UI） |
| `launch_viewer()` | `subprocess.Popen` / `tempfile` |
| `Canvas` の描画 | `QPainter`（PyQt6） |
| `RoadViewer` の描画 | Panda3D `ShowBase` |

### 10.3 C1 カバレッジ達成の方針

- `models.py` の全クラス・ユーティリティ関数を優先的にカバーする（I/O 依存なし）
- `Clothoid.compute()` は τ の存在条件（`d > R` の場合・`d ≤ R` の場合）を両方テストする
- `resolve_chain()` は要素数 1・2・3以上・孤立端点なし（環状）の各ケースをカバーする
- `ElementProfile.elev_at()` は縦断曲線範囲内・範囲外・`GradeLine` のみ・両方なし の 4 ケースをカバーする
- `Scene.from_dict()` の ID 衝突ケース（`_resolve_id`）を専用テストでカバーする
