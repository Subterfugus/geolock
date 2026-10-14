"""Optional "deep analysis": a local vision-language model reasons about the photo.

Uses OpenVINO GenAI's VLMPipeline with an INT4 model exported by
``python -m geolock.setup_models --vlm`` (default Qwen2.5-VL-7B-Instruct, Apache-2.0).
It reads signs in any script, spots driving side, plates, bollards, flora and so on,
and its country guesses are fused with the other evidence at moderate weight.
"""
import json
import re
from functools import cached_property

import numpy as np

from .clues import Clue
from .countrymeta import LEFT_DRIVING

PROMPT = """You are an expert at GeoGuessr-style photo geolocation.
Study this photo and list the concrete visual clues that reveal where it was taken:
text and its language/script, road markings, driving side, license plates, signs,
bollards, utility poles, architecture, vegetation, terrain, climate, vehicles, people.
Then give your best country guesses with probabilities that sum to at most 1.
Answer ONLY with JSON in exactly this shape:
{"clues": [{"clue": "...", "suggests": "..."}],
 "driving_side": "left" | "right" | "unknown",
 "text_seen": "...",
 "countries": [{"country": "...", "iso2": "XX", "probability": 0.0}],
 "region_guess": "..."}"""


class VisionLanguageModel:
    def __init__(self, model_dir, device="GPU"):
        self.model_dir, self.device = model_dir, device

    @property
    def available(self):
        return (self.model_dir / "openvino_language_model.xml").exists()

    @cached_property
    def pipe(self):
        import openvino_genai as ov_genai
        try:
            return ov_genai.VLMPipeline(str(self.model_dir), self.device)
        except Exception:
            return ov_genai.VLMPipeline(str(self.model_dir), "CPU")

    def analyse(self, img):
        import openvino as ov
        import openvino_genai as ov_genai
        im = img.convert("RGB")
        scale = min(1.0, 896 / max(im.size))
        if scale < 1:
            im = im.resize((int(im.width * scale), int(im.height * scale)))
        tensor = ov.Tensor(np.asarray(im, dtype=np.uint8)[None])
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = 600
        out = self.pipe.generate(PROMPT, images=[tensor], generation_config=cfg)
        text = out.texts[0] if hasattr(out, "texts") else str(out)
        return text, parse(text)


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    raw = m.group(0)
    for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def vlm_clues(data, raw_text, code_from_name, all_codes):
    """Turn the VLM's JSON into Clue objects. code_from_name maps a country name to iso2."""
    if not data:
        return [Clue(kind="vlm", title="Vision-language model notes",
                     detail=raw_text.strip()[:400])]
    clues = []
    for c in data.get("clues") or []:
        if isinstance(c, dict) and c.get("clue"):
            detail = c.get("suggests") or ""
            clues.append(Clue(kind="vlm", title=str(c["clue"])[:120], detail=str(detail)[:200]))
    side = str(data.get("driving_side", "")).lower()
    if side in ("left", "right"):
        countries = {c: 1 for c in all_codes if (c in LEFT_DRIVING) == (side == "left")}
        clue = Clue(kind="driving", title=f"Traffic drives on the {side}",
                    detail="Read by the vision-language model from vehicles and road layout.",
                    strength=0.55, countries=countries, background=0.1)
        clues.append(clue)
    guesses = {}
    for g in data.get("countries") or []:
        if not isinstance(g, dict):
            continue
        code = (g.get("iso2") or "").upper()
        if len(code) != 2:
            code = code_from_name(g.get("country", ""))
        try:
            p = float(g.get("probability", 0))
        except (TypeError, ValueError):
            p = 0
        if code and p > 0:
            guesses[code] = guesses.get(code, 0) + p
    if guesses:
        top = max(guesses.values())
        names = ", ".join(f"{c} {p:.0%}" for c, p in sorted(guesses.items(), key=lambda kv: -kv[1])[:4])
        clues.append(Clue(kind="vlm_guess", title="Vision-language model's country guess",
                          detail=names + (f". Region: {data['region_guess']}" if data.get("region_guess") else ""),
                          strength=0.5, countries={c: p / top for c, p in guesses.items()},
                          background=0.15))
    if data.get("text_seen"):
        clues.append(Clue(kind="vlm", title="Text read by the model",
                          detail="“" + str(data["text_seen"])[:200] + "”"))
    return clues
