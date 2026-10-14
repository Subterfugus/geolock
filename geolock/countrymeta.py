"""Hand-curated facts that tie visible clues to countries.

Codes are ISO 3166-1 alpha-2, matching the ``iso2`` property in data/countries.geojson.
Weights in the language table: 1.0 = official / dominant on signage, 0.5 = common
second language or large minority. Everything not listed gets the clue's background
likelihood, so these tables only need to name where a clue is *typical*.
"""

# Countries and territories that drive on the left.
LEFT_DRIVING = set("""
AG AI AU BB BD BM BN BS BT BW CK CY DM FJ FK GB GD GG GY HK ID IE IM IN IO JE JM JP
KE KI KN KY LC LK LS MO MS MT MU MV MW MY MZ NA NF NP NR NU NZ PG PK PN SB SC SG SH
SR SZ TC TH TL TO TT TV TZ UG VC VG VI WS ZA ZM ZW
""".split())

# Lingua language name -> {iso2: weight}
LANGUAGE_COUNTRIES = {
    "AFRIKAANS": {"ZA": 1, "NA": 1},
    "ALBANIAN": {"AL": 1, "XK": 1, "MK": 0.5, "ME": 0.5},
    "AZERBAIJANI": {"AZ": 1},
    "BASQUE": {"ES": 1, "FR": 0.3},
    "BOKMAL": {"NO": 1},
    "NYNORSK": {"NO": 1},
    "BOSNIAN": {"BA": 1},
    "CATALAN": {"ES": 1, "AD": 1, "FR": 0.2},
    "CHINESE": {"CN": 1, "TW": 1, "HK": 1, "MO": 1, "SG": 0.7, "MY": 0.4},
    "CROATIAN": {"HR": 1, "BA": 0.7},
    "CZECH": {"CZ": 1},
    "DANISH": {"DK": 1, "GL": 0.7, "FO": 0.7},
    "DUTCH": {"NL": 1, "BE": 1, "SR": 1, "CW": 1, "AW": 1, "SX": 1},
    "ENGLISH": {"US": 1, "GB": 1, "CA": 1, "AU": 1, "NZ": 1, "IE": 1, "ZA": 0.8,
                "IN": 0.6, "SG": 0.8, "PH": 0.7, "NG": 0.8, "KE": 0.7, "GH": 0.8,
                "UG": 0.7, "ZM": 0.8, "ZW": 0.8, "BW": 0.8, "JM": 1, "TT": 1,
                "BS": 1, "BB": 1, "MT": 0.7, "HK": 0.6, "MY": 0.5, "PK": 0.5,
                "LK": 0.5, "BZ": 1, "GY": 1, "LR": 1, "SL": 1, "PG": 0.7, "FJ": 0.8,
                "NA": 0.7, "TZ": 0.5, "MW": 0.7, "RW": 0.4, "CM": 0.4, "PR": 0.5},
    "ESTONIAN": {"EE": 1},
    "FINNISH": {"FI": 1},
    "FRENCH": {"FR": 1, "BE": 1, "CH": 0.7, "LU": 1, "MC": 1, "CA": 0.5, "SN": 1,
               "CI": 1, "ML": 1, "BF": 1, "NE": 1, "GN": 1, "BJ": 1, "TG": 1, "CM": 0.8,
               "GA": 1, "CG": 1, "CD": 1, "MG": 0.8, "HT": 1, "MA": 0.6, "DZ": 0.6,
               "TN": 0.6, "TD": 0.8, "CF": 1, "DJ": 0.7, "KM": 0.7, "BI": 0.6,
               "RW": 0.3, "LB": 0.4, "NC": 1, "PF": 1, "MU": 0.5, "SC": 0.4, "VU": 0.5},
    "GANDA": {"UG": 1},
    "GERMAN": {"DE": 1, "AT": 1, "CH": 1, "LI": 1, "LU": 0.7, "BE": 0.2, "IT": 0.2,
               "NA": 0.2},
    "HUNGARIAN": {"HU": 1, "RO": 0.2, "SK": 0.2, "RS": 0.1},
    "ICELANDIC": {"IS": 1},
    "INDONESIAN": {"ID": 1},
    "IRISH": {"IE": 1},
    "ITALIAN": {"IT": 1, "SM": 1, "VA": 1, "CH": 0.5},
    "LATIN": {"VA": 0.5},
    "LATVIAN": {"LV": 1},
    "LITHUANIAN": {"LT": 1},
    "MALAY": {"MY": 1, "BN": 1, "SG": 0.6, "ID": 0.5},
    "MAORI": {"NZ": 1},
    "POLISH": {"PL": 1},
    "PORTUGUESE": {"PT": 1, "BR": 1, "AO": 1, "MZ": 1, "CV": 1, "GW": 1, "ST": 1,
                   "TL": 0.6, "MO": 0.3},
    "ROMANIAN": {"RO": 1, "MD": 1},
    "SHONA": {"ZW": 1},
    "SLOVAK": {"SK": 1},
    "SLOVENE": {"SI": 1},
    "SOMALI": {"SO": 1, "DJ": 0.5, "ET": 0.3, "SOL": 1},
    "SOTHO": {"LS": 1, "ZA": 0.7},
    "SPANISH": {"ES": 1, "MX": 1, "AR": 1, "CO": 1, "PE": 1, "VE": 1, "CL": 1,
                "EC": 1, "GT": 1, "CU": 1, "BO": 1, "DO": 1, "HN": 1, "PY": 1,
                "SV": 1, "NI": 1, "CR": 1, "PA": 1, "UY": 1, "PR": 1, "GQ": 1,
                "US": 0.3, "AD": 0.5},
    "SWAHILI": {"TZ": 1, "KE": 1, "UG": 0.4, "CD": 0.3},
    "SWEDISH": {"SE": 1, "FI": 0.4, "AX": 1},
    "TAGALOG": {"PH": 1},
    "TSONGA": {"ZA": 1, "MZ": 0.5},
    "TSWANA": {"BW": 1, "ZA": 0.7},
    "TURKISH": {"TR": 1, "CY": 0.5, "CYN": 1},
    "VIETNAMESE": {"VN": 1},
    "WELSH": {"GB": 1},
    "XHOSA": {"ZA": 1},
    "YORUBA": {"NG": 1, "BJ": 0.5},
    "ZULU": {"ZA": 1},
}

# Writing system -> {iso2: weight}. Latin is everywhere, so it carries no evidence.
SCRIPT_COUNTRIES = {
    "Cyrillic": {"RU": 1, "UA": 1, "BY": 1, "BG": 1, "RS": 1, "MK": 1, "KZ": 1,
                 "KG": 1, "MN": 1, "TJ": 1, "ME": 0.6, "BA": 0.6},
    "Greek": {"GR": 1, "CY": 1},
    "Arabic": {"SA": 1, "AE": 1, "EG": 1, "MA": 1, "DZ": 1, "TN": 1, "LY": 1, "JO": 1,
               "IQ": 1, "SY": 1, "LB": 1, "OM": 1, "YE": 1, "KW": 1, "QA": 1, "BH": 1,
               "SD": 1, "IR": 1, "PK": 1, "AF": 1, "MR": 1, "PS": 1},
    "Hebrew": {"IL": 1, "PS": 0.3},
    "Devanagari": {"IN": 1, "NP": 1},
    "Bengali": {"BD": 1, "IN": 0.5},
    "Tamil": {"IN": 0.6, "LK": 1, "SG": 0.3},
    "Thai": {"TH": 1},
    "Lao": {"LA": 1},
    "Khmer": {"KH": 1},
    "Burmese": {"MM": 1},
    "Georgian": {"GE": 1},
    "Armenian": {"AM": 1},
    "Korean Hangul": {"KR": 1, "KP": 1},
    "Japanese": {"JP": 1},
    "Chinese characters": {"CN": 1, "TW": 1, "HK": 1, "MO": 1, "SG": 0.6, "JP": 0.4},
    "Ethiopic": {"ET": 1, "ER": 1},
    "Sinhala": {"LK": 1},
}

# Country-code top-level domains whose code differs from ISO alpha-2.
TLD_EXCEPTIONS = {"uk": "GB"}
# Generic TLDs that look like country codes but are used worldwide.
TLD_GENERIC = {"co", "tv", "io", "me", "ai", "fm", "ly", "to", "ws", "cc", "gg", "nu",
               "la", "app", "dev", "com", "net", "org", "edu", "gov", "info", "biz"}

# International dialling prefixes (longest match wins).
PHONE_PREFIXES = {
    "1": ["US", "CA"], "7": ["RU", "KZ"], "20": ["EG"], "27": ["ZA"], "30": ["GR"],
    "31": ["NL"], "32": ["BE"], "33": ["FR"], "34": ["ES"], "36": ["HU"], "39": ["IT"],
    "40": ["RO"], "41": ["CH"], "43": ["AT"], "44": ["GB"], "45": ["DK"], "46": ["SE"],
    "47": ["NO"], "48": ["PL"], "49": ["DE"], "51": ["PE"], "52": ["MX"], "53": ["CU"],
    "54": ["AR"], "55": ["BR"], "56": ["CL"], "57": ["CO"], "58": ["VE"], "60": ["MY"],
    "61": ["AU"], "62": ["ID"], "63": ["PH"], "64": ["NZ"], "65": ["SG"], "66": ["TH"],
    "81": ["JP"], "82": ["KR"], "84": ["VN"], "86": ["CN"], "90": ["TR"], "91": ["IN"],
    "92": ["PK"], "93": ["AF"], "94": ["LK"], "95": ["MM"], "98": ["IR"], "212": ["MA"],
    "213": ["DZ"], "216": ["TN"], "234": ["NG"], "254": ["KE"], "255": ["TZ"],
    "256": ["UG"], "351": ["PT"], "352": ["LU"], "353": ["IE"], "354": ["IS"],
    "356": ["MT"], "357": ["CY"], "358": ["FI"], "359": ["BG"], "370": ["LT"],
    "371": ["LV"], "372": ["EE"], "380": ["UA"], "381": ["RS"], "385": ["HR"],
    "386": ["SI"], "420": ["CZ"], "421": ["SK"], "852": ["HK"], "886": ["TW"],
    "966": ["SA"], "971": ["AE"], "972": ["IL"], "974": ["QA"],
}

# Currency markers seen on price tags and shop signs.
CURRENCY_MARKERS = {
    "€": {"DE": 1, "FR": 1, "IT": 1, "ES": 1, "NL": 1, "BE": 1, "AT": 1, "PT": 1,
          "IE": 1, "FI": 1, "GR": 1, "SK": 1, "SI": 1, "EE": 1, "LV": 1, "LT": 1,
          "LU": 1, "MT": 1, "CY": 1, "HR": 1, "ME": 0.7, "XK": 0.7},
    "£": {"GB": 1, "IM": 1, "JE": 1, "GG": 1, "FK": 1, "GI": 1, "EG": 0.3},
    "₹": {"IN": 1}, "₩": {"KR": 1}, "฿": {"TH": 1}, "₱": {"PH": 1}, "₫": {"VN": 1},
    "₺": {"TR": 1}, "₽": {"RU": 1}, "₴": {"UA": 1}, "₦": {"NG": 1}, "₪": {"IL": 1},
    "₸": {"KZ": 1}, "₾": {"GE": 1}, "R$": {"BR": 1}, "zł": {"PL": 1}, "Kč": {"CZ": 1},
    "Ft": {"HU": 0.7}, "lei": {"RO": 0.7, "MD": 0.7}, "CHF": {"CH": 1, "LI": 1},
    "RM": {"MY": 0.8}, "Rp": {"ID": 1}, "S$": {"SG": 1}, "HK$": {"HK": 1},
    "NT$": {"TW": 1}, "A$": {"AU": 1}, "NZ$": {"NZ": 1}, "C$": {"CA": 0.8},
    "¥": {"JP": 1, "CN": 1},
}

# Speed units: miles per hour is rare.
MPH_COUNTRIES = {"US": 1, "GB": 1, "LR": 1, "PR": 1, "BS": 1, "BZ": 1, "AG": 1,
                 "KN": 1, "LC": 1, "VC": 1, "GD": 1, "DM": 1, "KY": 1, "VG": 1,
                 "VI": 1, "FK": 1, "IM": 1, "JE": 1, "GG": 1, "WS": 1, "MM": 0.3}
