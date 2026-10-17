# Phase 0: 型付き SQL 値の往復検証

- 日付: 2026-10-17（Asia/Tokyo）
- 環境: Python 3.14.7 / SQLite 3.53.1、macOS 27.0.1 / 26A434
- 対象: DESIGN §2.3、O-002
- 状態: SQL 観測値の codec 検証のみ。record 保全方式は未採用。

## 保持するものと限界

`pocs/raw_metadata/values.py` は単一 SQL 値を型付きバイト列へ変換し、
decode / encode 後の一致を検証する。未知のキーや BLOB の内容は解釈しない。

| SQL 格納型 | tag と本体 |
| --- | --- |
| NULL | `n` のみ |
| INTEGER | `i` + signed big-endian int64 |
| REAL | `r` + big-endian IEEE754 8 bytes |
| TEXT | `t` + `CAST(value AS BLOB)` のバイト列 |
| BLOB | `b` + 元の BLOB バイト列 |

TEXT の Unicode decode / 正規化、BLOB の JSON 化、日付変換を行わない。
NULL と空 TEXT / 空 BLOB は異なる表現となる。codec は NaN の bit pattern、
負のゼロ、不正 UTF-8、NUL、未知 BLOB を合成テストで保持する。
SQLite 自体が SQL 値として返す前に変換したものを復元する機能ではない。

この frame 自体には長さ・version・table / column・row identity を含めない。
将来の record artifact には別の container、encoding、schema、provenance と
対応付けが必要であり、この PoC を完成した metadata archive とみなさない。
SQLite の物理レコード表現、元の行順、全 schema のバイト保全も対象外。

## コピー側での検査

`verify_database(isolated_copy)` は保護済みコピーだけを SQLite で開き、
メモリ backup 上の通常テーブル全セルを検査する。view / virtual / shadow
table と schema 自身は除外する。名前・値・hash はメモリから出さない。
TEXT の元 encoding は PRAGMA encoding の固定値として別途報告する。
UTF-8 / UTF-16le / UTF-16be 以外は拒否する。

SQL は trusted_schema=OFF、temp_store=MEMORY、query_only=ON。
上限は 64 tables、各 512 columns / 10,000 rows、全体 100 万 cells、
1 cell 1 MiB、値の本体の合計 64 MiB。backup・query・Python の cell 境界で
約 5 秒の期限を確認する。これはハードな実時間上限ではない。
全 DB backup は値の上限検査より先なので、入力 DB の容量は呼出前の
`sqlite_capture` の 64 MiB 上限に依存する。一般の live DB を渡さない。

## 実機結果

明示許可済みの raw read-only DB / WAL 取得を使い、repo 外の AES-256 image
でコピー側だけを検査した。各試行の Source DB / WAL は取得前後で一致。
quick_check は成功し、最終試行は detach 1 回で一時コピーを削除した。

| 最終試行の項目 | 結果 |
| --- | ---: |
| 検査 / 往復一致したセル | 154,351 / 154,351 |
| SQLite TEXT encoding | UTF-8 |
| NULL | 37,024 |
| INTEGER | 84,143 |
| REAL | 14,741 |
| TEXT | 7,369 |
| BLOB | 11,074 |

encoding 追加前の別試行でも 154,269 セルすべてが一致した。時点が異なる
ため件数を混ぜず、Source の変化をゼロと主張しない。各試行内での
DB / WAL 前後一致だけを確認した。raw 値は出力・保存していない。

## 再現と検証

```python
from pathlib import Path

from pocs.raw_metadata.roundtrip import verify_database

print(verify_database(Path("/mounted/encrypted/approved-copy.sqlite")))
```

codec の合成 35 テストと DB 往復の合成 16 テストが成功し、対象の分岐込み
coverage は 100%。UTF-16 の両 byte order、SQL / Python timeout、容量と
件数の境界、不一致注入、識別子の引用、固定エラーを確認した。
サブエージェントの独立レビューも実施した。

この結果は raw metadata の完全取得・永続保全・復元の証明ではない。
未解釈の NULL を missing 等へ変換せず、取得完全性は UNKNOWN、削除は無効。
O-002 と Phase 0 Go 判定は引き続き未決とする。
