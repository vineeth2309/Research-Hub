"""Optional background sampling of the machine a run trains on: CPU, memory, GPU and CPU temperature.

    run = hub.init(..., system=True)                          # everything this machine exposes, every 15 s
    run = hub.init(..., system=["gpu", "cpu"], system_interval=5)

or, without touching the script, ``HUB_SYSTEM=1`` (or ``HUB_SYSTEM=gpu,cpu``) and ``HUB_SYSTEM_INTERVAL=5``.

Values are logged as metrics under ``system/`` with seconds since the run started as the step. On Linux this
needs nothing beyond the standard library (/proc, /sys and the nvidia-smi command); on other systems CPU and
memory need psutil. Whatever a machine does not expose is left out silently.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

PARTS = ("cpu", "memory", "gpu", "temperature")
CPU_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal")
GPU_QUERY = ("index", "utilization.gpu", "memory.used", "memory.total", "temperature.gpu", "power.draw")
GPU_KEYS = ("utilization_percent", "memory_gb", "memory_percent", "temperature_c", "power_w")


def parts(value) -> tuple[str, ...]:
    """What to sample, from ``True``, a list of part names, or the HUB_SYSTEM string ("1", "gpu,cpu", "0")."""
    if value is None or value is False or value in ("", "0", "false", "off"):
        return ()
    if value is True or value in ("1", "true", "on", "all"):
        return PARTS
    wanted = tuple(p.strip() for p in value.split(",")) if isinstance(value, str) else tuple(value)
    unknown = [p for p in wanted if p not in PARTS]
    if unknown:
        raise ValueError(f"system metrics: unknown part {unknown}; choose from {list(PARTS)}")
    return wanted


def _cpu_times() -> tuple[int, int]:
    """(busy, total) jiffies since boot, from /proc/stat."""
    fields = [int(v) for v in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    return sum(fields) - idle, sum(fields)


def _visible_gpus() -> set[int] | None:
    """GPU indices this process may use (CUDA_VISIBLE_DEVICES), or None for all of them."""
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is None:
        return None
    ids = [v.strip() for v in visible.split(",") if v.strip()]
    return {int(v) for v in ids} if all(v.isdigit() for v in ids) else None


class Monitor(threading.Thread):
    """Samples every ``interval`` seconds and hands {key: value} and the elapsed seconds to ``send``."""

    def __init__(self, send, wanted: tuple[str, ...], interval: float, started: float):
        super().__init__(daemon=True, name="hub-system-metrics")
        self.send, self.wanted, self.interval, self.started = send, set(wanted), max(1.0, float(interval)), started
        self.done = threading.Event()
        self.cpu_before = None
        if "cpu" in self.wanted:  # the first reading needs something to compare with
            self._cpu()

    def run(self):
        while not self.done.wait(self.interval):
            values = self.sample()
            if values:
                self.send(values, int(time.time() - self.started))

    def stop(self):
        self.done.set()

    def sample(self) -> dict:
        out: dict = {}
        for part in PARTS:
            if part in self.wanted:
                try:
                    out.update(getattr(self, f"_{part}")())
                except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                    self.wanted.discard(part)  # this machine does not expose it; stop asking
        return {f"system/{k}": v for k, v in out.items()}

    def _cpu(self) -> dict:
        if psutil:
            return {"cpu_percent": psutil.cpu_percent(None)}
        busy, total = _cpu_times()
        before, self.cpu_before = self.cpu_before, (busy, total)
        if not before or total == before[1]:
            return {}
        return {"cpu_percent": 100 * (busy - before[0]) / (total - before[1])}

    @staticmethod
    def _memory() -> dict:
        if psutil:
            return {"memory_percent": psutil.virtual_memory().percent,
                    "process_memory_gb": psutil.Process().memory_info().rss / 2**30}
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        total, free = (int(info[k].split()[0]) for k in ("MemTotal", "MemAvailable"))
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
        return {"memory_percent": 100 * (total - free) / total, "process_memory_gb": int(status["VmRSS"].split()[0]) / 2**20}

    @staticmethod
    def _temperature() -> dict:
        readings = [int(sensor.read_text()) / 1000
                    for name in Path("/sys/class/hwmon").glob("hwmon*/name") if name.read_text().strip() in CPU_SENSORS
                    for sensor in name.parent.glob("temp*_input")]
        if not readings:
            raise OSError("no CPU temperature sensor")
        return {"cpu_temperature_c": max(readings)}

    @staticmethod
    def _gpu() -> dict:
        rows = subprocess.run(["nvidia-smi", f"--query-gpu={','.join(GPU_QUERY)}", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip().splitlines()
        visible, out = _visible_gpus(), {}
        for row in rows:
            index, util, used, total, temp, power = (v.strip() for v in row.split(","))
            if visible is not None and int(index) not in visible:
                continue
            values = (util, float(used) / 1024, 100 * float(used) / float(total), temp, power)
            for key, value in zip(GPU_KEYS, values):
                try:
                    out[f"gpu{index}/{key}"] = float(value)
                except ValueError:  # "[N/A]": this card does not report it
                    pass
        return out
