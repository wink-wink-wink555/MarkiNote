# 贡献指南

## 支持环境

- Python 3.12；`uv.lock` 是开发与 CI 的唯一 Python 解析结果。
- Node.js 22（最低 20.19）；`apps/web` 与 `packages/api-client` 分别维护 lockfile。
- Docker Desktop（或 Docker Engine）与 Compose v2 用于完整栈、数据库、恢复和镜像门禁。

Windows PowerShell 初始化：

```powershell
uv sync --frozen --all-extras
npm ci --prefix packages/api-client
npm ci --prefix apps/web
Copy-Item .env.example .env
```

不要手工编辑 lockfile。依赖变更必须由对应包管理器重新解析，并在 PR 中说明供应链、镜像和运行时影响。根 `package.json` 只汇总跨项目命令，不需要第三套 Node 安装。

## 本地运行

推荐通过同源网关运行完整栈：

```powershell
docker compose up -d --build --wait
```

访问 `http://127.0.0.1:8080`。日志可通过 `docker compose logs -f api gateway` 查看。

只调试 API：

```powershell
uv run uvicorn markinote_api.application:app --host 127.0.0.1 --port 8000 --reload
```

只调试 React：

```powershell
$env:VITE_API_PROXY='http://127.0.0.1:8000'
npm run dev --prefix apps/web
```

## 提交前门禁

后端：

```powershell
uv run ruff check apps/api/src apps/api/scripts tests apps/api/tests infra
uv run mypy apps/api/src/markinote_api
uv run pytest -q
uv run pytest apps/api/tests -q --cov=markinote_api --cov-config=pyproject.toml --cov-report=term-missing
```

契约、前端与浏览器：

```powershell
uv run python apps/api/scripts/export_openapi.py
npm run generate --prefix packages/api-client
npm run typecheck --prefix packages/api-client
npm run typecheck --prefix apps/web
npm run lint --prefix apps/web
npm run test:coverage --prefix apps/web
npm run build --prefix apps/web
npx --prefix apps/web playwright install chromium
npm run e2e --prefix apps/web -- --project=chromium --project=mobile-chrome
```

容器模型：

```powershell
docker compose config --quiet
```

真实 PostgreSQL、NGINX SSE、备份恢复、安全扫描、SBOM 和镜像 hardening 由 CI 独立 job 验证。涉及这些边界的修改应按 [README](README_CN.md) 中的发布、备份与故障处置说明补做相应演练。

## 架构与数据约束

- 依赖方向保持为 HTTP adapter → application/domain port → infrastructure adapter；新增跨层导入需在 PR 中记录设计决策，并同步公开 README 中受影响的架构说明。
- 文件路径统一通过 `markinote_api.platform.paths` 和文档领域服务解析，禁止直接拼接用户输入。
- 持久化使用原子写、乐观版本或事务；不得绕开配额、锁、journal、before-image 与补偿语义。
- 数据库 schema 只通过 Alembic 演进；生产禁止 ORM 隐式建表。
- OpenAPI 与版本化 Agent SSE 事件是外部契约。OpenAPI 快照、生成客户端和相关 SSE 契约测试必须可重复且无意外 drift。
- LocalFS 当前只允许一个 API writer；没有共享存储与跨进程协调前，不得通过增加 worker 或副本掩盖容量问题。

## 安全与隐私

- Access token 与 AI API Key 不得进入 URL、浏览器持久化、日志、trace、测试快照或制品。
- 用户正文、附件和 prompt 默认不进入结构化日志与 telemetry；审计只记录低基数 metadata/hash。
- 用户或 AI 生成的内容进入 HTML 前必须经过现有清洗管线；URL fetch 必须保留 DNS、peer 与逐跳 redirect 校验。
- 新文件入口、工具参数和迁移脚本需覆盖 traversal、symlink、Unicode/Windows 路径、超限、冲突、失败补偿和损坏输入。
- 不得通过降低测试、覆盖率或扫描阈值让门禁“恢复通过”。

## Pull Request 与发布

PR 至少说明：

1. 用户价值、根因与行为变化；
2. 数据、契约、安全、并发和回滚影响；
3. 可复现的验证命令与结果；
4. UI 变更的脱敏桌面/移动证据；
5. 新迁移、配置、指标、告警或 README 操作说明更新。

提交信息建议使用 `feat:`、`fix:`、`docs:`、`refactor:`、`test:` 或 `chore:` 前缀。Release tag、required checks、审批和分支保护仍须由 GitHub 仓库设置实际启用；工作流文件本身不等于外部控制已经生效。具体发布门禁见 [README](README_CN.md#release-governance)。
