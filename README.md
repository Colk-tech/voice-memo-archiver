# Voice Memo Archiver

現在は Phase 0 の SQLite・ホスト・構成調査 PoC を実装している。
使い捨ての PoC とテストは `pocs/` に隔離し、
本番用の `src/` はまだ作成していない。
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
uv run pytest --cov=pocs --cov-branch \
  --cov-report=xml --cov-fail-under=100 -W error::ResourceWarning
uv run yamllint .github/workflows codecov.yml .yamllint
```

## 隔離コピーの調査

```sh
uv run python -m pocs.sqlite_probe.cli --database /path/to/approved-copy.sqlite
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
実機 PoC の観測範囲は後述の記録を参照。ID の本番契約は未確定である。

CI は Linux/macOS で合成 DB のみを検査する。ローカルと CI の
分岐込みカバレッジ閾値は 100%。実機 E2E と branch protection は未設定。
本番コードとの分離は
[ARCHITECTURE](docs/ARCHITECTURE.md) を参照。

CI の発火条件は `.github/workflows/on-push.yml`、検査ジョブの定義は
`.github/workflows/template-quality-ci.yml` に分離している。
定義側は `workflow_call` で発火側から呼び出す。

## 依存更新とカバレッジ

`renovate.json` で Python 依存、uv.lock、GitHub Actions の更新を管理する。
lock file maintenance を有効にし、メジャー更新は Dashboard で承認する。
更新 PR は `Colk-tech` に割り当て、既存の `enhancement` ラベルを付ける。
自動マージは無効。Renovate App でこのリポジトリを対象にする必要がある。

Codecov には Linux CI から `coverage.xml` のみを OIDC で送信する。
アップロード失敗は CI を失敗させ、Project / Patch の閾値は 100% とする。
トークンの登録は不要。実行結果は
[Codecov](https://app.codecov.io/gh/Colk-tech/voice-memo-archiver) で確認する。
GitHub の status 連携には Codecov App のリポジトリへの導入も必要。

## macOS ホストとアクセスの調査

```sh
uv run python -m pocs.macos_inventory.cli --source-root /approved/source/root
```

OS / Voice Memos のバージョンと、指定 root の直下件数を出力する。
root の最終要素が symlink の場合は追従せず、子ファイルは開かない。
権限拒否や上限超過は終了コード 1。録音数・完全性・materialization は
この観測だけでは判定しない。合成 fixture のみを CI で使う。
実機結果と未検証項目は
[調査記録](docs/POC/2026-10-17-macos-inventory.md) を参照。

## Source 構成と snapshot の調査

```sh
uv run python -m pocs.source_layout.cli --source-root /approved/source/root
```

directory のみを開き、DB / WAL / SHM / 音声 / sidecar の候補件数を
固定拡張子で分類する。名前・内容は出力しない。既定は深さ 4、全体
10,000 entry。symlink を追従せず、深さによる未訪問 directory は別計数、
走査失敗・上限超過は終了コード 1。候補数は録音数や完全性の証拠ではない。

[構成観測](docs/POC/2026-10-17-source-layout.md) と
[合成 snapshot 実験](docs/POC/2026-10-17-snapshot-trial.md) を参照。
実機の安全な snapshot 方式は未決。DB 本体のみのコピーや稼働中 DB の
`immutable=1` 読取を採用しない。DB backup と音声の一貫性は別途検証する。

明示同意の後、元 DB / WAL を raw read-only で読み、AES-256 の repo 外
隔離コピーだけを SQLite で検査した。
[取得記録](docs/POC/2026-10-17-readonly-db-capture.md) に結果を示す。
`pocs/sqlite_capture/` の API は操作者による暗号化・隔離・cleanup を要する。
DB の構造集計を確認できたが、Phase 0 は未完了である。

続く [ID・格納型の観測](docs/POC/2026-10-17-metadata-profile.md) では、
隔離コピーで NULL / 空値 / DISTINCT と実際の格納型を集計し、音声名との
一致候補を数えた。名前・値は出力しない。ID 安定性、音声 / sidecar の
関連性、raw metadata の保全を確認したものではない。

続いて [型付き値の往復検証](docs/POC/2026-10-17-typed-metadata.md) と
[sidecar 署名](docs/POC/2026-10-17-sidecar-signatures.md) を観測した。
ユーザーが明示許可した
[合成録音の変更・export](docs/POC/2026-10-17-synthetic-recording.md) では、
TEXT ID 候補が名称変更・短縮後も一致し、BLOB ID 候補は編集で変化した。
無変換コピーの SHA-256 / size は一致したが、native ID の契約や忠実な
Voice Memos 復元を確認したものではない。削除は引き続き無効である。

[合成 record envelope](docs/POC/2026-10-17-record-envelope.md) では、型付き値を
schema・encoding・観測内の位置と結び付け、メモリ内の可逆性と不正形式の
拒否を検証する。実 DB の採取・永続保全・保存形式の採用は対象外である。

[合成 SQL との対応検証](docs/POC/2026-10-17-sql-record-trial.md) は、実験自身が
作るメモリ DB から schema・列・型付き値を取り、seed の期待値と envelope の
往復を照合する。generated 列と重複行も対象だが、実機 reader ではない。
