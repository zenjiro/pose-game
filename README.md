# pose-game

MediaPipe Pose と OpenCV を用いた、Webカメラ入力のオフライン 2 人対戦 2D ゲーム・プロトタイプです。カメラ映像からプレイヤーの頭・手・足を検出し、上から落ちてくる岩を「頭で避け、手や足で対処」してスコアとライフを競います。

- 入力: Webカメラ (OpenCV)
- 姿勢推定: MediaPipe Pose
- 方式: ローカル実行（映像データは送信しません）
- 管理: uv（仮想環境・依存管理・実行）

---

## ゲーム概要
- プレイヤー: 最大 2 人（オフライン対戦、同一カメラ）
- ルール:
  - 上からランダムに岩が落下
  - 頭に当たるとライフ -1（初期ライフ 3、0 でゲームオーバー）
  - 手に当てると岩は壊れるがスコアは増えない
  - 足に当てると岩が壊れてスコア +1
  - スコアが 3 になるごとにライフ +1（3, 6, 9, ...）
- 時間: 1 分（60 秒）。スコアが多い方の勝ち
- 画面・操作:
  - 実行中いつでも: C でカメラ切替、Esc で終了
  - タイトル画面: Space/Enter で開始
  - 終了画面: Space/Enter で次ゲーム

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

- `--jp-font` を指定しない場合は OS のデフォルトフォントを使って日本語表示します。

uv の詳細は https://docs.astral.sh/uv/ を参照してください。

---

## カメラの選択と切り替え
- 起動時にカメラ選択ダイアログは表示しません。
- 起動時に利用可能なカメラを自動検出し、最初のカメラを開きます。
- 検出に失敗した場合はインデックス 0 を試みます。
- コマンドライン引数で初期カメラを指定できます（仕様は変更していません）。
  - 例: `uv run python -m game.main -c 1`
- 実行中に `C` キーで次のカメラへ順送りに切り替えできます（失敗した場合は現在のカメラを維持）。

---

## ディレクトリ構成
```
.
├─ AGENTS.md
├─ .gitignore
├─ LICENSE
├─ pyproject.toml
├─ README.md
├─ uv.lock
├─ models/
│  ├─ pose_landmarker_full.task
│  ├─ pose_landmarker_heavy.task
│  └─ pose_landmarker_lite.task
└─ src/
   └─ game/
      ├─ __init__.py
      ├─ camera.py             # カメラ、フルスクリーン表示、入力
      ├─ collision.py          # 衝突判定（円と円など）
      ├─ devices.py            # プラットフォーム固有のカメラ名検出
      ├─ entities.py           # プレイヤー、岩などのデータモデル
      ├─ gameplay.py           # スポーン、スコア/ライフ更新、タイマー
      ├─ main.py               # エントリポイント（状態管理、ゲームループ）
      ├─ player.py             # プレイヤー状態、ゲーム状態管理
      ├─ pose.py               # MediaPipe Pose 推論とランドマーク処理
      └─ render.py             # オーバーレイ/UI描画
```

---

## プライバシー
- カメラ映像はローカルで処理され、外部送信は行いません。

---

## ライセンス
このリポジトリのライセンスは `LICENSE` を参照してください。
