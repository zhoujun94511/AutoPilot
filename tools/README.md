# tools/

本目录只放 **开发者 / 运维 CLI**（环境预检、契约门禁、无头跑批、排障），不放冒烟或真机 E2E。联调脚本见 [`tests/live/`](../tests/live/README.md)。

| 脚本 | 用途 |
|------|------|
| `preflight.py` | 依赖与工具链体检 |
| `verify_realenv.py` | 真机 / 外部服务连通 |
| `run_suite.py` | 无头批量执行 |
| `check_dual_repo_contract.py` | 与 Platform 执行内核契约门禁 |
| `codegen_mgmt_client_stubs.py` | 管理台客户端桩生成 |
| `export_icon.py` | 品牌图标导出 |
| `config_doctor.py` | IDE Platform URL 与 Bootstrap 对照 |
| `trigger_platform_job.py` | 提交远程批跑 |
| `verify_keywords.py` | 已连接设备上的关键字核实 |
| `keyword_matrix.py` | 关键字可测性盘点 |
| `intent_hitrate_run.py` | Intent 命中率实验室跑法 |
| `ios_monkey_run.py` | iOS Monkey CLI |
| `ios_parity_*.py` / `android_parity_run.py` / `ios_golden_reference_run.py` | 真机 parity 实验室 |
| `diag_ios_wda.py` / `diag_authoring_capture.py` | 排障 |
| `ios_avf_capture/` | macOS 高帧镜像 helper 源码 |
