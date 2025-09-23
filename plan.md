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