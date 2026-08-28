# AI 自动化后续规划（双仓）

> 依据：2026-07-30 GitHub 热门 AI 自动化调研评审 + 双仓现状审计  
> 相关：[TOKEN_BUDGET.md](./TOKEN_BUDGET.md) · [DUAL_REPO_CONTRACT.md](./DUAL_REPO_CONTRACT.md) · [API_TESTING_PLAN.md](./API_TESTING_PLAN.md)  
> Platform 镜像：`Autopilot-Platform/docs/architecture/AI_AUTOMATION_ROADMAP.md`（摘要指针，权威在本文）  
> 修订：2026-08-06（三链路定型）

---

## 0. 三链路定型（产品主叙事）

| 链路 | 职责 | 状态 |
|------|------|------|
| **1 · 传统** | IDE 关键字 + Platform Job，无 AI；定名见 [KEYWORD_DRIVEN_MODEL.md](./KEYWORD_DRIVEN_MODEL.md)（元数据驱动的可视化 KDT） | **默认可交付** |
| **2 · 设计 AI** | Platform：NL/文档 → 常规用例 + 人审；不承诺可执行 | 独立测设；Webhook/入队为高级可选 |
| **3 · AI 辅助编写** | IDE：采页 + NL → REGISTRY 关键字 → 传统 `.tc` → 试跑 | **增强建设中**（`autopilot/authoring/`） |

```text
传统自动化负责稳定执行（链路 1）
链路 2 负责测设资产，不假装自动化
链路 3 加速写自动化，生成物回归链路 1
```

| 侧 | 职责 |
|----|------|
| **Platform** | 链路 2 设计域；Job/设备/报告；**持有厂商 AI Key**；链路 3 LLM 网关（`/ops/ai/codegen`） |
| **AutoPilot IDE** | 链路 1 编排真源；链路 3 采页 + 经登录态调网关；Binding / Inspector |
| **Runner + `ap/`** | 确定性关键字执行 + 有限 Intent 自愈/Vision（兼容资产） |

**密钥边界：** 企业部署锁定 Platform URL 后，链路 3 默认 `platform` 模式——IDE **不持** `AP_AI_*`；本机 Key 仅单机开发逃生口。

**链路 3 会话与门禁：** 会话驱动编写复用检视器已建立的会话（平台/设备一致时不重建 driver），自动完成选设备、解析包名、Android 启动 Activity 与 iOS Appium caps；单步失败只回退重规划，连续 3 次失败熔断。逐步执行成功的草稿记为已验证并允许上传批跑，仅规划草稿必须本地 F5；门禁结论写 `authored/_authoring.json`，上传工程时据此拦截。编写结束（成功/失败/关窗）按「自建关 driver、复用只软清理」回收资源，不把临时会话挂到检视器。配置见 [CONFIGURATION.md](../CONFIGURATION.md)。

**明确不做（延续边界）：**

- Platform 下发 xpath/定位器  
- 无 IDE / 无 Binding 的无人值守全 AI 批跑（除非另立「云端 Binding 仓」产品）  
- 默认开启 Vision  
- 用 MCP/多 Agent 聊天框架替换内部关键字协议  
- 用纯视觉 Computer Use 替代结构化 UI 树  
- 把链路 2 APPROVED 当作「生成即可云跑」  
- 把厂商 AI Key 写入 IDE `settings.json` 或工程仓

---

## 1. 目标架构（6–12 个月愿景）

```text
自然语言 / 需求
        │
        ▼
┌───────────────────┐
│ Planner（Platform）│  生成 logical_case / intent_steps / 质量分
└─────────┬─────────┘
          │ APPROVED
          ▼
┌───────────────────┐
│ Workflow Engine   │  Job 状态机 →（远期）轻量跨通道 DAG
│ + Policy Gate     │  风险等级、人工审批票、Token 配额
└─────────┬─────────┘
          │
    ┌─────┼─────┐
    ▼     ▼     ▼
 Android  iOS   Web/API Executor   ← 关键字 / Appium / WDA / Selenium(/PW) / httpx
    └─────┼─────┘
          ▼
┌───────────────────┐
│ Verifier（独立）   │  UI/HTTP/日志/埋点断言 + 规则；LLM 仅摘要不过判
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Report & AgentOps │  result.v1 trace、成本、回放索引、automation_status
└───────────────────┘
```

与调研「五层模型」映射：

| 调研层 | 落点 |
|--------|------|
| 确定性执行层 | 现有关键字 + engine（已具备） |
| 统一工具协议层 | keyword REGISTRY；MCP 仅作可选对外适配（低优） |
| AI 感知与自愈层 | intent resolve/heal/vision（增强 trace/验证挂钩） |
| 测试规划 Agent | Platform 设计 LLM（强化质量门禁，不开放式 ReAct） |
| 独立验证与治理 | **本规划重点新建/加厚** |

---

## 2. 分期总览

| 阶段 | 周期（建议） | 主题 | 成功标准 |
|------|--------------|------|----------|
| **A · 夯实混合闭环** | 2–4 周 | 验证点 + Intent Trace + 现有 P1 收尾 | Intent PASS 必须带验证证据；Platform 能看 warnings/成本 |
| **B · 验证与治理** | 4–8 周 | Verifier 产品化 + 风险策略 + Token 硬配额 | PENDING_VERIFY→EXECUTABLE 有正式签批；高风险关键字可拦 |
| **C · API First 通道** | 6–10 周 | Intent→HTTP / channel=auto + OpenAPI 导入评估 | 核心业务流可「API 主、GUI 辅」 |
| **D · 可观测与固化** | 与 B/C 并行后半 | AgentOps 看板 + Binding 降级为确定性步骤 | heal/Vision 率可度量；EXECUTABLE 可一键去 Intent 化 |
| **E · 可选增强** | 按需 | Playwright backend、轻量跨通道 DAG、MCP 只读适配 | 不破坏双仓契约与 Binding 边界 |

依赖关系：

```text
A（Trace + 验证挂钩）
 └─► B（Verifier + Policy）
      ├─► C（Intent→HTTP，需契约）
      └─► D（看板依赖 Trace schema）
           └─► E（可选）
```

---

## 3. 阶段 A — 夯实混合闭环（立即）

> **状态（2026-07-30）：A1 / A2 / O6 / O7 / O8 / O9 / O10 已落地**。

**主题：** 不改产品边界，把「能跑」变成「可证明、可看见」。

### A1. Intent 成功 = 动作 + 验证点（AutoPilot）

| 项 | 说明 |
|----|------|
| **做什么** | `intent_act` 命中并执行关键字后，支持/要求关联验证：同步 UI assert、或步骤级 `expect` 元数据；缺验证的 Intent 在报告中标 `unverified_action` |
| **契约** | 扩展 `result.v1`：`verification_status` = `passed` / `failed` / `skipped` / `missing` |
| **不做** | 不引入第二套 LLM 裁判 |

### A2. 步骤级 Intent Trace（双仓同构）

写入 `result.v1` / StepResult meta：

- 感知摘要（平台、元素数、是否截图）  
- 候选数、选用 strategy（cache / heuristic / heal / vision）  
- `binding_hit` / `heal_applied` / `fail_reason`（已有则对齐规范化）  
- Vision：latency_ms、usage tokens（若有）  
- 验证证据引用（截图路径、断言 id）  

门禁：`tools/check_dual_repo_contract.py` + schema 双仓同步。

### A3. 收尾现有 P1（低成本）

双链路 P0/P1（enqueue 警告、`intent_readiness`、Verifier、`vision-doctor` 等）已于 2026-07 落地。当时清单：

| ID | 项 | 仓 |
|----|-----|-----|
| O6 | 设计 AI degraded 运维汇总 | Platform |
| O7 | Web Console 展示 enqueue `warnings` | Platform |
| O8 | Webhook `--sync-status` 说明强化 | IDE |
| O9 | heal_attr 识别「像 HTTP」意图（仍不执行） | IDE → 为 C 铺路 |
| O10 | `vision-doctor` 连通性体检 | IDE |

### A4. 验收

- 含 Intent 的套件 `result.json` 可被 schema 校验且含 trace  
- Platform Job 详情能展示至少：binding 警告、intent fail_reason、token 汇总入口  
- 回归：`pytest` intent / result_json / dual_repo / enqueue 相关全绿  

---

## 4. 阶段 B — 独立验证与执行治理

> **状态（2026-07-31）：B1 / B2 深化 / B3(T7) 已落地**。

**主题：** Planner ≠ Verifier；Prompt 不等于安全。

### B1. Verifier 产品化（Platform 为主）

| 状态流 | 含义 |
|--------|------|
| `APPROVED` | 人审/半自动通过设计质量 |
| `PENDING_VERIFY` | 已入队或已有制品，等待首跑+验证证据 |
| `EXECUTABLE` / `BINDING_PARTIAL` | 仅当 result 中 verification 达标且 Binding 覆盖满足 |

规则引擎优先：

1. 用例声明的断言步骤全 PASS  
2. `automation_status_evidence` 完整  
3. 可选：禁止 `verification_status=missing` 的 Intent 步骤晋升 EXECUTABLE  

LLM 仅用于失败摘要（可选），**不参与 PASS/FAIL 终裁**。

### B2. Keyword 风险分级（AutoPilot → 契约 → Runner）— **深化 done（2026-07-31）**

| risk_level | 示例 | 默认策略 |
|------------|------|----------|
| `read` | 截图、get_text、HTTP GET | 自动允许 |
| `write` | click、input、HTTP POST（测试环境） | 允许；审计日志 |
| `irreversible` | 删除、真支付、发正式邮件、清用户数据 | 默认拒绝或需 Platform 审批票 |

已落地：

- XML `risk_level` + `KeywordDef.risk_level`；`risk.py` 优先读表，硬编码 fallback  
- resolve/Vision 候选经 `filter_safe_candidates` 过滤 irreversible  
- `AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE=1` 调试放行  

仍延后：Platform 审批票 UI / Job 策略下发；与 Design Chat 的设计侧 `risk_level`（high/medium）勿混淆。

### B3. Token 组织级硬配额（Platform T7）

承接 [TOKEN_BUDGET.md](./TOKEN_BUDGET.md) T7：

- 组织/项目日配额  
- 设计 Chat 与（若上报）Vision usage 分账视图  
- `ENFORCE` 可按组织开关  

### B4. 验收

- 无验证证据的用例不能标 EXECUTABLE（可配置严格度）  
- irreversible 关键字在策略开启时被拦截并有审计  
- 配额超限时设计生成可阻断  

---

## 5. 阶段 C — API First，GUI Last

> **状态（2026-07-31）：C1 已落地**；**C2 深化**（确定性 HTTP + 可选 Intent 混合壳；脚本引擎仍不做）。

**主题：** 把调研趋势二落成测试通道，而不是另做 RPA。

### C1. Intent → HTTP（原 O11）— **done**

| 项 | 说明 |
|----|------|
| **契约** | `intent_act.channel`: `ui` \| `http` \| `auto`（默认 `ui`）；`logical_import` 透传 |
| **resolve** | `_http_candidates` → `http_*`；`auto`：HTTP Binding 或 `looks_like_http_intent` → http |
| **Binding** | `channel/method/path/assert/follow_ups`，仍存 IDE `bindings/*.json` |
| **风险** | `http_delete` 仍受 B2 irreversible 门禁 |
| **测试** | `tests/test_intent_http_channel.py` + `tests/fixtures/intent_http/` |

### C2. OpenAPI / Postman → `.tc.yaml`（原 O14）— **深化（脚本引擎仍不做）**

- **已做**：`openapi_import.py` — OpenAPI 3.x / Postman v2.1 → 确定性 HTTP `.tc.yaml`  
- CLI：`python -m autopilot.mgmt openapi-import --spec … --project …`  
- **新增**：`--with-intent-shell` 在 HTTP 步前插入 `intent_act(channel=http)` 并写 Binding 占位  
- **仍不做**：Postman 脚本引擎、双向同步、完整 body/schema 断言导入  
- 见 [API_TESTING_PLAN.md](./API_TESTING_PLAN.md) C6/P3

### C3. 验收

- 至少 1 条业务主路径：登录/下单/查询类以 HTTP 为主、UI 仅做关键验收  
- 同逻辑用例在缺 UI Binding 时仍可部分 EXECUTABLE（HTTP 段）  

---

## 6. 阶段 D — AgentOps 与「生成后固化」

> **状态（2026-07-31）：D1 / D2 深化 / D3 证据预览已落地**。

### D1. Platform AgentOps 看板 — **done**

- `GET /api/v1/ops/agentops`：扫近期 `result.json` Intent Trace + `ai_usage` 日摘要  
- Dashboard `AgentOpsCard`：cache/heal/Vision 率、步均耗时、fail_reason Top  
- 实现：`platform/services/agentops.py`

### D2. Binding / Intent 降级为确定性步骤（IDE）— **深化 done**

- 单步：`solidify_intent_step` + CLI `--logical-case-id/--intent-id`  
- Binding `success_streak`（成功累加，heal/失败清零）  
- 批量：`solidify --stable-min N` / IDE「固化稳定意图步…」  
- remark `solidified:intent:{id}`  

### D3. 失败回放索引 — **深化 done（可预览）**

- FAIL 落盘 `reports/evidence/...`；Runner 打包 `evidence.zip` 上传  
- Platform：`GET /jobs/{id}/evidence/{path}` + ReportsPanel 截图嵌图  
- `attachments[]` 字段：`case`（兼 `case_name` 兼容）  

---

## 7. 阶段 E — 可选增强（按需，不挡主线）

> **状态（2026-07-31）：E1 深化 / E2 / E3 只读适配已落地**。

| 项 | 状态 | 备注 |
|----|------|------|
| E1 Playwright 可选 Web backend | **深化 done** | **Selenium 主力**；PW：截图/DOM/cookie/元素 + P0 Select/右键/双击/悬停/拖拽/组合键 + P1 偏移滑块 + AND/OR Locator/scrollMode；IDE/Job `web_engine` 二选一；`tests/test_web_live.py` 双引擎 parametrized live（~82）；Selenium/PW 未找到与非 iframe 切换统一 `KeywordError`；未映射能力仍 `require_selenium_feature` |
| E2 轻量 Job `depends_on` | **done** | `JobCreate.depends_on`；claim 门禁；前置失败/取消级联 fail；**非** CrewAI 多 Agent |
| E3 MCP 只读工具适配 | **done** | `python -m autopilot_platform.platform.mcp_readonly`（list/get job、devices、report）；执行仍走 Job+关键字 |
| 专用 GUI Grounding 模型 | 低优 | 等 Vision 命中率瓶颈数据说话再引入 |
| 跨 Runner 设备分片 | 低优 | 现有同 Runner 多设备已够用一段时间 |

---

## 8. 双仓工作分工

| 工作包 | AutoPilot IDE | Platform | 同构 `ap/` |
|--------|---------------|----------|------------|
| Intent Trace / result.v1 | 写 | 索引展示 | 必须同步 |
| 验证点挂钩 | 写 | Verifier 状态机 | runtime 同步 |
| risk_level | 元数据+执行拦截 | 策略下发/审批票 | 同步执行拦截 |
| Intent→HTTP | resolve/runtime/binding | schema/导出/enqueue | 同步 |
| AgentOps 看板 | usage 上报 | 看板+聚合 | — |
| 固化步骤 | IDE UX | 可选标记 automation 模式 | — |
| O6/O7/T7 | — | 主做 | — |
| O8/O9/O10 | 主做 | 文档镜像 | 视同构范围 |

每次改同构面：先改一侧 → 同步另一侧 → `check_dual_repo_contract.py`。

---

## 9. 与现有 backlog 对照

| 原 ID | 原状态 | 本规划归入 |
|-------|--------|------------|
| O6–O10 | P1 未做 | **阶段 A** |
| O11 Intent→HTTP | P2 缓做 | **阶段 C1 done（2026-07-31）** |
| O12 无 IDE AI 批跑 | 不做 | **仍不做** |
| O13 Platform 重型编辑器 | 不做 | **仍不做** |
| O14 OpenAPI 导入 | deferred | **阶段 C2 partial（确定性 HTTP）** |
| T7 组织配额 | P2 | **阶段 B** |
| 新 | — | A1 验证点、A2 Trace、B1 Verifier、B2 risk、D1–D3、E1–E3（2026-07-31） |

---

## 10. 建议执行顺序（第一个月）

1. **A2 Trace schema**（双仓）— 后续一切可观测的地基  
2. **A1 验证挂钩（最小版）** — Intent 缺验证打标，暂不强制失败  
3. **O7 + O9** — Console 警告可见；HTTP 意图可归因  
4. **B1 规则：PENDING_VERIFY 晋升条件** — 与 A1 字段打通  
5. **B2 risk_level 读表 + Vision 白名单** — 安全底线  
6. 并行：**O6/O8/O10** 运维体验  

第二个季度重心：**B3 Token 配额 → C1 Intent→HTTP → D1 看板 → D2 固化**。

---

## 11. 风险与约束

| 风险 | 缓解 |
|------|------|
| Trace 字段膨胀导致 result.json 过大 | 摘要化；大 DOM 只存路径/hash |
| Verifier 过严阻断交付 | 组织级 `verification_strictness`: soft/hard |
| Intent→HTTP 契约破坏旧用例 | `channel` 默认 `ui`，旧行为不变 |
| 双仓同步漂移 | 门禁 + RUNTIME_PIN；改 schema 必须双仓同 PR 节奏 |
| 范围膨胀成通用 Agent 平台 | 阶段 E 严格按需；主线始终服务「可回归测试」 |

---

## 12. 一句话里程碑

> **Q 近：** 可证明的混合执行（Trace + 验证 + 警告可见）  
> **Q 中：** 可治理的执行（Verifier + 风险策略 + 配额）  
> **Q 远：** 更便宜的正确路径（API First + 固化脚本 + AgentOps）  

AI 始终是规划/适配/自愈层；Selenium/Appium/WDA/httpx 仍是可靠执行基础设施。
