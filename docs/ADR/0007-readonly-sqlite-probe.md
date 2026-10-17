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
