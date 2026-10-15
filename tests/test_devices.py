"""Device choice and CPU fallback (geolock/devices.py) with a fake OpenVINO core, so the
GPU / NPU paths are exercised on machines that have neither."""
import numpy as np
import pytest

from geolock.devices import VisionRunner, benchmark

X = np.zeros((4, 3, 224, 224), np.float32)


class FakeCore:
    """available: device -> full name. broken: device -> 'compile' | 'run' | 'nan'."""

    def __init__(self, available, broken=None):
        self.available = available
        self.broken = broken or {}
        self.compiled_on = []
        self.runs = []

    @property
    def available_devices(self):
        return list(self.available)

    def get_property(self, dev, key):
        assert key == "FULL_DEVICE_NAME"
        return self.available[dev]

    def compile_model(self, model, dev, cfg):
        self.compiled_on.append((dev, dict(cfg)))
        if self.broken.get(dev) == "compile":
            raise RuntimeError(f"[{dev}] driver not loaded\nlong trace")

        def run(x):
            self.runs.append(dev)
            if self.broken.get(dev) == "run":
                raise RuntimeError(f"[{dev}] device lost")
            out = np.ones((x.shape[0], 768), np.float32)
            if self.broken.get(dev) == "nan":
                out[0, 0] = np.nan
            return [out]
        return run


LAPTOP = {"CPU": "Intel(R) Core(TM) Ultra 7 258V", "GPU": "Intel(R) Arc(TM) 140V GPU (16GB)",
          "NPU": "Intel(R) AI Boost"}


def test_auto_prefers_the_intel_gpu_with_a_kernel_cache(tmp_path):
    core = FakeCore(LAPTOP)
    r = VisionRunner(core, "model", "AUTO", tmp_path / "cache")
    assert r.device == "GPU" and r(X).shape == (4, 768)
    assert core.compiled_on[0][1]["CACHE_DIR"] == str(tmp_path / "cache")
    rep = r.report()
    assert rep["fallback"] is None and rep["device_name"].startswith("Intel(R) Arc")
    assert rep["first_run_ms"] is not None and rep["runs"] == 1


def test_auto_skips_a_gpu_that_fails_to_compile_and_says_why():
    core = FakeCore(LAPTOP, {"GPU": "compile"})
    r = VisionRunner(core, "model", "AUTO")
    assert r.device == "NPU"
    assert r.fallback.startswith("GPU couldn't start (RuntimeError: [GPU] driver not loaded)")
    assert "long trace" not in r.fallback


def test_device_that_fails_while_running_falls_back_and_the_photo_still_works():
    core = FakeCore(LAPTOP, {"GPU": "run", "NPU": "nan"})
    r = VisionRunner(core, "model", "AUTO")
    out = r(X)
    assert r.device == "CPU" and np.isfinite(out).all()
    assert core.runs == ["GPU", "NPU", "CPU"]
    assert "NPU failed while running" in r.fallback and "invalid numbers" in r.fallback
    assert [a["device"] for a in r.attempts if not a["ok"]] == ["GPU", "NPU"]
    r(X)
    assert core.runs[-1] == "CPU"  # stays on the CPU afterwards


def test_chosen_device_missing_falls_back_to_cpu():
    core = FakeCore({"CPU": "Intel CPU"})
    r = VisionRunner(core, "model", "NPU")
    assert r.device == "CPU"
    assert r.fallback == "NPU isn't available on this computer, so GeoLock is using the CPU."


def test_auto_on_a_desktop_ignores_non_intel_gpus_quietly():
    core = FakeCore({"CPU": "Intel i7-14700F", "GPU": "NVIDIA GeForce RTX 4070 Ti SUPER (OpenCL)"})
    r = VisionRunner(core, "model", "AUTO")
    assert r.device == "CPU" and r.fallback is None
    assert core.compiled_on == [("CPU", {"PERFORMANCE_HINT": "LATENCY"})]


def test_cpu_failure_is_not_hidden():
    core = FakeCore({"CPU": "cpu"}, {"CPU": "run"})
    r = VisionRunner(core, "model", "AUTO")
    with pytest.raises(RuntimeError, match="device lost"):
        r(X)
    with pytest.raises(RuntimeError, match="any device"):
        VisionRunner(FakeCore({"CPU": "cpu"}, {"CPU": "compile"}), "model", "CPU")


def test_benchmark_has_a_row_per_device():
    core = FakeCore(dict(LAPTOP, **{"GPU.1": "Intel dGPU"}), {"NPU": "compile"})
    rows = {r["device"]: r for r in benchmark(core, "model", X, n=3)}
    assert rows["GPU"]["ok"] and rows["CPU"]["ok"] and rows["GPU"]["ms"] is not None
    assert not rows["NPU"]["ok"] and "driver not loaded" in rows["NPU"]["error"]
    rows = {r["device"]: r for r in benchmark(FakeCore({"CPU": "cpu"}), "model", X, n=1)}
    assert rows["NPU"]["error"] == "not found on this computer" and rows["CPU"]["ok"]
