# 合成 SQLite と外部ファイルの snapshot 実験

- 日付: 2026-10-17
- 対象: DESIGN §2.2、§15、O-001、O-005、ADR-0007
- 環境: macOS、Python 3.14.7、SQLite 3.53.1
- 実装: `pocs/snapshot_trial/`
- 状態: 合成入力の反例を確認。実機 Source の取得方式は未決。

## 目的と範囲

WAL の確定済み変更を取り込む方法と、DB 外の音声との一貫性を分けて
検証する。関数はパスを受け付けず、TemporaryDirectory 内で全入力を
生成する。実アカウント、Voice Memos、既存 DB にはアクセスしない。
模擬音声は任意の合成バイト列であり、有効な音声形式ではない。
実データの永続コピー、クラウド送信、削除機能は含まない。

## 再現方法

```bash
uv run pytest pocs/snapshot_trial \
  --cov=pocs.snapshot_trial --cov-branch --cov-fail-under=100 \
  -W error::ResourceWarning
uv run python -c \
  'from pocs.snapshot_trial.trial import run_trial; print(run_trial())'
```

schema の作成後に checkpoint し、自動 checkpoint を無効化したまま
1 行を commit する。writer 接続を維持し、終了時 checkpoint によって
差異が消えない状態で比較する。未 commit の別行も作成し、backup 後に
rollback する。これらはすべて実験用 DB への操作である。

## 観測結果

| 方法・検証 | 観測 |
| --- | --- |
| main DB のみを別パスへコピーして読む | 0 行 |
| 元 DB を `mode=ro&immutable=1` で読む | 0 行 |
| `mode=ro` 接続からメモリへ backup API | commit 済みの 1 行 |
| 未 commit 行の backup への混入 | なし |
| 読み取りを挟んだ元 DB / WAL のバイト比較 | 両方一致 |
| DB backup 後に外部ファイルを更新して取得 | DB 内 digest と不一致 |

`immutable=1` の結果は、この WAL fixture に対する観測である。
変化する実機 DB に安全に使えるという証拠ではない。
main DB のコピーは成功して開けても、確定済み変更を欠落し得る。
読み取り前後の比較は DB / WAL のみで、SHM を含む無副作用性は
証明していない。SQLite の読み取り専用接続は SHM に触れる場合がある。

外部ファイルの race は sleep や並列実行に依存しない。DB backup を
先に完了し、音声相当のバイト列と元 DB を revision 2 に更新してから
外部ファイルを読む。snapshot の revision 1 と取得バイト列は一致しない。
DB backup の成功だけではファイル群の原子性を保証できない反例である。
これは実機 Voice Memos の更新順序や挙動を再現したものではない。

## 検証と制約

2 テスト成功、実験コードの分岐込み coverage 100%。Ruff check / format、
`ty check`、`mypy --strict` も成功した。

実装は取得 API ではなく、隔離された合成実験である。一般入力に対する
エラー処理、時間・容量制限、復旧方式、音声取得は提供しない。
ファイルコピーの順序変更、quiet period、二重読み取りだけで一貫性が
保証できるかは未検証。実機 DB の raw metadata、ID、sidecar、Cloud
materialization、録音中・編集中の一貫性、無変換 export は未確認。

O-001、O-003、O-005 を解決したとは扱わない。Phase 0 は未完了、
取得完全性は UNKNOWN、削除は無効のままとする。実機 DB 全体の
永続コピーには DESIGN の明示同意要件を適用する。
