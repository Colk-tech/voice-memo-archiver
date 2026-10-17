# ADR-0007: 読み取り専用 SQLite 調査の第一歩

- 日付: 2026-10-17
- 状態: PoC 基盤のみ採用。実機 adapter の採用判断は未決。
- 対象: DESIGN §2.2、§15 Phase 0、O-001。

## 判断

private store のパス、テーブル、録音 ID を推測して実装しない。
明示された SQLite パスを `mode=ro` で開き、backup API でメモリ内へ
複製する。WAL のコミットを含むスキーマを並び順付きで JSON 化し、
SHA-256 とオブジェクト数のみ返す。raw 行や DDL は表示・保存しない。
空スキーマと失敗は調査成功にしない。backup は約 5 秒を上限とする。

ディスクへの全 DB コピーは不要な保持を招くため今回は実装しない。
SQLite 本体と音声ファイル群の整合性は別問題であり、この成功だけでは
capture や ID 安定性を証明しない。fingerprint は schema の比較証拠で、
許可済み schema 判定や compatibility guard ではない。

## 安全性と制約

`mode=ro` は DB 書き込みを禁止するが、WAL の共有メモリファイルを
作成・更新する場合がある。無副作用のファイルシステム走査とは呼ばない。
実機は自動探索せず、最初は隔離した合成 DB または承認済みコピーを使う。
メモリ内には全 DB が載るため、機微データを含む場合は保護されたホストを
使う。swap や crash dump の保護はホスト依存。大容量 DB は今後の課題。

## 証拠と未検証事項

合成 SQLite DB の WAL、URI 特殊文字、未知スキーマ、行変更、欠損・破損、
空 DB、CLI の情報縮減とタイムアウトを自動テストする。
実 Apple Account、Voice Memos DB、音声にはアクセスしていない。

次に build 別の承認済み実機観測を行い、native ID の安定性、raw metadata、
録音中・編集中の一貫性、materialization、1 録音の無変換 export を測定する。
O-001 は未解決で、Phase 0 の Go 判定は保留。削除は実装しない。

## PoC 配置の更新

使い捨ての調査コードとテストを `src/` から `pocs/sqlite_probe/` に移設。
本番用の層構造、console script、パッケージ化、専用 tach 設定を撤去した。
調査内容と安全性の扱いは維持し、実行は
`uv run python -m pocs.sqlite_probe.cli --database PATH` とする。
型検査・テスト・カバレッジは `pocs/` を対象とする。

## 実機の到達性観測

macOS 27.0.1 / 26A434、Voice Memos 4.0 / 1438 で保存先へのアクセスを
観測した。権限拒否後、権限確認を経た再試行で直下の列挙に成功した。
調査コードは `pocs/macos_inventory/`、環境と証拠・限界は
[観測記録](../POC/2026-10-17-macos-inventory.md) に記録する。
今回も native ID や DB / 音声の snapshot 一貫性は未検証のままである。

## 構成調査と snapshot 反例

[構成観測](../POC/2026-10-17-source-layout.md) で通常ファイルを開かず、
固定拡張子の候補件数を記録した。実機 DB の SQLite 接続は行っていない。
[合成実験](../POC/2026-10-17-snapshot-trial.md) では main DB 単独 copy と
`immutable=1` が WAL の commit を欠落し、backup API が取得すること、
DB backup と外部ファイルの組が不整合になり得ることを確認した。

稼働中 Source の本体単独 copy と `immutable=1` は取得方式に採用しない。
後者の不変性の前提を実機で立証していない。backup API も SHM 副作用と
DB 外の整合性が未解決であり、実機の安全な取得方式として採用していない。
実機 DB 全体の保全は明示同意と暗号化・分離を要する。今回実行していない。
O-001 / O-003 / O-005 と Phase 0 Go 判定は未決のままとする。

参照: [SQLite WAL](https://www.sqlite.org/wal.html)、
[URI immutable](https://www.sqlite.org/uri.html)、
[Backup API](https://www.sqlite.org/backup.html)。

## 明示同意後の実機コピー調査

ユーザーが読み取り専用 DB コピーを明示許可したため、
[取得記録](../POC/2026-10-17-readonly-db-capture.md) の手順を実施した。
元 DB / WAL は raw O_RDONLY で読み、2 回読取・属性比較・WAL checksum
検証の後、AES-256 の repo 外隔離コピーだけを SQLite で検査する。
元の SHM は開かない。コピー側は quick_check 成功、構造集計を得た。
実機 DB / WAL の観測前後のバイト列は一致し、一時コピーは削除した。

この限定 PoC を許可済み実機観測として記録する。2 回一致と quick_check
は atomic snapshot、最新性、音声 / sidecar の整合性の証明ではない。
本番取得方式の採用、native ID 安定性、raw metadata 保全は引き続き未決。
過去の「実機アクセスなし」「snapshot メモリのみ」は当時の実施範囲であり、
今回の明示同意後の暗号化一時コピーを禁止する恒久方針ではない。

## ID・格納型の集計

[観測記録](../POC/2026-10-17-metadata-profile.md) で、コピー側の ID 候補の
NULL / 空値 / DISTINCT、全通常カラムの格納型、名前の一致候補を集計した。
ID 名称候補 8 カラムのうち 4 カラムは値があり観測上の一意性が true だが、
native recording ID の意味・名称変更や編集後の安定性は未確定である。
音声名と一致する DB セルはあったが、関連性・原本性・materialization や
sidecar の取得状態は確定していない。値・名前は出力せず、一時コピーは
削除した。O-001 / O-002 / O-003 / O-005 と Go 判定は引き続き未決。

## 合成録音と型付き値の追加証拠

[型付き SQL 値](../POC/2026-10-17-typed-metadata.md) のメモリ内往復と
[sidecar 署名](../POC/2026-10-17-sidecar-signatures.md) を追加検証した。
値の codec は raw metadata record や原本 DB の物理表現を置き換えない。

別途ユーザーが合成録音 1 件の作成・名称変更・編集を明示許可した。
[実機記録](../POC/2026-10-17-synthetic-recording.md) では TEXT ID 候補は
名称変更・短縮編集で一致し、BLOB ID 候補は編集で変化した。全ての ID 名称
候補を一律に永続 recording ID と扱わない。無変換 export の size / SHA-256
とローカル decode を確認したが、cloud materialization・全 metadata・
忠実な復元・atomic snapshot は未検証であり、Phase 0 Go は引き続き保留。

## 合成 record framing の検証

[record envelope](../POC/2026-10-17-record-envelope.md) で、型付き値と caller
指定の schema / encoding / 観測内位置を長さ付き形式で往復した。DB を読む
API は追加せず、合成入力のみを用いる。保存形式の採用判断や実機 metadata
保全の証拠とはしない。取得完全性は UNKNOWN、Phase 0 Go は保留のまま。

## 固定合成 SQLite と record container の対応

[SQL-to-record trial](../POC/2026-10-17-sql-record-trial.md) は、引数なしで
自作メモリ DB を生成し、schema / 列 / 同一行の型付き値を seed の期待値と
照合して envelope を往復する。実データ入力や汎用 reader は追加しない。
SQL 観測値の対応だけの証拠とし、Phase 0 Go / 完全取得の判断は保留する。
