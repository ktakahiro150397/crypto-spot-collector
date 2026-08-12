# yanelmoserver 再デプロイ前ベースライン

調査日時: 2026-08-13（JST）

この文書は、リファクタリング後の再デプロイに備えて、調査時点の
`yanelmoserver` 上の稼働状態と既知の問題を記録したものです。
認証情報やWebhook URLなどの秘密値は記載していません。

## 配置情報

- サーバー: `yanelmoserver`（調査時のIPv4アドレス: `192.168.3.20`）
- 配置先: `/home/ktakahiro150397/repo/crypto-spot-collector`
- Composeファイル: `/home/ktakahiro150397/repo/crypto-spot-collector/docker-compose.yml`
- ブランチ: `main`
- コミット: `3360d676b399c7536d8a59744ae11bb622b2b5df`
- サーバーと調査元の作業ツリー: 同一コミット、未コミット差分なし
- Docker Engine: `28.5.1`
- Docker Compose: `v2.40.2`

## 調査時点の稼働状態

| Composeサービス | コンテナ | 状態 | 最終状態の概要 |
| --- | --- | --- | --- |
| `app` | `crypto-spot-collector-app-1` | 停止 | 2025-12-22 03:00 JSTに終了コード1で異常終了 |
| `app_perp` | `crypto-spot-collector-app_perp-1` | 停止 | 2025-12-24 06:39 JSTに終了コード143（SIGTERM相当）で停止 |
| `bot` | `crypto-spot-collector-bot-1` | 停止 | 2026-02-11 21:28 JSTに終了コード143で停止 |
| `mysql` | `crypto-spot-collector-mysql-1` | 稼働 | 2026-02-11 21:31 JSTから稼働 |
| `dozzle` | `dozzle` | 稼働 | 約6か月稼働 |
| `portainer` | `portainer` | 稼働 | 約6か月稼働 |

ホスト上の別プロセス、systemdサービス、ユーザーcronから
`buy_spot.py`、`buy_perp.py`、`discord_appliation.py` が実行されている形跡は
確認されなかった。

## 判明した停止原因と既知の問題

### 現物Collector

Bybit APIから `retCode=10002`（サーバー時刻または`recv_window`の不整合）が
返り、未処理の`ccxt.base.errors.InvalidNonce`でプロセスが終了していた。
Composeの`app`に再起動ポリシーがないため、その後は復帰していない。

### Perp Collector

終了コード143で停止しており、OOMによる停止ではない。停止直前には
Hyperliquid WebSocketが約1分間隔で切断・再接続し、購読復元時に
`'coin'`エラーが繰り返されていた。最終的な停止操作の実行者・経路までは
ログから特定できなかった。

### Discord Bot

ホストの起動時刻は2026-02-11 21:29 JSTで、Botの停止時刻と一致するため、
ホスト再起動に伴って停止したと判断できる。Composeの`bot`に再起動ポリシーが
ないため、ホスト起動後に復帰しなかった。

停止前のログには、Bybit APIキーの期限切れ（`retCode=33004`）も記録されていた。
サーバー上の`secrets.json`は2025-12-04以降更新されていないため、再デプロイ前に
現在のキーの有効性確認または更新が必要である。

### サーバー時刻

調査時点で次の状態だった。

- 調査元端末よりサーバー時計が約28秒進んでいた
- `System clock synchronized: no`
- `systemd-timesyncd`自体はactiveだが、同期先は`n/a`、受信パケット数は0
- RTCはローカル時刻として構成され、OSから警告が出ていた

Bybit APIの時刻検証エラーが再発するため、単純なコンテナ再起動では解決しない。

### 常駐設定

`mysql`、`dozzle`、`portainer`には再起動ポリシーがある一方、`app`、
`app_perp`、`bot`には設定がない。異常終了およびホスト再起動後の自動復帰を
実現するには、アプリ3サービスの再起動ポリシーとヘルスチェックを見直す必要がある。

### 秘密情報とネットワーク

- 現物・Perp CollectorがDiscord Webhook URLを平文でログ出力している。
  該当ログはサーバーに残っているため、ログ出力を修正しWebhookをローテーションする。
- MySQLの3306番ポートが`0.0.0.0`および`::`に公開されている。
- DB認証情報が`docker-compose.yml`に固定値で記載されている。

## リファクタリング後の再デプロイ前チェック

- [ ] OSのNTP同期を正常化し、`System clock synchronized: yes`を確認する
- [ ] RTCをUTC運用に直すか、現在のローカルRTC構成を意図したものとして是正する
- [ ] Bybit APIキーを更新し、読み取り専用APIで有効性と時刻差エラーがないことを確認する
- [ ] Discord Webhookのログ出力を削除し、露出したWebhookをローテーションする
- [ ] Hyperliquid WebSocketの購読復元時に発生する`'coin'`エラーを修正する
- [ ] `app`、`app_perp`、`bot`へ適切な再起動ポリシーを設定する
- [ ] 各アプリとMySQLへヘルスチェックを追加または見直す
- [ ] DB認証情報をComposeから分離し、3306番ポートの外部公開要否を見直す
- [ ] 本番設定で現物、Perp、Botのどれを起動するか明示する
- [ ] 実注文を無効化できる検証モードまたは読み取り専用の起動確認手順を用意する
- [ ] デプロイ前にバックアップとロールバック対象のイメージ・コミットを記録する

## 再デプロイ後の確認項目

- [ ] `docker compose ps`ですべての対象サービスがrunning/healthyになる
- [ ] Bybitの`retCode=10002`および`retCode=33004`が発生しない
- [ ] Hyperliquid WebSocketの切断・購読復元エラーが継続しない
- [ ] ログにAPIキー、Webhook URL、秘密鍵などが出力されない
- [ ] コンテナを1つ停止して自動復帰を確認する
- [ ] ホスト再起動後に対象サービスが自動復帰する
- [ ] 注文を有効化する前に、設定値と現在ポジションを人手で最終確認する

## 調査時に実施していないこと

- コンテナの起動、停止、再起動、再ビルド
- サーバー設定、時刻、NTP、Firewallの変更
- APIキーやWebhookの更新・有効性確認
- DBへの書き込み、注文APIの実行
