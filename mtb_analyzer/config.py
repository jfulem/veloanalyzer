import os

from rich.console import Console

console = Console()

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.normpath(os.path.join(_HERE, "..", ".mtb_cache"))
CACHE_MAX_AGE_DAYS = 7
XCODATA_BASE = "https://www.xcodata.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

FLAG = {
    "AUT": "🇦🇹", "CZE": "🇨🇿", "SVK": "🇸🇰", "HUN": "🇭🇺",
    "ITA": "🇮🇹", "POL": "🇵🇱", "BEL": "🇧🇪", "GER": "🇩🇪",
    "IRL": "🇮🇪", "FRA": "🇫🇷", "SUI": "🇨🇭", "NED": "🇳🇱",
    "GBR": "🇬🇧", "ESP": "🇪🇸", "SWE": "🇸🇪", "NOR": "🇳🇴",
    "DEN": "🇩🇰", "USA": "🇺🇸", "CAN": "🇨🇦", "SLO": "🇸🇮",
    "CRO": "🇭🇷", "ROM": "🇷🇴", "POR": "🇵🇹", "AUS": "🇦🇺",
    "NZL": "🇳🇿", "RSA": "🇿🇦", "JPN": "🇯🇵", "BRA": "🇧🇷",
    "ARG": "🇦🇷", "COL": "🇨🇴", "CHI": "🇨🇱", "SRB": "🇷🇸",
    "BUL": "🇧🇬", "GRE": "🇬🇷", "ISR": "🇮🇱", "LUX": "🇱🇺",
    "MEX": "🇲🇽", "URU": "🇺🇾", "TUR": "🇹🇷", "UKR": "🇺🇦",
    "LTU": "🇱🇹", "LVA": "🇱🇻", "EST": "🇪🇪",
}

COUNTRY_NORMALIZE = {
    "österreich - austria": "AUT", "austria": "AUT", "österreich": "AUT",
    "czech republic": "CZE", "czechia": "CZE",
    "slovakia": "SVK", "slovensko": "SVK",
    "hungary": "HUN", "maďarsko": "HUN",
    "italy": "ITA", "itálie": "ITA",
    "poland": "POL", "polsko": "POL",
    "belgium": "BEL", "belgie": "BEL",
    "germany": "GER", "německo": "GER",
    "ireland": "IRL", "irsko": "IRL",
    "france": "FRA", "frankreich": "FRA",
    "switzerland": "SUI", "schweiz": "SUI",
    "netherlands": "NED", "holland": "NED",
    "great britain": "GBR", "united kingdom": "GBR",
    "spain": "ESP", "španělsko": "ESP",
    "sweden": "SWE", "dänemark": "DEN", "denmark": "DEN",
    "norway": "NOR", "norwegen": "NOR",
    "united states of america": "USA", "usa": "USA",
    "canada": "CAN",
    "slovenia": "SLO", "slovinsko": "SLO",
    "croatia": "CRO",
    "romania": "ROM",
    "portugal": "POR",
    "australia": "AUS",
    "new zealand": "NZL",
    "south africa": "RSA",
    "japan": "JPN",
    "brazil": "BRA",
    "argentina": "ARG",
    "colombia": "COL",
    "chile": "CHI",
    "serbia": "SRB",
    "bulgaria": "BUL",
    "greece": "GRE",
    "israel": "ISR",
    "luxembourg": "LUX",
    "mexico": "MEX",
    "turkey": "TUR",
    "ukraine": "UKR",
    "lithuania": "LTU", 
    "latvia": "LVA", 
    "estonia": "EST",
    "finland": "FIN", 
    "suomi": "FIN",
    "russia": "RUS", 
    "ruská federace": "RUS", 
    "rusko": "RUS",
}

# Known typos in start lists: "Typo Full Name" → ("CorrectFirst", "CorrectLast")
NAME_CORRECTIONS: dict[str, tuple[str, str]] = {
    "Dwnis Vašíček": ("Denis", "Vašíček"),
    "Vojtěch Zaloha": ("Vojtěch", "Záloha")
}

CATEGORY_ALIASES = {
    "junioren": "Juniors",
    "amateure": "Amateur",
    "damen":    "Women",
    "herren":   "Men",
    "elit":     "Elite",
    "junior":   "Juniors",
    "amateur":  "Amateur",
}

# ISO 3166-1 alpha-2 → IOC alpha-3 (used by raceresult flag URLs)
ISO2_TO_IOC = {
    "AT": "AUT", "DE": "GER", "CH": "SUI", "FR": "FRA", "IT": "ITA",
    "CZ": "CZE", "SK": "SVK", "HU": "HUN", "PL": "POL", "SI": "SLO",
    "HR": "CRO", "BE": "BEL", "NL": "NED", "GB": "GBR", "ES": "ESP",
    "SE": "SWE", "NO": "NOR", "DK": "DEN", "IE": "IRL", "PT": "POR",
    "US": "USA", "CA": "CAN", "AU": "AUS", "NZ": "NZL", "ZA": "RSA",
    "JP": "JPN", "BR": "BRA", "AR": "ARG", "CO": "COL", "CL": "CHI",
    "RS": "SRB", "BG": "BUL", "GR": "GRE", "IL": "ISR", "LU": "LUX",
    "MX": "MEX", "TR": "TUR", "UA": "UKR", "RO": "ROM", "LT": "LTU",
    "LV": "LVA", "EE": "EST", "FI": "FIN", "RU": "RUS",
}

# Reverse: IOC alpha-3 → lowercase ISO2 (for flagcdn.com URLs)
IOC_TO_ISO2 = {ioc: iso2.lower() for iso2, ioc in ISO2_TO_IOC.items()}
