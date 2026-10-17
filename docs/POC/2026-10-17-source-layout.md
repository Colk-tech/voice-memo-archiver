# Phase 0: Source 構成のメタデータ観測

- 日付: 2026-10-17（Asia/Tokyo）
- 環境: macOS 27.0.1 / 26A434、Voice Memos 4.0 / 1438
- Python: 3.14.7
- 対象: DESIGN §2.2、O-001 / O-003 / O-005
- 判定: 構成候補のみ。Phase 0 は未完了。

## 方法

到達性調査で確認した application group root を明示指定し、
`pocs/source_layout/` でディレクトリを走査した。
通常ファイルは開かず、entry の名前をメモリ内で固定分類し、
`stat(follow_symlinks=False)` の種別と分類別件数だけを返す。
名前・パス・任意拡張子・size・時刻・xattrs・内容は出力しない。
SQLite 接続、DB 複製、音声読取、クラウド送信は行っていない。
未追跡の `poc.sqlite3` は対象外で、読み書きしていない。

```sh
uv run python -m pocs.source_layout.cli \
  --source-root /approved/source/root
```

root と再帰先は `O_DIRECTORY | O_NOFOLLOW` で開き、再帰先は
親 fd を基準にする。symlink は数えるだけで追従しない。
root の親要素は操作者が信頼する。ディレクトリ間の置換や mount の
変更全般を防ぐ sandbox ではなく、同時更新中の原子的 snapshot でもない。
OS によるアクセス時刻やキャッシュの更新まで不変とする保証はない。

既定は root を深さ 0 として深さ 4 まで、全体 10,000 entry 以下。
深さ境界で訪問しなかった directory は別計数する。上限超過・権限拒否・
消失・stat/open 失敗では部分結果を出さず終了コード 1 とする。
ディレクトリを開いた後は例外時も fd を閉じる。

## 観測値

| 分類 | 件数 |
| --- | ---: |
| 全 entry | 1,093 |
| directory | 29 |
| 深さ境界で未訪問の directory | 0 |
| symlink（非追従） | 1 |
| DB 候補 | 1 |
| WAL 候補 | 1 |
| SHM 候補 | 1 |
| 音声候補 | 914 |
| sidecar 候補 | 12 |
| その他の通常ファイル | 134 |
| 特殊ファイル | 0 |

DB は `.db / .sqlite / .sqlite3`、WAL / SHM はその接尾辞、
音声は `.m4a / .wav / .caf / .aiff / .mp4 / .aac`、sidecar は
`.plist / .json / .xml` で分類した。大文字小文字は区別しない。
未知形式はその他に残す。形式署名、DB と WAL の対応、sidecar と録音の
関係は未確認。音声候補数は録音数・原本数を意味しない。
symlink の先や未知形式・列挙外の保存先に情報がある可能性を排除しない。

## 検証と次の境界

合成 fixture の 19 テストで、固定分類、深さ・entry 上限、symlink、
FIFO 非読取、directory から link への置換、stat/scan 失敗、
fd 解放、CLI の情報縮減を確認した。対象の分岐込み coverage は 100%。

snapshot の反例は別の
[合成実験](2026-10-17-snapshot-trial.md) に記録する。
本体単独 copy と稼働中 DB への `immutable=1` は取得方式に採用しない。
SQLite backup は DB 外ファイルの整合性を保証しない。

次は、実機全 DB 保全の明示同意・暗号化・分離を満たす方法、または
全 DB 保全を必要としない最小取得方法を具体化する必要がある。
無断で実機 DB 全体をメモリや永続領域に複製しない。
live SQLite の SHM 副作用を回避する方法も未検証である。
native ID、raw metadata、materialization、無変換 export は未検証。
取得完全性・snapshot 一貫性は UNKNOWN、削除は無効のままとする。
