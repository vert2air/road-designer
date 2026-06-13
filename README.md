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

起動時にファイルを指定する場合:

```bash
uv run python src/main.py -i path/to/file.rdjson
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
│   ├── vertical_profile.py
│   ├── canvas.py
│   ├── right_panel.py
│   ├── _prop_builder.py
│   ├── main_window.py
│   ├── vertical_window.py
│   ├── road_viewer.py
│   └── _road_mesh.py
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_models_two_line_offset.py
    ├── test_models_scene_ops.py
    ├── test_canvas.py
    ├── test_canvas_qtest.py
    ├── test_canvas_multiselect.py
    ├── test_right_panel.py
    ├── test_right_panel_multiops.py
    ├── test_vertical_window.py
    ├── test_road_viewer.py
    ├── test_road_viewer_class.py
    ├── test_road_mesh.py
    ├── test_main_window.py
    ├── test_main_window_constraints.py
    ├── test_gui_interactions.py
    ├── test_main.py
    ├── test_spec_gui_ch4.py   # 仕様適合テスト 第4章（-m spec）
    ├── test_spec_gui_ch5.py   # 仕様適合テスト 第5章（-m spec）
    ├── test_spec_gui_ch6.py   # 仕様適合テスト 第6章（-m spec）
    └── test_spec_gui_ch8.py   # 仕様適合テスト 第8章（-m spec）
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `main.py` | エントリーポイント |
| `models.py` | データモデル（`Line`・`Segment`・`Circle`・`Arc`・`Clothoid`・`OffsetConstraint`・`TwoLineOffsetConstraint` 等）、`resolve_chain`・`tangent_at`・`effective_set` などのユーティリティ関数 |
| `vertical_profile.py` | 縦断線形データモデル（`ElementProfile`・`GradeLine`・`VerticalCurve` 等。`models.py` から再エクスポート） |
| `canvas.py` | メイン編集キャンバス（描画・マウス操作・ハンドル） |
| `right_panel.py` | 右パネル（図形選択コンボ・プロパティ表示・操作ボタン） |
| `_prop_builder.py` | プロパティパネル UI 構築 Mixin（`right_panel.py` が継承） |
| `vertical_window.py` | 縦断線形設計ウィンドウ |
| `main_window.py` | メインウィンドウ（メニュー・ファイル操作・ウィンドウ管理） |
| `road_viewer.py` | 3D 走行ビューア（Panda3D、別プロセス起動） |
| `_road_mesh.py` | 3D 道路メッシュ生成関数群（`road_viewer.py` から利用） |

## テスト

### 通常テスト（CI・自動実行）

```bash
# 全テストを実行（仕様適合テストは自動除外）
uv run pytest

# 詳細出力
uv run pytest -v

# 特定ファイルのみ
uv run pytest tests/test_models.py
```

### 仕様適合テスト（手動・GUI が必要）

要求仕様書との適合を確認する GUI テストです。Qt ウィンドウを実際に開くため、**ディスプレイのある環境で手動実行**してください。

```bash
# 第4〜6章まとめて実行
uv run pytest -m spec tests/test_spec_gui_ch4.py tests/test_spec_gui_ch5.py tests/test_spec_gui_ch6.py -v

# 章ごとに個別実行
uv run pytest -m spec tests/test_spec_gui_ch4.py -v   # 平面線形編集
uv run pytest -m spec tests/test_spec_gui_ch5.py -v   # 右パネル
uv run pytest -m spec tests/test_spec_gui_ch6.py -v   # 縦断線形ウィンドウ

# spec マーカーの全テスト
uv run pytest -m spec -v
```

> **注意**: 仕様適合テストは CI では除外されます（`pyproject.toml` の `addopts = "-m 'not spec'"`）。

### カバレッジ計測

`uv run pytest` を実行すると、ターミナル表示と `htmlcov/index.html` の両方が
自動生成されます（ブランチカバレッジ込み）。

```bash
# 通常テストを実行（htmlcov/ が生成される）
uv run pytest

# 仕様適合テストを追加計測して htmlcov/ を更新する場合
uv run pytest -m spec --cov-append --cov-report=term-missing --cov-report=html
```

`htmlcov/index.html` をブラウザで開くとファイル別・行別の詳細が確認できます。

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

#### 通常テスト（CI 対象）

| ファイル | 対象 | 件数 |
|---|---|---|
| `test_models.py` | データモデル・計算ロジック | 262件 |
| `test_models_two_line_offset.py` | 2直線+1円オフセット拘束・循環依存検出 | 20件 |
| `test_models_scene_ops.py` | ID 振り直し・マージ・effective_set | 25件 |
| `test_canvas.py` | 座標変換・ヒット判定・UI ロジック | 122件 |
| `test_canvas_qtest.py` | `QTest` を使ったイベント・描画 | 84件 |
| `test_canvas_multiselect.py` | ラバーバンド選択・AABB 変換・折れ線追従 | 42件 |
| `test_right_panel.py` | 隣接検索・接線判定・結合操作 | 272件 |
| `test_right_panel_multiops.py` | 複数選択操作・拘束パネル | 27件 |
| `test_vertical_window.py` | 縦断線形の計算・snap | 168件 |
| `test_road_viewer.py` | 3D 中心線生成（Panda3D なしでスキップ） | 83件 |
| `test_road_viewer_class.py` | RoadViewer クラス（ShowBase モック） | 140件 |
| `test_road_mesh.py` | 3D メッシュ生成 | 39件 |
| `test_main_window.py` | ウィンドウの操作ロジック | 101件 |
| `test_main_window_constraints.py` | 拘束設定・ID 振り直し・マージのハンドラ | 11件 |
| `test_gui_interactions.py` | GUI 相互作用 | 20件 |
| `test_main.py` | エントリーポイント | 15件 |

合計 1,431件（うち通常実行 1,372件、環境依存スキップあり）。

#### 仕様適合テスト（手動・`-m spec`）

| ファイル | 対象仕様書章 | 件数 |
|---|---|---|
| `test_spec_gui_ch4.py` | 第4章 平面線形編集（モード切替・直線/円・ラバーバンド選択・AABB 操作・オフセット拘束・Undo・描画検証） | 37件 |
| `test_spec_gui_ch5.py` | 第5章 右パネル（マウス座標・ホバー情報・道なり・Copy/Paste・複数選択パネル・ニックネーム） | 40件 |
| `test_spec_gui_ch6.py` | 第6章 縦断線形ウィンドウ（モード切替・Undo/Redo・カラーバー・数値入力） | 23件 |
| `test_spec_gui_ch8.py` | 第8章 メニュー・ショートカット（初期化保存・マージ・全削除・ID 振り直し・右パネル表示） | 12件 |

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
- `Shift`+左ドラッグ（図形なし）: ラバーバンド選択（矩形に完全に含まれる図形を一括選択。ドラッグ中は対角距離を右パネルに表示＝簡易測距）
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
| `Ctrl+Shift+I` | 子図形を初期化して保存（別名保存。元シーンは変更しない） |
| `Ctrl+O` | ファイルを開く |
| `Ctrl+Shift+O` | 追加で読み込む（現在のシーンにマージ） |
| `Ctrl+Z` | Undo（最大 500 手順） |
| `Ctrl+0` | 全体表示 |
| `Ctrl+Shift+V` | 縦断線形ウィンドウを開く |
| `Ctrl+Shift+3` | 3D 走行ビューアを起動 |
| —（メニューのみ） | 全削除（確認ダイアログ後、Undo 対応） |
| —（ビューメニュー） | 右パネルを表示（デフォルト非表示、チェックで表示） |

### キーボードショートカット（縦断線形ウィンドウ）

| ショートカット | 機能 |
|---|---|
| `S` | 選択モード |
| `G` | 勾配直線モード |
| `Esc` | 連続入力のリセット |
| `Ctrl+0` | 全体表示 |
| `Del` | 選択した勾配直線・縦断曲線を削除 |
| `Ctrl+Z` | Undo（最大 50 手順） |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |

### 3D 走行ビューア操作

| キー | 動作 |
|------|------|
| `V` | 追従視点 ↔ 車載視点 |
| `O` | 俯瞰視点をサイクル（追従俯瞰 → 固定俯瞰 → 通常）|
| `I` / `K` | 俯瞰モードでズームイン / ズームアウト |
| `A` | オートドライブ ON/OFF（全要素をランダムに走行）|
| `P` / `Shift+P` | 周囲車両を 1 台追加 / 削除 |
| `R` | 路面表示 ON/OFF |
| `Space` | 一時停止 / 再開 |
| `↑` / `↓` | 速度 ±10 m/s |
| `←` / `→` | 100m 後退 / 前進（オートドライブ時は走行履歴を移動） |
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
- **オフセット拘束**: 2 種類（詳細は後述）
- **ハンドル編集**: 参照点・端点・半径・共有点をドラッグで変形。ドラッグ操作は Undo に記録される
- **ラバーバンド選択**: `Shift`+ドラッグの矩形に完全に含まれる図形を一括選択（線分・円弧は親の直線・円も同時選択）。ドラッグ中は対角線のワールド距離を表示する簡易測距ツールを兼ねる
- **複数選択 AABB 操作**: 2 図形以上を選択すると AABB 枠線とハンドルを表示。辺ドラッグ=平行移動、頂点ドラッグ=等率拡大縮小、対角線ドラッグ=AABB 中心回転。Undo 対応
- **Undo**: 最大 500 手順。ハンドルドラッグ・AABB ドラッグ・右パネルからのプロパティ変更も対象

### 右パネル

- **ホバー情報表示**: キャンバス上でカーソルが図形の上にあるとき、ニックネーム（未設定時は `(タイプ#id)` 形式）・親図形情報をリアルタイム表示
- **スピンボックスのフォーカス制御**: スピンボックスはクリックしてフォーカスを当てた後のみホイール操作で値が変化（ホバーだけでは変化しない）
- 図形選択コンボボックス（隣接図形を優先表示、`[順]`/`[逆]` で接続方向を表示）
  - 1個目を選択すると直ちに2個目の高優先候補が更新される（手段を問わず）
  - **道なり選択**: 高優先候補が1件（または順方向が1件）の場合、`[道なり] <図形名>` アイテムが自動追加され、選択すると残りのコンボを連鎖的に埋める
- プロパティの数値入力・マウスホイールによる精密編集（変更は Undo に記録）
- ドラッグ完了後にプロパティが即座に更新される
- **子の図形リスト**: 直線を選択すると所属する線分の一覧、円を選択すると所属する円弧の一覧を表示
- **円弧を追加 / 全追加ボタン**: 円の空き区間（円弧のない範囲）がある場合に表示
- **Copy / Paste ボタン**: 直線・線分の始点/終点ペアをクリップボード経由でコピー＆ペースト。Paste の右クリックで回転（90°/180°/−90°）・線対称（y=0 / x=0 / y=x / y=−x）変換ペーストも可能
- **関連オフセット拘束の一覧**: 選択図形が関与する拘束を表示し、ワンクリックで拘束パネルに切り替え
- **複数選択時の操作パネル**: コピー（複製して新規選択）・平行移動（ΔX/ΔY）・回転（角度＋基準点）・拡大縮小（倍率＋基準点）を数値入力で実行。基準点は AABB 中心または原点を選択可
- 縦断設計情報の表示（勾配直線・縦断曲線の一覧）
- 図形の削除・再描画ボタン

### 縦断線形

- 勾配直線の作成・編集（重複区間の自動置換、隣接スナップ）
- 縦断曲線（放物線）の挿入（PVI・VPC・VPT・K 値の自動計算）
- 縦断曲線と勾配直線が重なる区間は縦断曲線を優先して高さを計算
- 平面線形チェーンのカラーバー表示（線分=青・クロソイド=緑・円弧=紫）
- **Undo/Redo**: `Ctrl+Z` / `Ctrl+Y`（最大 50 手順）

### 3D 走行ビューア

- 選択した平面線形チェーンを 3D で走行（未選択時は全要素）
- 全道路要素を背景として表示
- 道路幅 3.5m の路面メッシュ・路肩白線・橋脚（約 30m おき）を表示
- 路面表示 ON/OFF で立体感を確認可能
- **俯瞰ビュー**: 自車追従俯瞰 / 固定俯瞰（マウスでパン可能）をサイクルで切替
- **複数台走行**: 周囲車両（トラフィック）を `P`/`Shift+P` で増減
- **オートドライブ**: 全要素グラフをランダムに辿って自動走行

### ファイル

- `.rdjson` 形式（JSON）で保存・読み込み
- 保存前に ID 重複を自動検出・修正（`_fix_duplicate_ids()`）
- ロード時の ID 衝突を自動検出・振り直し（`_resolve_id()`）。振り直しが起きてもクロソイドの参照が失われない
- **追加読み込み（`Ctrl+Shift+O`）**: 現在のシーンに JSON ファイルをマージ。追加した図形のみ選択状態になる
- **ID 振り直し**（メニュー「ID を振り直す」）: 全図形の ID を 1 から連番で付け直す。クロソイド参照・ニックネームキーも自動更新（Undo 非対応のため実行前に確認ダイアログを表示）
- **子図形を初期化して保存（`Ctrl+Shift+I`）**: 直線の線分を参照始点〜参照終点の1本に初期化・円弧を全削除・クロソイドの snap=off にした状態で別名保存。元のシーンは変更しない
- **全削除**（メニューのみ）: 確認ダイアログ後にシーン全データを削除。Undo 対応
- **ニックネーム**: デフォルトなし。未設定時は `(タイプ#id)` 形式（例: `(直線#3)`）を画面表示にのみ使用（ファイル保存時は空欄）
- 旧フォーマット（トップレベル `nicknames`）との後方互換

### オフセット拘束

選択図形の組み合わせに応じて2種類の拘束を設定できる。いずれも右パネルのスピンボックスで `off_a`・`off_b` をリアルタイム編集可能。設定・解除操作は Undo に対応。

**① OffsetConstraint（円 2 個 + 直線 1 本）**

円 A・円 B・直線 S を選択した状態で設定する。円が動くと直線が追従する（`Circle → Line`）。

- 直線 S から円 A の中心への垂直距離 = `A.radius + off_a` を常に維持
- 直線 S から円 B の中心への垂直距離 = `B.radius + off_b` を常に維持
- スムーズ接続で生成された円（`bisector_dir` が設定された円）は設定不可
- 法線方向（直線が 2 円の間・外側のどちら側にあるか）を設定時点から維持する
- 2 円が近すぎて拘束が成立しない状態では直線を変更せず、条件が回復次第追従を再開する

**② TwoLineOffsetConstraint（直線 2 本 + 円 1 個）**

直線 A・直線 B・円 C を選択した状態で設定する。直線が動くと円の中心が追従する（`Line → Circle`）。

- 直線 A から円 C の中心への垂直距離 = `C.radius + off_a` を常に維持
- 直線 B から円 C の中心への垂直距離 = `C.radius + off_b` を常に維持
- 法線方向（円が各直線のどちら側にあるか）を設定時点から維持する
- 2 直線が平行のときは拘束不能（直線を傾けると自動的に追従を再開する）

**循環依存の検出**: `OffsetConstraint`（円→直線）と `TwoLineOffsetConstraint`（直線→円）が互いを参照し合う循環が生じる場合、設定時に警告ダイアログを表示して拒否する。

## データモデル概要

```
Scene
├── lines: list[Line]
│   └── segments: list[Segment]
├── circles: list[Circle]
│   └── arcs: list[Arc]
├── clothoids: list[Clothoid]              # line + circle で定義
├── offset_constraints: list[OffsetConstraint]          # 2円+直線のオフセット拘束
├── two_line_offset_constraints: list[TwoLineOffsetConstraint]  # 2直線+円のオフセット拘束
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
