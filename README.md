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
  - タイトル画面: 手を頭より上に2秒上げると開始（Space/Enterは無効）
  - 終了画面: 手を頭より上に2秒上げると再スタート（Space/Enterは無効）

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

3) 実行（Arcade が既定のレンダリングです）
```
uv run python -m game.main
# --arcade は不要です（Arcade がデフォルト）。OpenCV ウィンドウ版は廃止されました。
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

---

## パラメーター調整

現時点ではゲーム内パラメーターはコード内の定数で管理しています。主な調整箇所は以下です。

- 岩の生成と速度: src/game/gameplay.py
  - 生成間隔: RockManager.spawn_interval
    - 例: 0.5 秒ごとに生成: spawn_interval = 0.5
  - 垂直速度の範囲: RockManager.speed_min / RockManager.speed_max
    - 例: 150〜250: speed_min = 150.0, speed_max = 250.0
  - 水平速度の範囲: gameplay.py の maybe_spawn() 内の vx の一様乱数
    - 例: -50〜50: vx = random.uniform(-50.0, 50.0)
  - 岩の半径（サイズ）: RockManager.min_radius / RockManager.max_radius
    - 例: 20〜40: min_radius = 20, max_radius = 40

- その他（参考）
  - カメラ入力や描画に関する調整は src/game/main.py と src/game/render.py を参照
  - 姿勢推定のリサイズは --infer-size で指定可能
  - カメラのキャプチャ解像度は --capture-width / --capture-height で指定可能

将来的に config.py に集約し、CLI からの上書きや外部設定ファイルに対応する拡張も可能です。ご希望があれば対応します。

---

## プロファイリング (計測)
- 実行時間の計測は `--profile-csv` オプションで有効化します。
- `--profile` と `--profile-osd` は廃止されました。CSV 指定のみでプロファイラが起動します。
- 例:
```
uv run python -m game.main --profile-csv profile.csv
```
- 出力される CSV 列 (ms 単位):
  - frame_ms (1 フレーム全体)
  - camera_read / pose_infer / draw_camera / draw_pose / draw_rocks / collide / draw_fx / sfx / draw_osd
- フレーム時間から FPS を計算するには: `FPS = 1000 / frame_ms`。
- OSD 表示によるリアルタイム統計機能は削除しました。必要に応じて表計算ソフト等で集計してください。


## ライセンス
このリポジトリのライセンスは `LICENSE` を参照してください。
