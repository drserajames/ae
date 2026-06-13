# Synthetic vaccine list for cc/tal/test/test-mark-vaccines.py — mirrors the shape of
# acmacs-data/semantic_vaccines.py (a module exposing sData[subtype] -> [{"name": ...}])
# but uses made-up names so no real data lives in the repo. Plain dict: no imports needed.
sData = {
    "TESTVT": [
        {"name": "A", "year": 2020},
        {"name": "E", "year": 2021},
    ],
}
