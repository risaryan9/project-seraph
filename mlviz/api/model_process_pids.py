"""
Resolve OS PIDs for Seraph model workloads for optimizer remediation commands.

Discovery order per model_id:
1. SERAPH_OPTIMIZER_MODEL_PIDS_JSON env (explicit overrides for demos / Docker API split)
2. psutil scan: cmdline contains workload module markers (docker-compose / python -m runs)

When the FastAPI container cannot see host PIDs (default Docker), set e.g.:
  export SERAPH_OPTIMIZER_MODEL_PIDS_JSON='{"resnet18-train":12847,"distilbert-infer":12848}'

Docker-compose container names match mlviz-<service> where service keys are resnet18-train, etc.
In-container workload process is typically PID 1 for `docker exec ... renice -p 1`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

import psutil

logger = logging.getLogger(__name__)

# Cmdline substrings for `python -m mlviz.workloads.<module>` (compose + local).
_CMDLINE_MARKERS: Dict[str, Tuple[str, ...]] = {
    "resnet18-train": ("resnet_main", "mlviz.workloads.resnet"),
    "distilbert-infer": ("bert_main", "mlviz.workloads.bert"),
    "data-pipeline": ("pipeline_main", "mlviz.workloads.pipeline"),
}

# Compose service keys -> default container_name from docker-compose.yml
_DEFAULT_DOCKER_CONTAINER: Dict[str, str] = {
    "resnet18-train": "mlviz-resnet18-train",
    "distilbert-infer": "mlviz-distilbert-infer",
    "data-pipeline": "mlviz-data-pipeline",
}

_ENV_CONTAINER_PREFIX = "SERAPH_DOCKER_CONTAINER_"


def _env_json_overrides() -> Dict[str, int]:
    raw = (os.getenv("SERAPH_OPTIMIZER_MODEL_PIDS_JSON") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Invalid SERAPH_OPTIMIZER_MODEL_PIDS_JSON: %s", e)
        return {}
    out: Dict[str, int] = {}
    if not isinstance(data, dict):
        return {}
    for k, v in data.items():
        mid = str(k).strip()
        try:
            pid = int(v)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            out[mid] = pid
    return out


def _docker_container_for_model(model_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", model_id).upper()
    env_key = f"{_ENV_CONTAINER_PREFIX}{slug}"
    return (os.getenv(env_key) or "").strip() or _DEFAULT_DOCKER_CONTAINER.get(
        model_id, f"mlviz-{model_id}"
    )


def _find_host_pids_for_models(model_ids: Set[str]) -> Dict[str, Optional[int]]:
    """Return best-effort host PID per model_id via psutil (same PID namespace as this process)."""
    my_pid = os.getpid()
    found: Dict[str, List[int]] = {m: [] for m in model_ids}

    markers_needed = {m: _CMDLINE_MARKERS[m] for m in model_ids if m in _CMDLINE_MARKERS}

    for proc in psutil.process_iter(attrs=["pid", "cmdline"]):
        try:
            if proc.info["pid"] == my_pid:
                continue
            blob = " ".join(proc.info["cmdline"] or []).lower()
            if not blob:
                continue
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

        for mid, markers in markers_needed.items():
            if any(marker.lower() in blob for marker in markers):
                found[mid].append(proc.info["pid"])

    out: Dict[str, Optional[int]] = {}
    for mid in model_ids:
        pids = [p for p in found.get(mid, []) if p and p != my_pid]
        if not pids:
            out[mid] = None
        else:
            # Stable choice: smallest PID (main workload tends to be earlier than respawns).
            out[mid] = min(pids)
    return out


def resolve_process_identifiers(model_ids: Iterable[str]) -> Dict[str, dict]:
    """
    Build per-model identifier dict for prompts and fallback commands.

    Each value: host_pid (int|None), docker_container (str), in_container_pid (int, usually 1).
    """
    ids: Set[str] = {str(m).strip() for m in model_ids if m and str(m).strip()}
    overrides = _env_json_overrides()
    scanned = _find_host_pids_for_models(ids) if ids else {}

    result: Dict[str, dict] = {}
    for mid in sorted(ids):
        host_pid: Optional[int] = overrides.get(mid) or scanned.get(mid)
        result[mid] = {
            "host_pid": host_pid,
            "docker_container": _docker_container_for_model(mid),
            "in_container_pid": 1,
        }
    return result


def format_pid_lines_for_prompt(identifiers: Dict[str, dict]) -> List[str]:
    """Human-readable lines for Gemini (no pgrep)."""
    lines: List[str] = []
    for mid in sorted(identifiers.keys()):
        info = identifiers[mid]
        hp = info.get("host_pid")
        dc = info.get("docker_container", "")
        icp = info.get("in_container_pid", 1)
        if hp is not None and isinstance(hp, int) and hp > 0:
            lines.append(f'{mid} host_pid: {hp} (use this PID on the host shell)')
        else:
            lines.append(
                f"{mid} host_pid: unknown — use docker exec {dc} ... -p {icp} "
                f"(workload is typically PID {icp} inside that container)"
            )
    return lines


def remediation_command_rules_text() -> str:
    return (
        "For recommended_fixes[].command: use ONLY numeric PIDs from process_identifiers — "
        "never $(pgrep), never subshell PID discovery. "
        "If host_pid is a positive integer, prefer bare tools on the host, e.g. "
        "'taskset -cp 0-3 <host_pid>', 'renice -n 10 -p <host_pid>'. "
        "If host_pid is null, scope the command inside Docker: "
        "'docker exec <docker_container> taskset -cp 0-3 <in_container_pid>' "
        "and same pattern for renice, numactl. "
        "Use the exact docker_container and in_container_pid values provided."
    )
