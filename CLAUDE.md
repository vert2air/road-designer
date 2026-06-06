# road-designer Claude 設定

## Gitコミットメッセージ

必ず **Conventional Commits** スタイル（<https://www.conventionalcommits.org/>）を使うこと。

書式：
```
<タイプ>: <日本語の要約>

<本文（任意）>

Co-Authored-By: ...
```

主なタイプ：
| タイプ | 使いどころ |
|--------|-----------|
| `feat:` | 新機能追加 |
| `fix:` | バグ修正 |
| `refactor:` | 動作変更なしのリファクタリング |
| `chore:` | ビルド・設定・依存関係 |
| `docs:` | ドキュメントのみの変更 |
| `test:` | テスト追加・修正 |
| `style:` | フォーマット等（ロジック変更なし） |
| `perf:` | パフォーマンス改善 |

破壊的変更は `feat!:` または本文・フッターに `BREAKING CHANGE:` を記載する。
