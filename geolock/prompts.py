"""Text prompts for CLIP zero-shot clue detection.

Text embeddings for every prompt here are computed once at setup time
(``python -m geolock.setup_models``) and stored in models/prompts.npz, so the
runtime never needs the CLIP text encoder. If you edit this file, re-run setup with
``--prompts-only``.

Each attribute is a list of options. An option has a label, one or more prompts
(their embeddings are averaged), and optionally ``countries``: where that option is
typical. Options without ``countries`` only describe the scene and add no evidence.
"""

COUNTRY_TEMPLATES = [
    "a street view photo taken in {}.",
    "a photo taken in {}.",
    "a landscape photo of {}.",
    "a photo of a city in {}.",
    "a photo of a road in {}.",
]

_POST_SOVIET = {c: 1 for c in "RU UA BY KZ KG UZ TJ TM GE AM AZ MD LT LV EE MN".split()}
_EASTERN_BLOC = {c: 1 for c in "PL CZ SK HU RO BG RS BA HR SI MK ME AL DE".split()}
_EASTERN_BLOC["DE"] = 0.3
_EAST_ASIA = {c: 1 for c in "CN JP KR TW HK MO KP".split()}
_SE_ASIA = {c: 1 for c in "TH VN MY ID PH KH LA MM SG".split()}
_ISLAMIC = {c: 1 for c in ("SA AE EG MA DZ TN LY JO IQ SY OM YE KW QA BH IR PK AF TR "
                           "UZ TJ TM AZ BD ID MY SD MR ML NE SN").split()}
_LATAM = {c: 1 for c in ("MX GT HN SV NI CR PA CU DO PR CO VE EC PE BO PY UY AR CL "
                         "BR").split()}
_N_AMERICA = {"US": 1, "CA": 1}
_ANGLO_SUBURB = {"US": 1, "CA": 1, "AU": 0.7, "NZ": 0.7}
_NORDIC = {c: 1 for c in "NO SE FI DK IS FO GL".split()}
_MEDITERRANEAN = {c: 1 for c in "ES PT IT GR HR MT CY FR TR MA TN".split()}
_SOUTH_ASIA = {c: 1 for c in "IN PK BD NP LK".split()}
_SUBSAHARAN = {c: 1 for c in ("NG GH KE TZ UG ET ZA ZM ZW MW MZ AO CM CI SN ML BF NE "
                              "TD SD SS CD CG GA RW BI SO BW NA LS SZ MG GN SL LR TG BJ "
                              "ER DJ CF GQ GM GW MR").split()}
_YELLOW_CENTRELINE = {c: 1 for c in ("US CA MX BR AR CL CO PE VE EC BO PY UY GT HN SV NI "
                                     "CR PA AU NZ JP KR TH").split()}
_YELLOW_CENTRELINE["AU"] = 0.2
_YELLOW_CENTRELINE["NZ"] = 0.2

ATTRIBUTES = {
    "setting": {
        "title": "Setting",
        "options": [
            {"label": "city centre", "prompts": ["a photo of a busy city centre street.",
                                                 "a photo of downtown buildings."]},
            {"label": "residential street", "prompts": ["a photo of a residential street with houses."]},
            {"label": "rural road", "prompts": ["a photo of a rural road through the countryside."]},
            {"label": "highway", "prompts": ["a photo of a multi-lane highway."]},
            {"label": "farmland", "prompts": ["a photo of farmland and fields."]},
            {"label": "mountains", "prompts": ["a photo of mountains."]},
            {"label": "coast or beach", "prompts": ["a photo of a beach and the sea.",
                                                    "a photo of a coastline."]},
            {"label": "desert", "prompts": ["a photo of a desert."]},
            {"label": "forest", "prompts": ["a photo of a forest."]},
            {"label": "village", "prompts": ["a photo of a small village."]},
            {"label": "famous landmark", "prompts": ["a photo of a famous tourist landmark."]},
            {"label": "indoors", "prompts": ["a photo taken indoors."]},
        ],
    },
    "climate": {
        "title": "Climate and vegetation",
        "options": [
            {"label": "tropical, palm trees", "prompts": ["a photo of tropical vegetation with palm trees."]},
            {"label": "arid desert", "prompts": ["a photo of a dry arid landscape with sparse vegetation."]},
            {"label": "Mediterranean scrub", "prompts": ["a photo of a dry Mediterranean landscape with olive trees and scrub."]},
            {"label": "temperate green", "prompts": ["a photo of green temperate deciduous trees and lawns."]},
            {"label": "boreal conifers", "prompts": ["a photo of a boreal forest of pine and spruce trees."]},
            {"label": "savanna", "prompts": ["a photo of savanna with red soil and acacia trees."]},
            {"label": "grassland steppe", "prompts": ["a photo of a vast treeless grassland steppe."]},
            {"label": "snow and winter", "prompts": ["a photo of a snowy winter landscape."]},
            {"label": "rice paddies", "prompts": ["a photo of rice paddies."]},
        ],
    },
    "architecture": {
        "title": "Architecture",
        "options": [
            {"label": "modern skyscrapers", "prompts": ["a photo of modern glass skyscrapers."]},
            {"label": "Soviet-era apartment blocks", "countries": {**_POST_SOVIET, **_EASTERN_BLOC},
             "prompts": ["a photo of Soviet-era concrete panel apartment blocks."]},
            {"label": "European historic old town", "prompts": ["a photo of a historic European old town with old stone buildings."]},
            {"label": "North American suburban houses", "countries": _ANGLO_SUBURB,
             "prompts": ["a photo of North American suburban wooden houses with front lawns."]},
            {"label": "East Asian buildings", "countries": _EAST_ASIA,
             "prompts": ["a photo of an East Asian city street with dense signage."]},
            {"label": "Southeast Asian shophouses", "countries": _SE_ASIA,
             "prompts": ["a photo of Southeast Asian shophouses and tangled power lines."]},
            {"label": "Islamic architecture", "countries": _ISLAMIC,
             "prompts": ["a photo of a mosque with domes and minarets.",
                         "a photo of Middle Eastern sand-coloured buildings."]},
            {"label": "Latin American colourful houses", "countries": _LATAM,
             "prompts": ["a photo of colourful Latin American houses with flat roofs."]},
            {"label": "Scandinavian wooden houses", "countries": _NORDIC,
             "prompts": ["a photo of red and white Scandinavian wooden houses."]},
            {"label": "Mediterranean whitewashed houses", "countries": _MEDITERRANEAN,
             "prompts": ["a photo of whitewashed Mediterranean houses with terracotta roofs."]},
            {"label": "South Asian street", "countries": _SOUTH_ASIA,
             "prompts": ["a photo of a crowded South Asian street with auto-rickshaws."]},
            {"label": "corrugated metal roofs", "countries": _SUBSAHARAN,
             "prompts": ["a photo of houses with corrugated metal roofs in Africa."]},
            {"label": "no distinctive buildings", "prompts": ["a photo of nature with no buildings."]},
        ],
    },
    "road": {
        "title": "Road markings",
        "options": [
            {"label": "yellow centre line", "countries": _YELLOW_CENTRELINE,
             "prompts": ["a road with a yellow center line."]},
            {"label": "white centre lines", "prompts": ["a road with white dashed center lines."]},
            {"label": "unpaved dirt road", "prompts": ["an unpaved dirt road."]},
            {"label": "cobblestones", "prompts": ["a cobblestone street."]},
            {"label": "no road visible", "prompts": ["a photo with no road."]},
        ],
    },
    "script": {
        "title": "Writing system",
        "options": [
            {"label": "no visible text", "prompts": ["a photo with no text or signs."]},
            {"label": "Latin", "prompts": ["a sign with text written in the Latin alphabet."]},
            {"label": "Cyrillic", "prompts": ["a sign with text written in Cyrillic script."]},
            {"label": "Greek", "prompts": ["a sign with text written in the Greek alphabet."]},
            {"label": "Arabic", "prompts": ["a sign with text written in Arabic script."]},
            {"label": "Hebrew", "prompts": ["a sign with text written in Hebrew."]},
            {"label": "Devanagari", "prompts": ["a sign with text written in Hindi Devanagari script."]},
            {"label": "Bengali", "prompts": ["a sign with text written in Bengali script."]},
            {"label": "Tamil", "prompts": ["a sign with text written in Tamil script."]},
            {"label": "Thai", "prompts": ["a sign with text written in Thai script."]},
            {"label": "Lao", "prompts": ["a sign with text written in Lao script."]},
            {"label": "Khmer", "prompts": ["a sign with text written in Khmer script."]},
            {"label": "Burmese", "prompts": ["a sign with text written in Burmese script."]},
            {"label": "Georgian", "prompts": ["a sign with text written in Georgian script."]},
            {"label": "Armenian", "prompts": ["a sign with text written in Armenian script."]},
            {"label": "Korean Hangul", "prompts": ["a sign with text written in Korean Hangul."]},
            {"label": "Japanese", "prompts": ["a sign with text written in Japanese."]},
            {"label": "Chinese characters", "prompts": ["a sign with text written in Chinese characters."]},
            {"label": "Ethiopic", "prompts": ["a sign with text written in Ethiopian Amharic script."]},
            {"label": "Sinhala", "prompts": ["a sign with text written in Sinhala script."]},
        ],
    },
}


def all_prompt_lists(country_names):
    """Every prompt group that needs a text embedding, keyed by a stable name."""
    groups = {}
    for i, name in enumerate(country_names):
        groups[f"country/{i}"] = [t.format(name) for t in COUNTRY_TEMPLATES]
    for key, attr in ATTRIBUTES.items():
        for j, opt in enumerate(attr["options"]):
            groups[f"attr/{key}/{j}"] = opt["prompts"]
    return groups
