BOARD_4L_CAPACITY = 280
BOARD_5L_CAPACITY = 350


# One authoritative list drives the non-Auckland workbook rows, board forecast
# rows, route-detail images, and the desktop app's route-group matching.  A new
# standalone city normally needs only one entry here.
NON_AUCKLAND_STATION_SPECS = [
    {"code": "HMT", "display": "Hamilton"},
    {"code": "TRG", "display": "Tauranga", "forecast_group": "TRG/RTR"},
    {"code": "RTR", "display": "Rotorua", "forecast_group": "TRG/RTR"},
    {"code": "TPO"},
    {"code": "NPL", "display": "Napier", "forecast_group": "NPL/HST", "message_group": "NPL_HST"},
    {"code": "HST", "display": "Hastings", "forecast_group": "NPL/HST", "message_group": "NPL_HST"},
    {
        "code": "PMN",
        "aliases": ("PMNV2", "Palmerston NorthV2"),
    },
    {
        "code": "WLTV2",
        "aliases": ("WLT", "AKL-DC"),
    },
    {"code": "WGR", "include_in_forecast": False},
    {
        "code": "NPMV2",
        "display": "New PlymouthV2",
        "aliases": ("New PlymouthV2",),
    },
    {
        "code": "WGU",
        "display": "Whanganui",
        "aliases": ("Whanganui",),
    },
    {
        "code": "GSB",
        "display": "Gisborne",
        "aliases": ("Gisborne",),
    },
    {
        "code": "CHC",
        "display": "Christchurch",
        "aliases": ("Christchurch",),
    },
    {"code": "CHCV2"},
    {
        "code": "DUD",
        "display": "Dunedin",
        "aliases": ("Dunedin",),
    },
]


def _ordered_groups(group_key):
    groups = {}
    for spec in NON_AUCKLAND_STATION_SPECS:
        if group_key == "forecast_group" and not spec.get("include_in_forecast", True):
            continue
        group_name = spec.get(group_key, spec["code"])
        groups.setdefault(group_name, []).append(spec["code"])
    return [tuple(codes) for codes in groups.values()]


def _message_station_groups():
    groups = {}
    for spec in NON_AUCKLAND_STATION_SPECS:
        group_name = spec.get("message_group", spec["code"])
        station_names = [spec["code"], *spec.get("aliases", ())]
        target = groups.setdefault(group_name, [])
        for station_name in station_names:
            normalized = station_name.upper()
            if normalized not in target:
                target.append(normalized)
    return {name: tuple(stations) for name, stations in groups.items()}


NON_AUCKLAND_STATIONS = [spec["code"] for spec in NON_AUCKLAND_STATION_SPECS]
BOARD_FORECAST_GROUPS = _ordered_groups("forecast_group")
STATION_ALIASES = {
    spec["code"]: [spec["code"], *spec.get("aliases", ())]
    for spec in NON_AUCKLAND_STATION_SPECS
}
STATION_DISPLAY_ALIASES = {
    spec["code"]: spec["display"]
    for spec in NON_AUCKLAND_STATION_SPECS
    if spec.get("display")
}
STATION_OVERVIEW_GROUPS = {
    spec["code"]: tuple(tuple(group) for group in spec["overview_groups"])
    for spec in NON_AUCKLAND_STATION_SPECS
    if spec.get("overview_groups")
}
STATION_OVERVIEW_LABELS = {
    spec["code"]: "/".join(
        group[0] for group in STATION_OVERVIEW_GROUPS.get(spec["code"], ())
    )
    or spec["code"]
    for spec in NON_AUCKLAND_STATION_SPECS
}
STATION_CODES_BY_OVERVIEW_LABEL = {
    label: station
    for station, label in STATION_OVERVIEW_LABELS.items()
}
PROVINCE_STATIONS_BY_MESSAGE = _message_station_groups()


# Supplier route groups are explicit business rules.  Never infer them from a
# shared numeric prefix: related route codes can belong to different suppliers
# or drivers (for example, 501C belongs to PANDA, not EMPIRE COURIER's 501 group).
SUPPLIER_ROUTE_GROUPS = {
    "EMPIRE COURIER": [
        ("101", "102", "103"),
        ("104", "105", "106"),
        ("107", "108"),
        ("204", "204S"),
        ("501", "501A", "501D"),
        ("502", "502B", "502C"),
        ("504", "505", "506", "507", "508"),
    ],
    "LIYANAGE LIMITED-DSP": [
        ("307", "307A", "307B"),
    ],
    "Goose": [
        ("308", "308A", "308B", "308C", "308D"),
    ],
    "Click'N Code": [
        ("203", "203A", "203B"),
        ("206", "210"),
        ("207", "207S"),
        ("405", "405A", "405B", "405C", "405D"),
    ],
    "Feng": [
        ("201", "201A", "201S"),
        ("202", "202S"),
        ("301", "301S"),
        ("302", "303"),
        ("401A", "401B", "401C", "401S"),
        ("404", "404A", "404B", "404S"),
        ("604", "604A", "604S"),
        ("605", "605A", "605S"),
    ],
    "Fast donkey": [
        ("211", "211A"),
        ("503", "503A", "503B"),
        ("607", "607S"),
        ("609", "609A"),
    ],
}
