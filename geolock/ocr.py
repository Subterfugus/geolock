"""Read text in the photo and turn it into clues (language, domains, phones, prices).

OCR uses RapidOCR (PaddleOCR PP-OCRv3 models in ONNX, Apache-2.0), which reads Latin
and Chinese text. Other scripts (Cyrillic, Arabic, Thai, Hangul...) are picked up by the
CLIP script detector and, if enabled, the vision-language model.
"""
import re
from functools import cached_property

import numpy as np

from .clues import Clue
from .countrymeta import (CURRENCY_MARKERS, LANGUAGE_COUNTRIES, MPH_COUNTRIES,
                          PHONE_PREFIXES, TLD_EXCEPTIONS, TLD_GENERIC)


def _script_of(ch):
    o = ord(ch)
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
        return "Han"
    if 0x3040 <= o <= 0x30FF:
        return "Kana"
    if 0xAC00 <= o <= 0xD7AF:
        return "Hangul"
    if ch.isalpha() and o < 0x250:
        return "Latin"
    return None


class TextReader:
    def __init__(self, min_score=0.6):
        self.min_score = min_score

    @cached_property
    def ocr(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            return None
        return RapidOCR()

    @cached_property
    def lang_detector(self):
        try:
            from lingua import Language, LanguageDetectorBuilder
        except ImportError:
            return None
        langs = [getattr(Language, n) for n in LANGUAGE_COUNTRIES if hasattr(Language, n)
                 and n != "CHINESE"]
        return LanguageDetectorBuilder.from_languages(*langs).build()

    def read(self, img):
        """Return a list of {text, score, box} for confident text lines."""
        if self.ocr is None:
            return []
        im = img.convert("RGB")
        scale = min(1.0, 1600 / max(im.size))
        if scale < 1:
            im = im.resize((int(im.width * scale), int(im.height * scale)))
        result, _ = self.ocr(np.asarray(im)[:, :, ::-1])
        lines = []
        for box, text, score in result or []:
            text = text.strip()
            if float(score) >= self.min_score and len(text) >= 2:
                lines.append({"text": text, "score": round(float(score), 3),
                              "box": (np.asarray(box) / scale).round().tolist()})
        return lines

    def clues(self, lines):
        if not lines:
            return []
        text = " ".join(l["text"] for l in lines)
        clues = [Clue(kind="ocr", title=f"Read {len(lines)} line(s) of text",
                      detail="“" + text[:160] + ("…" if len(text) > 160 else "") + "”")]
        scripts = {}
        for ch in text:
            s = _script_of(ch)
            if s:
                scripts[s] = scripts.get(s, 0) + 1
        if scripts.get("Kana", 0) >= 2:
            clues.append(Clue(kind="script", title="Japanese kana in text",
                              detail="Hiragana/katakana characters are used almost only in Japan.",
                              strength=0.85, countries={"JP": 1}, background=0.03))
        elif scripts.get("Han", 0) >= 2:
            clues.append(Clue(kind="script", title="Chinese characters in text",
                              detail="Han characters point to Greater China, Japan or Chinese communities.",
                              strength=min(0.8, 0.3 + 0.1 * scripts["Han"]),
                              countries=LANGUAGE_COUNTRIES["CHINESE"], background=0.05))
        latin = " ".join(re.findall(r"[^\W\d_]{2,}", text))
        if scripts.get("Latin", 0) >= 10 and self.lang_detector is not None:
            conf = self.lang_detector.compute_language_confidence_values(latin)
            if conf:
                best = conf[0]
                name = best.language.name
                n_letters = scripts["Latin"]
                strength = float(best.value) * min(1.0, n_letters / 25)
                if name == "ENGLISH":  # English signage appears everywhere
                    strength *= 0.5
                if strength > 0.15 and name in LANGUAGE_COUNTRIES:
                    clues.append(Clue(
                        kind="language", title=f"Text looks {name.title()}",
                        detail=(f"Language detector: {best.value:.0%} {name.title()} from "
                                f"{n_letters} letters of text."),
                        strength=min(strength, 0.92), countries=LANGUAGE_COUNTRIES[name],
                        background=0.1))
        clues += self._patterns(text)
        return clues

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
