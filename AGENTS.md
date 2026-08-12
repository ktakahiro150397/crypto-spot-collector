# Todoistプロファイル

- Todoist projectは`開発ごと`、Repositoryは`F:\repo\crypto-spot-collector`、canonical repository labelは`crypto-spot-collector`、手入力routing nameは`crypto-spot-collector`とする。大文字小文字、全半角、空白・区切りの揺れと、意図が一意な軽微誤記は許容する。
- 進行状態には`候補`、`次にやる`、`作業中`、`ユーザー確認待ち`、`ブロック中`を使う。手入力タスクの既定移動先は`候補`とする。
- セクション未設定の手入力タスクは、task ID・タイトル・セクション・完了状態だけを先に読み、タイトル先頭のメモ書きが`crypto-spot-collector`を意図するとLLMが高い確信を持てるものだけを候補にする。`crypto-spot-collecotr`のような明白な文字転置、case、全半角、空白・区切りの揺れは許容するが、一般的な`crypto`だけ、内容だけが暗号資産関連、リポジトリ名がタイトル途中にある場合は候補にしない。候補化前は既存label、説明、コメント、Repository、関連task、実装参照をroutingに使わない。
- 候補だけ全フィールドとコメントを読み、タイトル判定と矛盾しないことを確認する。矛盾・曖昧さがあれば変更せず、明示的な全体監査依頼時だけ確認を求める。
- routing一致後のタスクについては、継続的許可により正規化、このRepository内で必要なnative subtask分割、既存labelを保持したlabel設定、優先度見直し、tracking parentのセクション移動、対応コメント追加を行ってよい。別Repositoryの成果は作成・変更せず報告する。削除・完了は含まない。
- 分割したtracking parentには`保留`labelを付け、parent自体は自動選定しない。native subtaskへ`sectionId`を設定・変更せず、parentのsectionでfamily状態を表す。子は依存順に並べ、最初の未完了・未ブロック子だけを実行対象とする。作成後は`parentId`と`childCount`を再取得して検証する。
- 自動選定はcanonical repository labelがあり、他のrepository labelと競合しないtask familyまたはstandalone taskだけを対象とする。`次にやる`familyを`候補`より優先し、familyでは最初のopen native subtask、standaloneではtask本体を選ぶ。`p1`、`p2`、`p3`、同順位では古い順とし、最大1件を選ぶ。`p4`、`保留`parent、他の実行が着手済みのtaskは除外する。`p4`はユーザーが対象を明示した場合だけ着手する。
- ユーザーが特定タスクを進めるよう依頼した場合、対象タスクへの対応報告、確認依頼、指摘への返答と、このRepository内の完了に必須でない発見を`候補`へ派生タスクとして登録して元タスクから関連付けることを含む。派生タスクの削除・完了までは含まない。
- Todoistタスクの完了条件を受入条件として扱う。mainnetへの接続・照会・発注、testnetでの外部操作、秘密情報の使用は、個別タスクの明示的な許可と安全条件がある場合だけ行う。
