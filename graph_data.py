# Sample road network. All weights are estimated travel times in minutes.
# Roads are undirected in this academic demonstration.

ROAD_GRAPH = {
    "H": [("A", 4), ("B", 2)],
    "A": [("H", 4), ("B", 1), ("C", 5), ("D", 9)],
    "B": [("H", 2), ("A", 1), ("C", 8), ("D", 10)],
    "C": [("A", 5), ("B", 8), ("D", 2), ("P", 6)],
    "D": [("B", 10), ("A", 9), ("C", 2), ("P", 3)],
    "P": [("C", 6), ("D", 3)],
}

LOCATION_NAMES = {
    "H": "Hospital",
    "A": "Junction A",
    "B": "Junction B",
    "C": "Junction C",
    "D": "Junction D",
    "P": "Patient Location",
}
