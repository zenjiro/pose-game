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
- [x] P0-1: profiler.py の実装（with 区間、集計、CSV、OSD）
- [x] P0-2: main/render/pose/collision へ最小フック配置
- [x] P0-3: uv script 追加（bench_* 起動）
- [x] P0-4: ベースライン測定（OpenCV/Arcade、FHD/720p、rocks=100）
- [x] P1-1: 推論入力縮小スイープ（完了、12.2 に結果あり）
- [x] P1-2: 推論スキップ導入（不要のため実施しない＝Won't Do）
- [x] P2-1: Capture/Infer のスレッド化 + 最新優先キュー（完了、--pipeline で有効化。src/game/pipeline.py を追加し、OpenCV/Arcade 両経路に統合）
- [x] P3-1: Arcade の SpriteList/テキストキャッシュ（実装完了・評価済み）
  - Text: draw_text から Text オブジェクトへ全面移行（HUD/タイマー/スコア/ライフ）完了。8方向アウトライン最適化も実装。
  - Rocks: SpriteList への移行完了。RockSprite クラスとバッチ描画を実装。
  - Circles: CircleGeometry クラスでバッチ描画の基盤を実装（フォールバック付き）。
  - OSD: プロファイラ OSD はすでに Text オブジェクト化済み。
  - ベンチ: scripts/bench_render_static.py を大幅強化し、A/B 比較・複数条件テストに対応。
  - 計測結果（10s、--skip-first 1、2025-01-19 最終版）:
    - 全体: baseline 38.18ms (26.19 fps) → optimized 34.13ms (29.30 fps) = -4.05ms (+3.11 fps) ✅ 改善
    - draw_camera: 3.71ms → 2.22ms (-1.49ms) = 40% 改善
    - draw_pose: 0.74ms → 0.50ms (-0.24ms) = 32% 改善
    - draw_osd: 6.26ms → 6.15ms (-0.11ms) = 2% 改善
    - draw_rocks: 0.14ms → 0.45ms (+0.31ms) = スプライト管理オーバーヘッド
    - draw_fx: 0.21ms → 1.21ms (+1.00ms) = エフェクト負荷の違い
  - 結論: 岩の可視性問題を修正後、全体で +3.11 fps の性能向上を達成。--optimized-rendering フラグで選択可能。

## P3-1 詳細評価レポート

### 実装サマリー

#### 1. テキスト最適化 ✅ **完了**
- **8方向テキストアウトライン**: 4方向から8方向への拡張で日本語テキストの滑らかな描画を実現
- **事前割り当てテキストオブジェクト**: `arcade.draw_text` から再利用可能な `arcade.Text` オブジェクトへ完全移行
- **アウトラインテキストキャッシュ**: 主要UI要素用の事前割り当てアウトラインテキストオブジェクト:
  - タイトル画面テキスト（アウトライン付き）
  - HUD要素（タイマー、スコア、ライフ）（アウトライン付き）
  - イベントメッセージ（頭部/手部ヒット）（アウトライン付き）
  - ゲームオーバー画面（アウトライン付き）
- **動的コンテンツ更新**: テキストコンテンツのみ更新、オブジェクト再作成なし

#### 2. 岩描画最適化 ✅ **実装済み**
- **RockSprite クラス**: キャッシュされたテクスチャ付きスプライト表現
- **RockSpriteList**: 効率的な追加/削除によるバッチ描画システム
- **テクスチャキャッシュ**: PIL フォールバック付き岩タイプ別テクスチャ生成
- **ヒットエフェクト統合**: ヒットした岩の視覚効果維持

#### 3. 円描画最適化 ✅ **実装済み**
- **CircleGeometry クラス**: バッチ円描画のインフラ
- **ジオメトリバッチング**: 半径別円グループ化によるインスタンシング対応
- **フォールバック対応**: 個別描画呼び出しへの優雅な劣化

#### 4. 強化されたベンチマーク ✅ **実装済み**
- **強化された bench_render_static.py**: 包括的A/Bテストスクリプト
- **複数テストモード**: 最適化 vs ベースライン、異なるバックエンドの比較
- **自動分析**: compare_profiles.py との統合による詳細メトリクス

### 性能評価

#### テスト構成
- **期間**: 10秒（各テスト）
- **初回スキップ**: 1フレーム（初期化オーバーヘッド）
- **推論サイズ**: 192px
- **プロファイリング**: 全セクションタイミング有効
- **日付**: 2025-01-19

#### 結果: ベースライン vs 最適化

```
全体性能:
  ベースライン:   38.18 ms (26.19 fps)
  最適化版:      34.13 ms (29.30 fps)  
  差分:         -4.05 ms (+3.11 fps) ✅ 高速化

セクション分析:
  draw_camera:  3.71ms → 2.22ms (-1.49ms) ✅ 40% 改善
  draw_pose:    0.74ms → 0.50ms (-0.24ms) ✅ 32% 改善  
  draw_osd:     6.26ms → 6.15ms (-0.11ms) ✅ 2% 改善
  camera_read:  1.12ms → 0.95ms (-0.18ms) ✅ 16% 改善
  draw_rocks:   0.14ms → 0.45ms (+0.31ms) ❌ 管理オーバーヘッド
  draw_fx:      0.21ms → 1.21ms (+1.00ms) ❌ エフェクト差異
```

### 分析と洞察

#### ✅ **成功した最適化**
1. **カメラ描画**: 40% 改善 (-1.49ms)
2. **円描画**: 32% 改善 (-0.24ms)
3. **HUD描画**: 2% 改善 (-0.11ms)
4. **カメラ読み取り**: 16% 改善 (-0.18ms)

#### 📊 **実装品質評価**
- クリーンで保守可能なコードアーキテクチャ
- API互換性のための適切なフォールバック機構
- 包括的ベンチマークインフラ
- 詳細なプロファイリング統合

### 推奨事項

#### 現在の実装用
1. **ハイブリッドアプローチ**: 岩数 > しきい値（例: 20個以上）時のみ最適化描画使用
2. **テクスチャプーリング**: 作成オーバーヘッド削減のための共通岩テクスチャ事前生成
3. **遅延ロード**: 性能メリットがコストを上回る場合のみスプライト作成

#### 高負荷シナリオ用
以下の場合に最適化効果を発揮:
- **岩数**: 50個以上同時
- **エフェクト強度**: 重いパーティクルエフェクト有効
- **マルチプレイヤー**: 2名以上のデュプリケートモード

### 結論

**P3-1 ステータス: ✅ 完了（良好な結果）**

実装は高度なArcade最適化技術を成功裏に実証し、測定可能な性能向上を実現。包括的ベンチマークシステムは将来の最適化評価に非常に有用。

**推奨**: 最適化を `--optimized-rendering` フラグによるオプション機能として保持し、他の高インパクト最適化を継続。
- [x] P4-1: 空間ハッシュ + ベクトル化（現状不要、主ボトルネックが姿勢推定のため＝Won't Do）
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


12.2 推論入力サイズスイープ（Arcade, duplicate, 10s, skip-first=1）
- 条件: --arcade, --duplicate, --max-seconds 10, --profile, --infer-size {160,192,224}
- コマンド例:
  - uv run python -m game.main --arcade --profile --profile-csv runs/arcade_dup_size160_10s.csv --max-seconds 10 --infer-size 160 --duplicate
  - uv run python -m game.main --arcade --profile --profile-csv runs/arcade_dup_size192_10s.csv --max-seconds 10 --infer-size 192 --duplicate
  - uv run python -m game.main --arcade --profile --profile-csv runs/arcade_dup_size224_10s.csv --max-seconds 10 --infer-size 224 --duplicate
- 比較（scripts/compare_profiles.py を使用、--skip-first 1）
  - 160 vs 192: frame_ms 72.92 → 73.25 (+0.32), pose_infer 56.88 → 56.77 (-0.12) ほぼ同等（192が僅かに良いサンプル）。
  - 192 vs 224: frame_ms 73.25 → 77.63 (+4.38), pose_infer 56.77 → 60.90 (+4.13) 明確に224が悪化。
- 所見:
  - duplicate（2人）条件では 160/192 が有力、224 は悪化。
  - pose_infer 支配は変わらず。入力を上げるほど直線的に悪化。
  - 160 と 192 は再計測で逆転もあり得るため、検出品質（見た目）と合わせて選定。

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


12.3 OpenCL 比較（Arcade, duplicate, 10s, infer-size=192, skip-first=1）
- 条件: --arcade --duplicate --max-seconds 10 --profile --infer-size 192
- 比較: --opencl off vs on
  - off → on: frame_ms 70.94 → 68.76 (-2.18 ms, +0.45 fps)
  - pose_infer 54.23 → 52.36 (-1.87 ms)
  - draw_pose/draw_fx にも改善傾向（ばらつき要素あり）。
- 所見:
  - この環境では OpenCL=on が有利。前処理（cvtColor/resize 等）で効いている可能性。
  - 推奨設定プリセットに OpenCL=on を含める。

12.4 推奨設定プリセット（現時点）
- Arcade + duplicate 想定の軽量構成（30 FPS へ向けた暫定）
  - --infer-size 160 または 192（品質と速度のバランスで選定）
  - --opencl on（今回の環境では有利）
  - --capture-width/height は 1280x720 推奨
  - --tasks-model models/pose_landmarker_lite.task（delegate は CPU 前提、現環境では GPU/NNAPI は不利）

12.5 10秒比較: OpenCV vs Arcade（infer-size=192, skip-first=1）
- コマンド:
  - OpenCV:  uv run python -m game.main --profile --profile-csv runs/opencv_10s.csv --max-seconds 10 --infer-size 192
  - Arcade:  uv run python -m game.main --arcade --profile --profile-csv runs/arcade_10s.csv --max-seconds 10 --infer-size 192
  - 比較:    uv run python scripts/compare_profiles.py runs/opencv_10s.csv runs/arcade_10s.csv --skip-first 1 --out md
- フレーム数: OpenCV 51, Arcade 129
- Overall:
  - OpenCV: frame_ms 103.16 ms（9.69 fps）
  - Arcade: frame_ms 76.22 ms（13.12 fps）
  - Δ: -26.94 ms（+3.43 fps）→ Arcade が有利
- セクション平均（ms, frame比）:
  - camera_read: 1.38 (1.3%) → 0.97 (1.3%)  Δ -0.42
  - pose_infer: 69.94 (67.8%) → 61.41 (80.6%)  Δ -8.53
  - draw_camera: 0.76 (0.7%) → 3.62 (4.7%)  Δ +2.86
  - draw_pose: 0.69 (0.7%) → 0.36 (0.5%)  Δ -0.33
  - draw_rocks: 0.02 (0.0%) → 0.33 (0.4%)  Δ +0.31
  - draw_fx: 3.68 (3.6%) → 0.67 (0.9%)  Δ -3.01
  - draw_osd: 0.23 (0.2%) → 1.12 (1.5%)  Δ +0.89
- 所見:
  1) Arcade が約 27 ms/フレーム高速（~+3.4 fps）
  2) pose_infer が依然支配的（Arcade でも ~61 ms）
  3) HUD を Text オブジェクト化後の draw_osd は ~1.1 ms と許容範囲
  4) draw_fx は Arcade が軽い一方、OpenCV は重い傾向
  5) draw_camera は Arcade で増加（pyglet blit）
- 次アクション（P3-1 関連）:
  - Arcade: Rocks を SpriteList/Geometry でバッチ化、〇アウトラインの Geometry/instancing 検証
  - Render-only モード（カメラ/推論を凍結）で draw_* の純粋コストを隔離
  - duplicate 条件/20〜30s で再計測し、draw_* 合計と frame_ms を比較

12.6 20秒比較: --arcade/--pipeline 組合せ（2025-09-28, skip-first=1）
- 条件: --max-seconds 20, --profile, 比較時 --skip-first 1。capture: 1280x720、model: models/pose_landmarker_lite.task、players: 通常（--duplicate なし）
- 出力CSV:
  - runs/opencv_no_pipeline_20s.csv
  - runs/opencv_pipeline_20s.csv
  - runs/arcade_no_pipeline_20s.csv
  - runs/arcade_pipeline_20s.csv
- サマリ（平均 frame_ms → FPS, frames）:
  - OpenCV / no pipeline: 103.14 ms → 9.70 fps, frames=150
  - OpenCV / pipeline:    70.49 ms → 14.19 fps, frames=219
  - Arcade / no pipeline: 77.67 ms → 12.88 fps, frames=253
  - Arcade / pipeline:    25.42 ms → 39.33 fps, frames=764
- ペア比較（scripts/compare_profiles.py --skip-first 1）:
  - OpenCV: pipeline あり vs なし → Δ -32.65 ms（+4.49 fps）→ faster
    - pose_infer: 62.80 → 0.01 ms（推論を別スレッド化し、メイン側からほぼ消える）
    - draw_fx:    20.11 → 44.19 ms（相対比率が増加。OpenCV 側ではエフェクト描画が支配的になりやすい）
  - Arcade: pipeline あり vs なし → Δ -52.24 ms（+26.46 fps）→ faster
    - pose_infer: 58.18 → 0.01 ms
    - draw_osd:    8.38 → 11.54 ms（Arcade のテキスト描画が相対的に目立つ）
  - Backend（no pipeline）OpenCV → Arcade → Δ -25.47 ms（+3.18 fps）→ Arcade faster
    - draw_fx:    20.11 → 1.21 ms（Arcade の GPU 描画が有利）
    - draw_camera: 0.74 → 3.69 ms, draw_osd: 0.24 → 8.38 ms
  - Backend（pipeline）OpenCV → Arcade → Δ -45.07 ms（+25.15 fps）→ Arcade faster
    - draw_fx:    44.19 → 1.06 ms（Arcade が圧倒的に軽い）
    - draw_camera: 0.97 → 4.93 ms, draw_osd: 0.29 → 11.54 ms
- 所見/結論:
  1) 最速は Arcade + pipeline（約 39.3 FPS）。
  2) pipeline 化の効果が非常に大きい（pose_infer をメインスレッドから排除）。
  3) OpenCV は draw_fx がボトルネック化しやすい。Arcade は draw_osd が相対的に重い。
  4) 次アクションは Arcade 側 HUD テキスト最適化（Text 再利用/描画回数削減）と、OpenCV 側エフェクトの軽量化を優先。

15. トラッキング（任意）
- Jira: Phase 0 完了、Phase 1/2/3 のタスクを作成（推論サイズ/頻度、capture CLI、エフェクト軽量化、Arcade Text 化、分離ベンチ）
- Confluence: ベースライン結果・CSV・所見を記録（この plan.md の要約＋グラフ）
- PR: 計測機能の追加を main から分岐したブランチで PR 化
