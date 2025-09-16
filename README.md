# pose-game

MediaPipe Pose と OpenCV を用いた、Webカメラ入力のオフライン 2 人対戦 2D ゲーム・プロトタイプです。カメラ映像からプレイヤーの頭・手・足を検出し、上から落ちてくる岩を「頭で避け、手や足で対処」してスコアとライフを競います。

- 入力: Webカメラ (OpenCV)
- 姿勢推定: MediaPipe Pose
- 方式: ローカル実行（映像データは送信しません）
- 管理: uv（仮想環境・依存管理・実行）

詳細な実装計画は `plan.md` を参照してください。

---

## ゲーム概要（最終仕様）
- プレイヤー: 最大 2 人（オフライン対戦、同一カメラ）
- ルール:
  - 上からランダムに岩が落下
  - 頭に当たるとライフ -1（初期ライフ 5、0 でゲームオーバー）
  - 手に当てると岩は壊れるがスコアは増えない
  - 足に当てると岩が壊れてスコア +1
  - スコアが 3 になるごとにライフ +1（3, 6, 9, ...）
- 時間: 3 分（180 秒）。スコアが多い方の勝ち
- 画面・操作:
  - タイトル画面: Space/Enter で開始、Esc で終了
  - ゲーム中: フルスクリーン表示、Esc で終了
  - 終了画面: Space/Enter で次ゲーム、Esc で終了

---

## 段階的実装ステップ（ロードマップ）
- [x] 1. カメラ映像をフルスクリーンでそのまま表示（Esc で終了）
- [x] 2. MediaPipe Pose の頭・手・足を検出し、オーバーレイ描画（最大2人、Tasks API 利用時）
- [x] 3. 上からランダムに岩を落下
- [x] 4. 岩と頭の当たり判定
- [x] 5. 岩と手の当たり判定（破壊のみ、スコア加算なし）
- [x] 6. 岩と足の当たり判定（破壊＋スコア加算）
- [x] 7. ライフ計算（初期 5、頭ヒットで -1、0 でゲームオーバー）
- [x] 8. スコア処理（足ヒットで加算）
- [x] 9. スコアが 3 に到達でライフ +1（3, 6, 9, ...）
- [x] 10. 終了画面（Space/Enter で次のゲーム、Esc で終了）

各ステップの詳細と設計方針は `plan.md` に記載しています。

---

## セットアップ（uv 使用）
前提: Python 3.10+ 推奨、uv がインストール済み

**Note:** 姿勢検出モデルはリポジトリに含まれているため、手動でのダウンロードは不要です。

1) 仮想環境の作成

```
uv venv
```

2) 依存関係の追加（開発序盤）
```
uv add opencv-python mediapipe numpy
# （任意）開発ツール
uv add --dev black ruff mypy
```

3) 実行（コード実装後）
```
uv run python -m game.main
```

### 日本語タイトル表示（任意）
- 日本語表示には Pillow と日本語フォントが必要です。
- 依存に `pillow` を追加済みなので、環境にインストールされます。
- OS に含まれる日本語フォント、または任意のフォントファイル（.ttf/.ttc/.otf）を指定してください。

使用例:
```
# Windows の例（Meiryo）
uv run python -m game.main --jp-font "C:\\Windows\\Fonts\\meiryo.ttc"

# macOS の例（ヒラギノ角ゴ）
uv run python -m game.main --jp-font "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

# Linux の例（Noto CJK）
uv run python -m game.main --jp-font "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"
```

- `--jp-font` を指定しない場合は英語のタイトルにフォールバックします。

uv の詳細は https://docs.astral.sh/uv/ を参照してください。

---

## ディレクトリ構成（予定）
```
.
├─ plan.md
├─ README.md
├─ LICENSE
├─ pyproject.toml              # uv により生成予定
├─ src/
│  └─ game/
│     ├─ __init__.py
│     ├─ main.py              # エントリポイント（状態管理、ゲームループ）
│     ├─ camera.py            # カメラ、フルスクリーン表示、入力
│     ├─ pose.py              # MediaPipe Pose 推論とランドマーク処理
│     ├─ entities.py          # プレイヤー、岩などのデータモデル
│     ├─ collision.py         # 衝突判定（円と円など）
│     ├─ game_state.py        # タイトル/プレイ/終了の状態管理
│     ├─ gameplay.py          # スポーン、スコア/ライフ更新、タイマー
│     ├─ render.py            # オーバーレイ/UI描画
│     ├─ config.py            # 定数・パラメータ
│     └─ utils.py             # 汎用ユーティリティ
└─ assets/
   ├─ fonts/
   └─ images/
```

---

## プライバシー
- カメラ映像はローカルで処理され、外部送信は行いません。

---

## ライセンス
このリポジトリのライセンスは `LICENSE` を参照してください。
