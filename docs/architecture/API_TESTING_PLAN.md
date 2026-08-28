# 接口测试能力 · 组件化方案

> **目标**：在现有关键字驱动模型上补齐 API 自动化能力，覆盖 IDE 编写与 Platform 执行。  
> **原则**：不另起 Postman 产品壳；Platform 不实现第二套 HTTP 引擎。  
> **可视化**：见 Cursor Canvas `api-testing-capability-plan.canvas.tsx`。  
> **修订**：2026-07-28

---

## 0. 现状结论

| 层 | 现状 |
|----|------|
| 关键字 | `http_get/post/put/delete` + header/cookie + JsonPath/XML + Mock（`autopilot/keywords/http/`） |
| 引擎 | `Executor` + `ExecutionContext`；断言=关键字步骤，无独立 assertions 字段 |
| IDE | `metadata/keyword_defs/http.xml` + ParamForm |
| Platform | Runner → `run_project_directory` → 同源 `REGISTRY`；无独立 API 路径 |

主要缺口（相对完整 API 产品）：~~Session / Auth / 断言 / 环境~~（P0–P2 已补）；OpenAPI/Postman 导入（**缓做**）。

---

## 1. 六组件边界

| ID | 组件 | 职责 | 非职责 | 状态 |
|----|------|------|--------|------|
| C1 | **HttpSession** | 用例级 `httpx.Client`、cookie jar、默认 header、base_url、proxy、timeout | 浏览器 Cookie、与 Selenium 混会话 | **done** |
| C2 | **HttpClient** | PATCH/HEAD/OPTIONS；请求统一走 Session；proxy/cookie 生效 | GraphQL/gRPC/WebSocket 一等公民 | **done** |
| C3 | **AuthHelpers** | Basic / Bearer / API-Key | 完整 IdP、交互式 OAuth | **done** |
| C4 | **ApiAssert** | 状态码范围、耗时 SLA、body、JSON Schema | 嵌入 JS/Python 脚本引擎 | **done** |
| C5 | **ApiEnv** | 多环境 profile（`api_env.yaml`） | 云端密钥保险库 | **done** |
| C6 | **ImportBridge** | OpenAPI / Postman → `.tc.yaml` | 双向同步、完整 Postman 脚本 | **partial（2026-07-31）**：确定性 HTTP 导入已做；脚本/双向同步仍不做 |

---

## 2. 双仓契约

| 组件 | AutoPilot（真源） | Platform | 契约口 |
|------|------------------|----------|--------|
| C1–C5 | 实现 + `http.xml` + 单测 | `ap/keywords/http` 须与 IDE 字节一致 | `tools/check_dual_repo_contract.py` 含 Http 同步检查；边界见 [DUAL_REPO_CONTRACT.md](./DUAL_REPO_CONTRACT.md) |
| C6 | `mgmt/openapi_import.py` | 可选同步 `ap/mgmt` | CLI / 单测 |
| 执行 | 本地 Executor | Runner；无设备 Job 取决于 `require_job_devices` | 无需为本能力改协议 |
| 报告 | 步骤级结果；`ctx.last_http` 供断言 | `api_calls[]` **未做**（可选后置） | 不阻塞关键字增强 |

---

## 3. 增量关键字契约

| keyword_id | 组件 | 行为要点 |
|------------|------|----------|
| `http_session_begin` / `end` | C1 | 绑定/关闭 `ctx.http_session` |
| `http_patch` / `head` / `options` | C2 | OUT 与 get/post 一致 |
| `http_set_auth_basic` / `bearer` / `apikey` | C3 | 写入 Session 或变量 |
| `http_assert_status` / `time_lt` / `body_contains` | C4 | 默认读 `ctx.last_http` |
| `json_assert_schema` | C4 | 需 `jsonschema` |
| `api_env_use` | C5 | 注入变量；可同步 Session `base_url` |

旧 `http_get/post/...` **保留**；有 Session 则复用，无则短生命周期 Client。

---

## 4. 开源借鉴（底层）

| 项目 | 借鉴 | 不借 |
|------|------|------|
| encode/httpx | Client、Auth、Timeout、Proxy | 强制全异步 |
| Karate / REST Assured | 断言分层思路 | 另起 DSL |
| Tavern | YAML 步骤=请求+期望 | 另起 YAML 语法 |
| Postman Collection / Schemathesis | （C6 缓做时再参考） | Newman / 全量 fuzz |

---

## 5. 分期验收

| 期 | 内容 | 验收 | 状态 |
|----|------|------|------|
| **P0** | Session + cookie/proxy + PATCH/HEAD/OPTIONS | `tests/test_http_session.py`；双仓同步 | **done** |
| **P1** | Auth + status/time/schema/body 断言 | 同测 + `jsonschema` | **done** |
| **P2** | `api_env.yaml` + `api_env_use` | 同测 Env 用例 | **done** |
| **P3** | OpenAPI/Postman → `.tc.yaml` | `tests/test_openapi_import.py`；`python -m autopilot.mgmt openapi-import` | **done**（确定性 HTTP + `--with-intent-shell`；Postman 脚本引擎仍缓做） |
| **收尾** | 核实矩阵 + dual-repo Http 同步检查 | 矩阵已增行；门禁含 `http.xml` / `openapi_import.py` | **done** |

### 本轮已落地文件（AutoPilot 真源）

- `autopilot/keywords/http/session.py` / `auth.py` / `assert_kw.py` / `env.py`
- `autopilot/keywords/http/client.py`（Session 感知）
- `autopilot/metadata/keyword_defs/http.xml`
- `tests/test_http_session.py`、`tests/fixtures/api_env.example.yaml`
- Platform：`autopilot_platform/ap/keywords/http/*` + `context.py` + `teardown.py` + `http.xml`
- `docs/keyword-verification-matrix.md`（增量行）
- `tools/check_dual_repo_contract.py`（Http 文件一致性）

### 明确不做 / 缓做

- 独立 API IDE；用例内嵌 JS；Platform 第二套引擎；gRPC/GraphQL 一等；AI 直接吐 keyword  
- **P3 导入桥**完整 Postman 脚本 / 双向同步 — 仍缓做；**确定性 HTTP 导入已落地**（`openapi_import`）
- `result.json` 的 `api_calls[]` — 可选后置，不阻塞

---

## 6. 使用提示

```text
http_session_begin   base_url=${base_url}
api_env_use          profile=dev          # 或先切环境再 begin
http_set_auth_bearer token=${api_token}
http_get             url=/api/v1/health   resp_code=code  resp_body=body
http_assert_status   expected=200-299
http_session_end
```

关联：`docs/ROADMAP.md`、`docs/keyword-verification-matrix.md`、`docs/managementconsole.md`。
