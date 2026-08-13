BOARD_3L_CAPACITY = 200
BOARD_5L_CAPACITY = 350


# Supplier route groups are explicit business rules.  Never infer them from a
# shared numeric prefix: related route codes can belong to different suppliers
# or drivers (for example, 501B is not part of EMPIRE COURIER's 501 group).
SUPPLIER_ROUTE_GROUPS = {
    "EMPIRE COURIER": [
        ("101", "102", "103"),
        ("104", "105", "106"),
        ("107", "108"),
        ("204", "204S"),
        ("501", "501A", "501C", "501D"),
        ("502", "502B", "502C"),
        ("504", "505", "506", "507", "508"),
    ],
    "Fast Rabbit": [
        ("307", "307A", "307B"),
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
        ("309", "309A"),
        ("503", "503A", "503B"),
        ("607", "607S"),
        ("609", "609A"),
    ],
    "PANDA": [
        ("501B", "502A"),
    ],
}
