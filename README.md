# Foundry Hosted SharePoint Agent

Azure AI FoundryのHosted Agentとして動作する、SharePoint向けのFoundry IQ検索エージェントです。Knowledge Baseを使ったagentic retrievalをそのまま維持しつつ、実行面はAzure AI AgentServer SDKでResponses互換のHTTPサーバーに切り替えています。

## 変更後の構成

- [main.py](main.py): Hosted Agentのエントリーポイント。Foundryのhosting adapterで`localhost:8088`を公開します。
- [agents/sharepoint_agent.py](agents/sharepoint_agent.py): Indexed/Remoteの統合検索バックエンド。Knowledge Baseへの接続とAgent Frameworkの構築を担当します。
- [agents/indexed_sharepoint.py](agents/indexed_sharepoint.py): Indexedパターンのスタンドアロンデモスクリプト。
- [agents/remote_sharepoint.py](agents/remote_sharepoint.py): Remoteパターンのスタンドアロンデモスクリプト。
- [agents/grounding_sharepoint.py](agents/grounding_sharepoint.py): SharePoint Groundingツールを使った代替アプローチ。
- [providers/sharepoint_context_provider.py](providers/sharepoint_context_provider.py): リモートSharePoint用のカスタムコンテキストプロバイダー。
- [auth/obo_token_provider.py](auth/obo_token_provider.py): OBOトークン交換ヘルパー。
- [server/api_server.py](server/api_server.py): OBO対応のレガシーHTTP APIサーバー。
- [Dockerfile](Dockerfile): Foundry Hosted Agent用のコンテナー定義。
- [scripts/deploy_hosted_agent.sh](scripts/deploy_hosted_agent.sh): ACRビルド、capability host作成、agent version作成、デプロイ開始をまとめて実行します。
- [scripts/create_hosted_agent_version.py](scripts/create_hosted_agent_version.py): Azure AI Projects SDKでhosted agent versionを登録します。

## アーキテクチャ

```text
User / Foundry Playground
   |
   v
Hosted Agent Runtime (Azure AI AgentServer SDK)
   |
   v
Agent Framework Agent
   |
   v
AzureAISearchContextProvider (mode="agentic")
   |
   v
Azure AI Search Knowledge Base
   |
   +----+----+
   |         |
Indexed   Remote
```

## 検索パターン

`SHAREPOINT_SEARCH_PATTERN` で起動時の検索パターンを切り替えます。

- `indexed`: 既存のSharePoint indexer経由で高速に検索
- `remote`: Knowledge BaseのremoteSharePointソース経由で最新コンテンツを検索

Hosted AgentではHTTPヘッダーを自前で受け取る構成を廃止しています。したがって、以前のAPIサーバー方式で行っていたBearerトークン中継とOBO前提の経路は、Hosted Agentの主経路では使いません。基本はManaged IdentityまたはDefaultAzureCredentialでKnowledge Baseへアクセスします。

## 認証の使い分け

- Hosted Agentの標準運用: Managed Identityを使う
- 既存のHTTP API互換運用: OBOを使う

推奨理由は単純です。

- Hosted AgentはFoundryランタイム配下で動くため、通常は呼び出し元のHTTP Authorizationヘッダーをそのまま自前で受け回す前提にしない方が自然です。
- SharePointやKnowledge Baseに対するアプリケーション権限で十分なら、Managed Identityの方が構成と運用が安定します。
- ユーザーごとのACLを厳密に保持したまま検索したい場合に限り、[server/api_server.py](server/api_server.py) のような中継層で `Authorization: Bearer <token>` を受け、`Bearer ` を除いた生トークンを `user_assertion` として OBO に渡します。

判断基準:

- Foundry Hosted Agentをそのまま運用するなら、OBOは原則不要です。
- エンドユーザーのSharePoint権限をそのまま検索結果に反映したいなら、OBO経路を別入口として残す意味があります。
- BearerラベルはHTTPヘッダーでは必要ですが、OBOに渡す `user_assertion` には不要です。

## 前提条件

- Python 3.10以上
- Azure CLIにサインイン済み
- Azure AI Foundry project
- Azure AI Search service
- SharePointを接続したKnowledge Base
- Azure Container Registry
- Foundry projectのマネージドIDにACR pull権限を付与できる権限

## ローカル実行

1. 依存関係を入れます。

```bash
python3 -m venv .venv
source .venv/bin/activate
uv pip install --prerelease=allow -r requirements.txt
```

`agent-framework-azure-ai` が `azure-ai-agents` のベータ版に依存しているため、`uv` では prerelease を許可する必要があります。このリポジトリでは [pyproject.toml](pyproject.toml) に `tool.uv.prerelease = "allow"` を追加してありますが、`uv pip` を直接使う場合はコマンド側にも `--prerelease=allow` を付けておくのが確実です。

2. 環境変数を用意します。

```bash
cp .env.sample .env
```

最低限必要なのは次です。

- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_KNOWLEDGE_BASE_NAME`
- `SHAREPOINT_SEARCH_PATTERN`

リモートSharePoint検索で、knowledge source定義の`filterExpression`に加えて取得時だけ条件を追加したい場合は、次も使えます。

- `AZURE_SEARCH_REMOTE_KNOWLEDGE_SOURCE_NAME`
- `SHAREPOINT_REMOTE_FILTER_EXPRESSION_ADD_ON`

`SHAREPOINT_REMOTE_FILTER_EXPRESSION_ADD_ON`はAzure AI Searchの2025-11-01-previewでサポートされるretrieve時の`filterExpressionAddOn`に対応します。remote SharePoint knowledge source側の`filterExpression`と併用した場合、両者はAND条件で結合されます。

3. Hosted Agentをローカル起動します。

```bash
python3 main.py
```

起動後は`http://localhost:8088/responses`にOpenAI Responses互換のリクエストを送れます。

## デプロイ

デプロイスクリプトは以下をまとめて行います。

1. ACRでlinux/amd64イメージをビルド
2. Foundry accountのcapability hostを作成
3. Foundry project managed identityへACR pull権限を付与
4. Hosted agent versionを作成
5. エージェントを起動

### 必須環境変数

- `AZURE_SUBSCRIPTION_ID`
- `AZURE_RESOURCE_GROUP`
- `AZURE_FOUNDRY_ACCOUNT_NAME`
- `AZURE_FOUNDRY_PROJECT_NAME`
- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_AGENT_NAME`
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `AZURE_CONTAINER_REGISTRY_NAME`
- `AZURE_AI_PROJECT_RESOURCE_ID`

### 実行

```bash
chmod +x scripts/deploy_hosted_agent.sh
./scripts/deploy_hosted_agent.sh
```

既定値:

- CPU: `1`
- Memory: `2Gi`
- Min replicas: `0`
- Max replicas: `1`
- Image tag: UTCタイムスタンプ

## 主なファイル

```text
.
├── main.py
├── agent_sharepoint.py
├── Dockerfile
├── requirements.txt
├── .env.sample
├── scripts/
│   ├── create_hosted_agent_version.py
│   └── deploy_hosted_agent.sh
├── api_server.py
├── agent_indexed_sharepoint.py
├── agent_remote_sharepoint.py
└── agent_sharepoint_grounding.py
```

## 補足

- [api_server.py](api_server.py) は旧来のHTTPラッパーです。Hosted Agent運用では使いません。
- 機密情報は`.env`やイメージに焼き込まず、Managed IdentityとFoundry側の構成で扱う前提です。
- `AZURE_SEARCH_API_KEY`は互換用途で残していますが、Hosted AgentではManaged Identityを優先してください。
