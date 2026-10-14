"""Paths and defaults. Override with environment variables if needed."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = Path(os.environ.get("GEOLOCK_MODELS", ROOT / "models"))
WEB_DIR = Path(__file__).resolve().parent / "web"

CLIP_ID = "openai/clip-vit-large-patch14"
VLM_ID = os.environ.get("GEOLOCK_VLM", "Qwen/Qwen2.5-VL-7B-Instruct")

# Number of image crops fed to CLIP per photo (the OpenVINO model has this fixed batch,
# which keeps it NPU-compatible).
CROPS = 4

# Preferred OpenVINO device order. GPU = Arc 140V, NPU = AI Boost.
DEVICE = os.environ.get("GEOLOCK_DEVICE", "AUTO")
