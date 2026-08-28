# Token / 上下文预算控制

> 审计 Canvas：`token-budget-audit.canvas.tsx`  
> 修订：2026-07-29

## 目标

在**不引入完整计费系统**的前提下：

1. **继续**输入侧节流（压缩截图、截断 RAG、限制条数）  
2. **新增**解析厂商返回的 `usage`，落盘 + 日志 + 设计域 stats / Prometheus  
3. **可选**日累计软/硬预算（环境变量）

**明确不做（本轮）**：按用户/项目账单、tiktoken 预估硬拦截、跨进程分布式配额。

---

## Plan → Todo

| ID | 项 | 状态 |
|----|-----|------|
| T1 | Platform `ai_usage`：extract / JSONL / 日汇总 | **done** |
| T2 | `ai_client` 记录 usage + `check_budget_before_call` | **done** |
| T3 | `design_stats.tokens` 接真实汇总 | **done** |
| T4 | Prometheus `mc_ai_*` 计数 | **done** |
| T5 | IDE Vision `intent/usage.py` 落盘+日志 | **done** |
| T6 | 文档（本文 + AI_CONFIG / .env.example） | **done** |
| T7 | 组织级硬配额 / 按项目分账 | backlog P2 |

---

## 配置

### Platform（设计 Chat / 生成）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AP_AI_MAX_TOKENS` | 4096 | 单次**输出**上限 |
| `AP_AI_DAILY_TOKEN_BUDGET` | 0 | 日累计 `total_tokens`；0=关闭 |
| `AP_AI_ENFORCE_TOKEN_BUDGET` | 0 | 1=超预算抛错阻断；0=仅 warning |
| `AP_RAG_TOP_K` / `AP_CHUNK_SIZE` / `AP_MAX_CASE_NUM` | 见运维配置 | 输入侧节流 |

落盘目录：`{artifacts_root 的 parent}/ai_usage/usage-YYYY-MM-DD.jsonl`  
汇总：设计域 stats 的 `tokens` 字段；`/metrics` 含 `mc_ai_chat_calls_total` / `mc_ai_tokens_total`。

### IDE（Vision）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AUTOPILOT_INTENT_VISION` | 0 | 总开关 |
| `AUTOPILOT_VISION_*` | 见 `.env.example` | 压缩/DOM/detail/WHEN |
| Vision 请求 `max_tokens` | 800 | 代码内写死输出封顶 |
| `AUTOPILOT_VISION_USAGE_DIR` | `~/.autopilot/vision_usage` | usage JSONL 目录 |

---

## 代码锚点

| 仓 | 路径 |
|----|------|
| Platform | `platform/ai/ai_usage.py`、`ai_client.py`、`services/design_stats.py`、`core/metrics.py` |
| IDE | `autopilot/intent/usage.py`、`vision_plugin.py`、`context_budget.py`、`config.py` |

---

## 验证

```powershell
# Platform
python -m pytest tests/test_ai_usage.py tests/test_ai_providers.py -q

# IDE
python -m pytest tests/test_intent_usage.py tests/test_intent_vision_webhook.py -q
```
