# SellerAI Copilot 战略调整迁移计划 v0.1

日期：2026-08-24
状态：B0a 战略冻结合同；不授权删除、部署、外部调用、启用 Amazon、公开 Analysis 或实现新业务 API
正式代码基线：已合并的 `origin/main@e71522d`（`e71522dfa72516056f24ee351d2ba17e7f46caa8`）
脏工作区：仅作为待收编资产来源，**不是** source of truth

## 1. 为什么从 Amazon-first 转到 Listing Audit

`main@e71522d` 已经具备可复用的认证、会话、配额、幂等、Generation 执行内核，以及完整的 Amazon OAuth / 账户 / 市场 / 同步 / Catalog 基础设施。Amazon 能力在工程上已经完成并完整保留。

它不再适合作为当前发布主线，原因不是“Amazon 没做完”，而是产品验证顺序变了：

1. 公开测试仍被 HTTPS/DNS/HSTS、外部监控和生产备份门禁挡住。用户已准备平台账号或域名，不等于已经部署或验证上线。
2. 继续 Amazon-first 会把容量绑在 Seller Central、真实卖家验收和原 R2e 上。这些不再是当前发布门禁。
3. 当前要验证的是卖家是否重视更好的 Listing 决策，而不是 SellerAI 能否执行 Amazon 操作或生产更多内容。
4. Listing Audit 可以先用文本输入证明价值，不必先打开 Amazon OAuth 或内容生成器。

因此：接受 Listing Audit 为当前主线；Amazon 完整保留为未来增强能力；默认关闭、入口隐藏（B0f，尚未实现）；暂停 A4+ 与原 R2e。恢复 Amazon 必须单独产品决策，并重新做上线验收。

## 2. 正式基线，而不是脏树或旧 PR 标签

| 项 | 合同 |
| --- | --- |
| 代码基线 | 已合并 `main@e71522d`。PR #1 已 fast-forward 合入 `main`，不是 Draft，也不再作为 baseline 标签 |
| 测试证据 | R3d：backend **1591 passed**；frontend Vitest **112**；ESLint **0/0**；Quality Gate [32489619995](https://github.com/biforch/seller-ai-copilot/actions/runs/32489619995) main push success |
| Alembic | 正式 head 仍为 `a0b1c2d3e4f6` |
| MFA | **尚未进入 main**，不能写成已完成 |
| Render | 适配器仍在 Draft [PR #3](https://github.com/biforch/seller-ai-copilot/pull/3)，未合并、未部署。R4d 指出的 backend `PORT` 与供应链扫描问题尚待修复。脏树 Render 文件是旧副本，禁止再提交 |
| Listing Audit | Sprint 0.5 schema / prompt / eval 资产只存在于冻结脏工作区，尚未提交。Listing Audit API **未实现** |
| Analysis 公开开关 | `ANALYSIS_PUBLIC_ENABLED=false` 是 **B0f 待实现合同**，main 上不存在该配置 |
| 公开 Analysis | B3 go/no-go 前禁止 |
| 本阶段禁止 | 实现 AnalysisReport、匿名 claim、新业务 API，或新增相关 migration |

## 3. Amazon 资产的保留 / 冻结原则

暂停表示：保留代码和迁移历史、保持 feature flag 关闭、不新增能力、不从主导航暴露。

**禁止删除** 历史表、Alembic migration、service、API 或测试。战略验证期间不做不可逆清理。

### 3.1 已在 main 完成并冻结

- `backend/app/integrations/amazon/` 及账户 / OAuth / marketplace / listing / catalog / sync 模型与服务。
- `api/amazon_oauth.py`、`amazon_accounts.py`、`amazon_marketplaces.py`、`amazon_listings.py` 及其测试。
- 前端 `/amazon`、OAuth success/error 页面和 `frontend/app/api/amazon.ts`。
- 默认值已 fail-closed：`AMAZON_SP_API_ENABLED=false`、`AMAZON_OAUTH_ENABLED=false`、`AMAZON_SP_API_ENDPOINT_MODE=mock`。

B0f 将同时隐藏 Amazon 与旧 Generate 入口，并保持服务端 fail-closed；**不删除实现**。该隐藏工作尚未落地，前端 Header / Dashboard 入口今天仍然可见。

不再执行原 R2e，除非未来独立战略决策恢复 Amazon。真实 Amazon 不再是当前发布门禁。

### 3.2 旧 generation 同样冻结

- `/generate` Listing / keywords 生成、proposal / diff / 审核收件箱。
- Amazon Catalog → AI Context。
- 这些实现保留，B0f 隐藏入口，不删除。

## 4. 可复用底座 vs 未提交资产

### 4.1 可从 main@e71522d 复用

- Cookie-only 会话、CSRF、限流、租户隔离、R3d session 隔离。
- Generation 状态机、幂等、配额、Product 存储。
- 当前 provider 合同：默认 OpenRouter（`OPENAI_BASE_URL=https://openrouter.ai/api/v1`）。默认 URL 变化与 `store=false` 等 AI 安全合同以后单独审查，不混入 MFA 或 Listing Audit 基础设施。

### 4.2 脏工作区待收编（不是已发布能力）

- 登录滥用防护、强制 MFA、日志脱敏。
- Sprint 0.5：schema、prompt 版本、15 个 synthetic cases、evaluation runner、summary、人工评分基础设施。`runs/**` 永不提交；`cases.json` / runner / rubric / schema / prompt / 可重复 summary 脚本必须保留。
- A3/A4 文档继续不提交、不删除、不处理。
- `docs/security/evidence/**` 等证据在对应代码落地后再提交，禁止提前声称完成。

## 5. 目标领域（未来，不是当前实现范围）

独立 `analysis` 包是方向，但 **B0 不实现** API、report 表或 claim。

建议的远期结构仅作地图，不构成本 PR 的工作授权：

```text
backend/app/analysis/          # Sprint 0.5 契约目前只在脏工作区
backend/app/api/analysis.py    # 禁止在 B0 新增
backend/app/models/analysis_report.py  # 禁止在 B0 新增
```

远期公开路径（B2 以后，且 B3 go 之前默认关闭）才考虑：

```text
POST /api/v1/analysis/listing-audits
GET  /api/v1/analysis/reports/{report_id}
POST /api/v1/analysis/reports/{report_id}/claim
```

B0/B1 不得实现这些端点。旧 `/generate/analyze` 仍是登录后 generation，不是公开 Listing Audit。

## 6. B0 → B1 → B2 → B3 gates

较晚阶段不得绕过较早的阻塞 gate。

### B0 基线拆分与战略冻结

**Status:** In progress

**Entry**

- 正式基线是 `main@e71522d`。
- 脏工作区已盘点；Render 只走 PR #3。

**本阶段做**

- 提交战略冻结文档（B0a，本文件）。
- 后续独立收编：日志脱敏（B0b）；同一 PR 内先登录防护再 MFA（B0c → B0d）；Listing Audit 基础设施（B0e，不含 runs）；隐藏 Amazon/Generate 并增加 `ANALYSIS_PUBLIC_ENABLED=false`（B0f）。

**Exit**

- 文档与后续收编可独立审查。
- Amazon / Generate 入口隐藏且服务端 fail-closed（B0f 完成后）。
- 必需测试绿色。
- **未部署。**

**Rollback / 停止条件**

- 发现不可拆分的 secret 或 provenance 问题：停止收编，不把脏树整包提交。

### B1 内部 Listing Audit 垂直切片

**Status:** 尚未进入已提交基线

**Entry**

- B0 冻结合同成立。
- 只服务注册测试用户。

**Exit**

- 契约稳定；证据可追溯；无 Amazon 依赖；人工质量评审通过。

**Rollback**

- **若 Listing Audit 人工质量 gate 失败，不得继续匿名体系，不得进入 B2。**

B1 仍禁止公开 Analysis、匿名 claim 和新的 AnalysisReport migration，除非后续单独授权且质量 gate 已通过。默认顺序是：先内部切片，再考虑匿名。

### B2 匿名价值路径与报告认领

**Entry:** B1 人工质量 gate 通过。

**Exit:** 匿名报告不可枚举；claim 单次、原子；滥用/预算/kill switch fail-closed。

**Rollback:** 任何 claim、日志泄漏 Listing 原文、或预算失控，立即保持 `ANALYSIS_PUBLIC_ENABLED=false` 并停止公开路径。

### B3 公开体验与 go/no-go

**Entry:** B2 完成；kill switch 仍默认关闭。

**Exit / go:** HTTPS/DNS/HSTS、外部监控、生产备份、隐私说明与明确授权。B3 go/no-go 前禁止公开 Analysis。

**不是 go 的信号：** 用户已准备平台、Draft Render PR 存在、或脏工作区里已有 schema。

## 7. 数据与删除禁令

- 不删除任何 Amazon、Listing Version、Proposal、Generation 表或对应测试。
- 新表只能 additive，且本阶段不新增 AnalysisReport。
- 正式 Alembic head 保持 `a0b1c2d3e4f6`，直到独立 MFA commit 被审查合并。
- eval `runs/**` 加入 gitignore 并永不提交。

## 8. 关键风险

1. 把脏工作区当成 source of truth，导致 MFA、Render、eval 输出和战略文档混提交。
2. 把 `ANALYSIS_PUBLIC_ENABLED` 或 Listing Audit API 写成已经存在。
3. 把 Draft PR #3 或平台准备写成已部署。
4. 过早实现匿名 claim，绕过 B1 质量 gate。
5. 误删 Amazon 历史实现，失去未来增强能力。
6. 继续执行原 R2e，把真实 Amazon 重新变成当前发布门禁。

## 9. 恢复 Amazon 的条件

恢复 Amazon 不是 B0–B3 的默认下一步。必须同时满足：

1. 独立产品决策，明确 Amazon 再次成为发布范围；
2. 重新上线验收（安全、日志、OAuth 回调、LOG-02、Seller Central / 受控卖家验收按当时合同重开）；
3. 不得静默打开 flag，也不得从脏树或过期 Render 副本启用。

在此之前：Amazon 保留、冻结、默认关闭。

## 10. 当前结论

迁移计划状态：**GO for B0 文档冻结与后续隔离收编；NO-GO for 公开 Analysis、Amazon-on、Render 生产或任何部署。**

NO-GO 原因包括：Listing Audit 尚未进入 main；公开开关未实现；MFA 未进入 main；Render adapter 仍为 Draft 且 R4d 问题未修；HTTPS/DNS/HSTS、外部监控和生产备份仍是公开测试门禁；脏工作区不是可发布基线。
