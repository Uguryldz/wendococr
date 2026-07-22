"""
Konteynerin GERÇEK CPU kotasını bulur.

Neden gerekli:
  ONNX Runtime thread havuzunu os.cpu_count() ile boyutlandırır — bu HOST'un çekirdek
  sayısıdır, cgroup kotası değil. `--cpus=2` limitli bir konteynerde 8 thread açılır,
  2 çekirdeklik kotayı paylaşmak için sürekli context switch olur ve OCR süperlineer
  yavaşlar (ölçüm: 8 çekirdek 2.0s → cpus=2 + 8 thread 13.4s → cpus=2 + 2 thread 3.1s).
"""
import os
from pathlib import Path


def _quota_from_cgroup_v2() -> float | None:
    try:
        raw = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if raw[0] == "max":
            return None
        return int(raw[0]) / int(raw[1])
    except Exception:
        return None


def _quota_from_cgroup_v1() -> float | None:
    try:
        base = Path("/sys/fs/cgroup/cpu")
        quota = int((base / "cpu.cfs_quota_us").read_text())
        period = int((base / "cpu.cfs_period_us").read_text())
        if quota <= 0 or period <= 0:
            return None
        return quota / period
    except Exception:
        return None


def effective_cpus() -> int:
    """Kullanılabilir efektif çekirdek sayısı (cgroup kotası varsa onu, yoksa host'u)."""
    quota = _quota_from_cgroup_v2() or _quota_from_cgroup_v1()
    host = os.cpu_count() or 1
    if quota is None:
        return host
    return max(1, min(host, int(quota)))
