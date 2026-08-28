"""Runner 设备选择策略的本地持久化缓存。

``exclude_udids`` 仅 IDE 本机写入（检视/镜像占用的那一台），Platform 心跳
响应没有这个字段；``update_device_policy`` 必须保留，不能被远端 revision 冲掉。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _norm_udids(values) -> set[str]:
    return {str(x).strip() for x in (values or []) if str(x).strip()}


@dataclass
class DevicePolicy:
    mode: str = "all"
    selected_udids: set[str] = field(default_factory=set)
    revision: int = 0
    exclude_udids: set[str] = field(default_factory=set)

    def filter(self, devices: list):
        if self.mode != "include":
            out = list(devices)
        else:
            out = [
                d
                for d in devices
                if str(getattr(d, "udid", "") or "") in self.selected_udids
            ]
        if self.exclude_udids:
            out = [
                d
                for d in out
                if str(getattr(d, "udid", "") or "") not in self.exclude_udids
            ]
        return out


def policy_would_report(policy: DevicePolicy, udid: str) -> bool:
    """该 UDID 若在库存中，按当前策略会不会进心跳 devices。"""
    uid = (udid or "").strip()
    if not uid:
        return False

    class _One:
        def __init__(self, serial: str):
            self.udid = serial

    return any(
        str(getattr(item, "udid", "") or "") == uid
        for item in policy.filter([_One(uid)])
    )


def _path(runner_id: str) -> Path:
    root = Path(
        os.environ.get("MC_RUNNER_STATE_DIR")
        or (Path.home() / ".autopilot" / "runner")
    )
    suffix = hashlib.sha256(runner_id.encode("utf-8")).hexdigest()[:16]
    return root / f"device-policy-{suffix}.json"


def load_device_policy(runner_id: str) -> DevicePolicy:
    try:
        raw = json.loads(_path(runner_id).read_text(encoding="utf-8"))
        return DevicePolicy(
            mode=str(raw.get("mode") or "all"),
            selected_udids=_norm_udids(raw.get("selected_udids", [])),
            revision=int(raw.get("revision") or 0),
            exclude_udids=_norm_udids(raw.get("exclude_udids", [])),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return DevicePolicy()


def save_device_policy(runner_id: str, policy: DevicePolicy) -> None:
    path = _path(runner_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "mode": policy.mode,
                "selected_udids": sorted(policy.selected_udids),
                "revision": policy.revision,
                "exclude_udids": sorted(policy.exclude_udids),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def sync_exclude_udids(runner_id: str, current: DevicePolicy) -> DevicePolicy:
    """心跳前从磁盘合并 exclude，IDE 改文件后下一拍即可摘除。"""
    current.exclude_udids = set(load_device_policy(runner_id).exclude_udids)
    return current


def add_exclude_udids(runner_id: str, udids) -> DevicePolicy:
    policy = load_device_policy(runner_id)
    policy.exclude_udids |= _norm_udids(udids)
    save_device_policy(runner_id, policy)
    return policy


def remove_exclude_udids(runner_id: str, udids) -> DevicePolicy:
    policy = load_device_policy(runner_id)
    drop = _norm_udids(udids)
    if not (policy.exclude_udids & drop):
        return policy
    policy.exclude_udids -= drop
    save_device_policy(runner_id, policy)
    return policy


def update_device_policy(
    runner_id: str, current: DevicePolicy, response: dict
) -> DevicePolicy:
    revision = int(response.get("device_policy_revision") or 0)
    disk_exclude = set(load_device_policy(runner_id).exclude_udids)
    exclude = disk_exclude | set(current.exclude_udids)
    if revision < current.revision:
        current.exclude_udids = exclude
        return current
    policy = DevicePolicy(
        mode=str(response.get("device_selection_mode") or "all"),
        selected_udids=_norm_udids(response.get("selected_device_udids", [])),
        revision=revision,
        exclude_udids=exclude,
    )
    save_device_policy(runner_id, policy)
    return policy
