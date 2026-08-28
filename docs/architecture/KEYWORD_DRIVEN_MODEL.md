# 链路 1 架构定名：元数据驱动的可视化关键字驱动

> 修订：2026-08-07  
> 相关：[AI_AUTOMATION_ROADMAP.md](./AI_AUTOMATION_ROADMAP.md) · [feature-modules.md](../feature-modules.md) · [ui-design.md](../ui-design.md)

---

## 1. 一句话定名

AutoPilot **链路 1** 采用 **Keyword-Driven Testing（KDT）** 架构，并在创作端实现 **Metadata-Driven Visual Composition**：

- 关键字**执行语义**由 Python **Keyword Implementation Registry**（`@keyword` / `REGISTRY`）提供；
- 关键字**编辑期元数据**由独立的 **Keyword Metadata Catalog**（`keyword_defs/*.xml`）提供；
- IDE 通过关键字库、拖拽与参数表单生成结构化步骤（`.tc.yaml`）；
- 执行器按 `keyword_id` **确定性派发**，不临场决策。

产品介绍可用简称：**可视化关键字驱动自动化测试 IDE**（Visual Keyword-Driven Test Automation IDE）。

---

## 2. 交互范式

```text
Library → Drag/Drop → Form Editing → Structured Test Model
关键字库 → 拖入步骤 → 参数表单 → .tc.yaml 结构化用例
```

编辑器本身可称：**Visual Keyword Composer / Keyword-Based Test Editor**（可视化关键字编排器 / 关键字用例编辑器）。

这比「Excel 表驱动」更准确：编排真源是 IDE 步骤树 + YAML，不是电子表格行。

---

## 3. 与 Tosca 的类比边界

**成立的部分（交互模型）：** Tosca 官方构建方式是把 Module drag & drop 到 TestCase，形成 TestStep，再编辑 TestStepValues。AutoPilot 对应为：关键字库拖入 → 步骤 → 参数表单（含 `${var}`）→ 结构化用例模型。

**不成立的部分（产品等价）：** 不宣称与 Tosca 在模型驱动测试、风险权重、TDM、企业治理等能力上等价。类比仅限「库组件拖入 + 表单填值 + 结构化用例」这一创作范式。

历史对标结论已并入本节与关键字目录；不另附审计长文。

---

## 4. 双轨结构（勿把 Catalog 叫成 Registry）

| 层 | 建议英文名 | 落点 | 职责 |
|----|------------|------|------|
| 实现 | Keyword Implementation | `autopilot/keywords/**` 中的 Python 函数 | 运行期行为 |
| 注册表 | Keyword Implementation Registry | `@keyword(id)` → `REGISTRY` | 按 id 派发 |
| 元数据目录 | Keyword Metadata Catalog | `metadata/keyword_defs/*.xml` | 中文名、分组、参数 schema、必填/枚举、platforms、risk 等 |
| 库面板 | Visual Keyword Library | `keyword_panel` + `load_catalog()` | 浏览 / 搜索 / 拖拽 |
| 表单 | Metadata-Driven Parameter Form | `param_form` | 由 Catalog 驱动，而非硬编码控件 |
| 用例模型 | Structured Test Case | `.tc.yaml` / `model/testcase` | 步骤序列 + 参数值 |
| 执行 | Runtime Dispatch | `engine/executor` | `REGISTRY.get(keyword_id)` |

```text
Keyword Implementation          Keyword Metadata Catalog
  Python function                 keyword_defs/*.xml
        │                                   │
        ▼                                   ▼
Keyword Registry              Visual Keyword Library
  @keyword / REGISTRY           拖拽 / 双击插入
        │                                   │
        │                     Metadata-Driven Parameter Form
        │                                   │
        │                                   ▼
        │                     Structured Test Case (.tc.yaml)
        │                                   │
        └────────────────┬──────────────────┘
                         ▼
              Runtime Dispatch by Keyword ID
```

`REGISTRY` 也可携带部分展示字段（如装饰器上的 `name`），但**权威编辑期 schema 以 XML Catalog 为准**；执行派发以 Registry 为准。

---

## 5. 与其它 KDT 模式对照

| 模式 | 典型形态 | AutoPilot 链路 1 |
|------|----------|------------------|
| 文本关键字驱动 | Robot `.robot` 手写 | 否（可导出/阅读 YAML，但创作主路径是 GUI） |
| 表格关键字驱动 | Excel/CSV 一行一步 | 否 |
| **元数据驱动可视化 KDT** | 库拖拽 + 表单 + 结构化模型 | **是** |
| 数据驱动叠加 | 变量 / 数据池 | 有（`${var}`、datapool），属 KDT 上的 DDT 增强，不改变创作范式定名 |

---

## 6. 在三链路中的位置

| 链路 | 关系 |
|------|------|
| **1 · 传统** | 本文件所述架构；默认可交付执行真源 |
| **2 · 设计 AI** | 测设资产；不承诺可执行；不替代本编排模型 |
| **3 · AI 辅助编写** | 加速写出链路 1 同构的 `.tc` / 关键字步骤，生成物回归本架构 |

详见 [AI_AUTOMATION_ROADMAP.md](./AI_AUTOMATION_ROADMAP.md)。

---

## 7. 参数可见性（步骤表单 vs 定义编辑器）

`ParamForm`（某一步的实例）与 `CustomKeywordEditor`（`KeywordDef` 定义）**不得共用同一套可见性规则**。

| 层 | 落点 | 可依赖 |
|----|------|--------|
| 运行时步骤 | `autopilot/ui/widgets/step_param_rules.py` | 当前步骤的 `type` / `platform`（如 iOS 才显示 `backendMode`） |
| 定义期 | `LocalParam.visible_on_platforms` | 仅静态元数据；无步骤实例、无 `backendMode`、无执行上下文 |

更复杂的表达式规则尚未做；不要在自定义关键字编辑器里读步骤平台或会话状态。
