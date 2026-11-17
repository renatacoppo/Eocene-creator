"""Classes of the OIFS surface fields: vegetation types (``tvh``, ``tvl``) and soil types (``slt``).

Source: IFS Documentation, Part IV: Physical processes, chapter 8 (surface parametrization), tables of the
vegetation types and of the soil types (the same numbering in cy43r3 to cy49r1).
"""

land_cover_types = {
    0: "No vegetation",
    1: "Crops, Mixed farming",
    2: "Grass",
    3: "Evergreen needleleaf trees",
    4: "Deciduous needleleaf trees",
    5: "Deciduous broadleaf trees",
    6: "Evergreen broadleaf trees",
    7: "Tall grass",
    8: "Desert",
    9: "Tundra",
    10: "Irrigated crops",
    11: "Semidesert",
    12: "Ice caps and Glaciers",
    13: "Bogs and marshes",
    14: "Inland water",
    15: "Ocean",
    16: "Evergreen shrubs",
    17: "Deciduous shrubs",
    18: "Mixed forest/woodland",
    19: "Interrupted forest",
    20: "Water and land mixtures",
}

soil_types = {
    0: "No soil (sea)",
    1: "Coarse",
    2: "Medium",
    3: "Medium fine",
    4: "Fine",
    5: "Very fine",
    6: "Organic",
    7: "Tropical organic",
}
