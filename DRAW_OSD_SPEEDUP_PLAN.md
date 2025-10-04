# draw_osd 高速化計画 (HUD / Text Rendering Optimization Plan)

目的: 現状 `draw_osd` 平均 4.61 ms (約 15.7% / 29.35 ms フレーム) を 2.0〜2.5 ms レベルまで低減し、平均フレーム 29.35 ms → 27 ms 前後 (≈ +2 FPS) を目指す。

## 現状課題の整理
| 要素 | 想定原因 | 症状/指標 |
|------|----------|-----------|
| 8方向アウトライン描画 | Text 1個につき 8+1 draw call | OSD テキスト数 ×9 回描画。累積で ms 増大 |
| 毎フレーム全テキスト再描画 | 値未更新でも位置/アウトライン更新 | 変更頻度低いスコア/ライフ/タイトルも毎回更新 |
| FPS/タイマー更新頻度過多 | 各フレームで文字列フォーマット | 1秒=60回不要 (10Hz で十分) |
| Title/GameOver など静的要素 | 都度 Text オブジェクト draw | フレーム毎冗長描画 |
| アウトラインロジック | 8 方向 offset 計算 + 更新 | p95 7.26 ms / max 178 ms の一因 (初期化/GC 連動) |
| Python 文字列/format | f-string 多用 | 小さいが積み上げで影響 |
| Text オブジェクト粒度 | 要素ごと | バッチ不可 / state change 多発 |

## 対応アイデア一覧 (カンバン形式)
| カテゴリ | 施策 | 難易度 | 見込み削減 | 優先 | 備考 |
|----------|------|--------|------------|------|------|
| Outline 方針 | 8方向アウトラインを維持 (品質優先) | - | - | High | 以降は差分更新/キャッシュで最適化 |
| Outline 動的最適化 | ライフ/スコア変化時のみ再生成 | Low | +5–10% | Med | 再生成時にのみ8方向等 |
| 静的キャッシュ | タイトル/ゲームオーバーを 1 枚の Texture にレンダー | Med | 0.3–0.6 ms | High | Startup で生成 |
| HUD 差分更新 | 値が変化したテキストのみ描画/更新 | Med | 0.5–0.9 ms | High | dirty flag 導入 |
| 更新頻度制御 | FPS 0.1s 間隔 / タイマー 250ms / スコア即時 | Low | 0.3–0.5 ms | High | 時間蓄積 delta 使用 |
| アウトラインシェーダ | シェーダで 1 pass 膨張 | High | 40–60% | Low (後段) | Arcade/Pyglet raw GL 要調査 |
| 文字列再利用 | f-string → preformatted + inplace 数値差替 | Low | 0.1–0.2 ms | Med | format 避ける |
| 複合 HUD スプライト | 全 HUD を 1 FBO に合成後 1 draw | High | 1–1.5 ms | Med | 部分更新難度高 |
| Adaptive Skip | frame_ms > 閾値で HUD 更新スキップ | Low | スパイク緩和 | High | 安定性向上 |
| GC / オブジェクト削減 | 一時タプル/リスト削減 | Low | 数% | Low | 効果小 |

## 優先実行ステップ (Phase)
### Phase 1 (即日 / 低リスク)
1. アウトラインは常に 8 方向を維持。差分更新とキャッシュ導入で描画回数を削減
2. FPS 更新: 0.1 秒ごと / タイマー表示: 250 ms ごと / スコア & ライフ: 値変化時のみ
3. dirty flag (score_dirty, lives_dirty, timer_dirty, fps_dirty)
4. Adaptive Skip: (直近 N=30 フレーム median) の 2× 超過で HUD 更新スキップ

### Phase 2 (明確な効果測定)
5. タイトル/ゲームオーバー文言を PIL or Arcade で一度描画→Texture 化 / 1 スプライト blit
6. ゲームオーバー/タイトル状態では HUD 更新頻度を 0.5 秒に緩和
7. ライフ・スコアの文字列生成をテンプレート + 数値差替に (e.g., `self.p1_score_tpl = "スコア：{}"`)

### Phase 3 (最適化深化)
8. HUD 全要素をオフスクリーン FBO へまとめ draw / 通常フレームは 1 blit
9. Outline をシェーダ(拡張: distance field) 方式へ移行 (可逆: フラグで旧実装保持)
10. Text オブジェクトの x,y, text の変更最小化 (値変化時のみ更新ルート)

### Phase 4 (拡張 / 未来計画)
11. Signed Distance Field (SDF) フォント導入でアウトライン/スケール自由度拡張
12. 国際化 (i18n) 対応時に文字列辞書 + キャッシュ再構築コスト抑制
13. Telemetry: HUD セクション (hud_update, hud_draw) を profiler に追加し改善度を CSV 比較

## 詳細タスク分解
| Task ID | 内容 | 依存 | Done条件 | 計測指標 |
|---------|------|------|----------|----------|
| T1 | アウトライン 8方向維持のまま最適化 | - | 差分更新/キャッシュで描画削減 | draw_osd 平均 -15% |
| T2 | 更新頻度制御 (fps 100ms / timer 250ms) | T1 | 変更フレームのみ更新 | draw_osd 平均 -5% |
| T3 | dirty flag 実装 | T1 | 値未変化で draw 呼び数減 | draw_osd 平均 -10% |
| T4 | Adaptive Skip | T2 | スパイク時 HUD skip ログ | p95, max 低下 |
| T5 | 静的タイトル/GO テクスチャ化 | T3 | ゲーム状態遷移で1描画 | タイトル/GO 中 avg -0.3ms |
| T6 | 文字列テンプレート化 | T3 | format/f文字列削減 | micro 0.1–0.2ms 減 |
| T7 | HUD FBO 合成検証 | T5 | 1 draw 化ベンチ成功 | draw_osd < 2.5ms 安定 |
| T8 | Outline シェーダ試作 | T7 | 互換 fallback | シェーダ版 < 1.5ms (10s 計測: draw_osd ≈ 1.06 ms, frame ≈ 27.34 ms) |
| T9 | hud_update / hud_draw 計測セクション | T1 | CSV に 2 列追加 | other 減少確証 |

## ロールバック戦略
- すべて段階的フラグ (例: `--hud-opt-level 0..3`) で調整可能に。
- 問題が起きた場合: レベルを 0 (従来挙動) に戻し差分 isolate。

## 測定方法
1. 基準: 現行 main (変更前) 30s, `--profile-csv runs/hud_base.csv`
2. 各フェーズ後: 同条件で 30s 計測 → `scripts/analyze_profile.py` 比較
3. 指標: draw_osd avg / p95 / max, frame_ms avg, other の減少 (hud_update 計測導入後)
4. 目標推移例:
   - Base: 4.6 ms
   - Phase1 後: 3.6–3.8 ms
   - Phase2 後: 3.0 ms
   - Phase3 後: 2.2–2.5 ms

## リスクと対策
| リスク | 影響 | 緩和策 |
|--------|------|--------|
| 文字にじみ (キャッシュ) | 視認性低下 | 8方向固定 / SDF移行検討 |
| FBO 実装複雑化 | バグ/クラッシュ | 段階導入 + fallback パス保持 |
| シェーダ非対応環境 | レンダ失敗 | シェーダ機能は optional + capability チェック |
| Adaptive Skip による HUD 遅延 | UX 低下 | スキップは 1 フレーム単位のみ / 連続スキップ制限 |

## 簡易 KPI
| KPI | 現状 | 目標 (Phase2) | 目標 (Phase3+) |
|-----|------|---------------|----------------|
| draw_osd avg ms | 4.6 | <=3.0 | <=2.5 |
| draw_osd p95 ms | 7.3 | <=5.0 | <=3.5 |
| draw_osd max (安定運用時) |  < 180 (初期除外後 ~15) | <=12 | <=10 |
| Frame avg ms | 29.3 | <=28.0 | <=27.0 |
| FPS (mean) | 34 | >=35.7 | >=37.0 |

## 実装順チェックリスト
- [ ] T1 8方向アウトライン維持 + 差分更新/キャッシュ
- [ ] T2 更新頻度制御 (fps/timer)
- [ ] T3 dirty flag 適用 (score/lives/timer/fps)
- [ ] T4 Adaptive Skip 実装 + ログ
- [ ] T5 静的テキスト → テクスチャ
- [ ] T6 文字列テンプレート化
- [ ] T9 hud_update / hud_draw セクション追加 (T1 直後でも可)
- [ ] (Optional) T7 FBO 合成プロト
- [x] T8 アウトラインシェーダ — デフォルトで有効（初期化に失敗した場合は自動フォールバック）

## まとめ
段階的 / 可逆的最適化により HUD 描画を 50%以上削減可能な余地がある。まず低リスクの描画回数削減と差分更新導入で効果を速やかに得てから、高難度の FBO 合成・シェーダ最適化に進む。改善度は profiler CSV で定量化し、Regression を防ぐためフラグ化・比較計測を継続する。
