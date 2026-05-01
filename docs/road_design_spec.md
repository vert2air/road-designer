# 道路設計アプリ 仕様書

（平面線形・縦断線形・3D走行ビューア）

---

## 目次

1. [概要](#1-概要)
2. [データモデル](#2-データモデル)
3. [幾何学的定義](#3-幾何学的定義)
4. [メイン編集画面](#4-メイン編集画面)
5. [右パネル](#5-右パネル)
6. [縦断線形設計ウィンドウ](#6-縦断線形設計ウィンドウ)
7. [3D走行ビューア](#7-3d走行ビューア)
8. [メニュー・ショートカット一覧](#8-メニューショートカット一覧)

---

## 1. 概要

### 1.1 アプリの目的

道路の平面線形（直線・円弧・クロソイド）と縦断線形（勾配直線・縦断曲線）を設計し、3D で走行シミュレーションを行うためのデスクトップアプリケーション。

### 1.2 技術スタック

| 項目 | 内容 |
|------|------|
| UI フレームワーク | PyQt6 |
| 3D 走行ビューア | Panda3D |
| 言語 | Python 3.10+ |
| ファイル形式 | JSON（拡張子 `.rdjson`） |

### 1.3 座標系の定義

本アプリは**数学座標系（ワールド座標）**を採用する。

- **x 軸**: 画面右方向が正（3時方向）
- **y 軸**: 画面上方向が正（12時方向）
- **有向角の正の向き**: 反時計回り（CCW）
- **z 軸**: x 軸から y 軸に回したとき右ねじが進む方向（画面手前）

モデルデータはすべてワールド座標で定義・保持する。GUI 描画時のみ `Canvas.w2s()` によりスクリーン座標（y 軸下向き）に変換する。

#### ワールド座標とスクリーン座標の変換

スクリーン座標は Qt ウィジェットのピクセル座標系（y 軸下向き正）。以下の変数を使う。

- `world_x`, `world_y`: ワールド座標
- `screen_x`, `screen_y`: スクリーン座標（ピクセル）
- `scale`: 現在のズーム倍率（ワールド単位あたりのピクセル数）
- `offset_x`, `offset_y`: ビューのパン量（ピクセル）

```
screen_x =  world_x * scale + offset_x
screen_y = -world_y * scale + offset_y   ← y 反転
```

#### Qt drawArc の角度

`QPainter.drawArc(rect, startAngle, spanAngle)` は数学座標（y 上向き・反時計が正）として解釈されるため、ワールド座標の角度をそのまま渡せばよい（符号反転不要）。

- `angle_start_deg`: 円弧始点の角度（度数）
- `arc_angle_deg`: 弧長角度（度数、正 = 反時計回り）

```python
startAngle_16 = int(round(angle_start_deg * 16))   # 符号反転不要
spanAngle_16  = int(round(arc_angle_deg   * 16))   # 正 = 反時計 (CCW)
```

#### 3D ビューア（Panda3D）への変換

Panda3D は右手系で z 軸が上向き。設計座標を次のように対応させる。

```
設計座標 (x右, y上) → Panda3D (x右, y奥, z上)
変換: P3D.x = world.x,  P3D.y = world.y,  P3D.z = 標高
```

---

## 2. データモデル

### 2.1 直線（Line）

「直線」は通過する異なる2点により定義する。また方向を持つ。

- **参照始点** (`ref_start`): 直線を定義する始点座標
- **参照終点** (`ref_end`): 直線を定義する終点座標
- **参照点**: 参照始点と参照終点の総称
- **方向ベクトル** (`direction`): `ref_start` から `ref_end` への単位ベクトル

**符号付き距離**（任意の点 `m` に対して）:

```
signed_dist(m) = direction.cross(m - ref_start)
```

ここで `cross` は 2D 外積（`direction.x * (m - ref_start).y - direction.y * (m - ref_start).x`）。
左側（反時計90°方向）が正、右側が負となる。

**左法線**（`direction` を CCW に 90° 回転したベクトル）:

```
# direction = (dx, dy) のとき
left_normal = (-dy, dx)
```

直線の変形は、直線が持つすべての線分の端点に波及する。各端点は、参照始点を `0.0`・参照終点を `1.0` とした相対位置（割合 t）を保つように更新される。

### 2.2 線分（Segment）

直線はその部分として複数の「線分」を持つことができる。

- **始点** (`start`): 線分の開始点（親直線上に束縛）
- **終点** (`end`): 線分の終了点（親直線上に束縛）
- **端点**: 始点と終点の総称
- **割合 t**: 線分上の位置を参照始点 = `0.0`、参照終点 = `1.0` として表した値

`ref_start` から `ref_end` への向きと、`start` から `end` への向きが一致している必要がある。

クロソイドの snap 機能によって位置が決まる端点は、他の方法では変形できない。

**線分の結合操作**: 同じ直線上の2本の線分を選択した状態で右パネルから実行できる。4通りの端点ペアをコンボボックスで選択し「結合する」ボタンで一方を削除してもう一方を延長する。snap により束縛されている端点は結合できない。

### 2.3 円（Circle）と円弧（Arc）

「円」は**中心** (`center`) と**半径** (`radius`) により定義する。円は複数の「円弧」を持つことができる。

**円弧の端点定義**:

- **始点** (`start`): 円弧の開始点（`angle_start` に対応する円周上の点）
- **終点** (`end`): 円弧の終了点（`angle_end` に対応する円周上の点）
- **端点**: 始点と終点の総称

**円弧の角度フィールド**:

| フィールド | 説明 |
|-----------|------|
| `angle_start` | 始点の角度（ラジアン、x 軸正方向 = 0、CCW が正） |
| `angle_end` | 終点の角度（ラジアン） |
| `arc_angle()` | `(angle_end − angle_start) % (2π)` — 常に正（CCW の弧長角度） |

始点から円上を**反時計回り**に進み、終点に至る側が「円弧」として定義される。

**円弧の結合操作**: 同じ円上の2本の円弧を選択した状態で右パネルから実行できる。snap により束縛されている端点は結合できない。

### 2.4 クロソイド（Clothoid）

「クロソイド」は**直線と円**により定義される曲線で、直線から円弧へ滑らかに曲率を変化させる（Euler spiral / Cornu spiral）。

| フィールド | 説明 |
|-----------|------|
| `line` | 接続する直線への参照 |
| `circle` | 接続する円への参照 |
| `reversed_flag` | 直線の向きを反転するか（`True` のとき `ref_start` と `ref_end` を入れ替えて使う） |
| `snap_segment` | 線分との snap 機能 on/off |
| `snap_arc` | 円弧との snap 機能 on/off |
| `is_left_curve` | 左カーブか右カーブか（直線に対して円の中心が左側なら `True`） |
| `_line_pt` | 線側接点座標（直線上の点） |
| `_circle_pt` | 円側接点座標（円周上の点） |
| `points` | 曲線の描画点列（`Vec2` のリスト、`_line_pt` から `_circle_pt` の順） |

#### snap 機能

**線分との snap（`snap_segment=True`）**:

クロソイドの線側接点に最も近い線分の端点を接点に一致させる。
- `reversed_flag=False` → 線分の**終点**をクロソイドの `_line_pt` に一致させる
- `reversed_flag=True`  → 線分の**始点**をクロソイドの `_line_pt` に一致させる

**円弧との snap（`snap_arc=True`）**:

クロソイドの円側接点に最も近い円弧の端点を接点に一致させる。
- **左カーブ** → 円弧の**始点**をクロソイドの `_circle_pt` に一致させる
- **右カーブ** → 円弧の**終点**をクロソイドの `_circle_pt` に一致させる

円弧が存在しない場合は中心角 45° で自動生成する。

**snap=off 時**: 接点が線分・円弧の内部点になる場合、その線分・円弧を接点で分割する。

#### クロソイドの反転

`reversed_flag` を切り替えることで `ref_start` と `ref_end` を入れ替えた向きとして扱える。同じ直線・円の組に対してクロソイドが2本ある場合、互いに逆の反転フラグを持ち、個々の反転操作は行えない。

### 2.5 ElementProfile（縦断線形データ）

平面線形要素（線分・円弧・クロソイド）と縦断線形データを 1 対 1 で対応させる。

| フィールド | 説明 |
|-----------|------|
| `element_id` | 対応する平面線形要素の ID |
| `element_type` | `"segment"` / `"arc"` / `"clothoid"` |
| `plan_length` | 要素の平面長 [m] |
| `reversed_flag` | チェーン上での逆順使用フラグ |
| `elev_start` / `elev_end` | 始端・終端標高 [m] |
| `grade_lines` | 勾配直線のリスト（`GradeLine`） |
| `vertical_curves` | 縦断曲線のリスト（`VerticalCurve`） |

### 2.6 シーン全体構造と保存フォーマット（.rdjson）

```json
{
  "lines": [
    { "id": 1, "nickname": "my_line", "ref_start": {"x": 0, "y": 0}, "ref_end": {"x": 100, "y": 0}, "segments": [] }
  ],
  "circles": [
    { "id": 3, "nickname": "my_circle", "center": {"x": 50, "y": 50}, "radius": 30, "arcs": [] }
  ],
  "clothoids": [
    { "id": 5, "line_id": 1, "circle_id": 3, "reversed_flag": false, "snap_segment": true, "snap_arc": true }
  ],
  "element_profiles": [
    {
      "id": 10, "element_id": 5, "element_type": "clothoid", "plan_length": 66.3,
      "grade_lines": [], "vertical_curves": []
    }
  ]
}
```

ニックネームは各図形定義の `id` フィールドの直後に `nickname` フィールドとして含める。旧フォーマット（トップレベル `nicknames` フィールド）との後方互換も維持する。

### 2.7 ID 管理とニックネーム

全図形（`Line`・`Segment`・`Circle`・`Arc`・`Clothoid`・`GradeLine`・`VerticalCurve`）の ID はタイプを通じてユニーク。ファイル読み込み後は `_id_counter` を全 ID の最大値 + 1 から再開して重複を防ぐ。読み込み時に ID 衝突を検出した場合、後から現れた図形に新 ID を割り当てる（`_resolve_id()`）。

**ニックネームのデフォルト**: `nickname_<図形type>_<図形ID>`（例: `nickname_line_6`）

---

## 3. 幾何学的定義

### 3.1 クロソイド曲線の数式

以下の変数を使う。

- `R`: 接続する円の半径 [m]
- `L`: クロソイドの曲線長 [m]（線側接点から円側接点までの弧長）
- `τ`（タウ）: 全偏角 [ラジアン]（直線の接線方向から円の接線方向までの方向変化量）
- `A`: クロソイドパラメータ [m]（曲線の「きつさ」を表す定数）

これらの間に以下の関係が成り立つ。

```
A² = R · L
L  = 2 · R · τ
```

弧長 `s`（線側接点からの距離）における曲率 `κ(s)` と曲率半径 `ρ(s)`:

```
κ(s) = s / A²
ρ(s) = A² / s
```

### 3.2 Fresnel 積分による計算

以下の変数を使う。

- `s`: 線側接点からの弧長 [m]（積分変数、`0 ≤ s ≤ L`）
- `xe`: 局所座標系における終点の x 変位 [m]（直線の方向を x 軸とする）
- `ye`: 局所座標系における終点の y 変位 [m]（直線の左法線方向を y 軸とする）

クロソイド終点の局所座標変位 `(xe, ye)` を台形則で数値積分する:

```
xe = ∫₀ᴸ cos(s² / (2 · A²)) ds
ye = ∫₀ᴸ sin(s² / (2 · A²)) ds
```

外部ライブラリ（scipy 等）は不要で、純粋な Python で実装する。

### 3.3 存在条件と全偏角の決定

以下の変数を使う。

- `d`: 円の中心から直線への垂直距離 [m]（常に正）
- `R`: 円の半径 [m]
- `τ`: 全偏角（求めたい値）
- `ye(τ)`: 全偏角が `τ` のときの局所座標 y 変位（3.2 節の Fresnel 積分の結果）

存在条件:

- `d ≤ R` のとき: クロソイドは存在しない（直線が円の内部または接線）
- `d > R` のとき: Fresnel 条件 `ye(τ) = d − R · cos(τ)` を満たす `τ` を二分法（80 回反復）で求める

### 3.4 接点の計算

以下の変数を使う。

- `circle.center`: 円の中心座標
- `ref_start`: 直線の参照始点座標
- `direction`: 直線の方向単位ベクトル（`ref_start` から `ref_end` への向き）
- `left_normal`: `direction` を CCW に 90° 回転した単位ベクトル（`(-dy, dx)` where `direction = (dx, dy)`）
- `d_signed`: `circle.center` の直線に対する符号付き距離（左側が正）
- `d`: `abs(d_signed)`（常に正）
- `xe`, `ye`: 3.2 節の Fresnel 積分で求めた終点変位
- `τ`: 3.3 節で求めた全偏角
- `proj_center`: 円の中心から直線への垂線の足（直線上の点）
- `sign`: 円が直線の左側（`d_signed > 0`）なら `+1.0`、右側なら `-1.0`

```python
import math

# proj_center: 円心から直線への垂線の足
proj_center = line.project(circle.center)

# d_signed: 符号付き距離（2D外積）
diff = circle.center - ref_start
d_signed = direction.x * diff.y - direction.y * diff.x

d    = abs(d_signed)
sign = +1.0 if d_signed > 0 else -1.0

# 円側接点 _circle_pt
_circle_pt = (proj_center
              + direction   * R * math.sin(τ)
              + left_normal * sign * (d - R * math.cos(τ)))

# 線側接点 _line_pt
_line_pt = proj_center + direction * (R * math.sin(τ) - xe)
```

### 3.5 点列の生成（等接線角度変化方式）

以下の変数を使う。

- `A²`: クロソイドパラメータの二乗（`= R · L`）
- `τ`: 全偏角（3.3 節で求めた値）
- `n_steps`: 出力する点の数（ビュースケールに応じて動的に変化）
- `i`: ステップのインデックス（`0` から `n_steps` まで）
- `θ_i`: ステップ `i` での接線方向変化量 [ラジアン]
- `s_i`: ステップ `i` での弧長 [m]（線側接点からの距離）

接線方向の変化量が各ステップで一定になるよう点を配置する（曲率の大きい部分で点が密になる）:

```
θ_i = i · τ / n_steps          # ステップ i の接線変化量
s_i = sqrt(2 · A² · θ_i)       # 対応する弧長
```

描画点密度はビュースケールに応じて `n_steps` を動的に変化させ、ズームインしても滑らかに表示される。

### 3.6 クロソイドのカーブ方向

以下の変数を使う。

- `direction`: 直線（実効直線）の方向単位ベクトル
- `ref_start`: 直線の参照始点座標
- `circle.center`: 円の中心座標
- `d_signed`: `direction` と `(circle.center - ref_start)` の 2D 外積（左側が正）

```python
# 2D 外積: cross(a, b) = a.x * b.y - a.y * b.x
diff = circle.center - ref_start
d_signed = direction.x * diff.y - direction.y * diff.x

is_left_curve = d_signed > 0  # True: 左カーブ、False: 右カーブ
```

---

## 4. メイン編集画面

### 4.1 ビュー操作

| 操作 | 動作 |
|------|------|
| マウスホイール | ズームイン/アウト（マウス位置を中心） |
| 左ドラッグ（何もない場所） | パン（4px 以上でパン判定、ドラッグ中は握り手カーソル） |
| 中ボタンドラッグ | パン |
| 4px 未満の移動 | クリック（選択解除）として扱う |

### 4.2 モード切替

| キー | モード |
|------|--------|
| `S` | 選択モード |
| `L` | 直線モード |
| `C` | 円モード |

### 4.3 直線モード

マウスを左クリックするたびに折れ線を描く。1回目のクリック位置を記憶し、2回目以降のクリックで直線を追加・折れ線接続する。ラバー線により次の直線の予定位置を表示する。`Esc` キーで連続入力をリセット。

### 4.4 円モード

マウスの左クリックで中心を決め、ドラッグで半径を仮表示し、左ボタンを離すことで半径を確定する。

### 4.5 選択モードでの図形操作

- 左クリックで選択、`Shift` + クリックで複数選択
- ホバー中の図形はハイライト表示
- `Del` キーで削除（直線・円を削除すると関連クロソイドも削除）

**1直線が選択された場合のハンドル**:

| ハンドル | 色 | 動作 |
|---------|------|------|
| 参照始点・参照終点（参照点） | 灰色 | ドラッグで参照点を移動、関連クロソイドを自動再計算 |
| 線分の始点・終点（端点） | 赤色 | ドラッグで端点を直線上で移動 |
| snap 済み端点 | — | ハンドルでなくマーカー（菱形）を表示 |
| 共有参照点 | 橙色 | 折れ線・スムーズ接続時に1つだけ表示、ドラッグで両直線が追従 |

**1円が選択された場合のハンドル**:

| ハンドル | 色 | 動作 |
|---------|------|------|
| 中心点 | 灰色 | ドラッグで移動（スムーズ接続時は角の二等分線上に束縛） |
| 半径ハンドル（円の右端） | 緑色 | ドラッグで半径変更 |
| 円弧の始点・終点（端点） | 赤色 | ドラッグで円周上を移動 |

### 4.6 2図形選択時の操作

**2直線が選択された場合（右パネルから操作）**:

| 操作 | 説明 |
|------|------|
| 折れ線接続 | 交点を共有参照点として2直線を接続 |
| スムーズ接続 | クロソイドを介した滑らかな接続（円・クロソイドを自動生成） |
| 接続解除 | 既存の接続を解除 |

**スムーズ接続の手順**:

以下の変数を使う。

- `X`: 直線 A と直線 B の交点座標
- `P`: 接続後の直線 A の、X と異なる側の参照点
- `Q`: 接続後の直線 B の、X と異なる側の参照点
- `J`: `P→X` 方向の実効直線（`PX` 方向ベクトルから `QX` 方向ベクトルへの有向角の sin が非負の場合は直線 A、負の場合は直線 B）
- `K`: `Q→X` 方向の実効直線（J と逆）
- `U`: J の X と異なる側の端点
- `V`: K の X と異なる側の端点
- `XU`, `XV`: X から U、V への単位ベクトル
- `bisect`: 角 UXV の二等分線方向の単位ベクトル（`normalize(XU + XV)`、折れ角の内側を向く）
- `C`: 二等分線上に配置する円

```python
import math

XU     = normalize(U - X)
XV     = normalize(V - X)
bisect = normalize(XU + XV)   # 折れ角の内側（小さい角度側）を向く
```

手順:

1. 直線 A・B を折れ線接続して交点 X を求める
2. 有向角の sin の符号から J・K の向きを決定し、U・V を特定する
3. `bisect` を計算する
4. `bisect` 方向の直線上にデフォルト距離（`d = 1.5 · R`）で円 `C` を配置する
5. 直線 J と円 `C` で**左カーブ**のクロソイド E を生成（`snap_segment=True`, `snap_arc=True`）
6. 直線 K と円 `C` で**右カーブ**のクロソイド F を生成（`snap_segment=True`, `snap_arc=True`）

スムーズ接続中、円の中心は角の二等分線上に束縛される。交点ハンドルや参照点の移動に連動して円も追従する。

**直線と円が選択された場合**（クロソイド本数 `n` により操作が変わる）:

| 操作 | n=0 | n=1 | n=2 |
|------|-----|-----|-----|
| クロソイドを追加 | 有効 | 有効（反転側） | 無効 |
| クロソイドを削除 | 無効 | 有効 | 無効 |
| クロソイドを反転 | 無効 | 有効 | 無効 |

### 4.7 図形の色分け

| 図形 | 色 |
|------|------|
| 直線（参照線、破線） | 灰色 |
| 線分 | 青色 |
| 円（円弧なし） | 紫色（実線） |
| 円（円弧あり） | 薄紫色（点線） |
| 円弧 | 紫色（太い実線） |
| クロソイド | 緑色 |
| クロソイド 線側接点マーカー（菱形） | 黄色 |
| クロソイド 円側接点マーカー（菱形） | 橙色 |
| 選択中の図形 | 黄橙色（ハイライト） |
| ホバー中の図形 | 黄色（ハイライト） |
| 参照点・中心点のハンドル | 灰色 |
| 端点のハンドル | 赤色 |
| 半径ハンドル | 緑色 |
| 共有点（交点）ハンドル | 橙色 |

### 4.8 Undo

`Ctrl+Z` で最大 500 手順まで遡ることができる。シーン全体を JSON でシリアライズしてスタックに積む方式。

---

## 5. 右パネル

### 5.1 マウス座標表示

編集画面上にマウスカーソルがある間、右パネルの上部にカーソルのワールド座標（X, Y）をリアルタイムで表示する（小数点以下3桁）。

### 5.2 図形選択コンボボックス

複数のコンボボックスから図形を選択し「選択を適用」ボタンで選択できる。コンボボックスの個数は `+`/`−` ボタンで増減可能。

**コンボボックスの表示ラベル形式**:

| 種別 | 形式 |
|------|------|
| 直線 | `{ニックネーム} [直線#{id}]` |
| 線分 | `線分#{id} (直線:{直線のニックネーム}) [線分#{id}]` |
| 円 | `{ニックネーム} [円#{id}]` |
| 円弧 | `円弧#{id} (円:{円のニックネーム}) [円弧#{id}]` |
| クロソイド | `{ニックネーム} [クロソイド#{id}]` |

**各コンボボックスの選択肢の構成**:

- **1つ目**: 全図形
- **2つ目**: 1つ目の両端点に隣接する全図形を先頭に表示し、区切り線を挟んで全図形
- **3つ目以降**: 前の図形の出口端点に隣接する図形を先頭に表示し、区切り線を挟んで全図形

最後のコンボボックスに図形が選択された場合、自動的に1個コンボボックスを追加する。

**`[順]` / `[逆]` の表示**（隣接候補が2個以上の場合）:

以下の変数を使う。

- `exit_tan`: 前の図形の出口での進行方向接線ベクトル（単位ベクトル）
- `entry_tan`: 次の候補図形の「共有端点→近傍点」方向ベクトル（単位ベクトル）
- `dot`: `exit_tan` と `entry_tan` の内積

```
dot = exit_tan.x * entry_tan.x + exit_tan.y * entry_tan.y
dot ≥ 0 → [順]（同方向、スムーズに繋がる）
dot < 0 → [逆]（逆方向、約180度ターン）
```

各図形の「共有端点→近傍点」ベクトルの計算方法:

| 図形 | 近傍点の求め方 |
|------|--------------|
| 線分 | 共有端点からもう一方の端点への方向ベクトル |
| 円弧 | 共有端点が始点なら `angle_start + 0.1°`、終点なら `angle_end − 0.1°` の円周上の点 |
| クロソイド | 点列 `points` で共有端点の隣の点 |

### 5.3 図形のプロパティ表示・編集

| 図形 | 表示・編集内容 |
|------|--------------|
| 直線 | 参照始点・参照終点の X/Y 座標（数値入力）、方向角（読み取り専用）、保持する線分の各プロパティ |
| 線分 | 親直線の表示、始点・終点の X/Y 座標と割合 t（数値入力、直線上に束縛） |
| 円 | 中心 X/Y・半径（数値入力）、保持する円弧の一覧 |
| 円弧 | 親円の表示、始点・終点の角度（度数）または X/Y 座標（数値入力、円上に束縛） |
| クロソイド | カーブ方向・`reversed_flag`・パラメータ A・全偏角 τ・接点座標（読み取り専用）、`snap_segment`/`snap_arc` on/off・反転ボタン |

### 5.4 縦断設計情報の表示

平面線形要素に対応する `ElementProfile` が存在する場合、右パネルの末尾に以下を表示する:

- 平面長 (`plan_length`)、始端標高 (`elev_start`)、終端標高 (`elev_end`)
- 勾配直線の一覧（距離範囲と勾配 [%]）
- 縦断曲線の一覧（PVI 位置・曲線長・K 値）

### 5.5 関連図形の表示と選択

プロパティ表示の最後に、接続している図形の一覧を表示する。各図形に「選択」ボタン（その図形のみ選択）と「選択追加」ボタン（現在の選択に追加）を提供する。

### 5.6 図形を削除ボタン

コンボボックスで選択中の図形を削除する。実行前に確認ダイアログを表示する。

### 5.7 ニックネーム管理

各図形（直線・円・クロソイド）に任意のニックネームを設定できる。ニックネームはファイル保存・読み込みに対応し、縦断線形ウィンドウのカラーバーラベルとしても使用される。

---

## 6. 縦断線形設計ウィンドウ

メニュー「縦断線形(&V)」→「縦断線形ウィンドウを開く」（`Ctrl+Shift+V`）で開く。メインウィンドウとは独立して操作できる。

### 6.1 ビュー操作

| 操作 | 動作 |
|------|------|
| マウスホイール | 距離方向スケールを変更 |
| `Shift` + ホイール | 標高方向スケールを変更 |
| 左ドラッグ（何もない場所） | パン |
| 中ボタンドラッグ | パン |
| `Ctrl+0` | 全体表示 |

### 6.2 モード切替

| キー | モード |
|------|--------|
| `S` | 選択モード（勾配直線・縦断曲線をクリックで選択） |
| `G` | 勾配直線モード（左クリックで始点→終点を指定） |
| `Esc` | 連続入力のリセット |

### 6.3 勾配直線の入力・編集

**スナップ動作**: 既存の端点に 12px 以内に近ければ自動スナップ（高さを揃える）。

**重複置換**: 新しい勾配直線を追加するとき、既存の勾配直線と距離方向に重複する部分は置換される。はみ出し部分は端点の標高を補間して残す。

**隣接スナップ（`_snap_grade_lines(direction)`）**: 勾配直線の追加・ハンドルドラッグ・数値入力のいずれの後も実行し、隣接する勾配直線の端点の距離・標高を強制一致させる。

- `direction='end'`: 前から後へ伝播（変更した勾配直線の終端値を次の勾配直線の始端へ）
- `direction='start'`: 後から前へ伝播
- `direction='both'`: 両方向

### 6.4 縦断曲線の挿入・編集

勾配直線を選択した状態で、右パネルから曲線長を入力し「縦断曲線を挿入」ボタンで挿入する。

**縦断曲線のパラメータ**:

以下の変数を使う。

- `g1`: 前勾配 [%]（PVI より手前の勾配直線の勾配）
- `g2`: 後勾配 [%]（PVI より奥の勾配直線の勾配）
- `L`: 曲線長 [m]
- `PVI`: Point of Vertical Intersection — 2勾配線の交点（距離 [m], 標高 [m]）。勾配直線の終点と一致する
- `VPC`: Vertical Point of Curvature — 縦断曲線の始点（距離 = `PVI の距離 − L/2`）
- `VPT`: Vertical Point of Tangency — 縦断曲線の終点（距離 = `PVI の距離 + L/2`）
- `elev_vpc`: VPC の標高 [m]
- `x`: VPC を原点とした局所距離 [m]（`0 ≤ x ≤ L`）

**放物線式**（VPC を原点とする局所距離 `x` に対する標高 `y(x)`）:

```
y(x) = elev_vpc + (g1 / 100) * x + ((g2 - g1) / (200 * L)) * x²
```

**K 値**（縦断曲線の緩やかさの指標）:

```
K = L / |g2 - g1|
```

縦断曲線を挿入しても勾配直線の端点（PVI）は変更しない。描画時は VPC〜VPT の範囲で縦断曲線の放物線を優先し、それ以外は勾配直線を使う。3D ビューアでの高さ計算も同様に縦断曲線を優先する。

### 6.5 平面線形との連携とカラーバー

縦断線形ウィンドウを開く際、設計画面で選択中の平面線形要素が渡される。チェーン順に並べた要素が縦断キャンバス上部のカラーバーとして表示される。

| 要素 | カラーバーの色 |
|------|--------------|
| 線分 | 青色 |
| クロソイド | 緑色 |
| 円弧 | 紫色 |

**チェーン順序の解決（`resolve_chain()`）**: 孤立端点（snap 接続のない端点）を持つ要素を先頭にし、既存 `ElementProfile` の `reversed_flag` と一致する候補を優先する。

### 6.6 ElementProfile への保存

縦断線形ウィンドウを閉じると `save_to_profiles()` が呼ばれ、チェーン全体の勾配直線・縦断曲線を各要素の距離範囲に切り出して `ElementProfile` に書き戻す。

ウィンドウを開いた時点で `set_plan_elements()` が `_snap_grade_lines('both')` を実行し、要素間の境界標高を揃える。これにより古いデータの不整合も自動修正される。

---

## 7. 3D走行ビューア

メニュー「3Dビューア(&3)」→「選択要素で3D走行ビューアを開く」（`Ctrl+Shift+3`）で起動。別プロセスとして Panda3D ウィンドウが開く。

### 7.1 起動と表示対象

- **走行対象**: 選択した平面線形要素のチェーン（未選択なら全要素）
- **背景表示**: シーン内の全線分・全円弧・全クロソイド（要素ごとに独立メッシュ）

走行チェーンはやや明るいグレーで表示し、背景は暗いグレーで表示する。

### 7.2 3D 中心線の生成

`build_centerline()` が平面線形と縦断線形から 3D 点列 `[(x, y, z, dist), ...]` を生成する。

- `x`, `y`: ワールド座標（平面位置）
- `z`: 標高 [m]
- `dist`: チェーン始端からの累積距離 [m]

生成手順:

1. 各要素から 2D 中心線を生成（線分: 直線補間、円弧: 角度補間、クロソイド: 点列リサンプリング）
2. 各点の標高 `z` は `ElementProfile` の `grade_lines` から補間（`vertical_curves` の VPC〜VPT 範囲内は縦断曲線が優先）
3. 各要素の先頭点（境界点）は前の要素の末端高さをそのまま継承（段差防止）

### 7.3 道路メッシュ・路面標示・橋脚の生成

| 要素 | 仕様 |
|------|------|
| 道路幅 | 全幅 3.5m（半幅 1.75m） |
| 路面メッシュ | 中心線に沿った帯状三角形メッシュ（`z + 0.02m` で地面より上） |
| センターライン | 黄色の線（走行チェーン）、グレーの線（背景） |
| 白線（路肩ライン） | 左右の道路端（路面より 0.08m 上） |
| 橋脚 | 約 30m おきに道路端から 0.5m 外側に左右1本ずつ、地面から道路面まで、断面 0.4m × 0.4m |

### 7.4 路面表示の on/off

`R` キーで路面メッシュの表示を切り替える。off のとき、地面グリーンがガラス床として見えて立体感が分かりやすくなる。

### 7.5 キー操作一覧

| キー | 動作 |
|------|------|
| `V` | 追従視点 ↔ 車載視点の切替 |
| `R` | 路面表示 ON/OFF |
| `Space` | 一時停止 / 再開 |
| `↑` / `↓` | 速度 ±10 m/s |
| `←` / `→` | 100m 後退 / 前進 |
| `Esc` | 終了 |

---

## 8. メニュー・ショートカット一覧

### メインウィンドウ

| ショートカット | 動作 |
|--------------|------|
| `Ctrl+S` | ファイルに保存 |
| `Ctrl+Shift+S` | 名前を付けて保存 |
| `Ctrl+O` | ファイルを開く |
| `Ctrl+Z` | Undo（最大500手順） |
| `Ctrl+0` | 全体表示 |
| `Ctrl+Shift+V` | 縦断線形ウィンドウを開く |
| `Ctrl+Shift+3` | 3D 走行ビューアを開く |
| `S` | 選択モード（編集画面） |
| `L` | 直線モード（編集画面） |
| `C` | 円モード（編集画面） |
| `Del` | 選択図形を削除 |
| `Esc` | 連続入力をリセット |

### 縦断線形ウィンドウ

| ショートカット | 動作 |
|--------------|------|
| `S` | 選択モード |
| `G` | 勾配直線モード |
| `Esc` | 連続入力のリセット |
| `Ctrl+0` | 全体表示 |
| `Del` | 選択した勾配直線・縦断曲線を削除 |

### 3D 走行ビューア

| ショートカット | 動作 |
|--------------|------|
| `V` | 追従視点 ↔ 車載視点 |
| `R` | 路面表示 ON/OFF |
| `Space` | 一時停止 / 再開 |
| `↑` / `↓` | 速度 ±10 m/s |
| `←` / `→` | 100m 後退 / 前進 |
| `Esc` | 終了 |

---

## 付録A. 実装仕様（再実装に必要な詳細）

### A.1 Vec2 クラス

2次元ベクトルを表す基本クラス。以下の演算を持つ。

```python
from dataclasses import dataclass
import math

@dataclass
class Vec2:
    x: float
    y: float

    def __add__(self, o):   return Vec2(self.x + o.x, self.y + o.y)
    def __sub__(self, o):   return Vec2(self.x - o.x, self.y - o.y)
    def __mul__(self, s):   return Vec2(self.x * s,   self.y * s)
    def __rmul__(self, s):  return self.__mul__(s)
    def __neg__(self):      return Vec2(-self.x, -self.y)
    def dot(self, o):       return self.x * o.x + self.y * o.y
    def cross(self, o):     return self.x * o.y - self.y * o.x   # 2D外積
    def length(self):       return math.hypot(self.x, self.y)
    def normalized(self):
        l = self.length()
        return Vec2(self.x / l, self.y / l) if l > 1e-12 else Vec2(1, 0)
    def perp(self):         return Vec2(-self.y, self.x)          # CCW 90°回転（left_normal）
```

`perp()` は `left_normal` の計算に使い、`direction.perp()` = `Vec2(-dy, dx)` となる。

### A.2 Fresnel 積分の数値計算詳細

#### 終点変位の計算（中点則）

```python
def _fresnel_xy_tau(tau_end: float, R: float, n: int = 500) -> tuple[float, float]:
    """
    クロソイド終点の局所座標変位 (xe, ye) を中点則で数値積分する。
    L = 2R*τ,  A² = R*L

    変数:
      tau_end: 全偏角 τ [ラジアン]
      R:       円の半径 [m]
      n:       積分ステップ数（デフォルト 500）
      L:       曲線長 [m]
      A2:      A² = R * L
      ds:      積分の刻み幅 [m]
      s:       中点の弧長 [m]
      theta:   s における接線変化量 = s² / (2A²) [ラジアン]
    """
    import math
    if tau_end < 1e-9:
        return 0.0, 0.0
    L  = 2.0 * R * tau_end
    A2 = R * L
    x, y = 0.0, 0.0
    ds = L / n
    for i in range(n):
        s     = (i + 0.5) * ds          # 中点
        theta = s * s / (2.0 * A2)
        x += math.cos(theta) * ds
        y += math.sin(theta) * ds
    return x, y
```

#### 全偏角 τ の二分法探索

```python
def _find_tau(R: float, d_abs: float,
              max_tau: float = 2.0 * math.pi * 0.999) -> float | None:
    """
    Fresnel 条件 ye(τ) = d_abs - R*cos(τ) を満たす τ を二分法で求める。

    変数:
      R:       円の半径 [m]
      d_abs:   円の中心から直線への垂直距離 [m]（常に正）
      max_tau: 探索上限（ほぼ 2π）
    """
    import math
    if d_abs <= R:
        return None

    def residual(tau):
        _, y = _fresnel_xy_tau(tau, R)
        return y - (d_abs - R * math.cos(tau))

    lo, hi = 1e-4, max_tau
    if residual(lo) * residual(hi) > 0:
        return None
    for _ in range(80):        # 80回反復
        mid = (lo + hi) / 2.0
        if residual(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
```

#### 点列生成の詳細アルゴリズム

等接線角度変化方式で、内部積分は `n_int = max(n_steps * 8, 800)` ステップの中点則で行い、等 θ 間隔の出力点を線形補間で取り出す。

```python
# n_steps: 出力点数 = max(80, int(tau / (2π) * 512) + 40)
# n_int:   内部積分ステップ数 = max(n_steps * 8, 800)
# ds_int:  内部積分の刻み幅 = L / n_int

# 出力する弧長リスト（等 θ 間隔）
output_s = []
for i in range(1, n_steps + 1):
    theta_i = i * tau / n_steps
    s_i     = math.sqrt(2.0 * A2 * theta_i)
    output_s.append(s_i)

# 内部積分しながら output_s の各点で wx, wy を記録
pts = [lc]   # 先頭は線側接点 lc
x_acc, y_acc = 0.0, 0.0
out_idx = 0

for i in range(n_int):
    s_mid  = (i + 0.5) * ds_int
    theta  = s_mid * s_mid / (2.0 * A2)
    x_acc += math.cos(theta) * ds_int
    y_acc += math.sin(theta) * ds_int
    s_cur  = (i + 1) * ds_int

    while out_idx < len(output_s) and s_cur >= output_s[out_idx] - 1e-9:
        wx = lc.x + direction.x * x_acc + left_n.x * sign * y_acc
        wy = lc.y + direction.y * x_acc + left_n.y * sign * y_acc
        pts.append(Vec2(wx, wy))
        out_idx += 1
```

### A.3 snap=off 時の線分・円弧の分割と復元

クロソイドが `snap_segment=False` のとき、線側接点 X で直線上の最も近い線分 AB を AX と XB に分割する。クロソイドは分割で生成した2本の線分の ID を `_split_seg_ids: list[int]` に保存し、接点が移動するたびに端点を追従更新する。

`snap_segment` を `False` から `True` に切り替えた場合や、クロソイドを削除した場合は XB を削除して AB に戻す（`_clear_segment_split()`）。

円弧の分割（`_split_arc_ids`）も同様の方式で管理する。

### A.4 LineConnection データ構造

2直線間の接続情報を保持するデータクラス。

```python
@dataclass
class LineConnection:
    kind:              str     # "polyline" | "smooth"
    line_a:            Line
    line_b:            Line
    shared_point:      Vec2    # 共有参照点の座標
    a_end_is_shared:   bool    # True: line_a.ref_end が共有点
    b_start_is_shared: bool    # True: line_b.ref_start が共有点
    # smooth 専用フィールド
    circle:            Circle | None = None
    bisector_dir:      Vec2 | None   = None   # 二等分線方向
    line_j_reversed:   bool          = False
    line_k_reversed:   bool          = False
```

`line_a.connection` と `line_b.connection` に同じ `LineConnection` オブジェクトが設定される。スムーズ接続時は `circle.bisector_origin`（二等分線の通過点）と `circle.bisector_dir` も設定し、円の中心を二等分線上に束縛する。

### A.5 GradeLine と VerticalCurve の保存フォーマット

**GradeLine のフィールドと保存形式**:

```json
{
  "id":         10,
  "dist_start": 0.0,
  "elev_start": 20.0,
  "dist_end":   66.33,
  "elev_end":   20.0
}
```

`next_curve`/`prev_curve`（隣接 VerticalCurve への参照）はメモリ上のみで管理し、ファイルには保存しない。勾配 [%] は `gradient = (elev_end - elev_start) / (dist_end - dist_start) * 100` で算出する。

**VerticalCurve のフィールドと保存形式**:

```json
{
  "id":           20,
  "pvi_dist":     303.52,
  "pvi_elev":     20.0,
  "g1":           2.5,
  "g2":           0.0,
  "length":       50.0,
  "prev_line_id": 11,
  "next_line_id": 12
}
```

派生値（読み取り専用プロパティ）:

```python
@property
def vpc_dist(self): return self.pvi_dist - self.length / 2
@property
def vpt_dist(self): return self.pvi_dist + self.length / 2
@property
def vpc_elev(self): return self.pvi_elev - self.g1 / 100 * self.length / 2
@property
def vpt_elev(self): return self.pvi_elev + self.g2 / 100 * self.length / 2
```

`elevation_at(dist)` の実装（`dist` はこの VerticalCurve が属する EP 内の相対距離）:

```python
def elevation_at(self, dist: float) -> float:
    """
    変数:
      dist:     EP 内の相対距離 [m]
      x:        VPC を原点とした局所距離 = dist - vpc_dist  [m]
      vpc_elev: VPC の標高 [m]（= pvi_elev - g1/100 * L/2）
    """
    x = dist - self.vpc_dist
    if x < 0 or x > self.length:
        return float('nan')   # 範囲外は NaN を返す
    return (self.vpc_elev
            + self.g1 / 100 * x
            + (self.g2 - self.g1) / (2 * self.length) / 100 * x ** 2)
```

### A.6 resolve_chain アルゴリズム

```python
SNAP_TOL = 1.0   # 端点が同一とみなす距離閾値 [m]

def resolve_chain(elems, scene):
    """
    要素リストから (順序付き要素リスト, reversed_flags) を返す。

    アルゴリズム:
    1. 各要素の endpoints (start_pt, end_pt) を取得する
       - Segment:  (seg.start, seg.end)
       - Arc:      (arc.start, arc.end)
       - Clothoid: (clo._line_pt, clo._circle_pt)

    2. 「片方の端点が孤立している」要素を先頭候補とする
       孤立端点 = 他のどの要素の端点とも SNAP_TOL 以内にない端点
       - 始点が孤立 → 正順（rev=False）で先頭
       - 終点が孤立 → 逆順（rev=True）で先頭

    3. 既存 ElementProfile の reversed_flag と一致する候補を優先する

    4. 貪欲法でチェーンを構築する
       - 現在のチェーン末尾要素の出口端点（正順なら end、逆順なら start）を求める
       - 残り要素の中で最も近い端点を持つ要素を次に追加する
       - 近い側が start なら rev=False、end なら rev=True
       - SNAP_TOL * 10 以内で見つからない場合は残り先頭を強制追加する
    """
```

### A.7 build_centerline の詳細仕様

```python
def build_centerline(elements, profiles, rev_flags,
                     n_per_m: float = 0.5) -> list[tuple]:
    """
    変数:
      elements:  Segment / Arc / Clothoid のリスト（チェーン順）
      profiles:  対応する ElementProfile のリスト
      rev_flags: 各要素を逆順で使うか否かのフラグのリスト
      n_per_m:   1m あたりの出力点数（デフォルト 0.5 点/m = 2m 間隔）

    各要素ごとに n = max(2, int(L * n_per_m)) 点の 2D 座標を生成する:
      Segment:   始点→終点を n 等分した線形補間
      Arc:       angle_start から CCW 方向に n 等分した角度補間
      Clothoid:  elem.points（Vec2 リスト）を累積弧長でリサンプリングして n 点取得

    逆順（rev=True）の場合は pts_2d を reversed() する。

    境界点の処理:
      各要素の先頭点（i=0）について、前の要素の末端点と座標が重複する。
      この点の高さは前の要素末端の高さ（points[-1][2]）をそのまま継承し、
      _ep_elev() を呼ばない（段差防止）。

    高さ計算（i >= 1 の点）:
      rel = dist - offset        （正順の場合）
      rel = L - (dist - offset)  （逆順の場合）
      z   = _ep_elev(ep, rel)

    _ep_elev(ep, rel):
      1. ep.vertical_curves の中で vpc_dist <= rel <= vpt_dist の VC を探す
         → 見つかれば vc.elevation_at(rel)（NaN でなければ採用）
      2. ep.grade_lines の中で dist_start <= rel <= dist_end の GL を探す
         → 線形補間
      3. 見つからなければ 0.0
    """
```

