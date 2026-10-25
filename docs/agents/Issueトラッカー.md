# Issue トラッカー：GitHub

> **言語 / Language / 語言 / 语言**：[繁體中文](議題追蹤.md) | [简体中文](议题跟踪.md) | [English](issue-tracker.md) | 日本語

このリポジトリの issue と仕様は GitHub の issue として管理しています。すべての操作に `gh` CLI を使ってください。

## 約束事

- **issue を作成する**：`gh issue create --title "..." --body "..."`。複数行の本文には heredoc を使います。
- **issue を読む**：`gh issue view <number> --comments`。コメントは `jq` で絞り込み、ラベルも取得します。
- **issue を一覧する**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` に、適切な `--label` と `--state` のフィルターを付けます。
- **issue にコメントする**：`gh issue comment <number> --body "..."`
- **ラベルを付ける／外す**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **クローズする**：`gh issue close <number> --comment "..."`

リポジトリは `git remote -v` から推定します。クローンの中で実行すれば `gh` が自動で行います。

## トリアージの対象としてのプルリクエスト

**PR をリクエストの窓口として扱うか：いいえ。** _（このリポジトリが外部の PR を機能リクエストとして扱う場合は `yes` にしてください。`/triage` がこのフラグを読みます。）_

`yes` の場合、PR も issue と同じラベルと状態で処理し、対応する `gh pr` コマンドを使います：

- **PR を読む**：`gh pr view <number> --comments`、差分は `gh pr diff <number>`。
- **トリアージ対象の外部 PR を一覧する**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` を実行し、`authorAssociation` が `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR`、`NONE` のものだけを残します（`OWNER`/`MEMBER`/`COLLABORATOR` は除外）。
- **コメント／ラベル／クローズ**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub は issue と PR で番号空間を共有しているため、単に `#42` とあればどちらの可能性もあります。`gh pr view 42` で解決し、だめなら `gh issue view 42` にフォールバックしてください。

## skill が「issue トラッカーに公開する」と言ったとき

GitHub の issue を作成します。

## skill が「関連するチケットを取得する」と言ったとき

`gh issue view <number> --comments` を実行します。

## Wayfinding の操作

`/wayfinder` が使います。**マップ**は 1 つの issue で、**子** issue がチケットです。

- **マップ**：`wayfinder:map` ラベルが付いた 1 つの issue で、Notes / Decisions-so-far / Fog の本文を持ちます。`gh issue create --label wayfinder:map`。
- **子チケット**：GitHub のサブ issue としてマップにリンクされた issue（サブ issue のエンドポイントに対して `gh api`）。サブ issue が有効でない場合は、マップの本文のタスクリストに子を追加し、子の本文の先頭に `Part of #<map>` を書きます。ラベル：`wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。着手されたら、チケットは作業を進める開発者に割り当てられます。
- **ブロック**：GitHub の**ネイティブな issue の依存関係**で表します。これが正規の、UI で見える表現です。エッジの追加は `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>` で行います。`<blocker-db-id>` はブロッカーの数値の **database id** です（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`。`#number` や `node_id` では_ありません_）。GitHub は `issue_dependencies_summary.blocked_by` を報告します（オープンなブロッカーだけで、これが現在のゲートです）。依存関係が使えない場合は、子の本文の先頭に `Blocked by: #<n>, #<n>` の行を書くことにフォールバックします。すべてのブロッカーがクローズされると、チケットのブロックは解除されます。
- **フロンティアの照会**：マップのオープンな子を一覧し（`gh issue list --state open`。マップのサブ issue／タスクリストに範囲を限定）、オープンなブロッカーがあるもの（`issue_dependencies_summary.blocked_by > 0`、または `Blocked by` 行にオープンな issue があるもの）や担当者がいるものを除外します。マップの順序で最初のものが優先です。
- **着手**：`gh issue edit <n> --add-assignee @me`。これがセッションで最初の書き込みです。
- **解決**：`gh issue comment <n> --body "<answer>"`、次に `gh issue close <n>`、その後マップの Decisions-so-far にコンテキストへの参照（要旨＋リンク）を追記します。
