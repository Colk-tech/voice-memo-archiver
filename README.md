# Voice Memo Archiver

現在は Phase 0 の SQLite スキーマ調査基盤のみ実装している。
Voice Memos の収集・保存・復元・削除機能は未実装。
設計は [DESIGN](docs/DESIGN.md)、判断と限界は
[ADR-0007](docs/ADR/0007-readonly-sqlite-probe.md) を参照。

## 開発

Python 3.14 と uv を使用する。

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy --strict
uv run tach check
uv run pytest --cov=src/voice_memo_archiver --cov-branch \
  --cov-report=xml --cov-fail-under=100 -W error::ResourceWarning
uv run yamllint .github/workflows/ci.yml
```

## 隔離コピーの調査

```sh
uv run vma-source-probe --database /path/to/approved-copy.sqlite
```

実機パスは自動探索しない。最初は合成 DB または承認済みの隔離コピーを
指定する。WAL を使う DB は本体だけをコピーして整合性を仮定しない。
実機コピーの取得手順は未検証で、稼働中 DB の単純コピーは推奨しない。

DB を読み取り専用で開き、メモリ内 backup の schema fingerprint と
オブジェクト数を出力する。録音内容・行・DDL・パスは出力しない。
`acquisition_completeness` は常に `UNKNOWN`、削除は常に無効。
不正 DB と空スキーマは終了コード 1、引数不足は 2。

SQLite が共有メモリを作成・更新する可能性があるため、ディレクトリ全体の
無変更は保証しない。この調査結果は録音の完全取得や復元の証明ではない。
macOS build、ID 安定性、音声 export の実機検証は今後実施する。

CI は Linux/macOS で合成 DB のみを検査する。Codecov の Project/Patch
連携、実機 E2E、branch protection の設定は未完了。ローカルと CI の
カバレッジ閾値は 100%。依存境界は
[ARCHITECTURE](docs/ARCHITECTURE.md) を参照。
