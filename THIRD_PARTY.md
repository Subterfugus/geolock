# Third-party models, data and code

| Component | Used for | Licence | Where it comes from |
|---|---|---|---|
| CLIP ViT-L/14 (OpenAI) | Image embedding, zero-shot clues | MIT | Downloaded at setup from Hugging Face `openai/clip-vit-large-patch14` |
| GeoCLIP (Vivanco Cepeda, Nayak, Shah; NeurIPS 2023) | Image → GPS embedding, 100k-location gallery | MIT | `geoclip` pip package, installed at setup |
| Qwen2.5-VL-7B-Instruct (optional) | Deep analysis | Apache-2.0 | Downloaded and converted at setup with `--vlm` |
| RapidOCR / PaddleOCR PP-OCRv6 + PP-OCRv5 language models | Reading text | Apache-2.0 | `rapidocr` pip package; extra language models downloaded at setup from RapidAI's ModelScope mirror |
| Lingua | Language identification | Apache-2.0 | `lingua-language-detector` pip package |
| GeoNames cities (via `reverse_geocoder`) | Nearest named place | CC BY 4.0 (GeoNames) | `reverse_geocoder` pip package |
| Natural Earth admin-0 / admin-1 | Offline map, country and region lookup | Public domain | Simplified copies in `geolock/data/` (see `tools/build_geodata.py`) |
| Leaflet 1.9.4 | Map UI | BSD-2-Clause | Vendored in `geolock/web/vendor/` |
| Leaflet.heat 0.2.0 | Heatmap | BSD-2-Clause | Vendored in `geolock/web/vendor/` |
| OpenVINO | Inference runtime | Apache-2.0 | pip |
