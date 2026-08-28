# Intent / Vision 真机命中率与推荐配置

> 验证脚本：`tools/intent_hitrate_run.py`  
> 样例：`tests/fixtures/intent_hitrate/`  
> 设备：通过 `--udid` 或环境变量 `ANDROID_SERIAL` / `IOS_PARITY_UDID` 指定，不要把实验室序列号写进仓库。

## 怎么跑

```powershell
# Android 启发式 + 自愈探针（腐蚀 Binding 后期望 healed）
python tools/intent_hitrate_run.py --platform android --udid <android-udid> --rounds 2 --heal-probe -v

# Web（本地 HTML 夹具，不依赖外网文案）
python tools/intent_hitrate_run.py --platform web --rounds 2 -v

# iOS（WDA 已就绪时可 --skip-ios-prep；首次需隧道/runwda）
$env:PYTHONPATH="."
$env:ENABLE_GO_IOS_AGENT="user"
$env:IOS_USE_GOIOS="1"
$env:AUTOPILOT_INTENT_KEEP_WDA="1"
python tools/intent_hitrate_run.py --platform ios --udid <ios-udid> --rounds 2 --heal-probe -v

# Vision / LLM 兜底（需 API Key）
# DeepSeek V4 官方为纯文本：auto 模式只传 DOM 摘要（不传 image_url）。
# 真截图多模态请改用 gpt-4o / Gemini，或自建支持 image_url 的网关 + IMAGE_MODE=force。
# AutoPilot\.env 示例（DeepSeek DOM 文本）：
#   AUTOPILOT_INTENT_VISION=1
#   DEEPSEEK_API_KEY=...
#   AUTOPILOT_VISION_BASE_URL=https://api.deepseek.com
#   AUTOPILOT_VISION_MODEL=deepseek-v4-flash
#   AUTOPILOT_VISION_IMAGE_MODE=auto
#   AUTOPILOT_VISION_DOM=1
python tools/intent_hitrate_run.py --platform android --udid <android-udid> --vision -v
```

输出：`logs/intent_hitrate_<platform>_*.json` 与工程内 `reports/hitrate_summary.json`。

## 基线结果（无 Vision）

| 面 | Round1 | Round2 | overall |
|---|---|---|---|
| Android Settings assert+click | resolved 5/5 | heal-probe → healed 5/5 | **100%** |
| Web 本地 HTML 夹具 | resolved 2/2 | cache 2/2 | **100%** |
| iOS Preferences assert+click | resolved 3/3 | heal-probe → healed 3/3 | **100%** |

说明：

- Android 真机首页文案为英文：`Wi-Fi` / `Bluetooth` / `VPN` / `About phone`。
- `noReset` 会话可能停在子页；harness 每轮会 `force-stop` + `SETTINGS` intent 清栈。
- iOS 本机 Settings 文案为 `WLAN` / `Bluetooth`（非 Wi-Fi）；harness 会按页面源码改写 fixture。
- iOS `mobile_app_start` 对 WDA 路径会先 `terminate` 再 `launch`，避免 Preferences 从 WLAN 子页恢复导致 Bluetooth 找不到。
- 批跑建议 `AUTOPILOT_INTENT_KEEP_WDA=1`，避免每条用例重跑隧道。
- 自愈：缓存失败后**优先新鲜候选**，并跳过与失败 locator 相同的旧候选；`heal_applied` 仅在成功写回时为 true。

## Vision / 自愈推荐配置

当前默认适合「启发式主路径 + Vision 兜底」：

| 变量 | 推荐 | 理由 |
|---|---|---|
| `AUTOPILOT_INTENT_VISION` | `0`（默），有 Key 再开 | 无 Key 时开关无意义 |
| `AUTOPILOT_VISION_WHEN` | `fallback` | 启发式全失败再调，省 token |
| `AUTOPILOT_VISION_IMAGE_MODE` | `auto` | DeepSeek/非 VL→文本+DOM；gpt-5 / Gemini 3.5 / qwen-vl→可传截图 |
| `AUTOPILOT_VISION_REASONING_EFFORT` | `none` | 定位默认不走深度思考；与 Platform `AP_AI_REASONING_EFFORT` 同源档位 |
| 推荐 Vision 模型 | `gpt-5.4-mini` / `gemini-3.5-flash` / `qwen-vl-plus` | 默认跟 Platform 目录对齐 |
| `AUTOPILOT_VISION_DOM_MODE` | `compact` | Settings/原生 App 控件树够用；DeepSeek 必开 DOM |
| `AUTOPILOT_VISION_IMAGE_DETAIL` | `low` | 真多模态时配合 JPEG 压缩 |
| `AUTOPILOT_VISION_IMAGE_MAX_KB` | `220` | Midscene 风格预算 |
| `AUTOPILOT_VISION_IMAGE_ENHANCED` | `0` | 仅反复 miss 再开 |

> 官方依据：[Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)（user content = Text string）；[Anthropic 兼容](https://api-docs.deepseek.com/guides/anthropic_api)（`type=image` Not Supported）。此前 `image_url` 400 与 `[Unsupported Image]` 均属文档预期行为，非跨端配置错误。

调参顺序建议：先保证启发式命中率 → 开 `fallback` Vision 看 healed/vision 占比 → 仍低再试 `enhanced` / `always`（成本高）。

## 自愈增强（本轮优化）

| 能力 | 说明 |
|---|---|
| 失败归因 | `fail_reason` / `fail_reason_label` 写入 StepResult 与 result.json；人审表「归因」列 |
| 超时预算 | `AUTOPILOT_INTENT_HEAL_BUDGET_MS`（默认 3000）+ 候选短超时；命中率批跑建议抬到 8000–12000 |
| 误愈回滚 | 自愈写 Binding 带 `provisional`+`previous`；下一跑 cache 失败则回滚上一版 |
| Vision 对照 | `--compare-vision`：OFF→ON；无 Key 时 ON 轮跳过并记入 compare_summary |

## Platform 半自动 APPROVED

生成接口增加可选字段（默认关）：

```json
{
  "auto_approve": true,
  "auto_approve_min_quality": 0.85
}
```

仅当 `quality.review_bucket=auto_approvable` 且 `score ≥ 阈值` 且 `risk != high` 时：

- `review_status=APPROVED`
- `automation_status=PENDING_VERIFY`（待首跑验证，不是可直接宣称 EXECUTABLE）

不达标 → 仍 `AI_DRAFT` 等人审。分桶：`auto_approvable` / `needs_review` / `reject_suggest`。

## iOS 运行注意

- 环境：Platform 仓 `.venv` + `PYTHONPATH` 指向 IDE 仓根；`IOS_USE_GOIOS=1`、`ENABLE_GO_IOS_AGENT=user`。
- go-ios：`resources/re_go_ios/executable/win/ios.exe`（可按本机安装路径补齐）。
- WDA 已在 8100 时可加 `--skip-ios-prep`；文案适配仍会执行。
- 汇总样例：`logs/intent_hitrate_ios_live5/reports/hitrate_summary.json`。
