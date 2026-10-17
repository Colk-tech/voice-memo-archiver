# PoC と本番コードの分離

使い捨ての調査コードとテストは `pocs/` に置く。
現在は本番コードがなく、`src/` と本番パッケージは作成していない。
ルートは uv の仮想プロジェクトとして開発依存のみを管理する。

```text
pocs/
  macos_inventory/  # ホストとアクセス可否の調査＋同居テスト
  source_layout/    # 内容を読まない構成候補の分類＋同居テスト
  snapshot_trial/   # 合成入力のみの WAL / 外部ファイル反例
  sqlite_capture/   # 許可された raw DB/WAL copy と隔離検査
  sqlite_probe/
    cli.py          # 調査 CLI
    probe.py        # SQLite 調査
    test_cli.py
    test_probe.py
docs/
  ADR/              # 調査判断・証拠・限界の記録
```

PoC に本番の層構造や依存境界規約は適用しない。
当初の bootstrap / infrastructure 分割と専用 tach 設定は撤去した。
PoC が不要になったらコード・専用テスト・設定を削除し、調査記録は残す。

将来の本番コードは DESIGN §5.2 に従い `src/voice_memo_archiver/` に
実装し、その時点で依存境界とパッケージ化を導入する。
PoC の成果を本番契約として使う場合は、証拠に基づいて別途判断する。
