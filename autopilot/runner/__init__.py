"""客户端 TestRunner：经 HTTP 对接 Platform；执行用本仓 engine/mobile。

禁止 import managementconsole（服务端包）；契约字段与 Console OpenAPI 对齐。
"""

from .agent import RunnerAgent, run_forever

__all__ = ["RunnerAgent", "run_forever"]
