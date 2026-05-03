# 道路設計アプリ 詳細設計書

---

## 目次

1. [models.py — データモデルとユーティリティ](#1-modelspy--データモデルとユーティリティ)
2. [canvas.py — メイン編集キャンバス](#2-canvaspy--メイン編集キャンバス)
3. [vertical_window.py — 縦断線形設計ウィンドウ](#3-vertical_windowpy--縦断線形設計ウィンドウ)
4. [road_viewer.py — 3D走行ビューア](#4-road_viewerpy--3d走行ビューア)
5. [right_panel.py — 右パネル](#5-right_panelpy--右パネル)
6. [main_window.py — メインウィンドウ](#6-main_windowpy--メインウィンドウ)

---

## 1. models.py — データモデルとユーティリティ

### 1.1 ID 管理（モジュールレベル）

#### `new_id() -> int`

グローバルカウンタ `_id_counter`（`itertools.count(1)` で初期化）から次の整数を取得して返す。

- **戻り値の範囲**: 1 以上の整数（呼び出しごとに単調増加）
- **スレッドセーフ**: `itertools.count` はアトミムなので Python GIL 下で安全
- **エッジケース**: アプリ起動中は減少しない。ファイル読み込み後は `_reset_id_counter_after` で再設定される

#### `_reset_id_counter_after(max_id: int)`

`_id_counter` を `max_id + 1` から再開する。ファイル読み込み後に呼ばれ、既存 ID との衝突を防ぐ。

- **入力範囲**: `max_id >= 0`
- **エッジケース**: `max_id = 0` のとき、次の ID は 1（通常起動と同じ）

---

### 1.2 `Vec2` クラス

2次元ベクトル。`dataclass` で実装。

#### `__add__(o)`, `__sub__(o)`, `__mul__(s)`, `__rmul__(s)`, `__neg__()`

成分ごとの演算。`__mul__` はスカラー倍。`__rmul__` は `s * v` の記法を可能にする。

#### `dot(o) -> float`

内積 `self.x * o.x + self.y * o.y` を返す。

- **例**: `Vec2(1,0).dot(Vec2(0,1))` → `0.0`（直交）、`Vec2(1,0).dot(Vec2(1,0))` → `1.0`

#### `cross(o) -> float`

2D 外積 `self.x * o.y - self.y * o.x` を返す。結果が正なら `o` は `self` の左側（CCW）。

- **例**: `Vec2(1,0).cross(Vec2(0,1))` → `1.0`（y方向は x方向の左）
- **例**: `Vec2(1,0).cross(Vec2(0,-1))` → `-1.0`（右側）

#### `length() -> float`

`math.hypot(self.x, self.y)` を返す。

- **エッジケース**: 零ベクトル `Vec2(0,0)` → `0.0`

#### `normalized() -> Vec2`

単位ベクトルを返す。長さが `1e-12` 未満のとき `Vec2(1, 0)` を返す（除算ゼロ防止）。

- **エッジケース**: 零ベクトル → `Vec2(1, 0)`（x 軸方向にフォールバック）

#### `perp() -> Vec2`

CCW 90° 回転したベクトル `Vec2(-self.y, self.x)` を返す。`direction` から `left_normal` を求めるときに使う。

- **例**: `Vec2(1,0).perp()` → `Vec2(0,1)`（x 軸方向を 90° 回転すると y 軸方向）

#### `to_dict() / from_dict(d)`

`{"x": float, "y": float}` との相互変換。

---

### 1.3 `Line` クラス

参照始点・参照終点で定義される有向直線。

#### `__init__(ref_start, ref_end, line_id=None)`

- `id`: `line_id` が `None` のとき `new_id()` で採番
- `segments`: 空リストで初期化
- `connection`: `None`（接続なし）

#### `direction` プロパティ

`(ref_end - ref_start).normalized()` を返す。

- **エッジケース**: `ref_start == ref_end` のとき `Vec2(1, 0)` にフォールバック（`normalized()` の挙動）

#### `angle` プロパティ

`math.atan2(dy, dx)` で方向角（ラジアン）を返す。範囲は `(-π, π]`。

#### `project_point(p: Vec2) -> Vec2`

点 p を直線に正射影した点（直線上の最近接点）を返す。

- **式**: `ref_start + direction * ((p - ref_start).dot(direction))`
- **例**: 直線が x 軸、`p=(3,4)` → `(3, 0)`

#### `project_t(p: Vec2) -> float`

点 p の直線上パラメータ t を返す（`ref_start=0`、`ref_end=1`）。直線の長さがゼロのとき `0.0` を返す。

- **範囲**: 値の範囲制限なし（直線の外側も返す）
- **例**: `ref_start=(0,0)`, `ref_end=(10,0)`, `p=(3,5)` → `0.3`

#### `point_at(t: float) -> Vec2`

パラメータ t の座標 `ref_start + (ref_end - ref_start) * t` を返す。

- **t=0** → `ref_start`、**t=1** → `ref_end`、**t=0.5** → 中点
- **境界値**: t は範囲制限なし（直線の外側も計算可能）

#### `distance_to(p: Vec2) -> float`

点 p から直線（無限長）への垂直距離（常に正）を返す。

- **式**: `|((p - ref_start).cross(direction))|`

#### `signed_dist(p: Vec2) -> float`

符号付き距離。直線の左側が正、右側が負。

- **式**: `direction.cross(p - ref_start)`
- **例**: 直線が x 軸正方向、`p=(0,5)` → `5.0`（左側=上が正）

#### `project(p: Vec2) -> Vec2`

`project_point()` の別名。`Clothoid.compute()` 内から互換用として呼ばれる。

#### `intersect(other: Line) -> Optional[Vec2]`

2直線の交点を返す。平行（外積 < 1e-12）のとき `None` を返す。

- **エッジケース**: 同一直線（完全一致）も `None` を返す（分母がゼロ）

#### `left_normal` プロパティ

`direction.perp()` を返す。`Vec2(-dy, dx)` で CCW 90° 回転した左法線。

---

### 1.4 `Segment` クラス

直線の部分区間。始点・終点は親 `Line` の `point_at(t)` で動的に計算する。

#### `__init__(line, t_start=0.0, t_end=1.0, seg_id=None)`

- `t_start`, `t_end` の範囲: 論理的には `[0, 1]` だが強制はしない（直線の外への延長も可能）
- **エッジケース**: `t_start >= t_end` は不正状態だが例外は投げない

#### `start` プロパティ

`line.point_at(t_start)` を返す。

#### `end` プロパティ

`line.point_at(t_end)` を返す。

#### `length() -> float`

`(end - start).length()` を返す。

- **エッジケース**: `t_start == t_end` のとき `0.0`

---

### 1.5 `LineConnection` データクラス

2直線の折れ線/スムーズ接続情報を保持するデータクラス。`line_a.connection` と `line_b.connection` が同一オブジェクトを参照する。

| フィールド | 型 | 説明 |
|---|---|---|
| `kind` | `str` | `"polyline"` または `"smooth"` |
| `line_a`, `line_b` | `Line` | 接続される2直線 |
| `shared_point` | `Vec2` | 共有参照点（交点）の座標 |
| `a_end_is_shared` | `bool` | `True`: `line_a.ref_end` が共有点 |
| `b_start_is_shared` | `bool` | `True`: `line_b.ref_start` が共有点 |
| `circle` | `Circle \| None` | スムーズ接続時の中間円 |
| `bisector_dir` | `Vec2 \| None` | 二等分線方向（スムーズ専用） |
| `line_j_reversed` | `bool` | スムーズ接続の J 直線の反転フラグ |
| `line_k_reversed` | `bool` | スムーズ接続の K 直線の反転フラグ |

---

### 1.6 `Circle` クラス

#### `__init__(center, radius, circle_id=None)`

- `arcs`: 空リストで初期化
- `bisector_origin`, `bisector_dir`: スムーズ接続時に設定される二等分線情報（`None` で初期化）

---

### 1.7 `Arc` クラス

円の部分区間。`angle_start` から CCW 方向に `angle_end` まで至る弧。

#### `arc_angle() -> float`

弧長角（常に正）を返す。`(angle_end - angle_start) % (2π)`。

- **エッジケース**: `angle_start == angle_end` → `0.0`（弧なし）
- **エッジケース**: 一周の弧（`angle_end = angle_start + 2π`）→ `2π` ではなく `0.0` になる。このケースは通常発生しない

#### `arc_length() -> float`

`radius * arc_angle()` を返す。

#### `start`, `end` プロパティ

`angle_start`, `angle_end` の円周上の座標を返す。

---

### 1.8 クロソイド計算関数（モジュールレベル）

#### `_fresnel_xy_tau(tau_end, R, n=500) -> tuple[float, float]`

クロソイド終点の局所座標変位 `(xe, ye)` を中点則で数値積分して返す。

- **引数**:
  - `tau_end`: 全偏角 `τ` [ラジアン]。`0` のとき `(0.0, 0.0)` を返す
  - `R`: 円半径 [m]（正の値）
  - `n`: 積分ステップ数（デフォルト 500）
- **計算**:
  - `L = 2R·τ`、`A² = R·L`
  - `ds = L/n`、各ステップの中点 `s = (i+0.5)*ds` で `cos(s²/2A²)` を積分
- **エッジケース**: `tau_end < 1e-9` → `(0.0, 0.0)` を即時返す
- **例**: `tau_end=π/4, R=50.0` → `(xe≈58.5, ye≈18.0)`（近似値）

#### `_find_tau(R, d_abs, max_tau=2π*0.999) -> Optional[float]`

Fresnel 条件 `ye(τ) = d_abs − R·cos(τ)` を満たす全偏角 `τ` を二分法（80 回）で求める。

- **引数**:
  - `R`: 円半径 [m]
  - `d_abs`: 円の中心から直線への垂直距離 [m]（常に正）
  - `max_tau`: 探索上限（ほぼ 2π）
- **戻り値**: 存在する場合は `τ`（`[1e-4, max_tau]` の範囲）、存在しない場合は `None`
- **存在条件**: `d_abs > R`（直線が円の外側にある場合のみ）
- **エッジケース**:
  - `d_abs <= R` → `None`（直線が円の内部または接線）
  - 両端点の `residual` が同符号 → `None`（解なし）
- **精度**: 80 回の二分法で区間が `(max_tau - 1e-4) / 2^80 ≈ 5.2e-27` に収束する

---

### 1.9 `Clothoid` クラス

#### `__init__(line, circle, reversed_flag=False, snap_segment=True, snap_arc=True, clothoid_id=None)`

- コンストラクタ末尾で `compute()` を自動呼び出す
- `_split_seg_ids`, `_split_arc_ids` は空リストで初期化

#### `_effective_line() -> Line`

`reversed_flag=True` のとき `ref_start` と `ref_end` を入れ替えた仮想 `Line` オブジェクトを返す。フィールド (`id`, `segments`, `connection`) は元の `Line` と共有する。

#### `is_left_curve` プロパティ

実効直線の `signed_dist(circle.center)` が正（円の中心が左側）のとき `True`。

#### `_A` プロパティ

クロソイドパラメータ `A = R * sqrt(2τ)` を返す。無効（`is_valid=False`）のとき `0.0`。

#### `effective_direction` プロパティ

`_effective_line()` の `(ref_end - ref_start).normalized()` を返す。`reversed_flag=True` のとき `direction` が反転した向きになる。

- **エッジケース**: `reversed_flag=True` かつ `ref_start == ref_end` → `Vec2(1, 0)` にフォールバック（`normalized()` の挙動）

#### `effective_ref_start` プロパティ

`_effective_line().ref_start` を返す。`reversed_flag=False` なら `line.ref_start`、`True` なら `line.ref_end`。クロソイドの接点計算（`compute()`）で方向・始点として使う。

#### `line_contact` プロパティ

`_line_pt`（線側接点座標）を返す。無効なとき `None`。`_line_pt` は `compute()` で計算・キャッシュされる。

#### `circle_contact` プロパティ

`_circle_pt`（円側接点座標）を返す。無効なとき `None`。

#### `points` プロパティ

描画点列 `_points`（`Vec2` リスト）を返す。`_line_pt` から `_circle_pt` の順。無効なとき空リスト。

#### `is_valid` プロパティ

`_valid` フラグを返す。`compute()` が成功した場合に `True`。失敗条件:
- `circle.radius < 1e-9`
- `d_abs <= R`（直線が円の内部または接線）
- `_find_tau()` が `None` を返した（解なし）

#### `compute()`

接点座標と描画点列を計算する。無効状態のとき `_valid=False`、`_points=[]`、`_line_pt=None`、`_circle_pt=None` を設定する。

有効なとき:
1. `_find_tau()` で `τ` を求める
2. `_fresnel_xy_tau()` で `xe` を計算
3. 接点 `cc`（円側）と `lc`（線側）を計算
4. 等接線角度変化方式で点列を生成（`n_steps = max(80, int(τ/(2π)*512)+40)` 点）
5. `_update_snaps()` を呼んで snap を反映する

#### `_update_snaps()`

`snap_segment` と `snap_arc` の状態に応じて下記を呼び分ける。

| snap 状態 | 呼び出すメソッド |
|---|---|
| `snap_segment=True` | `_apply_segment_snap()` |
| `snap_segment=False` | `_apply_segment_split()` |
| `snap_arc=True` | `_apply_arc_snap()` |
| `snap_arc=False` | `_apply_arc_split()` |

#### `_apply_segment_snap()`

線側接点 `_line_pt` に最も近い線分の端点（`t_end` または `t_start`）を接点の t 値に移動する。

- `reversed_flag=False` → 線分の `t_end` を移動
- `reversed_flag=True` → 線分の `t_start` を移動
- **エッジケース**: 移動後に `t_start >= t_end` になる場合、反対の端点を 0.1 だけ離す

#### `_apply_segment_split()`

線側接点 X で線分 AB を AX・XB に分割する。

- 既に `_split_seg_ids` が設定済みの場合は端点を追従更新のみ行う（再分割しない）
- 分割対象: `_split_seg_ids` 以外の線分のうち、接点に最も近いもの
- 接点が線分の端点に非常に近い（`t_x <= t_start + 1e-6` または `t_x >= t_end - 1e-6`）場合は分割しない
- **エッジケース**: 線分がない場合は何もしない

#### `_clear_segment_split()`

`_split_seg_ids` の2本目の線分（XB）を削除し、1本目（AX）の `t_end` を 2 本目の元の `t_end` に戻す。`_split_seg_ids` をクリアする。

#### `_apply_arc_snap()`

円側接点 `_circle_pt` の角度に最も近い円弧の端点を接点の角度に移動する。

- 左カーブ → 円弧の `angle_start` を移動
- 右カーブ → 円弧の `angle_end` を移動
- 円弧がない場合: 自動生成（中心角 45° の円弧）
  - 左カーブ: `angle_start=angle_contact`, `angle_end=angle_contact+π/4`
  - 右カーブ: `angle_start=angle_contact-π/4`, `angle_end=angle_contact`

#### `_apply_arc_split()`

円側接点 X で円弧を（start→X）と（X→end）に分割する。

- 既に `_split_arc_ids` が設定済みの場合は端点を追従更新のみ
- 分割対象: 接点 X が内部に含まれる円弧（`1e-4 < rel < span - 1e-4`）
- **エッジケース**: 接点が端点に非常に近い場合は分割しない

#### `_clear_arc_split()`

`_split_arc_ids` の 2 本目の円弧を削除し、1 本目の `angle_end` を 2 本目の元の `angle_end` に戻す。

#### `_dist_to_seg(pt, seg) -> float` （静的メソッド）

点 `pt` から線分 `seg` への最短距離を返す。線分の長さがゼロ（`l2 < 1e-12`）のとき始点からの距離を返す。

---

### 1.10 `plan_length_of`（モジュールレベル関数）(obj) -> float

| 入力型 | 計算式 |
|---|---|
| `Segment` | `obj.length()`（= `(end-start).length()`） |
| `Arc` | `obj.arc_length()`（= `radius * arc_angle()`） |
| `Clothoid` | `2 * R * τ`（`is_valid=False` または `τ=0` なら `0.0`） |
| その他 | `0.0` |

---

### 1.11 `ElementProfile` データクラス

#### `elev_at(rel: float) -> float`

相対距離 `rel` [m] での標高を返す。

- **引数の前処理**: `rel = max(0.0, min(rel, plan_length))`（クリップ）
- **優先順位**:
  1. `VPC - 0.001 ≤ rel ≤ VPT + 0.001` の `VerticalCurve` → 放物線式。`NaN` なら次へ
  2. `dist_start - 0.001 ≤ rel ≤ dist_end + 0.001` の `GradeLine` → 線形補間
  3. 見つからない → `0.0`
- **エッジケース**:
  - `grade_lines=[]`, `vertical_curves=[]` → `0.0`
  - 境界点（`rel=0` や `rel=plan_length`）は両隣の GL と 0.001m の許容で検索
  - `GradeLine` の `dist_end - dist_start < 1e-9` → 補間比 `t=0.0`（`elev_start` を返す）
- **例**:
  - GL: `dist_start=0, elev_start=10, dist_end=100, elev_end=20`
  - `elev_at(50)` → `15.0`、`elev_at(0)` → `10.0`、`elev_at(100)` → `20.0`

---

### 1.12 `GradeLine` データクラス

#### `gradient` プロパティ

`(elev_end - elev_start) / (dist_end - dist_start) * 100` [%]。`dist_end - dist_start < 1e-9` のとき `0.0`。

---

### 1.13 `VerticalCurve` データクラス

#### 派生プロパティ

| プロパティ | 計算式 |
|---|---|
| `vpc_dist` | `pvi_dist - length/2` |
| `vpt_dist` | `pvi_dist + length/2` |
| `vpc_elev` | `pvi_elev - g1/100 * length/2` |
| `vpt_elev` | `pvi_elev + g2/100 * length/2` |
| `K` | `length / |g2-g1|`（`\|g2-g1\| < 1e-9` なら `inf`） |

#### `elevation_at(dist: float) -> float`

局所距離 `x = dist - vpc_dist` での標高を返す。

- **有効範囲**: `0 ≤ x ≤ length`
- **範囲外**: `float('nan')` を返す
- **式**: `vpc_elev + (g1/100)*x + ((g2-g1)/(2*length)/100)*x²`
- **例**: `g1=2%, g2=0%, L=100m, vpc_elev=10.0`
  - `x=0` → `10.0m`、`x=50` → `10 + 1.0 - 0.5 = 10.5m`、`x=100` → `10 + 2.0 - 2.0 = 10.0m`
- **エッジケース**: `x < 0` または `x > length` → `nan`

---

### 1.14 `Scene` クラス

#### `get_nickname(obj_id, prefix="") -> str`

`nicknames[obj_id]` を返す。未設定のとき `f"nickname_{prefix}_{obj_id}"` を返す。

#### `set_nickname(obj_id, name)`

`name` が空文字のとき `nicknames` から削除する。

#### `add_line / add_circle / add_clothoid`

図形をリストに追加し、デフォルトニックネームを設定する（既存ニックネームは上書きしない）。

#### `remove_line(line)`

関連クロソイド（`c.line is line`）を先に削除してから `lines` から除去する。

#### `remove_circle(circle)`

関連クロソイド（`c.circle is circle`）を先に削除してから `circles` から除去する。

#### `clothoids_for(line, circle) -> list[Clothoid]`

`line` と `circle` の両方を参照するクロソイドをリストで返す。

#### `connected_objects(obj) -> list`

`obj` に接続している図形の一覧を返す。

| obj の型 | 返す内容 |
|---|---|
| `Line` | 参照するクロソイド + 接続中の相手直線 |
| `Circle` | 参照するクロソイド |
| `Clothoid` | 参照する直線と円 |

#### `to_dict() / from_dict(d)`

**to_dict**: 全図形を JSON シリアライズ可能な dict に変換する。各図形の `id` の直後に `nickname` を挿入する。

**from_dict**: 以下の順序で復元する:
1. `lines`（`segments` を含む）→ `lines_by_id` に格納
2. `circles`（`arcs` を含む）→ `circles_by_id` に格納
3. `clothoids`（`line_id`, `circle_id` で参照解決）
4. `element_profiles`, `vertical_alignments`
5. 旧フォーマット互換（トップレベルの `grade_lines`/`vertical_curves`）
6. 全 ID の最大値 + 1 でカウンタを再設定

**ID 衝突検出（`_resolve_id`）**: `seen_ids` セットで衝突を検出し、衝突した ID は `new_id()` で振り直す。

---

### 1.15 ユーティリティ関数（モジュールレベル）

#### `_elem_endpoints(obj) -> tuple[Optional[Vec2], Optional[Vec2]]`

要素の `(start_pt, end_pt)` を返す。`resolve_chain()` 内で使用する。

| 型 | start_pt | end_pt |
|---|---|---|
| `Segment` | `seg.start` | `seg.end` |
| `Arc` | `arc.start` | `arc.end` |
| `Clothoid`（有効） | `clo._line_pt` | `clo._circle_pt` |
| `Clothoid`（無効）/その他 | `None` | `None` |

#### `_pt_dist(a, b) -> float`

2点間の距離を返す。いずれかが `None` のとき `float('inf')` を返す。`resolve_chain()` 内で端点距離の比較に使用する。

#### `tangent_at(obj, at_end: bool) -> tuple[float, float]`

図形の始点（`at_end=False`）または終点（`at_end=True`）での接線単位ベクトルを `(dx, dy)` で返す。

| 図形 | at_end=False | at_end=True |
|---|---|---|
| `Segment` | `start → end` 方向（正規化） | 同じ（線分は全域で一定） |
| `Arc` | `angle_start` での接線 `(-sin, cos)` | `angle_end` での接線 |
| `Clothoid` | `points[1] - points[0]` 方向 | `points[-1] - points[-2]` 方向 |

- **エッジケース**:
  - `Clothoid.points` が 2 点未満 → `(1, 0)` を返す
  - 長さゼロのベクトル → 正規化で `(1, 0)` にフォールバック

#### `entry_tangent(obj, connect_at_start: bool) -> Optional[tuple]`

「共有端点→近傍点」方向の単位ベクトルを返す。`[順]/[逆]` 判定に使用。

| 図形 | connect_at_start=True | connect_at_start=False |
|---|---|---|
| `Segment` | `start → end` | `end → start` |
| `Arc` | `angle_start` から `+0.1°` 方向 | `angle_end` から `−0.1°` 方向 |
| `Clothoid` | `points[0] → points[1]` | `points[-1] → points[-2]` |

- **エッジケース**: `Clothoid.points` が 2 点未満 → `None`
- その他の型 → `None`

#### `resolve_chain(elems, element_profiles=None) -> tuple[list, list[bool]]`

要素リストからチェーン順序と `reversed_flags` を解決して返す。詳細は基本設計書 9 章を参照。

- **入力**: `elems` が空リスト → `([], [])` を返す
- **入力**: `elems` が 1 要素 → EP の `reversed_flag` をそのまま使う（EP がなければ `False`）
- **エッジケース**: 全要素が環状（孤立端点なし）の場合 → `candidates` が空になり `elems[0]` を強制先頭とする

---

## 2. canvas.py — メイン編集キャンバス

### 2.1 モジュールレベル定数

| 定数 | 値 | 説明 |
|---|---|---|
| `HIT_DIST` | `8` | ヒット判定の許容距離（スクリーンピクセル） |
| `HANDLE_R` | `6` | ハンドルの描画半径（ピクセル） |

### 2.2 `Handle` データクラス

ハンドルの描画・操作情報を保持するデータクラス。

| フィールド | 型 | 説明 |
|---|---|---|
| `pos` | `Vec2` | ワールド座標でのハンドル位置 |
| `color` | `QColor` | 描画色 |
| `tag` | `str` | ハンドルの種別識別子（例: `"ref_start"`, `"arc_end"`, `"radius"`） |
| `owner` | `Any` | このハンドルが属する図形オブジェクト |

### 2.2b モジュールレベルユーティリティ（canvas.py）

#### `qp(v: Vec2) -> QPointF`

`Vec2` を `QPointF` に変換するユーティリティ関数。`QPainter` の各描画メソッドに渡す際に使用する。

---

### 2.3 `Canvas` クラス

#### `__init__(scene, parent=None)`

初期状態:
- `_scale = 1.0`（1 px/m）
- `_offset = Vec2(width/2, height/2)`（中心原点）
- `mode = MODE_SELECT`
- `_undo_stack = []`（最大 500 エントリ）

#### `w2s(p: Vec2) -> QPointF`

ワールド座標 → スクリーン座標変換。

```
screen_x =  p.x * scale + offset.x
screen_y = -p.y * scale + offset.y   # y 反転
```

#### `s2w(x, y) -> Vec2`

スクリーン座標 → ワールド座標変換（`w2s` の逆変換）。

#### `s2w_qp(p: QPointF) -> Vec2`

`QPointF` を受け取る `s2w` のラッパー。

#### `scale_w2s(d) -> float`

ワールド距離 → スクリーン距離変換（`d * scale`）。

#### `scale_s2w(d) -> float`

スクリーン距離 → ワールド距離変換（`d / scale`）。

#### `set_mode(mode: str)`

描画モードを変更する。副作用:
- `_line_first_pt`, `_last_line`, `_rubber_end`, `_circle_center` をリセット
- 選択モード → 矢印カーソル、それ以外 → 十字カーソル
- `update()` で再描画

#### `push_undo()`

現在の Scene を `scene.to_dict()` で JSON シリアライズしてスタックに積む。500 件を超えると先頭を削除する（FIFO）。

#### `undo()`

スタックから最新の状態を取り出し `Scene.from_dict()` で復元する。選択・ハンドルをクリアして `selection_changed`・`scene_changed` を emit する。

- **エッジケース**: スタックが空のとき何もしない

#### `set_selection(objs: list)`

選択図形を更新し `_rebuild_handles()` を呼ぶ。`selection_changed` を emit する。

#### `_rebuild_handles()`

選択中の図形に応じてハンドルを生成する。選択図形の組み合わせによって異なるハンドルが生成される。

**1直線選択時**:
- `"ref_start"`, `"ref_end"`: 参照点ハンドル（灰色）
- `"seg_start"`, `"seg_end"`: 線分端点ハンドル（赤色）。snap 済みの端点はハンドルを生成しない
- 接続中の場合: 共有参照点ハンドル（橙色、1つのみ）

**1円選択時**:
- `"circle_center"`: 中心ハンドル（灰色）
- `"radius"`: 半径ハンドル（緑色、右端 `center + (radius, 0)`）
- `"arc_start"`, `"arc_end"`: 円弧端点ハンドル（赤色）。snap 済みの端点はスキップ

#### `is_shared(pt: Vec2) -> bool`（`_rebuild_handles` 内ヘルパー）

点 `pt` が他の線分・円弧・クロソイドの端点と `SNAP_TOL` 以内かどうかを確認する。`True` のとき当該端点のハンドルを生成しない（snap 済みマーカーとして扱う）。

#### `_hit_handle(sw: Vec2) -> Optional[Handle]`

スクリーン座標 `sw` に対して最初にヒットしたハンドルを返す。判定距離 `HIT_DIST=8px`。

#### `_hit_object(sw: Vec2) -> Optional[object]`

ワールド座標でのヒット判定。優先順位（高→低）:
1. クロソイド（折れ線近接）
2. 円弧（円上 ± tol かつ角度範囲内）
3. 円（円周 ± tol）
4. 線分（線分近接）
5. 直線（無限直線への距離）

各リストを `reversed()` で走査するため、後から追加した図形が優先される。

#### `_hit_polyline(pts, w, tol) -> bool`

連続する点列の各線分に対して `_dist_point_segment` を計算し、いずれかが `tol` 未満なら `True`。

#### `_hit_segment_line(a, b, w, tol) -> bool`

`_dist_point_segment(w, a, b) < tol` を返す。

#### `_hit_infinite_line(ln, w, tol) -> bool`

`ln.distance_to(w) < tol` を返す。

#### `_hit_arc(ci, arc, w, tol) -> bool`

`|dist(w, center) - radius| < tol` かつ `_angle_in_arc` が `True` のとき `True`。

#### `_angle_in_arc(ang, a_start, a_end) -> bool`

角度 `ang` が `[a_start, a_end)` の CCW 範囲内にあるか判定する。

- **式**: `(ang - a_start) % (2π) <= (a_end - a_start) % (2π)`
- **エッジケース**: `a_start == a_end` → `(ang - a_start) % 2π <= 0` → 境界点のみ `True`

#### `_dist_point_segment(p, a, b) -> float`

点 p から線分 AB への最短距離。

- `l2 = AB·AB < 1e-24` → 点 A との距離を返す（縮退した線分）
- そうでない場合: パラメータ `t = clamp((p-a)·(b-a)/l2, 0, 1)` で射影点を求め距離を返す

#### `fit_all()`

全図形の AABB（Axis-Aligned Bounding Box）を計算し、10% マージンを付けて画面全体に収まるようスケールとオフセットを設定する。

- **エッジケース**: 図形がない場合、`_offset` を画面中央に、`_scale` を `1.0` にリセット
- **エッジケース**: 全図形が1点に集中している場合（`mx=max(xmax-xmin,1.0)` で最小 1m 確保）

#### `paintEvent(event)`

シーン全体を描画する。描画順:
1. グリッド（`_draw_grid`）
2. 参照線（破線）
3. 線分
4. 円（弧なし）/ 円弧
5. クロソイド + 接点マーカー
6. ラバー線（入力中）
7. ハンドル

#### `_color_for(obj, base) -> QColor`

選択中 → 黄橙色（`#FFA500`）、ホバー中 → 黄色（`#FFFF00`）、それ以外 → `base`。

#### `_draw_grid(painter)`

スクリーンを覆うグリッド線を描画する。スケールに応じてグリッド間隔を動的に選択する（1m/5m/10m/50m/100m）。

#### `_draw_line_ref(painter, ln)`

参照線（`ref_start` から `ref_end` への破線）とニックネームラベルを描画する。

#### `_draw_segment(painter, seg)`

線分を青色の実線で描画する。

#### `_draw_circle(painter, ci)`

円弧があれば薄紫の点線、なければ紫の実線で円全体を描画する。

#### `_draw_arc(painter, arc)`

紫色の太い実線で円弧を描画する。`QPainter.drawArc` に `angle_start` と `arc_angle` を `* 16` して渡す（Qt の角度単位は 1/16 度）。

#### `_draw_clothoid(painter, clo)`

クロソイドの点列を折れ線で描画する。snap 状態に応じて接点マーカーを描画する:
- `snap_segment=True` → `_line_pt` に菱形マーカー（黄色）
- `snap_arc=True` → `_circle_pt` に菱形マーカー（橙色）

#### `_draw_contact_diamond(painter, pt, color, size=8)`

接点マーカーを菱形（4頂点のポリゴン）で描画する。

#### `_draw_rubber(painter)`

入力中のラバー線を描画する。直線モードでは始点から現在カーソルまでの点線、円モードでは中心から半径の円。

#### `_draw_handles(painter)`

`_handles` リストの全ハンドルを塗りつぶし円で描画する（半径 `HANDLE_R=6px`）。

#### `mousePressEvent(event)`

- 左ボタン + 選択モード: ハンドルヒット → ドラッグ開始。図形ヒット → 選択更新（Shift で複数選択）。ヒットなし → 選択解除
- 左ボタン + 直線モード: `_line_click(w)`
- 左ボタン + 円モード: 中心点を記憶
- 中ボタン: パン開始

#### `mouseMoveEvent(event)`

- ドラッグ中: `_do_drag(w)` で図形変形
- ハンドル外: ホバーオブジェクト更新 + マウス座標 emit
- パン中: `_offset` を更新

パン判定: マウスダウンからの移動が 4px 未満はパン開始しない（クリックと区別）。

#### `mouseReleaseEvent(event)`

- ドラッグ中: `push_undo()` + `scene_changed.emit()` でコミット
- 円モード左ボタンリリース: 中心・半径で `Circle` を生成して Scene に追加
- 4px 未満の移動: クリックとして扱い選択解除

#### `wheelEvent(event)`

マウス位置を中心にズーム。スケール変更比 = `1.15^(steps)` where `steps = angleDelta.y() / 120`。

- ズームイン/アウト後もマウス位置のワールド座標を一定に保つよう `_offset` を補正する
- **エッジケース**: `steps=0` の場合はズームしない

#### `keyPressEvent(event)`

| キー | 処理 |
|---|---|
| `S` | `set_mode(MODE_SELECT)` |
| `L` | `set_mode(MODE_LINE)` |
| `C` | `set_mode(MODE_CIRCLE)` |
| `Del` | `_delete_selected()` |
| `Ctrl+0` | `fit_all()` |
| `Esc` | 直線モードの連続入力リセット |

#### `_line_click(w: Vec2)`

直線モードでの左クリック処理。

- **1回目**: 始点を記憶（`_line_first_pt`）し、Scene に `Line` を追加
- **2回目以降**: 前の直線の終端に新しい直線を折れ線接続。前の直線の `ref_end` を共有参照点に設定

#### `_connect_polyline(a: Line, b: Line)`

2直線の折れ線接続を設定する。交点を計算し `LineConnection(kind="polyline")` を生成して両直線に設定する。交点がない（平行）場合は何もしない。

#### `_do_drag(w: Vec2)`

ドラッグ中にアクティブハンドルの位置を更新する。ハンドルの `tag` によって処理を分岐する。

| tag | 処理 |
|---|---|
| `"ref_start"` / `"ref_end"` | 参照点を移動 → `_propagate_line()` |
| `"shared_ref"` | 共有参照点を移動 → 両直線の参照点を更新 → 各直線を propagate |
| `"circle_center"` | 中心を移動（スムーズ接続時は bisector 上に束縛）→ `_propagate_circle()` |
| `"radius"` | 半径を更新（中心からの距離）→ `_propagate_circle()` |
| `"seg_start"` / `"seg_end"` | `t_start` / `t_end` を直線に射影して更新 |
| `"arc_start"` / `"arc_end"` | `angle_start` / `angle_end` を更新 → `_propagate_circle()` |

#### `_propagate_line(ln, _updating_smooth=False)`

直線変更をクロソイドと SegmentSnap に伝播する。

1. `ln` を参照するクロソイドに `compute()` を呼ぶ
2. `_propagate_segment_snaps(ln)` で SegmentSnap 追従
3. `_updating_smooth=False` かつスムーズ接続中のとき `_update_smooth_circle(conn)` を呼ぶ

#### `_propagate_segment_snaps(ln)`

`SegmentSnap` で繋がれた線分の端点を追従させる。`ln` が変更された場合に相手側の `t_start` / `t_end` を更新する。

#### `_propagate_circle(ci)`

円変更をクロソイドと ArcSnap に伝播する。

#### `_propagate_arc_snaps(ci)`

`ArcSnap` で繋がれた円弧の端点角度を追従させる。

#### `_update_smooth_circle(conn)`

スムーズ接続の円中心を現在の2直線の交点・二等分線に合わせて再配置する。

1. 新しい交点 `new_ix` を計算
2. 二等分線 `bisect = normalize(dP + dQ)` を計算
3. 現在の円中心の `bisector` 上の t 値（距離）を保って新しい中心を設定
4. 両直線の参照点を交点に揃える
5. 関連クロソイドを `compute()` で更新

- **エッジケース**: 2直線が平行（交点なし）→ 何もしない
- **エッジケース**: `bisect_sum.length() < 1e-9`（180° の折れ線）→ 何もしない

#### `_delete_selected()`

選択中の図形を削除する。削除前に `push_undo()` を呼ぶ。`Line` / `Circle` の削除時は `scene.remove_*()` 経由で関連クロソイドも自動削除する。

#### `smooth_connect(line_a, line_b) -> bool`

スムーズ接続を実行する。失敗条件:
- いずれかの直線に線分がない → `False`
- 2直線が平行（交点なし）→ `False`
- 二等分線が零ベクトル（180° の折れ線）→ `False`

成功時は `push_undo()` を呼び、円・クロソイド2本を生成して Scene に追加する。

**デフォルト半径**: `R_default=50.0m`、`d_default = R_default * 1.5 = 75.0m`（クロソイド存在条件 `d/R > 1` を満たす）

#### `far_end(ln, shared)` （`smooth_connect` / `_update_smooth_circle` 内ヘルパー）

直線 `ln` の参照点のうち `shared` から遠い方を返す。`smooth_connect` では `X` と反対側の端点 `P`, `Q` を特定するために使用する。

```python
ds = (ln.ref_start - shared).length()
de = (ln.ref_end   - shared).length()
return ln.ref_start if ds >= de else ln.ref_end
```

- **エッジケース**: `ds == de`（両端点が等距離）→ `ref_start` を返す

#### `disconnect_lines(line_a, line_b)`

`line_a.connection` と `line_b.connection` を `None` に設定する。`push_undo()` を呼ぶ。

---

## 3. vertical_window.py — 縦断線形設計ウィンドウ

### 3.1 `ProfileCanvas` クラス

#### `__init__(scene, parent=None)`

初期状態:
- `_scale_x = 2.0`（ピクセル/m）、`_scale_y = 5.0`（ピクセル/m）
- `_offset = Vec2(100, 400)`（距離=0 を x=100px、標高=0 を y=400px に対応）
- `_grade_lines = []`, `_vertical_curves = []`
- `HANDLE_R = 7`（ハンドル半径）
- `COLORBAR_H = 24`（カラーバーの高さ px）

#### `set_plan_elements(elements, profiles, rev_flags=None)`

チェーン全体の `ElementProfile` を統合して描画用データを構築する。

1. 各 EP の累積オフセット `offsets` を計算
2. 各 EP の `grade_lines` を累積距離に変換（`rev=True` のとき dist と elev を反転）
3. 各 EP の `vertical_curves` を累積距離に変換（`rev=True` のとき g1/g2 を符号反転）
4. `_grade_lines` を `dist_start` でソート
5. `_snap_grade_lines('both')` で境界標高を揃える

- **rev=True の逆順変換**:
  - `dist_start_merged = offset + (L - dist_end_orig)`
  - `elev_start_merged = elev_end_orig`（始端と終端が入れ替わる）
  - VerticalCurve: `g1 = -g2_orig`, `g2 = -g1_orig`

#### `save_to_profiles()`

チェーン全体の `_grade_lines` / `_vertical_curves` を各 EP の距離範囲に切り出して保存する。

- 各 EP について、`d_start = offset`〜`d_end = offset + L` の範囲で GL をクリップ
- `rev=True` の EP は逆順に戻して保存（dist・elev を反転）
- VC も同様に `pvi_dist` でクリップして保存
- 保存後に `ep.elev_start = ep.elev_at(0.0)`、`ep.elev_end = ep.elev_at(L)` を更新

#### `_elev_at(dist, gl) -> float`（静的メソッド）

勾配直線 1 本の上の線形補間標高を返す。`|dist_end - dist_start| < 1e-9` のとき `elev_start` を返す。

#### `w2s(dist, elev) -> QPointF`

縦断座標（累積距離、標高）→ スクリーン座標変換。

```
screen_x =  dist * scale_x + offset.x
screen_y = -elev * scale_y + offset.y   # y 反転
```

#### `s2w(sx, sy) -> tuple[float, float]`

`w2s` の逆変換。`(dist, elev)` を返す。

#### `wheelEvent(event)`

- 通常ホイール: `scale_x` を変更（距離方向）
- `Shift` + ホイール: `scale_y` を変更（標高方向）

スケール変更比 = `1.15^steps`。最小値 `0.01`、最大値 `1000`。

#### `_grade_lines_sorted() -> list`

`_grade_lines` を `dist_start` の昇順でソートして返す。

#### `_vc_for_pvi(dist) -> Optional[VerticalCurve]`

`|vc.pvi_dist - dist| < 0.01` を満たす縦断曲線を返す（先頭優先）。

#### `_vc_at(dist) -> Optional[VerticalCurve]`

`VPC - 0.001 ≤ dist ≤ VPT + 0.001` を満たす縦断曲線を返す（先頭優先）。

#### `_elevation_at(dist) -> Optional[float]`

`dist` での標高を返す。縦断曲線が優先。いずれも該当しない場合 `None`。

#### `_snap_grade_lines(changed_end='both')`

隣接する勾配直線の端点を強制一致させる。

- **`'end'`**: 前→後方向に伝播。`gls[i].dist_end / elev_end` → `gls[i+1].dist_start / elev_start`
- **`'start'`**: 後→前方向に伝播。`gls[i].dist_start / elev_start` → `gls[i-1].dist_end / elev_end`
- **`'both'`**: 'end' 方向 → 'start' 方向 の順に実行

- **エッジケース**: `_grade_lines` が空 → 何もしない

#### `_get_handles() -> list[dict]`

勾配直線の全端点にハンドル辞書を生成する。隣接する GL の境界点（`dist` が 0.01m 以内）は共有ハンドルに統合する。

各ハンドル辞書: `{'dist': float, 'elev': float, 'partners': list[(GradeLine, str)]}`

#### `_hit_handle(sx, sy) -> Optional[dict]`

スクリーン座標でハンドルヒット判定を行う。選択モード以外は常に `None`。距離 `HANDLE_R + 2 = 9px` 以内。

#### `paintEvent(event)`

描画順:
1. グリッド（`_draw_grid`）
2. カラーバー（`_draw_colorbar`）
3. 縦断プロファイル（`_draw_profile`）
4. ラバー線（`_draw_rubber`）
5. 軸ラベル（`_draw_axes`）
6. ハンドル（`_draw_handles`）

#### `_draw_colorbar(painter)`

平面線形要素を累積距離に応じた幅のバーで描画する。要素の色: 線分=青、クロソイド=緑、円弧=紫。ニックネームラベルを上部に表示する。

#### `_element_length(elem) -> float`

`plan_length_of()` の縦断ウィンドウ内でのラッパー。

#### `_element_color(elem) -> QColor`

`Segment` → 青、`Clothoid` → 緑、`Arc` → 紫。その他 → グレー。

#### `_draw_profile(painter)`

勾配直線を折れ線で描画する。縦断曲線の VPC〜VPT 範囲は放物線（多数の短い線分）で描画する。

#### `_make_empty_profile()` （`ProfileCanvas` 内）

`GradeLine` も `VerticalCurve` も持たない空の `ElementProfile` を生成して返す。`set_plan_elements()` で EP が存在しない要素のダミーとして使用する。

#### `_dist_point_seg(sx, sy, ax, ay, bx, by) -> float`

スクリーン座標での点と線分間の距離を返す。`_hit_test()` 内で使用。縮退した線分（`l2 < 1e-24`）のとき始点からの距離を返す。

#### `fit_all()`

全勾配直線と全縦断曲線の VPC/VPT を含む AABB を計算し、余白 10% で画面全体に収まるようスケールとオフセットを設定する。図形がない場合はデフォルト値（`scale_x=2.0, scale_y=5.0`）にリセットする。

---

### 3.2 `VerticalAlignmentWindow` クラス

縦断線形設計ウィンドウ本体（`QMainWindow` を継承）。

#### `__init__(scene, profiles, plan_elements, rev_flags, parent=None)`

`ProfileCanvas` と右パネル（プロパティ・操作ボタン）を `QSplitter` で左右に分割して配置する。初期比率は 700:300。`ProfileCanvas` の `selection_changed` シグナルを `_on_selection_changed` に接続する。

#### `_set_select_mode()`

`_canvas.set_mode("select")` を呼び、選択モードボタンを `checked=True`、勾配直線モードボタンを `checked=False` にする。

#### `_set_grade_mode()`

`_canvas.set_mode("grade")` を呼び、勾配直線モードボタンを `checked=True`、選択モードボタンを `checked=False` にする。

#### `keyPressEvent(event)`

| キー | 処理 |
|---|---|
| `S` | `_set_select_mode()` |
| `G` | `_set_grade_mode()` |
| `Esc` | 勾配直線モードの入力をリセット（`_grade_first = None`） |
| `Ctrl+0` | `_canvas.fit_all()` |

#### `eventFilter(obj, event)`

`ProfileCanvas` 上のキーイベントをこのウィンドウが代わりに受け取る。`QEvent.Type.KeyPress` のとき `keyPressEvent()` を呼んで `True` を返す。

#### `closeEvent(event)`

ウィンドウを閉じる際に `_canvas.save_to_profiles()` を呼んで縦断データを各 `ElementProfile` に保存してからウィンドウを閉じる。

#### `_update_mouse_pos(dist, elev)`

`ProfileCanvas` の `mouse_world_pos` シグナルを受け取り、右パネルの距離・標高ラベルを更新する（小数点以下3桁）。

#### `_on_selection_changed(obj)`

`ProfileCanvas` の選択変更を受け取り、`_refresh_props()` でプロパティパネルを再構築する。

#### `_refresh_props()`

選択中の図形に応じてプロパティパネルを再構築する。

| 選択状態 | 呼ばれるメソッド |
|---|---|
| `None`（未選択） | 「図形を選択してください」ラベル + `_build_grade_list()` |
| `GradeLine` | `_build_grade_props()` + `_build_grade_list()` |
| `VerticalCurve` | `_build_vc_props()` + `_build_grade_list()` |

#### `_build_grade_props(gl: GradeLine)`

勾配直線のプロパティパネルを構築する。

- 始点・終点の距離・標高をスピンボックスで編集できる
- 変更後は `_recalc_vc_gradients()` と `_snap_grade_lines()` を呼んで隣接曲線・直線を更新する
- `_block_grade_sb` フラグでスピンボックスの値変更シグナルの連鎖を防ぐ
- 「縦断曲線を挿入」ボタン: 次の勾配直線が存在しかつ PVI に縦断曲線がない場合のみ有効
- 「この勾配直線を削除」ボタン: `_delete_grade_line()` を呼ぶ

#### `_build_vc_props(vc: VerticalCurve)`

縦断曲線のプロパティパネルを構築する。

- PVI 距離・標高・g1・g2・勾配変化量を読み取り専用で表示
- 曲線長 L をスピンボックスで編集できる。変更時は前後の勾配直線の端点（VPC/VPT）も追従する
- VPC・VPT・K 値を読み取り専用ラベルで表示（L 変更時にリアルタイム更新）
- 「縦断曲線を削除」ボタン: `_delete_vertical_curve()` を呼ぶ

#### `_build_grade_list()`

`ProfileCanvas` の `_grade_lines` 全件をリスト表示する（距離範囲と勾配 [%]）。プロパティパネルの末尾に常に表示する。

#### `_insert_vertical_curve(gl: GradeLine, length: float)`

`gl` の終点（= 次の勾配直線の始点 = PVI）に縦断曲線を挿入する。

- PVI = `(gl.dist_end, gl.elev_end)`
- g1 = `gl.gradient`、g2 = 次の勾配直線の `gradient`
- `prev_line_id = gl.id`、`next_line_id = gl2.id`
- 挿入後、選択をリセットして `_refresh_props()` を呼ぶ
- **エッジケース**: `gl` が最後の勾配直線（次がない）→ 何もしない

#### `_delete_vertical_curve(vc: VerticalCurve)`

`_canvas._vertical_curves` から `vc` を削除する。存在しない場合は何もしない。削除後、選択をリセットして `_refresh_props()` を呼ぶ。

---

## 4. road_viewer.py — 3D走行ビューア

### 4.1 モジュールレベル関数

#### `_elev_at_dist(dist, profiles, offsets) -> float`

チェーン累積距離 `dist` での標高を返す。`ep.elev_at(rel)` に委譲する。

- 各 EP を順に走査し、`off ≤ dist ≤ off + L` の EP を見つけて `ep.elev_at(dist - off)` を呼ぶ
- 最後の EP は `dist > d_end` でも処理する（チェーン末端の誤差吸収）
- **エッジケース**: `dist` が全チェーンを超える → `0.0`

#### `build_centerline(elements, profiles, rev_flags, n_per_m=0.5) -> list[tuple]`

3D 中心線点列 `[(x, y, z, dist), ...]` を生成する。

- 各要素の点数: `n = max(2, int(L * n_per_m))`
- **Segment**: 線形補間（n+1 点）
- **Arc**: 角度補間。`span = (angle_end - angle_start) % 2π` で CCW 方向の弧長を確保
- **Clothoid**: 累積弧長リサンプリング。`cum` リストで累積距離を管理し、等間隔の `target` 距離で線形補間
- **境界点（i=0, points が非空）**: `z = points[-1][2]`（前の要素の末端高さを継承）
- **rev=True**: `pts_2d` を `reversed()` してから処理

- **エッジケース**:
  - `ep.plan_length < 0.001` → その要素をスキップ
  - `Clothoid.points` が空 → スキップ
  - クロソイドの `cum[-1] = 0`（点列が1点）→ 全点が末端点になる

#### `build_road_mesh(centerline, half_width=4.0, color_override=None, z_offset=0.02) -> GeomNode`

中心線に沿った帯状メッシュを生成する。

- 各点で接線方向を計算し、左法線方向に `half_width` だけオフセットした左右2頂点を生成
- 頂点の z 座標 = `centerline[i][2] + z_offset`（地面より上）
- 三角形: `(bl, tl, tr)` と `(bl, tr, br)` の2三角形、さらに裏面（逆順）も追加
- `color_override=None` のとき: デフォルト色 `(0.25, 0.25, 0.25, 1)`

#### `build_center_line_node(centerline, color_override=None) -> GeomNode`

中心線を `LineSegs` で描画するノードを生成する。

#### `build_piers(centerline, half_width, interval=30.0) -> GeomNode`

約 `interval` m おきに橋脚を生成する。

- 各点の `dist` が `next_dist` を超えた最初の点で橋脚を配置
- 橋脚位置: 中心線から `OUTER = half_width + 0.5m` 外側（左右各1本）
- 橋脚形状: `z=0` から `z=centerline[i][2]` までの角柱（断面 `PW=0.4m × 0.4m`）
- **エッジケース**: `z_top ≤ 0.05` → 橋脚を生成しない（地面と同じ高さ）

#### `build_road_markings(centerline, half_width) -> GeomNode`

左右の白線（`GeomLinestrips`）を生成する。白線の z = `centerline[i][2] + EDGE_Z` where `EDGE_Z=0.08m`。

#### `build_ground(cx, cy, size=2000) -> GeomNode`

緑色（`(0.3, 0.5, 0.25, 1)`）の 2000m×2000m 平板を生成する。z = `-0.1m`（路面より下）。

#### `add_quad(pts, normal)`（`build_piers` 内ヘルパー）

4頂点の四角形を2三角形（`(0,1,2)` と `(0,2,3)`）として追加する。`build_piers` の内部クロージャ。頂点データを `vdata` に追記し、三角形インデックスを `tris` に追記する。

#### `add_pier(cx, cy, z_top, nx_v, ny_v)`（`build_piers` 内ヘルパー）

指定座標に橋脚1セット（左右各1本）を追加する。`build_piers` の内部クロージャ。

- `z_top ≤ 0.05` → 何もしない（地面と同高さ）
- 各橋脚は上面1枚 + 側面4枚 = 5面で構成（`add_quad` を10回呼ぶ）

#### `prepare_viewer_data(scene, elements, profiles, rev_flags, all_display=None) -> dict`

I/O なしで走行データを計算する純粋関数。

戻り値:
```python
{
  "centerline_3d":    [(x, y, z, dist), ...],  # 走行チェーンの3D中心線
  "display_segments": [[(x, y, z, dist), ...], ...]  # 背景要素の独立点列
}
```

背景要素の EP: `scene.element_profiles` から `element_id` で検索し、なければダミー（grade_lines なし）を使用。

#### `launch_viewer(scene, elements, profiles, rev_flags, all_display=None)`

`prepare_viewer_data()` を呼び、結果を `tempfile`（JSON）に書き出して `road_viewer.py` を別プロセスで起動する。

#### `_main_from_file(path)`

tempfile から走行データを読み込み `RoadViewer` を起動するエントリーポイント。

### 4.2 `RoadViewer` クラス

#### `__init__(centerline, display_segs=None)`

- `self.cl`: 走行チェーンの 3D 点列
- `self.disp_segs`: 背景要素の点列リスト
- `self.dist`: 現在の累積距離（初期値 `0.0`）
- `self.speed`: 走行速度（初期値 `20.0` m/s）
- `self.paused`: 一時停止フラグ（初期値 `False`）
- `self.view_mode`: `"follow"` または `"onboard"`（初期値 `"follow"`）
- `self._total`: `cl[-1][3]` (チェーン全長)
- `self._surface_nodes`: 路面メッシュの NodePath リスト（on/off 制御用）

#### `_build_scene()`

1. `_surface_nodes = []` で初期化
2. 背景要素ごとに `build_road_mesh` + `build_center_line_node` + `build_road_markings` + `build_piers` を呼んでノードをアタッチ。路面ノードは `_surface_nodes` に追加、`set_two_sided(True)`, `set_light_off()` を設定
3. 走行チェーンの路面・中心線・白線・橋脚を同様に構築
4. 全点から AABB の重心を計算して `build_ground` を配置
5. 車ダミー（CardMaker）を作成
6. `_apply_surface_visible(ROAD_SURFACE)` で初期表示状態を設定

#### `_apply_surface_visible(visible)`

`_surface_nodes` の全ノードに対して `show()` または `hide()` を呼ぶ。

#### `_toggle_surface()`

`ROAD_SURFACE` フラグを反転し `_apply_surface_visible()` を呼ぶ。

#### `_setup_lighting()`

環境光（`AmbientLight`）と平行光（`DirectionalLight`）を設定する。

#### `_setup_hud()`

左上に `OnscreenText` で HUD を作成する。

#### `_setup_keys()`

| キー | メソッド |
|---|---|
| `Escape` | `sys.exit` |
| `v` | `_toggle_view` |
| `r` | `_toggle_surface` |
| `space` | `_toggle_pause` |
| `arrow_up` | `_change_speed(+10)` |
| `arrow_down` | `_change_speed(-10)` |
| `arrow_left` | `_rewind` |
| `arrow_right` | `_forward` |

#### `_move_task(task)`

毎フレーム呼ばれる走行タスク（Panda3D タスクチェーン）。

- `paused=True` のとき何もしない
- `dt = globalClock.dt`（フレーム間隔）
- `dist += speed * dt`。`dist > _total` で停止
- `_update_car_pose(dist)` と `_update_hud()` を呼ぶ

#### `_update_car_pose(dist)`

`_interp(dist)` で位置・接線方向を取得し、カメラ・車ダミーを配置する。

- **追従視点（follow）**: カメラを車の後方 `15m`・上方 `5m` に配置し車を注視
- **車載視点（onboard）**: カメラを車の前方 `0.5m`・上方 `1.5m` に配置し前方を注視

#### `_interp(dist) -> tuple`

`dist` に対応する位置 `(x, y, z)` と接線方向 `(tx, ty, tz)` を点列から線形補間して返す。

- `dist < 0` → 先頭点の情報
- `dist >= _total` → 末尾点の情報
- それ以外: `cl[i][3] ≤ dist ≤ cl[i+1][3]` となる区間で線形補間

#### `_update_hud()`

HUD テキストを現在の状態に更新する。

#### `_update_camera(dist)`（`_move_task` から委譲）

`_interp(dist)` で取得した位置と接線方向に基づいてカメラを配置する内部メソッド（`_update_car_pose` と同義）。

#### `_toggle_view()`

`view_mode` を `"follow"` ↔ `"onboard"` で切り替える。

#### `_toggle_pause()`

`paused` フラグを反転する。

#### `_change_speed(delta)`

`speed = max(1.0, speed + delta)` で速度を変更する。下限 1 m/s。

#### `_rewind()`

`dist = max(0.0, dist - 100.0)` で 100m 後退する。

---

## 5. right_panel.py — 右パネル

### 5.1 `RightPanel` クラス

シグナル一覧（emit 側）:

| シグナル | 型 | 用途 |
|---|---|---|
| `request_smooth_connect` | `(object, object)` | 2直線のスムーズ接続要求 |
| `request_polyline_connect` | `(object, object)` | 2直線の折れ線接続要求 |
| `request_disconnect` | `(object, object)` | 接続解除要求 |
| `request_add_clothoid` | `(object, object)` | クロソイド追加要求 |
| `request_delete_clothoid` | `(object)` | クロソイド削除要求 |
| `request_flip_clothoid` | `(object)` | クロソイド反転要求 |
| `request_select` | `list` | 図形選択要求 |
| `request_delete` | `list` | 図形削除要求 |
| `scene_changed` | — | シーン変更通知 |

#### `_on_combo_changed(idx: int)`

コンボボックスの選択変更時に呼ばれる。最後のコンボに図形が選択された場合は `_add_nick_combo()` で1個追加する。`_refresh_nick_combos()` で全コンボの選択肢を更新する。

#### `_remove_nick_combo()`

末尾のコンボボックスを削除する。コンボが1個のみの場合は削除しない（最低1個維持）。削除後 `_refresh_nick_combos()` を呼ぶ。

#### `update_mouse_pos(x, y)`

マウスのワールド座標を右パネル上部のラベルに表示する（小数点以下3桁）。

#### `update_selection(selected, scene)`

選択図形が変わったとき呼ばれる。プロパティパネルを再構築し、コンボボックスの選択肢を更新する。

#### `_all_items() -> list[str]`

Scene 内の全図形のラベル文字列リストを返す。空要素 `"(なし)"` を先頭に含む。

#### `_label_for_obj(obj) -> str`

図形の表示ラベルを返す。形式は仕様書 5.2 節を参照。

#### `_find_by_nick_label(text) -> Optional[object]`

ラベル文字列からブラケット内の型と ID を解析して図形オブジェクトを返す。`[順]`/`[逆]` プレフィックスを除去してから検索する。`"(なし)"` → `None`。

#### `_endpoints_of(obj) -> list[Vec2]`

図形の端点座標リスト `[start, end]` を返す。

| 型 | 戻り値 |
|---|---|
| `Segment` | `[seg.start, seg.end]` |
| `Arc` | `[arc.start, arc.end]` |
| `Clothoid`（有効） | `[_line_pt, _circle_pt]` |
| その他 / 無効 | `[]` |

#### `_adjacent_from_pt(pt, excludes=None, prev_obj=None) -> list[tuple]`

点 `pt` の近傍（`SNAP_TOL=1.0m`）にある図形をリストで返す。戻り値: `[(figure, is_forward), ...]`。

- 同じ直線上の線分の端点を検索
- 同じ円上の円弧の端点を検索
- クロソイドの `_line_pt` / `_circle_pt` を検索
- 折れ線/スムーズ接続中の共有点から他の直線の線分も検索

#### `_adjacent_from_obj(obj, excludes=None) -> list[tuple]`

図形の全端点から `_adjacent_from_pt` を呼び、重複なく結果を集約する。2つ目コンボボックス用（両端点の隣接をすべて収集）。

#### `_next_is_forward(prev_obj, prev_is_fwd, next_obj) -> bool`

チェーンを `prev_obj → next_obj` と進むとき、`next_obj` の `is_forward` を返す。`exit_pt` と `next_obj` の両端点との距離を比較して、より近い側が始点なら `True`（正順）。

#### `_compute_next_forward(prev_obj, prev_is_fwd, cand) -> bool`

`[順]/[逆]` 表示用の判定。`exit_tan` と `entry_tangent(cand, ...)` の内積が非負なら `True`（順方向）。

#### `_prev_is_fwd_for_adj(prev_obj, cand) -> bool`

2つ目コンボボックス専用。`cand` が `prev_obj` のどちらの端点側に接続しているかで `prev_obj` の通過方向を返す。

#### `_refresh_nick_combos()`

全コンボボックスの選択肢を更新する。`_fill_adjacent_items()` で隣接候補に `[順]/[逆]` を付与する。選択中のテキストを可能な限り復元する（`[順]/[逆]` プレフィックスが変わっても復元する）。

#### `_fill_adjacent_items(cb, adj, prev_obj, prev_is_fwd, is_2nd)`

隣接候補リストをコンボボックスに追加する。`len(adj) >= 2` のとき `[順]/[逆]` を付与する。

#### `_apply_nick_select()`

コンボボックスの選択を Canvas の選択に反映する。`(なし)` や未選択は除外する。

#### `_add_nick_combo() / _remove_nick_combo()`

コンボボックスを追加/削除する。最低1個は維持する。

#### `_delete_selected_objs()`

コンボボックスで選択中の図形を削除する。`QMessageBox` で確認してから `request_delete` を emit する。

#### `_redraw()`

全クロソイドに `compute()` を呼び直し、`scene_changed` を emit する。

#### `_build_line_props(ln)`

直線のプロパティパネルを構築する（参照始点・終点の X/Y 数値入力）。

#### `_build_segment_props(seg)`

線分のプロパティパネルを構築する。始点・終点の X/Y 座標と割合 t を数値入力で編集できる。t の入力範囲: `[0, 1]`（逆順も可だが警告なし）。

#### `_refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)`

線分端点スピンボックスの表示を現在値に更新するヘルパー。`self._block=True` で他のコールバックへの連鎖を防ぐ。

#### `_build_arc_props(arc)`

円弧のプロパティパネルを構築する。`add_arc_endpoint(label, get_angle, set_angle)` で始点・終点それぞれの入力フォームを生成する。

`add_arc_endpoint` の内部コールバック:
- `on_ang(v)`: 角度入力 → `set_angle(math.radians(v))`
- `on_x(v)`: X 座標入力 → 現在の Y との組み合わせで `atan2` から角度を決定。`|v - center.x| > radius` のとき無視
- `on_y(v)`: Y 座標入力 → 同様に `atan2` から角度を決定

#### `_build_clothoid_props(clo)`

クロソイドのプロパティパネルを構築する。有効なとき: A 値、τ、接点座標、スナップ設定、接合確認を表示。反転ボタンは同一直線・円に2本あるとき無効化する。

#### `_build_two_segments(seg_a, seg_b)`

同一直線上の2線分の結合パネルを構築する。異なる直線の場合はエラー表示。

#### `_candidate_seg_pairs(seg_a, seg_b) -> list`

2線分の近接端点ペアの候補を返す（snap 済みの端点は除外）。

#### `_build_line_circle(ln, ci)`

直線と円が選択された場合のクロソイド操作パネルを構築する。クロソイド本数 n に応じてボタンの有効/無効を切り替える。

#### `_build_ep_info(ep)`

ElementProfile の縦断情報（平面長・始終端標高・GL/VC 一覧）を表示するパネルを構築する。

#### `_build_related_objects(obj)`

接続している図形の一覧と「選択」「選択追加」ボタンを構築する。

---

## 6. main_window.py — メインウィンドウ

### 6.1 `MainWindow` クラス

#### `__init__()`

メインウィンドウを構築する。`Canvas`・`RightPanel`・`VerticalAlignmentWindow`（遅延生成）を生成し、シグナルを接続する。

#### `_setup_signals()`

以下のシグナルを接続する:
- `Canvas.selection_changed` → `_on_selection_changed` + `RightPanel.update_selection`
- `Canvas.scene_changed` → `_on_scene_changed`
- `Canvas.mouse_world_pos` → `RightPanel.update_mouse_pos`
- `RightPanel` の各 `request_*` → 対応する `_do_*` メソッド

#### `_on_scene_changed()`

ウィンドウタイトルに `*` を付加して未保存を示す。

#### `_save() / _save_as()`

`_save`: `_filepath` が設定済みなら `_write_file` を呼ぶ。未設定なら `_save_as` に委譲。

`_save_as`: `QFileDialog.getSaveFileName` でパスを取得して `_write_file` を呼ぶ。

#### `_write_file(path)`

`json.dump(scene.to_dict(), ...)` でファイルに書き出す。`ensure_ascii=False`, `indent=2`。例外を `QMessageBox.critical` で表示する。

#### `_open()`

`QFileDialog.getOpenFileName` でパスを取得し、`Scene.from_dict(json.load(...))` で読み込む。成功後に Canvas をリセット（選択・ハンドルのクリア）して `fit_all()` を呼ぶ。

#### `_get_or_create_ep(obj, rev) -> ElementProfile`

`obj` に対応する `ElementProfile` を返す。なければ新規作成して `scene.element_profiles` に追加する。`element_type`・`plan_length`・`reversed_flag` を常に最新値で上書きする。

#### `_collect_all_display() -> list`

全線分・全円弧・全クロソイドをフラットなリストで返す。3D ビューアの背景表示に使用する。

#### `_open_vertical_window()`

1. 選択中の平面線形要素を収集
2. `resolve_chain()` でチェーン順序を解決
3. `_get_or_create_ep()` で ElementProfile を用意
4. 隣接 EP 間の境界標高を同期（GL がある方の端点標高を優先）
5. `VerticalAlignmentWindow` を生成・表示

- **エッジケース**: 選択要素がない → 何もしない

#### `_open_3d_viewer()`

1. 選択中の平面線形要素を収集（なければ全要素）
2. `resolve_chain()` でチェーン順序を解決
3. `_get_or_create_ep()` で ElementProfile を用意
4. `launch_viewer()` を呼ぶ

- **エッジケース**: 図形が1つもない → `QMessageBox.information` で通知して終了

#### `_do_smooth_connect(a, b)`

`Canvas.smooth_connect(a, b)` を呼ぶ。

#### `_do_polyline_connect(a, b)`

`Canvas._connect_polyline(a, b)` と `push_undo()` を呼ぶ。

#### `_do_disconnect(a, b)`

`Canvas.disconnect_lines(a, b)` を呼ぶ。

#### `_do_add_clothoid(ln, ci)`

`push_undo()` 後に `Clothoid(ln, ci)` を生成して Scene に追加する。snap 設定はデフォルト（`snap_segment=True`, `snap_arc=True`）。

#### `_do_delete_clothoid(clo)`

`push_undo()` 後に `scene.remove_clothoid(clo)` を呼ぶ。

#### `_do_delete_objects(objs)`

`push_undo()` 後に各図形を型に応じて削除する（`Line` / `Circle` / `Clothoid` / `Segment` / `Arc`）。

#### `_do_flip_clothoid(clo)`

`push_undo()` 後に `clo.reversed_flag = not clo.reversed_flag` を設定し `clo.compute()` を呼ぶ。

#### `scene` プロパティ

`_canvas.scene` への委譲プロパティ。メインウィンドウ全体から `self.scene` で現在の Scene にアクセスするために使用する。

#### `_get_or_create_ep(obj, rev) -> ElementProfile`

既存 EP を返すか新規作成する。`element_type`・`plan_length`・`reversed_flag` を常に更新する。

---

## 補足: right_panel.py の追加詳細

### 5.2 モジュールレベル関数

#### `_make_spinbox(val, lo=-1e6, hi=1e6, step=0.01, decimals=3) -> QDoubleSpinBox`

スピンボックスを生成するファクトリ関数。

- `val`: 初期値
- `lo`, `hi`: 最小・最大値（デフォルト `−1e6`〜`+1e6`）
- `step`: 単一ステップ量（デフォルト `0.01`）
- `decimals`: 小数点以下桁数（デフォルト `3`）

#### `_separator() -> QFrame`

水平区切り線（`HLine` スタイル）を返す。

#### `_style_disabled(btn, disabled)`

ボタンの `enabled` を設定し、無効時は薄いグレースタイルを適用する。

---

### 5.3 `RightPanel` の追加メソッド

#### `_adjacent_elements(obj, exclude_pt=None) -> list[tuple]`

`obj` の端点に隣接する図形リストを返す。

- `exclude_pt` が指定された場合、その点と `SNAP_TOL` 以内の端点を除外してから隣接を探す
- 走査対象: 全線分・全円弧・全クロソイド
- 戻り値: `[(cand, is_forward), ...]`
  - `is_forward=True`: `cand` の始点で接続
  - `is_forward=False`: `cand` の終点で接続
- **エッジケース**: `obj` 自身は除外。`cand_pts` が 2 点未満のものも除外

#### `_free_endpoint(obj, shared_pt) -> Optional[Vec2]`

`obj` の端点のうち `shared_pt` と `SNAP_TOL` 以上離れている端点を返す。両端点が `shared_pt` と一致する場合は `None`。

#### `_shared_pt(obj_a, obj_b) -> Optional[Vec2]`

`obj_a` と `obj_b` の全端点ペアを総当たりし、`SNAP_TOL` 以内の組み合わせがあればその座標を返す。なければ `None`。

#### `_all_items() -> list[str]`

Scene 内の全図形のコンボラベルリストを返す。タイプ別にグループ化し、各グループ内でニックネーム順にソートする。先頭に `"(なし)"` を含む。

順序: 直線 → 線分 → 円 → 円弧 → クロソイド

#### `_tangent_at(obj, at_end) -> tuple`

`models.tangent_at()` への委譲メソッド。

#### `_entry_tangent(obj, connect_at_start) -> Optional[tuple]`

`models.entry_tangent()` への委譲メソッド。

#### `_next_is_forward(prev_obj, prev_is_fwd, next_obj) -> bool`

`prev_obj → next_obj` のチェーン接続において、`next_obj` の `is_forward` を返す。

- `prev_obj` の出口端点（`prev_is_fwd=True` なら末点、`False` なら始点）と `next_obj` の各端点を距離比較
- `next_obj` の始点側に近ければ `True`（正順）、終点側に近ければ `False`（逆順）
- **エッジケース**: `prev_obj` または `next_obj` の端点が取得できない → `True` を返す

#### `_compute_next_forward(prev_obj, prev_is_fwd, cand) -> bool`

`[順]/[逆]` 表示のための判定。`exit_tan` と `entry_tangent(cand, ...)` の内積が `≥ 0` なら `True`。

- `exit_tan`: `tangent_at(prev_obj, at_end=prev_is_fwd)`
- `entry_tangent`: 共有端点が `cand` の始点なら `connect_at_start=True`、終点なら `False`
- **エッジケース**: `entry_tangent` が `None` → `True` を返す（接線方向が不明なら正順扱い）

#### `_prev_is_fwd_for_adj(prev_obj, cand) -> bool`

2つ目コンボ専用。`cand` が `prev_obj` のどちらの端点で接続しているかを調べ、`prev_obj` の通過方向を返す。

- `cand` の端点が `prev_obj` の終点（`pts[-1]`）に近い → `True`（正順で通過）
- `cand` の端点が `prev_obj` の始点（`pts[0]`）に近い → `False`（逆順で通過）
- `Clothoid` 同士の場合: `_circle_pt` 側が終点、`_line_pt` 側が始点として判定
- **エッジケース**: どちらにも一致しない → `True` を返す（デフォルト）

#### `_adjacent_from_obj(obj, excludes=None) -> list[tuple]`

`obj` の全端点から隣接図形を収集する（2つ目のコンボ用）。

収集対象:
1. 各端点から `_adjacent_from_pt()` を呼んで隣接を収集
2. `Clothoid` の場合: `_line_pt` / `_circle_pt` からも追加で収集
3. `Arc` の場合: 端点に接するクロソイドも追加で収集
4. `Segment` の場合: 同じ直線のクロソイド接点（`project_t` で範囲内確認）も追加

重複は `id(cand)` で排除する。`excludes` に含まれる図形は除外する。

#### `_adjacent_from_pt(pt, excludes=None, prev_obj=None) -> list[tuple]`

座標 `pt` に近接する図形の一覧を返す（3つ目以降のコンボ用）。

走査順:
1. 全線分の各端点 (`start`, `end`) → `SNAP_TOL` 以内で一致
2. 全円弧の各端点 → `SNAP_TOL` 以内で一致
3. 全クロソイドの `_line_pt` / `_circle_pt` → `SNAP_TOL` 以内で一致
4. `prev_obj` がクロソイドで `pt` が `_line_pt` の場合: その点を内部に含む線分（端点でなくても）も候補

- **エッジケース**: `prev_obj` が `None` のとき 4. は実行しない

#### `update_selection(selected, scene)`

外部から選択変更を受け取る。`_refresh_nick_combos()` → `_sync_combos_to_selection()` → `_rebuild_props()` の順に呼ぶ。

#### `_sync_combos_to_selection(selected)`

Canvas での選択をコンボボックスに反映する。コンボの数が不足している場合は `_add_nick_combo()` で補充する。ラベルの検索は `[順]`/`[逆]` プレフィックスを考慮する。

#### `_clear_props()`

プロパティパネルの全ウィジェットを削除する（`deleteLater()` で安全に削除）。

#### `_rebuild_props()`

選択図形の組み合わせに応じてプロパティパネルを再構築する。

| 選択数 | 組み合わせ | 呼ばれるメソッド |
|--------|-----------|----------------|
| 0 | — | 「図形を選択してください」ラベルを表示 |
| 1 | 任意 | `_build_single()` |
| 2 | Segment + Segment（同一直線） | `_build_two_segments()` |
| 2 | Arc + Arc（同一円） | `_build_two_arcs()` |
| 2 | Line + Line（または Segment 経由） | `_build_two_lines()` |
| 2 | Line + Circle（または Segment 経由） | `_build_line_circle()` |
| 2 | その他 | 各図形に `_build_single()` を呼ぶ |
| 3以上 | — | 図形数とニックネーム一覧を表示 |

#### `_build_single(obj)`

単一図形のプロパティパネルを構築する。構成:
1. `_add_nickname_editor(obj)`: ニックネーム入力
2. 型ごとのプロパティ: `_build_line_props()` / `_build_segment_props()` / `_build_circle_props()` / `_build_arc_props()` / `_build_clothoid_props()`
3. `_add_vertical_profile_info(obj)`: 対応する ElementProfile の縦断情報
4. `_add_related_objects(obj)`: 接続図形の一覧

#### `_add_vertical_profile_info(obj)`

`scene.element_profiles` から `element_id == obj.id` の ElementProfile を検索し、存在すれば縦断情報を表示する。表示内容:
- 平面長 [m]、始端標高・終端標高 [m]
- 勾配直線の一覧（距離範囲・勾配 [%]）
- 縦断曲線の一覧（PVI 位置・曲線長・K 値）

#### `_add_nickname_editor(obj)`

ニックネーム入力フィールドを構築する。`scene.get_nickname()` で現在値を表示し、入力変更時に `scene.set_nickname()` を呼ぶ。

#### `_add_related_objects(obj)`

`scene.connected_objects(obj)` で接続図形を取得し、各図形に「選択」・「選択追加」ボタンを配置する。「選択」: `request_select.emit([cand])`、「選択追加」: `request_select.emit(self._selected + [cand])`

#### `_build_line_props(ln)`

直線のプロパティパネルを構築する。`add_vec2(label, get_fn, set_fn)` ヘルパーで参照始点・参照終点の X/Y スピンボックスを生成する。

`add_vec2` のコールバック:
- `on_x(v)`: X 入力 → `set_fn(Vec2(v, get_fn().y))`
- `on_y(v)`: Y 入力 → `set_fn(Vec2(get_fn().x, v))`
- 変更後: `_propagate_line()` → `scene_changed.emit()`

方向角（読み取り専用ラベル）を `math.degrees(ln.angle)` で表示する。

#### `_build_circle_props(ci)`

円のプロパティパネルを構築する。中心 X/Y・半径のスピンボックスを生成する。

コールバック:
- `on_cx(v)`: `ci.center.x = v` → `_propagate_circle()`
- `on_cy(v)`: `ci.center.y = v` → `_propagate_circle()`
- `on_r(v)`: `ci.radius = max(0.01, v)` → `_propagate_circle()`（半径の最小値 `0.01m`）

#### `_build_clothoid_props(clo)`

クロソイドのプロパティパネルを構築する。

有効（`clo.is_valid=True`）のとき表示する情報:
- カーブ方向（左/右）
- `reversed_flag` の状態
- パラメータ A [m]（`clo._A`）
- 全偏角 τ [°]（`math.degrees(clo._tau)`）
- 線側接点座標（`_line_pt`）
- 円側接点座標（`_circle_pt`）

操作:
- `snap_segment` チェックボックス: 変更後 `clo.compute()` を呼ぶ
- `snap_arc` チェックボックス: 変更後 `clo.compute()` を呼ぶ
- 反転ボタン: `request_flip_clothoid.emit(clo)`。同じ直線・円に2本ある場合は無効化

コールバック `on_seg(v)` / `on_arc(v)`: `snap_segment` / `snap_arc` を設定して `compute()` → `scene_changed.emit()`

#### `_build_segment_props(seg)`

線分のプロパティパネルを構築する。`add_endpoint(label, get_t, set_t, other_t_getter)` ヘルパーで始点・終点の入力フォームを生成する。

`add_endpoint` のコールバック:
- `on_x(v)`: X 入力 → Y を現在値で保持して `project_t` で t を計算して `set_t()`
- `on_y(v)`: Y 入力 → X を現在値で保持して同様
- `on_t(v)`: t 入力 → `set_t(v)` を直接呼ぶ。ただし `|v - other_t_getter()| < 1e-4` の場合は無視（線分の縮退防止）

X/Y 入力後の表示更新は `_refresh_seg_display()` で行う。

#### `_refresh_seg_display(sb_x, sb_y, sb_t, lbl_t, ln, get_t)`

スピンボックスの表示を現在値に更新する。`self._block=True` でシグナルの連鎖を防ぐ（スピンボックスへの setValue が on_x コールバックを再帰的に呼ばないよう）。

#### `_build_arc_props(arc)`

円弧のプロパティパネルを構築する。`add_arc_endpoint(label, get_angle, set_angle)` ヘルパーで始点・終点それぞれの入力フォームを生成する。

`add_arc_endpoint` の各コールバック:
- `on_ang(v)`: 角度（度数）入力 → `set_angle(radians(v))` → 再描画
- `on_x(v)`: X 座標入力 → 現在の Y と組み合わせて `atan2(current_y - cy, v - cx)` で角度を決定。`|v - cx| > radius` の場合は X をクランプして計算
- `on_y(v)`: Y 座標入力 → 同様に角度を決定

変更後: `_propagate_circle()` → `scene_changed.emit()`

#### `_seg_end_blocked(seg, end) -> bool`

線分 `seg` の `end`（`'start'` または `'end'`）側の端点がクロソイドに束縛されているか確認する。

束縛条件:
1. `snap_segment=True` のクロソイドの `_line_pt` が `t_end` または `t_start` と `1e-4` 以内で一致
2. `seg.id` が `clo._split_seg_ids` に含まれている

#### `_candidate_seg_pairs(seg_a, seg_b) -> list[dict]`

2線分の全端点ペア（4通り）を距離でソートして返す。各エントリは `{'end_a', 'end_b', 'dist', 'blocked_a', 'blocked_b', 'label'}` を持つ辞書。

#### `_merge_segments(seg_a, seg_b, end_a, end_b)`

`seg_b` を削除し、`seg_a` の `end_a` 側を `seg_b` の反対端まで延長する。

| end_a | end_b | 処理 |
|-------|-------|------|
| `'end'` | `'start'` | `seg_a.t_end = seg_b.t_end`; `seg_b` を削除 |
| `'end'` | `'end'` | `seg_a.t_end = seg_b.t_start`; `seg_b` を削除 |
| `'start'` | `'start'` | `seg_a.t_start = seg_b.t_end`; `seg_b` を削除 |
| `'start'` | `'end'` | `seg_a.t_start = seg_b.t_start`; `seg_b` を削除 |

#### `_arc_end_blocked(arc, end) -> bool`

円弧の端点がクロソイドに束縛されているか確認する。

束縛条件:
1. `snap_arc=True` のクロソイドの `_circle_pt` の角度が `angle_start` または `angle_end` と `1e-4` 以内で一致
2. `arc.id` が `clo._split_arc_ids` に含まれている

#### `_candidate_arc_pairs(arc_a, arc_b) -> list[dict]`

2円弧の全端点ペア（4通り）を距離でソートして返す。`'label'` は角度（度数）と座標距離を含む。

#### `_merge_arcs(arc_a, arc_b, end_a, end_b)`

`arc_b` を削除し、`arc_a` の `end_a` 側を `arc_b` の反対端の角度まで延長する。

| end_a | end_b | 処理 |
|-------|-------|------|
| `'end'` | `'start'` | `arc_a.angle_end = arc_b.angle_end` |
| `'end'` | `'end'` | `arc_a.angle_end = arc_b.angle_start` |
| `'start'` | `'start'` | `arc_a.angle_start = arc_b.angle_end` |
| `'start'` | `'end'` | `arc_a.angle_start = arc_b.angle_start` |

#### `_build_two_lines(a, b)`

2直線の接続操作パネルを構築する。

現在の接続状態を判定して表示:
- 未接続: 「折れ線接続」「スムーズ接続」ボタンを有効化
- 折れ線接続中: 「スムーズ接続」「接続解除」ボタンを有効化
- スムーズ接続中: 「接続解除」ボタンのみ有効化

各ボタンのコールバック:
- 折れ線接続: `request_polyline_connect.emit(a, b)`
- スムーズ接続: `request_smooth_connect.emit(a, b)`
- 接続解除: `request_disconnect.emit(a, b)`

#### `_build_line_circle(ln, ci)`

直線と円が選択されたときのクロソイド操作パネルを構築する。

現在のクロソイド本数 `n = len(scene.clothoids_for(ln, ci))` に応じてボタンの有効/無効を制御する:

| n | 追加 | 削除 | 反転 |
|---|------|------|------|
| 0 | 有効 | 無効 | 無効 |
| 1 | 有効（反転側） | 有効 | 有効 |
| 2 | 無効 | 無効 | 無効 |

- 追加ボタン（`do_add`）: `request_add_clothoid.emit(ln, ci)`
- 削除ボタン（`do_del`）: n=1 のとき `request_delete_clothoid.emit(clothoids[0])`
- 反転ボタン（`do_flp`）: n=1 のとき `request_flip_clothoid.emit(clothoids[0])`

既存クロソイドの snap 設定も `QCheckBox` で表示・編集できる。
