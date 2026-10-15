"""Where CLIP runs: the Arc GPU, the NPU or the CPU.

`VisionRunner` compiles the CLIP vision model on the chosen device and falls back to the
next one (in the end the CPU) when a device fails to compile, fails to run, or returns
invalid numbers. Everything it tries is recorded so the app can show which device ran,
why it fell back and how long things took. `benchmark` times every device side by side.

Works with anything shaped like `openvino.Core` (`available_devices`, `get_property`,
`compile_model`), so the fallback logic is tested with a fake core.
"""
import statistics
import time

import numpy as np

ORDER = ("GPU", "NPU", "CPU")  # AUTO tries them in this order


def _short(err, limit=240):
    text = str(err).strip().splitlines()
    text = text[0] if text else type(err).__name__
    text = f"{type(err).__name__}: {text}" if not isinstance(err, str) else text
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000)


def present(core, dev):
    return any(a.split(".")[0] == dev for a in core.available_devices)


def device_name(core, dev):
    try:
        return str(core.get_property(dev, "FULL_DEVICE_NAME"))
    except Exception:
        return None


def is_intel_gpu(core):
    """OpenVINO can list NVIDIA/AMD cards as GPU through OpenCL, but its GPU plugin only
    has kernels for Intel graphics."""
    return any(d.split(".")[0] == "GPU" and "intel" in (device_name(core, d) or "").lower()
               for d in core.available_devices)


def config(dev, cache_dir=None):
    cfg = {"PERFORMANCE_HINT": "LATENCY"}
    # GPU kernels and NPU blobs take a while to build; the cache makes later starts fast.
    if dev in ("GPU", "NPU") and cache_dir:
        cfg["CACHE_DIR"] = str(cache_dir)
    return cfg


class VisionRunner:
    """Callable: batch of crops in, float32 embeddings out, on the first device that works."""

    def __init__(self, core, model, requested="AUTO", cache_dir=None):
        self.core, self.model, self.cache_dir = core, model, cache_dir
        self.requested = (requested or "AUTO").upper()
        self.attempts = []   # every compile / run failure or success, in order
        self.failed = set()
        self.device = self.compiled = None
        self.compile_ms = self.first_run_ms = self.last_run_ms = None
        self.runs = 0
        self._compile_next()

    def _order(self):
        if self.requested == "AUTO":
            return ORDER
        return (self.requested,) if self.requested == "CPU" else (self.requested, "CPU")

    def _note(self, dev, step, ok, ms=None, error=None):
        self.attempts.append({"device": dev, "step": step, "ok": ok, "ms": ms,
                              "error": None if error is None else _short(error)})

    def _compile_next(self):
        for dev in self._order():
            if dev in self.failed:
                continue
            if not present(self.core, dev):
                self.failed.add(dev)
                if dev == self.requested:
                    self._note(dev, "compile", False, error="not found on this computer")
                continue
            if dev == "GPU" and self.requested == "AUTO" and not is_intel_gpu(self.core):
                self.failed.add(dev)
                self._note(dev, "compile", False, error="not an Intel GPU (OpenVINO can't use it)")
                continue
            t0 = time.perf_counter()
            try:
                compiled = self.core.compile_model(self.model, dev, config(dev, self.cache_dir))
            except Exception as e:  # e.g. NPU driver missing -> fall through
                self.failed.add(dev)
                self._note(dev, "compile", False, _ms(t0), e)
                continue
            self.compile_ms = _ms(t0)
            self._note(dev, "compile", True, self.compile_ms)
            self.device, self.compiled = dev, compiled
            self.first_run_ms = None
            return
        errors = [f"{a['device']}: {a['error']}" for a in self.attempts if not a["ok"]]
        raise RuntimeError("Could not run CLIP on any device:\n" + "\n".join(errors))

    def __call__(self, x):
        while True:
            dev = self.device
            t0 = time.perf_counter()
            try:
                out = np.asarray(self.compiled(x)[0], dtype=np.float32)
                if not np.isfinite(out).all():
                    raise FloatingPointError("returned invalid numbers (NaN or infinity)")
            except Exception as e:
                self.failed.add(dev)
                self._note(dev, "run", False, _ms(t0), e)
                if dev == "CPU" or self.requested == "CPU":
                    raise
                self.compiled = None
                self._compile_next()  # raises when nothing is left
                continue
            ms = _ms(t0)
            if self.first_run_ms is None:
                self.first_run_ms = ms
                self._note(dev, "first run", True, ms)
            self.last_run_ms = ms
            self.runs += 1
            return out

    @property
    def fallback(self):
        """One sentence when CLIP is not on the device the user asked for (or, on Auto,
        a faster device failed), else None."""
        failures = [a for a in self.attempts if not a["ok"] and a["device"] != self.device
                    and not (self.requested == "AUTO" and a["error"] and a["error"].startswith("not "))]
        if not failures:
            return None
        f = failures[-1]
        what = "couldn't start" if f["step"] == "compile" else "failed while running"
        if f["error"] == "not found on this computer":
            what, why = "isn't available on this computer", ""
        else:
            why = f" ({f['error']})"
        return f"{f['device']} {what}{why}, so GeoLock is using the {self.device}."

    def report(self):
        return {"requested": self.requested, "device": self.device,
                "device_name": device_name(self.core, self.device) if self.device else None,
                "compile_ms": self.compile_ms, "first_run_ms": self.first_run_ms,
                "last_run_ms": self.last_run_ms, "runs": self.runs,
                "fallback": self.fallback, "attempts": list(self.attempts)}


def benchmark(core, model, x, n=5, cache_dir=None, devices=ORDER):
    """Compile and time CLIP on every device this computer has. One row per device:
    compile time, first run (includes one-off kernel set-up) and the median of n runs."""
    rows = []
    for dev in devices:
        row = {"device": dev, "name": None, "ok": False, "compile_ms": None,
               "first_run_ms": None, "ms": None, "error": None}
        rows.append(row)
        if not present(core, dev):
            row["error"] = "not found on this computer"
            continue
        row["name"] = device_name(core, dev)
        if dev == "GPU" and not is_intel_gpu(core):
            row["error"] = "not an Intel GPU (OpenVINO can't use it)"
            continue
        compiled = None
        try:
            t0 = time.perf_counter()
            compiled = core.compile_model(model, dev, config(dev, cache_dir))
            row["compile_ms"] = _ms(t0)
            t0 = time.perf_counter()
            out = np.asarray(compiled(x)[0], dtype=np.float32)
            row["first_run_ms"] = _ms(t0)
            if not np.isfinite(out).all():
                raise FloatingPointError("returned invalid numbers (NaN or infinity)")
            times = []
            for _ in range(max(1, n)):
                t0 = time.perf_counter()
                compiled(x)
                times.append((time.perf_counter() - t0) * 1000)
            row["ms"] = round(statistics.median(times))
            row["ok"] = True
        except Exception as e:
            row["error"] = _short(e)
        finally:
            del compiled
    return rows
