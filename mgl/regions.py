"""Grouped scouting regions mapped onto FC26 Player.nationality values."""

# Keys are stored on scout assignments. Labels match the scouting dropdown.
# Parent groups (europe, africa, asia) are unions of their subgroups plus
# leftover nations from that continent that are present in FC26.

BRITISH_ISLES = frozenset(
    {
        "England",
        "Scotland",
        "Wales",
        "Northern Ireland",
        "Republic of Ireland",
    }
)
NORDIC = frozenset(
    {
        "Denmark",
        "Finland",
        "Iceland",
        "Norway",
        "Sweden",
        "Faroe Islands",
    }
)
BALTIC = frozenset({"Estonia", "Latvia", "Lithuania"})
WESTERN_EUROPE = frozenset(
    {
        "Andorra",
        "Austria",
        "Belgium",
        "France",
        "Germany",
        "Gibraltar",
        "Liechtenstein",
        "Luxembourg",
        "Netherlands",
        "Switzerland",
    }
)
SOUTHERN_EUROPE = frozenset(
    {
        "Cyprus",
        "Greece",
        "Italy",
        "Malta",
        "Portugal",
        "Spain",
    }
)
EASTERN_EUROPE = frozenset(
    {
        "Belarus",
        "Bulgaria",
        "Czechia",
        "Hungary",
        "Moldova",
        "Poland",
        "Romania",
        "Russia",
        "Slovakia",
        "Ukraine",
    }
)
BALKANS = frozenset(
    {
        "Albania",
        "Bosnia and Herzegovina",
        "Croatia",
        "Kosovo",
        "Montenegro",
        "North Macedonia",
        "Serbia",
        "Slovenia",
    }
)
EUROPE_EXTRA = frozenset(
    {
        "Armenia",
        "Azerbaijan",
        "Georgia",
        "Israel",
        "Türkiye",
    }
)
EUROPE = (
    BRITISH_ISLES
    | NORDIC
    | BALTIC
    | WESTERN_EUROPE
    | SOUTHERN_EUROPE
    | EASTERN_EUROPE
    | BALKANS
    | EUROPE_EXTRA
)

SOUTH_AMERICA = frozenset(
    {
        "Argentina",
        "Bolivia",
        "Brazil",
        "Chile",
        "Colombia",
        "Ecuador",
        "Guyana",
        "Paraguay",
        "Peru",
        "Suriname",
        "Uruguay",
        "Venezuela",
    }
)

NORTH_CENTRAL_AMERICA = frozenset(
    {
        "Antigua and Barbuda",
        "Barbados",
        "Bermuda",
        "Canada",
        "Costa Rica",
        "Cuba",
        "Curacao",
        "Dominican Republic",
        "El Salvador",
        "Grenada",
        "Guatemala",
        "Haiti",
        "Honduras",
        "Jamaica",
        "Mexico",
        "Montserrat",
        "Panama",
        "Puerto Rico",
        "Saint Kitts and Nevis",
        "Saint Lucia",
        "Trinidad and Tobago",
        "United States",
    }
)

NORTH_AFRICA = frozenset(
    {
        "Algeria",
        "Egypt",
        "Libya",
        "Mauritania",
        "Morocco",
        "Tunisia",
    }
)
WEST_AFRICA = frozenset(
    {
        "Benin",
        "Burkina Faso",
        "Cabo Verde",
        "Côte d'Ivoire",
        "Gambia",
        "Ghana",
        "Guinea",
        "Guinea-Bissau",
        "Liberia",
        "Mali",
        "Niger",
        "Nigeria",
        "Senegal",
        "Sierra Leone",
        "Togo",
    }
)
CENTRAL_AFRICA = frozenset(
    {
        "Cameroon",
        "Central African Republic",
        "Chad",
        "Congo",
        "Congo DR",
        "Equatorial Guinea",
        "Gabon",
    }
)
EAST_AFRICA = frozenset(
    {
        "Burundi",
        "Comoros",
        "Kenya",
        "Madagascar",
        "Rwanda",
        "Somalia",
        "Tanzania",
        "Uganda",
    }
)
SOUTHERN_AFRICA = frozenset(
    {
        "Angola",
        "Malawi",
        "Mozambique",
        "Namibia",
        "South Africa",
        "Zambia",
        "Zimbabwe",
    }
)
AFRICA = NORTH_AFRICA | WEST_AFRICA | CENTRAL_AFRICA | EAST_AFRICA | SOUTHERN_AFRICA

EAST_ASIA = frozenset(
    {
        "China PR",
        "Chinese Taipei",
        "Hong Kong",
        "Japan",
        "Korea Republic",
    }
)
MIDDLE_EAST = frozenset(
    {
        "Iran",
        "Iraq",
        "Israel",
        "Jordan",
        "Lebanon",
        "Palestine",
        "Qatar",
        "Saudi Arabia",
        "Syria",
        "Türkiye",
        "United Arab Emirates",
        "Yemen",
    }
)
SOUTH_ASIA = frozenset(
    {
        "Afghanistan",
        "Bangladesh",
        "India",
        "Pakistan",
        "Sri Lanka",
    }
)
SOUTHEAST_ASIA = frozenset(
    {
        "Indonesia",
        "Malaysia",
        "Philippines",
        "Thailand",
    }
)
ASIA_EXTRA = frozenset({"Tajikistan", "Uzbekistan"})
ASIA = EAST_ASIA | MIDDLE_EAST | SOUTH_ASIA | SOUTHEAST_ASIA | ASIA_EXTRA

OCEANIA = frozenset(
    {
        "Australia",
        "New Caledonia",
        "New Zealand",
        "Vanuatu",
    }
)

REGION_NATIONS = {
    "europe": EUROPE,
    "british-isles": BRITISH_ISLES,
    "nordic": NORDIC,
    "baltic": BALTIC,
    "western-europe": WESTERN_EUROPE,
    "southern-europe": SOUTHERN_EUROPE,
    "eastern-europe": EASTERN_EUROPE,
    "balkans": BALKANS,
    "south-america": SOUTH_AMERICA,
    "north-central-america": NORTH_CENTRAL_AMERICA,
    "africa": AFRICA,
    "north-africa": NORTH_AFRICA,
    "west-africa": WEST_AFRICA,
    "central-africa": CENTRAL_AFRICA,
    "east-africa": EAST_AFRICA,
    "southern-africa": SOUTHERN_AFRICA,
    "asia": ASIA,
    "east-asia": EAST_ASIA,
    "middle-east": MIDDLE_EAST,
    "south-asia": SOUTH_ASIA,
    "southeast-asia": SOUTHEAST_ASIA,
    "oceania": OCEANIA,
}

REGION_MENU = (
    ("", (("anywhere", "Anywhere"),)),
    (
        "Europe",
        (
            ("europe", "Europe (all)"),
            ("british-isles", "British Isles"),
            ("nordic", "Nordic"),
            ("baltic", "Baltic"),
            ("western-europe", "Western Europe"),
            ("southern-europe", "Southern Europe"),
            ("eastern-europe", "Eastern Europe"),
            ("balkans", "Balkans"),
        ),
    ),
    (
        "Americas",
        (
            ("south-america", "South America"),
            ("north-central-america", "North & Central America"),
        ),
    ),
    (
        "Africa",
        (
            ("africa", "Africa (all)"),
            ("north-africa", "North Africa"),
            ("west-africa", "West Africa"),
            ("central-africa", "Central Africa"),
            ("east-africa", "East Africa"),
            ("southern-africa", "Southern Africa"),
        ),
    ),
    (
        "Asia",
        (
            ("asia", "Asia (all)"),
            ("east-asia", "East Asia"),
            ("middle-east", "Middle East"),
            ("south-asia", "South Asia"),
            ("southeast-asia", "Southeast Asia"),
        ),
    ),
    ("Oceania", (("oceania", "Oceania"),)),
)

REGION_LABELS = {
    "anywhere": "Anywhere",
    **{
        key: label
        for _group, items in REGION_MENU
        for key, label in items
    },
}

SCOUT_POSITIONS = ("GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST")


def region_keys():
    return tuple(REGION_NATIONS.keys())


def nations_for_region(region):
    region = (region or "").strip()
    if not region or region == "anywhere":
        return None
    if region in REGION_NATIONS:
        return REGION_NATIONS[region]
    return None


def region_label(region):
    region = (region or "").strip() or "anywhere"
    if region in REGION_LABELS:
        return REGION_LABELS[region]
    return region or "Anywhere"


def mapping_count():
    return sum(len(nations) for nations in REGION_NATIONS.values())


def unique_mapped_nations():
    mapped = set()
    for nations in REGION_NATIONS.values():
        mapped |= set(nations)
    return frozenset(mapped)


def region_option_count():
    return sum(len(items) for _group, items in REGION_MENU)
