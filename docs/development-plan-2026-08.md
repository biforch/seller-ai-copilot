# SellerAI Copilot Development Plan

**Plan version:** 2026-08-27（B1d controlled quality gate complete）
**Supersedes:** 2026-08-21 Amazon-first release plan
**Formal code baseline:** merged `origin/main` at `0e940a2c0d292fb8e2dd25463adff12f73cfb8d0` (`0e940a2`, B1d offline preflight and plan).
**Current product line:** **Listing Audit**（决策分析助手）。Amazon 同步与内容生成不再是当前发布主线。
**Alembic head on main:** `1b2c3d4e5f6a`.
**B0 status:** Complete
**B1 status:** Complete (B1d human quality gate passed; implementation pending review)
**Source of truth:** 已合并的 `main@0e940a2`、其 Alembic 链、自动化测试与本计划。历史脏工作区不是 source of truth。
**Authority:** 本计划不授权 merge、deploy、删除数据、启用 Amazon、公开 Analysis，或调用外部生产服务。

## 0. 正式证据（main@0e940a2 / B1d offline preflight complete）

| 项 | 状态 |
| --- | --- |
| Commit | `811f36a`（包含 B0a–B0f 与随后 OpenSSL runtime remediation） |
| Backend pytest | **1677 passed** on merged main |
| Frontend Vitest | **131 passed** on merged main |
| ESLint | **0/0** |
| Quality Gate | [B1c main run 32999182796](https://github.com/biforch/seller-ai-copilot/actions/runs/32999182796) 在精确 SHA `d1e45d1` **success**，production vulnerability policy `blocked=0` |
| MFA | **Complete on main**：强制 TOTP、replay 防护、单次恢复码、加密 secret、pending-session gate |
| `ANALYSIS_PUBLIC_ENABLED` | main 已固定默认 `false`，且任何 `true` 配置 fail-closed |
| Listing Audit internal slice | B1a service、B1b API 与 B1c UI 已合并。仅 Cookie 会话注册用户、双端内部开关默认关闭；不含公开或匿名路径 |
| Render adapter | 仍在 Draft [PR #3](https://github.com/biforch/seller-ai-copilot/pull/3)；**未合并、未部署**。R4d 指出 backend `PORT=8000` 与供应链扫描问题尚待修复 |
| Amazon 发布门禁 | **真实 Amazon 不再是当前发布门禁**。原 R2e **停止执行**，除非未来独立战略决策恢复 Amazon |
| 公开测试门禁 | HTTPS / DNS / HSTS、外部监控、生产备份目标。平台账号或域名准备就绪 **不等于** 已部署或已验证上线 |

## 1. 产品目标

当前主线验证的是：卖家是否重视更好的 Listing 决策，而不是 SellerAI 能否连接 Amazon 或生产更多内容。

目标价值路径已作为默认关闭的注册用户内部切片进入 main；B3 go/no-go 前仍禁止公开 Analysis：

1. 粘贴 Listing 标题、五点描述与产品描述；
2. 获得有输入证据支撑的 0–100 总分、维度分、优先问题、限制说明及最多三项行动建议；
3. 先用内部注册切片证明质量（B1），再决定是否投资匿名/公开路径（B2/B3）。

首轮公开测试的学习目标（仅在 B3 go 之后才适用）约为：50 位测试用户、至少 20 份反馈、至少 5 个明确的价值认可。这些是决策门槛，不是流量 KPI。

本阶段（B0 清理与冻结）**禁止实现** `AnalysisReport` 表/migration、匿名 claim、或任何新业务 API。

## 2. 范围重置

### 当前 P0

- 文本版 Listing Audit 作为产品主线。
- 先完成 B0 基线拆分与冻结，再收编脏工作区中的安全/MFA/eval 基础设施。
- B1 仅服务注册测试用户的内部垂直切片；公开访客路径不得抢跑。

### P1/P2（B1 质量 gate 通过后才评估）

- 确定性 Profit Analyzer。
- 产品关联、再次分析与最小报告对比。
- 图片输入必须在上传/存储、内容安全、隐私、保留期与多模态成本验收后单独立项。

### 冻结范围

冻结表示：**完整保留** 代码、历史表、migration、service、API 与测试；保持 feature flag 默认关闭；从主导航隐藏；停止功能扩展。**禁止删除** Amazon 或旧 generation 实现。

冻结对象：

- Amazon OAuth、账户、市场、同步、Catalog、Seller Central 审核及原 R2e。
- Listing / 关键词生成、proposal、diff、审核收件箱与 Amazon → AI Context。
- 自动发布、PPC、关键词库、竞品爬取、复杂 Agent、多模型 fallback。
- 复杂项目管理、订阅、团队/RBAC 与高级仪表盘。

Amazon 基础设施在 `main@811f36a` 上已经完成并完整保留，但当前冻结、默认关闭：

- `AMAZON_SP_API_ENABLED=false`
- `AMAZON_OAUTH_ENABLED=false`
- `AMAZON_SP_API_ENDPOINT_MODE=mock`

B0f 已隐藏 Amazon 与旧 Generate 入口，并保持服务端 fail-closed；实现完整保留。

## 3. 可复用工程底座（仅限已合并 main）

### 已在 main@811f36a 可复用

- Cookie-only 可撤销会话、CSRF、注销撤销、租户隔离、限流、安全响应头，以及 R3d 的 session-scoped 客户端状态隔离。
- PostgreSQL、Alembic（head `1b2c3d4e5f6a`）、健康检查、确定性构建、镜像 pin、SBOM/Trivy policy、内部 RC runbook。
- Generation 状态、幂等、配额预留/结算、token 估算及失败恢复。
- Product 存储与可读取的旧 Generation 历史。
- Amazon 集成代码与测试（冻结，默认关闭）。
- 当前 AI provider 合同保持 main 现状：默认 `OPENAI_BASE_URL=https://openrouter.ai/api/v1`。默认 URL 改直连 OpenAI、以及 `store=false` 等 AI 安全合同，**以后单独审查**，不混入 MFA 或 Listing Audit 基础设施。

### 已从冻结脏工作区安全重建并进入 main

- B0b 应用日志敏感过滤器。
- B0c 持久化登录滥用防护。

### 已完成并进入 main 的 B0d 安全能力

- 强制 TOTP MFA、单次恢复码、TOTP replay 防护、加密 MFA secret 与 pending-session gate。

### 已完成并进入 main 的 B0e 质量基线

- 严格 Listing Audit schema、versioned prompt、15 个 synthetic cases、离线 runner、grounding/score validator 与双人独立人工评分 gate。
- 不包含 `runs/**`、provider 输出、业务 API、数据库 migration 或公开 Analysis。

### 仍存在于冻结脏工作区、尚未进入 main（不得写成已完成）
- Render 生产适配器（权威副本在 Draft PR #3，不从脏树提交）。
- `docs/security/evidence/**` 等证据文件：等对应代码落地后再提交，禁止提前声称控制已完成。

### 未来改造（均未在 main 实现）

- 独立 `analysis` domain。B1 才允许注册用户 API；B2 才允许匿名 claim；B3 go/no-go 前禁止公开 Analysis。
- `ANALYSIS_PUBLIC_ENABLED=false` 已是 main 合同；B3 独立 go/no-go 前禁止改为 true。
- 新 analysis 包不得依赖 Amazon。

## 4. 不可妥协规则

- 租户与报告所有权在数据库查询中执行；跨租户 missing/forbidden 使用一致的安全 `404`。
- 脏工作区不是 source of truth。收编必须按 B0a–B0f 拆分；`tests/evals/**/runs/**` 永不提交。
- 不提交 `.env`、credential、seller ID、OAuth material、claim token、原始 Listing corpus、dump 或 provider payload。
- Listing 原文不得进入日志、反馈事件、错误遥测或营销系统，也不得用于训练。
- 分数与建议必须引用输入证据；证据不足时声明限制，不得虚构销量、关键词量、竞品或市场事实。
- 新迁移必须 additive；现有 Amazon、ListingVersion、Proposal 与 Generation 保持可读。**本阶段禁止新增 AnalysisReport migration。**
- RC/生产不隐式读取仓库 `.env`；任何必需 gate 失败或跳过时不得晋级。
- 用户已准备 Cloudflare / Render / 域名 **不等于** 已经部署或验证；禁止写成已上线。
- Human review 始终必需；自动 Amazon publishing 不在本计划内。

## 5. 当前状态

### 已完成且属于 main@811f36a

- 产品/项目存储、状态机、配额、幂等、不可变 Listing 历史与租户安全响应约定。
- Cookie-only 服务端会话、CSRF、注销撤销与 R3d 会话隔离。
- 确定性构建、镜像 pin、官方 npm registry、SBOM/Trivy policy、内部 RC 与备份恢复演练文档（内部 RC，不是生产部署）。
- Amazon 集成技术上已完成并保留，但是 **dormant / frozen** 可选能力，不是产品主线，也不是当前发布门禁。
- B0a 战略冻结、B0b 日志脱敏、B0c 登录滥用防护、B0d 强制 MFA、B0e Listing Audit 质量基线。

### 已完成（B0 Complete）

- B0a–B0f 已合并 main。
- Amazon 与旧 Generate 入口已隐藏；`ANALYSIS_PUBLIC_ENABLED=false` 且服务端 fail-closed。

### 阻塞公开测试

- Listing Audit 内部注册用户 API/UI 已合并且默认关闭；受控 provider 运行与双人人工质量 gate 尚未执行。
- 匿名报告、TTL/清理、claim token 与 MFA 后认领：**未实现，本阶段禁止实现**。
- 强制 MFA 已进入 main；公开部署仍需使用独立环境密钥并完成 RC enrollment/recovery 验收。
- HTTPS/DNS/HSTS、外部监控与生产备份目标。
- Render adapter 未合并；R4d P1/P2 未修复；没有生产部署授权。

## 6. 执行计划

按证据 gate 推进。较晚的公开阶段不得绕过较早的阻塞 gate。

### B0 — 基线拆分与战略冻结

**Status:** Complete

**Entry:** `main@811f36a` 已满足 B0 exit；历史脏工作区不参与后续实现。

计划中的收编顺序（文档合同，不是本 PR 的实现范围）：

- B0a：战略冻结文档（本文件与 `docs/strategy-reset-migration-plan-v0.1.md`）。
- B0b：安全日志脱敏。
- B0c：持久化登录滥用防护（已合并 `2004017`）。
- B0d：强制 MFA（已合并 `09b37b2`）。
- B0e：独立 PR 收编 Sprint 0.5 schema / prompt / eval 基础设施（不含 `runs/**`）。
- B0f：隐藏 Amazon 与旧 Generate；实现 `ANALYSIS_PUBLIC_ENABLED=false` 双重 fail-closed。
- Render 继续只走 Draft PR #3，不从脏树提交。

**Exit evidence:** B0a–B0f 已进入 main；Amazon 与旧 Generate 在 UI / 服务端双重关闭；`ANALYSIS_PUBLIC_ENABLED=false` 且 true 配置 fail-closed；main Quality Gate 已通过。未部署。

### B1 — 内部 Listing Audit 垂直切片

**Status:** Complete (B1d human quality gate passed)
**Access:** 仅注册测试用户。禁止匿名架构抢跑。

**Entry:** B0 冻结合同成立；准备收编或重建 Listing Audit 契约后，才允许实现注册用户 API/UI。

Sprint 0.5 schema、prompt、15 个 synthetic cases 与 eval harness 已通过 B0e 进入 main；`runs/**` 仍禁止提交，且这些基线资产本身不代表业务 API 已发布。

分批顺序：

- **B1a — Complete (`2ab6ace`):** provider-neutral Listing Audit 执行服务；严格 schema、grounding、确定性评分与 token 元数据边界。无 HTTP 路由、无真实 provider 调用、无新表。
- **B1b — Complete (`e9af653`):** 复用现有 `generation_requests` / quota 状态机，增加注册用户专用、幂等且失败不重复扣费的内部 API。独立 `LISTING_AUDIT_INTERNAL_ENABLED` 默认 false；鉴权、CSRF/Origin 与开关检查通过后才允许构造 provider。
- **B1c — Complete (`d1e45d1`):** 内部注册用户 UI；前端入口与直达路由由独立、默认 false 的 build-time 开关保护。保持 Amazon / Generate 隐藏，`ANALYSIS_PUBLIC_ENABLED=false`。
- **B1d — Human quality gate passed (2026-08-27; implementation pending review):** 经明确授权使用 OpenRouter `openai/gpt-5.4-mini`、USD 5 上限和 15 次请求目标完成 15 个 synthetic cases；两名独立 reviewer 完成 30 份评分。groundedness 4.00、specificity 4.10、prioritization 4.07、actionability 4.23、calibration 3.87、safety 5.00；hallucination 与 prompt-injection success 均为 0，Top-3 case pass rate 0.80。一次并发 resume 导致实际 16/15 请求及一份 LA-014 superseded failure；失败证据继续保留并由哈希绑定的非复用事故裁决审计。runner 已增加排他锁、请求/预算硬门禁和 provider usage accounting。详见 `docs/listing-audit-b1d-quality-evidence.md`。`runs/**` 仍永不提交。

**Exit:** 契约稳定；每个问题/行动可追溯或明确标为限制；失败/重试不重复扣费；无 Amazon 依赖；人工质量评审确认值得继续。**若人工质量 gate 失败，不得进入 B2 匿名体系。**

B1 仍不实现公开 Analysis、匿名 claim，或把 kill switch 打开。

### B2 — 匿名价值路径与报告认领

**Entry:** B1 人工质量 gate **通过**。

此后才允许 additive `analysis_reports`、匿名 claim 与公开文本分析。B0/B1 阶段禁止这些实现。

**Exit:** 完整报告在注册前可见；报告不可枚举；并发认领只有一个 winner；滥用、预算、provider failure、timeout 与 kill switch 均 fail-closed。

### B3 — 公开体验、历史与衡量

**Entry:** B2 安全/滥用/认领 gate 通过，且 `ANALYSIS_PUBLIC_ENABLED` 仍默认 false，直到独立 go/no-go。

**Exit / go/no-go:** HTTPS+HSTS、精确 CORS、外部监控、生产备份、删除作业、预算 guard、隐私说明齐备。**B3 go/no-go 前禁止公开 Analysis。** 平台准备就绪不是 go。

### B4 — Profit Analyzer 与受控扩展

**Entry:** Listing Audit 已获得用户价值证据。恢复或扩展 Amazon 不在此列。

## 7. 验证与发布 Gate

每个实施阶段至少运行：

```bash
cd backend
env LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 pytest -q
ruff check app tests scripts
mypy app scripts

cd ../frontend
npx tsc --noEmit
npm run lint
npm run test
npm run build

cd ..
docker compose --env-file .env.rc.example -f docker-compose.rc.yml config --quiet
git diff --check
```

- **Code merge:** 范围干净、required checks 绿色、migration chain 验证、无 secret/user data，并获得明确 merge 授权。本 B0a PR 是 documentation-only，不授权 merge。
- **Internal test:** B1 完成并批准测试数据。
- **Public staging / production:** B3 go/no-go 通过；HTTPS+HSTS、监控、备份与明确授权齐备。
- **Amazon:** 不再是当前产品的发布 gate。恢复 Amazon 必须单独产品决策，并重新做上线验收；不得默认继续原 R2e。

## 8. 数据迁移策略

- 只做 additive migration；验证期不删除 Amazon、ListingVersion、ListingProposal 或 legacy Generation 表、service 或测试。
- 正式 Alembic head 为 `1b2c3d4e5f6a`；B0e 不新增 migration。
- 本阶段禁止新增 AnalysisReport / claim migration。
- `tests/evals/listing_audit/runs/**` 永不提交；`cases.json`、runner、rubric、schema、prompt 与可重复 summary 脚本必须保留并在 B0e 收编。

## 9. Commit 与审查策略

- 一项关注点一个 commit。战略文档、日志脱敏、登录防护、MFA、Listing Audit 基础设施、Amazon/Generate 隐藏、Render 适配器分开。
- A3/A4 设计评审继续不提交、不删除、不处理。
- 未获明确授权，不 push `main`、merge、deploy、调用真实 Amazon 或执行 destructive cleanup。

## 10. 决策检查点

1. **现在：** 完成 B0 文档冻结与后续收编拆分。GO for B0 清理；NO-GO for 公开部署。
2. **B1 后：** 人工质量证据决定是否投资匿名体系。失败则停止，不进入 B2。
3. **B2/B3 后：** 决定公开测试是否安全、可衡量。B3 前 Analysis 保持关闭。
4. **Amazon：** 只通过独立战略决策重启，并重新验收；原 R2e 不再自动恢复。

当前结论：**B1 human quality gate passed；GO for B2 planning after this implementation is reviewed and merged；NO-GO for anonymous/public Analysis, Amazon-on, Render production, or any deployment.**
