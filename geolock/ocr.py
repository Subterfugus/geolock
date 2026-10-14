"""Read text in the photo and turn it into clues (script, language, domains, phones, prices).

OCR uses RapidOCR (PaddleOCR models, Apache-2.0) on the OpenVINO engine. The default
PP-OCRv6 model reads Latin (with accents), Chinese and Japanese. Extra PP-OCRv5 models
read Cyrillic, Greek, Korean, Thai, Arabic, Devanagari, Tamil and Telugu; setup downloads
them, and at run time they are tried when CLIP sees that script or when the default model
finds text it cannot read confidently.
"""
import re
import unicodedata
from functools import cached_property

import numpy as np

from .clues import Clue
from .countrymeta import (CURRENCY_MARKERS, LANGUAGE_COUNTRIES, MPH_COUNTRIES,
                          PHONE_PREFIXES, SCRIPT_COUNTRIES, TLD_EXCEPTIONS, TLD_GENERIC)

# Script name (as in SCRIPT_COUNTRIES) -> RapidOCR recognition language.
EXTRA_SCRIPTS = {
    "Cyrillic": "CYRILLIC", "Greek": "EL", "Korean Hangul": "KOREAN", "Thai": "TH",
    "Arabic": "ARABIC", "Devanagari": "DEVANAGARI", "Tamil": "TA", "Telugu": "TE",
}

# Unicode block ranges -> script name.
_RANGES = [
    (0x0370, 0x03FF, "Greek"), (0x0400, 0x052F, "Cyrillic"), (0x0530, 0x058F, "Armenian"),
    (0x0590, 0x05FF, "Hebrew"), (0x0600, 0x06FF, "Arabic"), (0x0750, 0x077F, "Arabic"),
    (0x0900, 0x097F, "Devanagari"), (0x0980, 0x09FF, "Bengali"), (0x0A00, 0x0A7F, "Gurmukhi"),
    (0x0A80, 0x0AFF, "Gujarati"), (0x0B80, 0x0BFF, "Tamil"), (0x0C00, 0x0C7F, "Telugu"),
    (0x0D80, 0x0DFF, "Sinhala"), (0x0E00, 0x0E7F, "Thai"), (0x0E80, 0x0EFF, "Lao"),
    (0x1000, 0x109F, "Burmese"), (0x10A0, 0x10FF, "Georgian"), (0x1200, 0x139F, "Ethiopic"),
    (0x1780, 0x17FF, "Khmer"), (0x3040, 0x30FF, "Japanese"), (0x3400, 0x4DBF, "Chinese characters"),
    (0x4E00, 0x9FFF, "Chinese characters"), (0xAC00, 0xD7AF, "Korean Hangul"),
    (0x1100, 0x11FF, "Korean Hangul"),
]
# Scripts used by many languages: the language detector narrows them down.
_MULTI_LANGUAGE = {"Latin", "Cyrillic", "Arabic", "Devanagari"}
# Letters needed before a script counts (dense scripts need fewer).
_MIN_CHARS = {"Chinese characters": 2, "Japanese": 2, "Korean Hangul": 2}


def script_of(ch):
    o = ord(ch)
    for lo, hi, name in _RANGES:
        if lo <= o <= hi:
            return name
    if ch.isalpha() and o < 0x250:
        return "Latin"
    return None


def _center(box):
    b = np.asarray(box, dtype=float)
    return b[:, 0].mean(), b[:, 1].mean()


def _inside(pt, box):
    b = np.asarray(box, dtype=float)
    return b[:, 0].min() <= pt[0] <= b[:, 0].max() and b[:, 1].min() <= pt[1] <= b[:, 1].max()


def _model_file(lang):
    """Where RapidOCR keeps the PP-OCRv5 recognition model for a language."""
    import importlib.util
    from pathlib import Path
    from rapidocr import LangRec
    spec = importlib.util.find_spec("rapidocr")
    root = Path(list(spec.submodule_search_locations)[0]) / "models"
    return root / f"{getattr(LangRec, lang).value}_PP-OCRv5_rec_mobile.onnx"


class TextReader:
    def __init__(self, min_score=0.6, allow_download=False):
        self.min_score = min_score
        self.allow_download = allow_download  # only setup downloads; the app stays offline
        self._extra = {}
        self.unavailable = set()  # extra models that could not be loaded (not downloaded)

    @staticmethod
    def _params(lang=None):
        from rapidocr import EngineType
        # The text-angle classifier flips long upright lines and garbles them; photos of
        # signs are almost always upright, so it stays off.
        p = {"Global.log_level": "error", "Global.text_score": 0.3, "Global.use_cls": False}
        for stage in ("Det", "Cls", "Rec"):
            p[f"{stage}.engine_type"] = EngineType.OPENVINO
        if lang:
            from rapidocr import LangRec, ModelType, OCRVersion
            p.update({"Rec.lang_type": getattr(LangRec, lang), "Rec.ocr_version": OCRVersion.PPOCRV5,
                      "Rec.model_type": ModelType.MOBILE})
        return p

    @cached_property
    def ocr(self):
        try:
            from rapidocr import RapidOCR
        except ImportError:
            return None
        return RapidOCR(params=self._params())

    def extra(self, script):
        """OCR engine for a non-Latin script, or None if its model isn't installed."""
        if script in self._extra or script in self.unavailable:
            return self._extra.get(script)
        try:
            from rapidocr import RapidOCR
            if not self.allow_download and not _model_file(EXTRA_SCRIPTS[script]).exists():
                raise FileNotFoundError(script)
            eng = RapidOCR(params=self._params(EXTRA_SCRIPTS[script]))
            # Recognise a blank strip so the model loads (or downloads) now, not mid-photo.
            eng(np.full((48, 160, 3), 255, dtype=np.uint8), use_det=False, use_cls=False)
            self._extra[script] = eng
        except Exception:
            self.unavailable.add(script)
            return None
        return self._extra[script]

    @cached_property
    def lang_detector(self):
        try:
            from lingua import Language, LanguageDetectorBuilder
        except ImportError:
            return None
        langs = [getattr(Language, n) for n in LANGUAGE_COUNTRIES if hasattr(Language, n)
                 and n not in ("CHINESE", "JAPANESE", "KOREAN")]
        return LanguageDetectorBuilder.from_languages(*langs).build()

    @staticmethod
    def _run(engine, arr, scale, script):
        res = engine(arr)
        if res is None or res.txts is None:
            return []
        out = []
        for box, text, score in zip(res.boxes, res.txts, res.scores):
            text = unicodedata.normalize("NFC", str(text).strip())
            if len(text) >= 2:
                out.append({"text": text, "score": round(float(score), 3),
                            "box": (np.asarray(box) / scale).round().tolist(), "model": script})
        return out

    def read(self, img, script_hints=None):
        """Return confident text lines [{text, score, box, model}].

        script_hints: {script name: probability} from CLIP; scripts with an extra model and
        enough probability are read with that model too, and so are all extra models
        when the default model sees text it can't read confidently.
        """
        if self.ocr is None:
            return []
        im = img.convert("RGB")
        scale = min(1.0, 1600 / max(im.size))
        if scale < 1:
            im = im.resize((int(im.width * scale), int(im.height * scale)))
        arr = np.asarray(im)[:, :, ::-1]
        runs = {"default": self._run(self.ocr, arr, scale, "default")}

        hinted = [s for s, p in sorted((script_hints or {}).items(), key=lambda kv: -kv[1])
                  if s in EXTRA_SCRIPTS and p >= 0.12][:2]
        weak = [l for l in runs["default"] if l["score"] < 0.8]
        no_text = (script_hints or {}).get("no visible text", 0.0)
        unreadable = (len(weak) >= max(1, len(runs["default"]) / 2)
                      or (not runs["default"] and script_hints is not None and no_text < 0.5))
        todo = hinted or (list(EXTRA_SCRIPTS) if unreadable else [])
        for script in todo:
            eng = self.extra(script)
            if eng is not None:
                try:
                    runs[script] = self._run(eng, arr, scale, script)
                except Exception:
                    self.unavailable.add(script)
                    self._extra.pop(script, None)

        # For each text region keep the reading the most confident model gave it.
        cands = sorted((l for r in runs.values() for l in r), key=lambda l: -l["score"] * len(l["text"]) ** 0.5)
        kept = []
        for l in cands:
            c = _center(l["box"])
            if any(_inside(c, k["box"]) or _inside(_center(k["box"]), l["box"]) for k in kept):
                continue
            kept.append(l)
        return [l for l in kept if l["score"] >= self.min_score]

    def clues(self, lines):
        if not lines:
            return []
        text = " ".join(l["text"] for l in lines)
        models = sorted({l["model"] for l in lines if l.get("model") not in (None, "default")})
        clues = [Clue(kind="ocr", title=f"Read {len(lines)} line(s) of text",
                      detail="“" + text[:160] + ("…" if len(text) > 160 else "") + "”"
                      + (f" (also read with the {', '.join(models)} model)" if models else ""))]
        groups = {}
        for ch in text:
            s = script_of(ch)
            if s:
                groups.setdefault(s, []).append(ch)
        if len(groups.get("Japanese", [])) >= 2:
            groups.pop("Chinese characters", None)  # kanji alongside kana means Japanese
        for script, chars in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            n = len(chars)
            if n < _MIN_CHARS.get(script, 6):
                continue
            if script != "Latin" and script in SCRIPT_COUNTRIES:
                single = len([w for w in SCRIPT_COUNTRIES[script].values() if w >= 1]) <= 2
                clues.append(Clue(
                    kind="script", title=f"{script} text",
                    detail=f"{n} characters in {script} script were read in the photo.",
                    strength=min(0.9, 0.5 + 0.03 * n) if single else min(0.75, 0.4 + 0.02 * n),
                    countries=SCRIPT_COUNTRIES[script], background=0.03 if single else 0.06))
            if script in _MULTI_LANGUAGE:
                clue = self._language(script, text, n)
                if clue:
                    clues.append(clue)
        clues += self._patterns(text)
        return clues

    def _language(self, script, text, n):
        if self.lang_detector is None:
            return None
        words = [w for w in re.findall(r"[^\W\d_]{2,}", text)
                 if all(script_of(c) == script for c in w)]
        if not words:
            return None
        conf = self.lang_detector.compute_language_confidence_values(" ".join(words))
        if not conf:
            return None
        best = conf[0]
        name = best.language.name
        strength = float(best.value) * min(1.0, n / 25)
        if name == "ENGLISH":  # English signage appears everywhere
            strength *= 0.5
        if strength <= 0.15 or name not in LANGUAGE_COUNTRIES:
            return None
        return Clue(kind="language", title=f"Text looks {name.title()}",
                    detail=f"Language detector: {best.value:.0%} {name.title()} from {n} letters of {script} text.",
                    strength=min(strength, 0.92), countries=LANGUAGE_COUNTRIES[name], background=0.1)

    def _patterns(self, text):
        out = []
        low = text.lower()
        tlds = set(re.findall(r"\b[a-z0-9-]{2,}(?:\.[a-z0-9-]+)*\.([a-z]{2,4})\b", low))
        # OCR often inserts spaces around dots; accept that only after "www".
        tlds |= set(re.findall(r"\bwww\s?\.\s?[a-z0-9-]+(?:\s?\.\s?[a-z0-9-]+)*?\s?\.\s?([a-z]{2})\b", low))
        for m in tlds:
            if m in TLD_GENERIC or len(m) != 2:
                continue
            code = TLD_EXCEPTIONS.get(m, m.upper())
            out.append(Clue(kind="domain", title=f"Web address ending .{m}",
                            detail=f"Country-code domain .{m} → {code}.",
                            strength=0.9, countries={code: 1}, background=0.03))
        for m in set(re.findall(r"\+\s?(\d{1,3})[\s\-(]", text)):
            for n in (3, 2, 1):
                codes = PHONE_PREFIXES.get(m[:n])
                if codes:
                    out.append(Clue(kind="phone", title=f"Phone number +{m[:n]}",
                                    detail=f"International dialling code +{m[:n]}.",
                                    strength=0.85, countries={c: 1 for c in codes},
                                    background=0.05))
                    break
        for marker, countries in CURRENCY_MARKERS.items():
            pat = re.escape(marker) if not marker.isalpha() else rf"\b{re.escape(marker)}\b"
            if re.search(pat, text):
                out.append(Clue(kind="currency", title=f"Currency sign {marker}",
                                detail=f"Prices in {marker}.", strength=0.6,
                                countries=countries, background=0.1))
        if re.search(r"\bmph\b", low):
            out.append(Clue(kind="units", title="Speeds in mph",
                            detail="Miles per hour are used in only a handful of countries.",
                            strength=0.7, countries=MPH_COUNTRIES, background=0.05))
        return out
