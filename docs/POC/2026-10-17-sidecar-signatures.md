# Phase 0: sidecar 候補の署名観測

- 日付: 2026-10-17（Asia/Tokyo）
- 環境: macOS 27.0.1 / 26A434、Voice Memos 4.0 / 1438
- 対象: DESIGN §2.3、O-001 / O-002 / O-003
- 状態: 形式候補だけを観測。関連性・完全取得は未確定。

## 方法

`pocs/sidecar_probe/` は、明示された Source root の directory を fd 相対、
O_NOFOLLOW で走査し、固定拡張子 `.plist / .json / .xml` の通常ファイル
だけを O_RDONLY で開く。DB / WAL / SHM / 音声は開かない。
内容はメモリ内で 2 回読み、バイト列・inode・mode・size・mtime・ctime と
同名 entry の一致を確認する。名前・値・サイズ・hash は出力しない。

上限は全体 10,000 entry、深さ 4、1 ファイル 1 MiB、合計 8 MiB。
深さ・件数・バイト上限、置換、読取中の変更、I/O エラーでは部分結果を
返さない。root の親要素は操作者が信頼する。atime、キャッシュ、OS による
materialization の影響や、ファイル群の瞬間的な混在を排除するものではない。

署名は `bplist00`、空白除去後の `<?xml / <plist`、`{ / [` の接頭辞だけ。
XML parser や plist / JSON decoder は使わない。XML の候補が plist である
ことも、内容が構文的・意味的に正しいことも証明しない。

## 実機観測

| 項目 | 件数 |
| --- | ---: |
| 読み取った固定拡張子候補 | 13 |
| 2 回のバイト列と属性が一致 | 13 |
| binary plist 署名候補 | 2 |
| XML 系署名候補 | 10 |
| JSON 系署名候補 | 1 |
| その他の署名 | 0 |

録音との対応、キー・値・未知フィールド、形式の妥当性は未検証。
固定拡張子以外の関連ファイルがないとは扱わない。
13 ファイルが同時点の状態であるとも、13 録音分であるとも扱わない。
内容のコピーは永続保存せず、実データを fixture / Git / 外部へ送っていない。

## 再現と検証

```python
from pathlib import Path

from pocs.sidecar_probe.probe import inspect_sidecars

print(inspect_sidecars(Path("/explicit/approved/source/root")))
```

合成 27 テストで bounds、symlink / FIFO、ファイル・directory の置換、
読取中の変化、fd 解放、他種別を開かないこと、出力縮減を確認した。
対象の分岐込み coverage は 100%。実機観測は CI に含めない。
取得完全性は UNKNOWN、削除は無効、O-001 / O-002 / O-003 は未解決。
