# 道路設計アプリ

平面線形（直線・円弧・クロソイド）と縦断線形（勾配直線・縦断曲線）を設計し、3D で走行シミュレーションを行うデスクトップアプリケーション。

## 必要環境

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（パッケージマネージャ）

> **ライセンス**: UI フレームワークに PySide6（LGPL v3）を使用しています。

## セットアップ

```bash
git clone <repository-url>
cd road_designer
uv sync
```

3D 走行ビューアも使う場合（Panda3D を含む）:

```bash
uv sync  # pyproject.toml の dependencies に panda3d が含まれるため自動でインストールされる
```

## 起動

```bash
uv run python src/main.py
```

## ディレクトリ構造

```
road_designer/
├── README.md
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── road_design_spec.md           # 仕様書（ユーザー向け・再実装向け）
│   ├── road_design_basic_design.md   # 基本設計書
│   └── road_design_detail_design.md  # 詳細設計書
├── src/
│   ├── main.py
│   ├── models.py
│   ├── canvas.py
│   ├── right_panel.py
│   ├── main_window.py
│   ├── vertical_window.py
│   └── road_viewer.py
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_canvas.py
    ├── test_canvas_qtest.py
    ├── test_right_panel.py
    ├── test_vertical_window.py
    ├── test_road_viewer.py
    ├── test_main_window.py
    └── test_main.py
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `main.py` | エントリーポイント |
| `models.py` | データモデル（`Line`・`Segment`・`Circle`・`Arc`・`Clothoid`・`ElementProfile` 等）、`resolve_chain`・`tangent_at` などのユーティリティ関数 |
| `canvas.py` | メイン編集キャンバス（描画・マウス操作・ハンドル） |
| `right_panel.py` | 右パネル（図形選択コンボ・プロパティ表示・操作ボタン） |
| `vertical_window.py` | 縦断線形設計ウィンドウ |
| `main_window.py` | メインウィンドウ（メニュー・ファイル操作・ウィンドウ管理） |
| `road_viewer.py` | 3D 走行ビューア（Panda3D） |

## テスト

### 実行方法

```bash
# 全テストを実行
uv run pytest

# 詳細出力
uv run pytest -v

# 特定ファイルのみ
uv run pytest tests/test_models.py
```

### カバレッジ計測

```bash
# ターミナルに未カバー行を表示
uv run pytest --cov=src --cov-branch --cov-report=term-missing

# HTML レポートを生成（htmlcov/index.html で確認）
uv run pytest --cov=src --cov-branch --cov-report=html
```

### Windows での注意

Qt のヘッドレス実行（`QT_QPA_PLATFORM=offscreen`）は Linux/macOS 向けの設定です。
`conftest.py` がプラットフォームを自動判別するため、Windows では設定不要です。

```bash
# Linux / macOS（CI 環境など）
QT_QPA_PLATFORM=offscreen uv run pytest

# Windows（設定不要）
uv run pytest
```

### テスト構成

| ファイル | 対象 | 件数 |
|---|---|---|
| `test_models.py` | データモデル・計算ロジック | 240件 |
| `test_canvas.py` | 座標変換・ヒット判定・UI ロジック | 94件 |
| `test_canvas_qtest.py` | `QTest` を使ったイベント・描画 | 47件 |
| `test_right_panel.py` | 隣接検索・接線判定・結合操作 | 74件 |
| `test_vertical_window.py` | 縦断線形の計算・snap | 79件 |
| `test_road_viewer.py` | 3D 中心線生成（Panda3D なしでスキップ） | 31件 |
| `test_main_window.py` | ウィンドウの操作ロジック | 50件 |
| `test_main.py` | エントリーポイント | 14件 |

## CI

GitHub Actions により push / PR のたびに自動テストを実行します。
設定ファイル: `.github/workflows/ci.yml`

- **対象 OS**: Ubuntu / macOS / Windows
- **対象 Python**: 3.11 / 3.12
- **カバレッジ**: Ubuntu + Python 3.12 の結果を Codecov にアップロード

## 操作方法

### モード切替

| キー | モード |
|------|--------|
| `S` | 選択モード |
| `L` | 直線モード |
| `C` | 円モード |

### 直線モード

- 左クリックで始点・終点を指定（折れ線を連続入力）
- `Esc` で連続入力をリセット

### 円モード

- 左クリック＆ドラッグで中心と半径を指定して円を作成

### 選択モード

- 左クリック: 図形を選択
- `Shift`+クリック: 複数選択
- `Del`: 選択図形を削除

### ビュー操作

- マウスホイール: ズームイン/アウト（マウス位置を中心）
- 左ドラッグ（図形なし）: パン
- 中ボタンドラッグ: パン

### キーボードショートカット（メイン画面）

| ショートカット | 機能 |
|---|---|
| `Ctrl+S` | 上書き保存 |
| `Ctrl+Shift+S` | 名前を付けて保存 |
| `Ctrl+O` | ファイルを開く |
| `Ctrl+Z` | Undo（最大 500 手順） |
| `Ctrl+0` | 全体表示 |
| `Ctrl+Shift+V` | 縦断線形ウィンドウを開く |
| `Ctrl+Shift+3` | 3D 走行ビューアを起動 |

### キーボードショートカット（縦断線形ウィンドウ）

| ショートカット | 機能 |
|---|---|
| `S` | 選択モード |
| `G` | 勾配直線モード |
| `Esc` | 連続入力のリセット |
| `Ctrl+0` | 全体表示 |
| `Del` | 選択した勾配直線・縦断曲線を削除 |

### 3D 走行ビューア操作

| キー | 動作 |
|------|------|
| `V` | 追従視点 ↔ 車載視点 |
| `R` | 路面表示 ON/OFF |
| `Space` | 一時停止 / 再開 |
| `↑` / `↓` | 速度 ±10 m/s |
| `←` / `→` | 100m 後退 / 前進 |
| `Esc` | 終了 |

## 主な機能

### 平面線形

- **直線**・**線分**: 参照始点/終点により定義。折れ線接続・スムーズ接続に対応
- **円**・**円弧**: 中心と半径により定義。円弧の始点・終点をハンドルで編集
- **クロソイド**: Fresnel 積分による正確な計算（scipy 不使用、二分法 80 回反復）
  - 線分・円弧への snap 機能（snap=off 時は線分・円弧を接点で自動分割）
  - デフォルト snap off。スムーズ接続で自動生成した場合のみ on
  - 反転フラグ（同一直線・円に 2 本作成可能）
- **接続操作**: 折れ線接続・スムーズ接続（クロソイドを自動生成）・接続解除
- **ハンドル編集**: 参照点・端点・半径・共有点をドラッグで変形
- **Undo**: 最大 500 手順

### 右パネル

- 図形選択コンボボックス（隣接図形を優先表示、`[順]`/`[逆]` で接続方向を表示）
- プロパティの数値入力による精密編集
- 縦断設計情報の表示（勾配直線・縦断曲線の一覧）
- 図形の削除・再描画ボタン

### 縦断線形

- 勾配直線の作成・編集（重複区間の自動置換、隣接スナップ）
- 縦断曲線（放物線）の挿入（PVI・VPC・VPT・K 値の自動計算）
- 縦断曲線と勾配直線が重なる区間は縦断曲線を優先して高さを計算
- 平面線形チェーンのカラーバー表示（線分=青・クロソイド=緑・円弧=紫）

### 3D 走行ビューア

- 選択した平面線形チェーンを 3D で走行（未選択時は全要素）
- 全道路要素を背景として表示
- 道路幅 3.5m の路面メッシュ・路肩白線・橋脚（約 30m おき）を表示
- 路面表示 ON/OFF で立体感を確認可能

### ファイル

- `.rdjson` 形式（JSON）で保存・読み込み
- ID 衝突を自動検出・修正（`_resolve_id()`）
- 旧フォーマット（トップレベル `nicknames`）との後方互換

## データモデル概要

```
Scene
├── lines: list[Line]
│   └── segments: list[Segment]
├── circles: list[Circle]
│   └── arcs: list[Arc]
├── clothoids: list[Clothoid]       # line + circle で定義
└── element_profiles: list[ElementProfile]  # 縦断線形データ
    ├── grade_lines: list[GradeLine]
    └── vertical_curves: list[VerticalCurve]
```

## クロソイドの数学

クロソイドパラメータ `A`、円の半径 `R`、曲線長 `L`、全偏角 `τ` の関係:

```
A² = R · L
L  = 2R · τ
```

終点の局所座標変位を中点則（500 ステップ）で数値積分:

```
xe = ∫₀ᴸ cos(s²/2A²) ds
ye = ∫₀ᴸ sin(s²/2A²) ds
```

存在条件 `d > R`（`d`: 円心から直線への垂直距離）のとき、Fresnel 条件:

```
ye(τ) = d − R·cos(τ)
```

を二分法（80 回反復）で解いて `τ` を求める。

## 詳細仕様

- 仕様書（ユーザー向け・再実装向け）: [`docs/road_design_spec.md`](docs/road_design_spec.md)
- 基本設計書: [`docs/road_design_basic_design.md`](docs/road_design_basic_design.md)
- 詳細設計書: [`docs/road_design_detail_design.md`](docs/road_design_detail_design.md)

## ライセンス

このリポジトリのコードのライセンスについては LICENSE を参照のこと。
このリポジトリのコードは、3rd party パッケージ を使用しています。
THIRD-PARTY-LICENSE.md を参照のこと。
