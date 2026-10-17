# Phase 0: macOS と Source アクセスの観測

- 日付: 2026-10-17（Asia/Tokyo）
- 対象: DESIGN §2、§15、O-001 / O-003。
- 判定: ホストと保存先への到達性のみ確認。Phase 0 の Go 判定は保留。

## 環境

| 項目 | 観測値 |
| --- | --- |
| macOS | 27.0.1 |
| OS build | 26A434 |
| Voice Memos bundle ID | com.apple.VoiceMemos |
| Voice Memos version / build | 4.0 / 1438 |
| Python | 3.14.7 |

OS とアプリの plist からバージョン情報のみを読む。
署名の entitlements を別途観測し、次の保存先候補を得た。
これらは当該 build の候補であり、安定した外部仕様とはみなさない。

- home-relative の Application Support 候補: `com.apple.voicememos`
- application group 候補: `group.com.apple.VoiceMemos.shared`

## 観測結果

Application Support 候補は不存在。application group 候補への初回アクセスと
再試行は権限拒否だった。権限確認後にシステム設定の認証画面を表示し、
その後の再試行では `listable`、直下 3 エントリを確認した。

実行経路は ChatGPT.app → codex → Python だった。この到達性は現時点の
ホスト権限に依存し、別ホストや将来の macOS への一般化はしない。
フルディスクアクセスはユーザーの個別承認を必要とし、PoC は権限設定を
変更・迂回しない。初回拒否を取得不能の恒久的な結論にはしない。

エントリ件数は録音数ではない。今回は録音・DB・sidecar の内容を読まず、
ファイル名、パス、アカウント情報、音声、文字起こしを出力・保存しなかった。
未追跡のユーザーファイルも調査対象に含めていない。

## 再現方法

```sh
uv run python -m pocs.macos_inventory.cli --source-root /approved/source/root
```

実機を自動探索せず、明示された root の直下を上限 10,000 件で数える。
子要素を開かず、root の最終要素が symlink の場合も追従しない。
エラー・上限超過は終了コード 1。出力は固定キー、状態、件数のみ。
`listable` は完全性や materialization の証拠ではなく、取得は常に
`UNKNOWN`、materialization は `unknown`、削除は無効とする。

合成 fixture で plist 異常、欠損情報、権限拒否、走査失敗時の fd 解放、
上限、symlink、子の非読取、CLI 出力の情報縮減を検証する。
CI は実アカウントへ接続せず、OS とアプリの情報も合成 fixture を使う。

## 次に測定すること

1. DB / WAL / SHM / 音声 / sidecar の内容を表示しない構成目録。
1. Source を変更しない SQLite snapshot 法と、DB と音声の一貫性。
1. native recording ID の候補と、名称変更・編集後も安定することの証拠。
1. 取得可能な raw metadata、未取得・unknown フィールドの識別。
1. 明示された合成録音 1 件の無変換 export と SHA-256 / size 比較。

今回の観測で native ID、録音中・編集中の一貫性、cloud materialization、
raw metadata、1 録音 export は検証できていない。
O-001 / O-003 は未解決であり、自動削除の条件を満たしたとは扱わない。
