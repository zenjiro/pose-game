# pose-game 高速化 実行計画（plan.md）

目的
- 現状: OpenCV 版 10–12 FPS、Arcade 版 15 FPS 程度。
- 目標: 「計測→ボトルネック特定→優先度順に最適化」を反復し、安定して 30 FPS 以上（最終目標 60 FPS 近辺）を目指す。
- 制約/前提:
  - 画面解像度は変更しない（例: 4K フルスクリーン維持）。
  - カメラ入力は FHD/720p で取得可。推論は縮小してよい。
  - CPU: 1コア×4ソケット（≒4 論理/物理のどちらか、要確認）。オンチップ GPU 利用可能。

成功基準（KPI）
- 実ゲーム時（岩あり・OSD あり・効果音あり）で Arcade 版 30 FPS 以上（中間目標）。
- 計測ログで、(1) カメラ, (2) 推論, (3〜5+9) 描画, (6) 当たり判定, (7) エフェクト, (8) 音 の各処理時間比率が可視化され、改善が定量的に示せる。
- 低解像度推論やスキップなどの工夫で「体感の遅延/品位」を損なわない。

全体方針
1) 正確な計測基盤を先に入れる（低オーバーヘッド、CSV 収集、OSD 表示）。
2) 実験モードを複数用意し、個別ボトルネックを分離評価（微小ベンチ）。
3) 大きいもの（姿勢推定→描画→当たり判定→エフェクト）から対処。
4) 並列化（スレッド化/パイプライン化）と解像度/頻度の最適化を併用。
5) GPU は可能なところから段階導入（MediaPipe delegate / Arcade のバッチ描画 / OpenCL）。


1. 計測設計（Instrumentation）
- 計測ポイント（1〜9 を網羅）
  1. camera_read: カメラ 1 フレーム取得
  2. pose_infer: 姿勢推定（前処理 resize/色変換込み/別計測も可）
  3. draw_camera: カメラ画像の描画（コピー/アップスケール含む）
  4. draw_pose: 推定結果の〇描画
  5. draw_rocks: 岩の描画
  6. collide: 岩×体の接触判定
  7. draw_fx: 接触時エフェクト描画
  8. sfx: 効果音トリガ処理（再生は非同期）
  9. draw_osd: OSD（FPS/ライフ/スコア/残り時間）
  - frame_total: 1 フレーム総時間

- 方式
  - time.perf_counter() で区間計測（軽量）。
  - 1フレーム中の各区間時間を dict に集計、リングバッファで平均化。
  - CSV へ追記: timestamp, frame_id, camera_res, infer_res, model, backend(opencv/arcade), rocks, fps_target, 各区間ms。
  - オンライン OSD: 直近 N=60 フレーム移動平均と割合バー表示（負荷増を避け簡素に）。

- 実装案
  - src/game/profiler.py（新規）
    - Prof, Section: with Prof.section("pose_infer") で区間計測
    - Prof.tick(frame_id, extra_meta={}) で 1 フレーム終了時に CSV 出力オプション
    - メモリ割当や GC の影響観察のため、時折 forced GC 計測モードも用意
  - main.py / gameplay.py / render.py / pose.py / collision.py に軽量フックを追加
  - CLI フラグ
    - --profile: 計測有効
    - --profile-csv path: CSV 出力先
    - --profile-osd: OSD に計測結果表示


2. 微小ベンチ（分離検証モード）
- bench_capture_infer: カメラ取り込み→（可変解像度に resize）→姿勢推定のみ、描画なし
- bench_render_static: 起動時に 1 枚キャプチャ or 画像読み込み→以降はフレーム固定で [3,4,5,9] のみ
- bench_collision: ランダム岩 N 個・ランダム関節位置 M セットで衝突判定だけループ
- bench_effects: パーティクル/エフェクト描画のみ
- bench_audio: 効果音のキューイング負荷検証（実際の音デバイス I/O の影響観察）
- それぞれ uv scripts で一発起動できるようにする


3. 実験マトリクス（優先度高→低）
- 姿勢推定
  - infer_input_size: {256, 192, 160, 128, 112}
  - model: models/pose_landmarker_{lite,full,heavy}.task
  - delegate: {CPU, GPU(可能なら)}
  - 推論頻度: 毎フレーム / 2 フレームに 1 回 / 3 フレームに 1 回
  - 前処理: BGR→RGB, resize 実装（cv2 vs numpy）比較、OpenCL 有効化

- カメラ
  - capture_res: {1920x1080, 1280x720}
  - backend: {MSMF, DSHOW, V4L2 等 OS 依存}（OS に応じて）
  - 取り込みスレッド: {単一, 別スレッドリングバッファ}
  - フレームドロップ戦略: 最新優先 / 厳密同期

- 描画（OpenCV / Arcade）
  - 表示解像度: 4K（固定）
  - 内部描画解像度: {native(=4K), 1440p, 1080p, 720p} → 最終 4K へ GPU 拡大（ウィンドウ解像度は維持）
  - テキスト描画: キャッシュ有/無、1回の draw_call 数
  - 〇/岩: バッチ描画（Arcade の SpriteList / Geometry） vs 個別 draw

- 岩とエフェクト/当たり判定
  - 岩数: {50, 100, 200, 400}
  - エフェクト粒子数上限: {50, 100, 200}
  - 判定アルゴリズム: 全探索 vs グリッド分割/空間ハッシュ vs ベクトル化
  

4. 最適化方針（優先度順）
A) 姿勢推定
- 入力縮小（inference only downscale）: 720p/1080p 取り込み→推論は 160〜192 辺りで実験。
- 低頻度推論: 推論は 30/2=15Hz でも、描画は 30Hz、補間は「前回の推定を保つ」。
- ROI トラッキング: 前フレームの関節 bbox を拡大して切り出し→小さく推論→全体座標へ戻す。
- モデル選択: 基本 lite を既定、負荷に応じて full/heavy 切替。
- GPU delegate（可能なら）: MediaPipe Tasks の GPU サポート（プラットフォーム依存）。
- 前処理高速化: cv2.resize の最適補間選択（INTER_AREA/LINEAR）、色変換 cvtColor の OpenCL 有効化。

B) 描画（3〜5＋9）
- Arcade の活用最大化: SpriteList / batch で draw call 削減、Geometry/instancing を検討。
- テキスト描画の最小化: フレーム毎に変わらない文字列はテクスチャ化して再利用、数値だけ更新。
- 円/岩の描画: 頂点を事前生成、描画は transform だけ変更（シェーダ or 変換行列）。
- オフスクリーン低解像度合成→4K へ拡大: 画面解像度は維持しつつ内部 FBO を低解像度で描画し、最終パスでスケールアップ（体感品質と性能の折衷）。
- OpenCV 版は draw 処理のコピー回数削減、putText の呼び出し回数削減（まとめ描画）。

C) 当たり判定（6）
- 早期除外: 半径和の二乗と距離二乗で sqrt を回避。
- 空間分割: ユニフォームグリッド or 空間ハッシュで「同一/近傍セル」のみ判定。
- ベクトル化: NumPy で複数岩との距離をまとめて計算（SIMD 効果）。
- 並列: 岩リストを分割しスレッドプールで集計（GIL は NumPy/Cython 部分で解放される見込み）。

D) エフェクト（7）
- パーティクルの上限と寿命管理、プール再利用で GC/alloc を抑制。
- Arcade の ParticleEmitter を使い、更新/描画のバッチ化。

E) カメラ（1）
- 別スレッドで VideoCapture を回し、最新フレームのみを共有（Drop Old）。
- バックエンド選択（Windows: MSMF/DSHOW、Linux: V4L2）。
- バッファサイズ最小化、露光/オートホワイトバランス固定で揺らぎを減らす。

F) 効果音（8）
- 事前ロード済み。短い SE は同時発音数の上限/クールダウン導入でスパム抑止。
- オーディオは基本軽いが、トリガ密度を抑制（N フレームあたり最大 M 回）。

G) OSD（9）
- 数字・固定文字はテクスチャ化、桁変化時のみ更新。
- 複数テキストを 1 描画にまとめる（Arcade の Text API 最適化）。


5. 並列化設計（パイプライン）
- ステージ分割
  - Capture（別スレッド）→ QueueA → Infer（別スレッド、低頻度）→ QueueB → Render/Main（メイン）
- 方針
  - 各ステージは最新データを参照（古いフレームは破棄）。
  - フレーム ID とタイムスタンプで整合性を管理、描画は「最新の推論結果 × 最新フレーム」を合成。
  - Python スレッド: OpenCV I/O と MediaPipe/C++ 部分は GIL 解放が見込めるため有効。
  - さらに CPU 負荷が高いときは multiprocessing で推論を分離（共有メモリ + 軽量圧縮で受け渡し）。


6. GPU 活用
- MediaPipe Tasks の GPU delegate（環境依存）。可能なら有効化を実験。
- OpenCV の OpenCL（cv.ocl.setUseOpenCL(True) で確認）。resize/cvtColor が速くなる場合あり。
- Arcade は OpenGL バックエンド。SpriteList/Geometry でインスタンシング/バッチを最大活用。
- 将来的には「円レンダリング用の簡易シェーダ + インスタンス配列」で 〇 と岩を 1〜2 draw call に集約。


7. ロードマップ（実施順）
- Phase 0: 基線
  - (P0-1) 計測基盤（profiler.py）導入、main/render/pose/collision へ区間フック
  - (P0-2) 計測 CSV / OSD 出力、uv スクリプト追加
  - (P0-3) ベースライン測定（OpenCV/Arcade 両方、実ゲーム）

- Phase 1: 姿勢推定の最適化
  - (P1-1) 推論入力縮小のスイープ（128〜256）
  - (P1-2) 推論スキップ（2〜3フレームに1回）
  - (P1-3) モデル lite を既定化、必要時に full/heavy 切替
  - (P1-4) OpenCL 有効化有無比較
  - (P1-5) 可能なら GPU delegate の可否と効果測定

- Phase 2: パイプライン化/スレッド化
  - (P2-1) Capture スレッド + 最新フレームバッファ
  - (P2-2) Infer スレッド + 低頻度 + 最新結果共有
  - (P2-3) レンダリングはメインスレッドで一貫

- Phase 3: 描画最適化（3〜5＋9）
  - (P3-1) Arcade: SpriteList/Geometry へ移行、テキストキャッシュ
  - (P3-2) OpenCV: putText まとめ、コピー削減
  - (P3-3) 低解像度 FBO → 4K 拡大（最終ウィンドウ/フルスクリーンは 4K 維持）

- Phase 4: 当たり判定/エフェクト
  - (P4-1) 空間ハッシュ導入 + 早期除外
  - (P4-2) パーティクルのプール化・上限

- Phase 5: 仕上げ
  - (P5-1) 各最適化オン/オフのアブレーション比較
  - (P5-2) 構成別プリセット用意（低負荷/標準/高画質）
  - (P5-3) ドキュメント整備


8. 成果物（この計画で新規に追加/変更する想定）
- 新規ファイル
  - src/game/profiler.py: 軽量プロファイラ（区間計測、CSV、OSD 支援）
  - scripts/bench_capture_infer.py: 取り込み+推論ベンチ
  - scripts/bench_render_static.py: 固定フレームで描画ベンチ（OpenCV/Arcade）
  - scripts/bench_collision.py: 衝突判定ベンチ
  - scripts/bench_effects.py: エフェクト描画ベンチ
- 既存変更
  - main.py / render.py / pose.py / collision.py / gameplay.py: 計測フックとオプション追加
  - pyproject.toml: uv scripts を追加


9. リスクと対策
- MediaPipe GPU delegate が環境で動かない → CPU 最適化&低頻度推論を主軸に。
- 4K 表示の描画負荷が高い → 内部レンダリング解像度可変 + 最終スケールアップ（品質と性能の折衷）。
- Python GIL の影響 → C++/NumPy 区間主体なのでスレッドで効果あり。必要なら multiprocessing。
- カメラバックエンド差異 → OS ごとの最適設定をプロファイルで検証。


10. テスト/検証計画
- 各 Phase 毎に「同条件で計測→CSV→グラフ化」。
- ランダム種固定で比較可能にする。
- 計測 OS/マシン情報（CPU/GPU/ドライバ/OpenCL可否）を CSV に記録。


11. 次アクション（実装タスク詳細）
- [ ] P0-1: profiler.py の実装（with 区間、集計、CSV、OSD）
- [ ] P0-2: main/render/pose/collision へ最小フック配置
- [ ] P0-3: uv script 追加（bench_* 起動）
- [ ] P0-4: ベースライン測定（OpenCV/Arcade、FHD/720p、rocks=100）
- [ ] P1-1: 推論入力縮小スイープ
- [ ] P1-2: 推論スキップ導入
- [ ] P2-1: Capture/Infer のスレッド化 + 最新優先キュー
- [ ] P3-1: Arcade の SpriteList/テキストキャッシュ
- [ ] P4-1: 空間ハッシュ + ベクトル化
- [ ] P5-1: アブレーション比較まとめ & ドキュメント


補足・実装メモ
- CSV 例: ts,frame,id,camera_res,infer_res,model,backend,rocks,fps,[camera_read,pose_infer,draw_camera,draw_pose,draw_rocks,collide,draw_fx,sfx,draw_osd,frame_total]
- 低頻度推論の注意: 入力遅延を感じるなら、補間（手/頭の線形補間）や、岩速度に応じた判定余裕を調整。
- 空間ハッシュ: セルサイズ ≒ 岩の最大直径、セル→岩ID の dict、各体パーツは自セルと 8 近傍のみ照合。
- 〇/岩の描画: 円は三角ファン/インスタンシングで GPU に寄せると効果大（Arcade 側の API 調査）。

---
この plan.md に沿って、まずは「計測基盤（Phase 0）」を最優先で実装します。


12. Phase 0 ベースライン計測 速報（2025-09-23）および追加結果（duplicate/解像度比較）
- 実行条件（共通）
  - capture: 1280x720（open_camera()の既定値）
  - model: models/pose_landmarker_lite.task（Tasks API, multi-person）
  - players: 通常（--duplicate なし）
  - 計測: --profile, --profile-csv, --max-seconds 10

- OpenCV 版（runs/baseline_opencv_10s.csv）
  - pose_infer: おおむね 56〜62 ms/フレーム、たまに 80 ms 超のスパイク
  - draw_camera（imshow）: 0.7〜1.3 ms
  - draw_pose/draw_rocks/draw_osd: 各 0.6〜1.4 ms 程度
  - draw_fx: エフェクト発生時に 49〜57 ms 程度の大きな負荷。これにより frame_ms が 125〜140 ms（約 7〜8 FPS）まで落ちるフレームが散発
  - collide: 通常 0.01〜0.3 ms 程度（現状の岩数条件では軽い）
  - 総合: エフェクトが出ていないフレームは 70〜85 ms（約 12〜14 FPS）。ボトルネックは pose_infer、次点で draw_fx のスパイク

- Arcade 版（runs/baseline_arcade_10s.csv）
  - pose_infer: 約 56〜60 ms（OpenCV 版と同程度）
  - draw_camera（pyglet blit）: 3〜4 ms 前後
  - draw_pose/draw_rocks/draw_osd: 0.2〜0.8 ms 程度
  - 初回フレームの draw_osd が約 186 ms（初期化/フォント等の影響）。以後は 0.2〜1.8 ms 程度で安定
  - 総合: 多くのフレームが 64〜70 ms（約 14〜16 FPS）。OpenCV 版よりやや良好
  - 注意: arcade.draw_text に PerformanceWarning（Text オブジェクト利用推奨）

- まとめ（現時点の所見）
  1) 姿勢推定が最大ボトルネック（約 57〜62 ms/フレーム）。duplicate（2人）時も支配的
  2) OpenCV 版のエフェクト描画がスパイク要因（50 ms 級）があるため、FPS閾値連動の抑制が有効候補
  3) 描画（カメラ背景/〇/岩/OSD）は Arcade 版のほうが若干有利
  4) 取り込み解像度は 720p のほうが平均フレーム時間が短く、1080pは camera_read の増分で不利


12.1 Arcade テキスト描画最適化 比較（10s, skip-first=1）
- 対象CSV: runs/baseline_arcade_10s.csv（A）, runs/arcade_text_10s.csv（B）
- 設定: Arcade, --profile, --max-seconds 10, 初期1フレームスキップ
- 概要:
  - A frame: 66.84 ms (14.96 fps), median 66.52 ms
  - B frame: 69.06 ms (14.48 fps), median 68.56 ms
  - 差分: +2.22 ms (-0.48 fps) → B が遅い（この10秒サンプル）
- セクション別平均(ms)と frame 比:
  - camera_read: A 1.04 (1.6%) → B 0.97 (1.4%)  Δ -0.07
  - pose_infer: A 58.16 (87.0%) → B 56.44 (81.7%)  Δ -1.72
  - draw_camera: A 3.44 (5.1%) → B 3.33 (4.8%)  Δ -0.11
  - draw_pose: A 0.23 (0.3%) → B 0.35 (0.5%)  Δ +0.11
  - draw_rocks: A 0.00 (0.0%) → B 0.10 (0.1%)  Δ +0.10
  - collide: A 0.00 → B 0.00  Δ +0.00
  - draw_fx: A 0.00 (0.0%) → B 0.37 (0.5%)  Δ +0.37
  - sfx: A 0.00 → B 0.00  Δ +0.00
  - draw_osd: A 0.70 (1.0%) → B 0.61 (0.9%)  Δ -0.08
- 所見:
  - Text オブジェクト化により draw_osd は僅かに改善（-0.08 ms）。pose_infer も -1.72 ms と今回サンプルではやや良化。
  - ただし B は draw_pose/draw_rocks/draw_fx が合計 +0.58 ms。さらに計測外「other」（update系/イベント処理等）が増え、結果的に +2.22 ms の悪化。
  - ラン内のゲーム状態（岩数やエフェクト発生）の差・未計測区間の増加が支配的で、テキスト最適化単体の効果は埋もれている可能性。
- アクション:
  1) 計測点の追加: update_rocks / update_fx / update_game を計測し「other」を分離。
  2) 固定条件ベンチ: bench_render_static（固定フレーム・固定岩）でテキスト描画差分を単独評価。
  3) 再計測: 同条件（capture/infer/duplicate固定、seedがあれば固定）で10〜30s計測・リピートし統計化。
  4) ドキュメント化: 本比較結果をグラフ化して記録。

13. 次回再開時の進め方（実験プラン）
- 早期に --duplicate の計測を追加（2 人対戦負荷の想定）[実施済み]
  - 例（OpenCV 版）:
    - uv run python -m game.main --profile --profile-csv runs/opencv_dup_10s.csv --max-seconds 10 --duplicate
  - 例（Arcade 版）:
    - uv run python -m game.main --arcade --profile --profile-csv runs/arcade_dup_10s.csv --max-seconds 10 --duplicate
  - 目的: 2 人時の描画・当たり判定・エフェクト増加の影響を早期に把握

- Phase 1（推論最適化）をすぐ測れる仕掛けの追加（頻度間引きは採用しない方針）
  - CLI を追加
    - --infer-size {128,160,192,224,256}（推論入力の縮小）
    - 推論は毎フレーム実行（ゲーム性を重視し、間引きはしない）
  - スイープの実行と CSV 収集
    - 固定条件: capture=720p, --duplicate の有無それぞれで比較
    - 期待: pose_infer を 30〜40 ms 台以下に抑え、全体 30 FPS 付近を狙う

- capture 解像度を CLI 化 [実装済み]
  - --capture-width/--capture-height で 720p/1080p の比較が容易に
  - 描画解像度は変えない（要件どおり）。取り込みは FHD/720p を使い分ける（現状では720pの方が有利）

- エフェクト描画のスパイク対策（OpenCV 版）
  - 既存の fps_threshold_for_glow=10.0 を 18〜20 へ一時的に引き上げて検証（12〜16 FPS 帯では glow を抑止）
  - sigma/halo/core_weight 等のパラメタを軽量側にシフト
  - 粒子数(count)の上限/寿命/layer 合成のコストを FPS に応じて段階制御

- Arcade 描画の改善
  - Text オブジェクトへの置換（draw_text からの移行）
  - 将来的には SpriteList/Geometry でのバッチ化を検討

- 分離ベンチの実装（短期で）
  - scripts/bench_capture_infer.py（取り込み＋推論のみ）
  - scripts/bench_render_static.py（固定フレームで描画のみ、OpenCV/Arcade）


14. 推奨実行レシピ（次回計測用コマンド例）
- ベースライン + duplicate
  - OpenCV:  uv run python -m game.main --profile --profile-csv runs/opencv_dup_10s.csv --max-seconds 10 --duplicate
  - Arcade:  uv run python -m game.main --arcade --profile --profile-csv runs/arcade_dup_10s.csv --max-seconds 10 --duplicate
- 推論サイズスイープ（例）
  - OpenCV:  uv run python -m game.main --profile --profile-csv runs/opencv_size160.csv --max-seconds 10 --infer-size 160
  - Arcade:  uv run python -m game.main --arcade --profile --profile-csv runs/arcade_size160.csv --max-seconds 10 --infer-size 160
- 推論間引き（例）
  - OpenCV:  uv run python -m game.main --profile --profile-csv runs/opencv_skip2.csv --max-seconds 10 --infer-skip-n 2
  - Arcade:  uv run python -m game.main --arcade --profile --profile-csv runs/arcade_skip2.csv --max-seconds 10 --infer-skip-n 2


15. トラッキング（任意）
- Jira: Phase 0 完了、Phase 1/2/3 のタスクを作成（推論サイズ/頻度、capture CLI、エフェクト軽量化、Arcade Text 化、分離ベンチ）
- Confluence: ベースライン結果・CSV・所見を記録（この plan.md の要約＋グラフ）
- PR: 計測機能の追加を main から分岐したブランチで PR 化
