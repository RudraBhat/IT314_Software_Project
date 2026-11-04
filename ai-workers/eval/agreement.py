"""Agreement on the 60 shared texts. Run: python eval/agreement.py neeti.csv dhruvil.csv rudra.csv

Each CSV needs the columns text,label. Prints pairwise Cohen's kappa over the texts all files share.
"""

from __future__ import annotations

import csv
import itertools
import sys

from sklearn.metrics import cohen_kappa_score


def read(path: str) -> dict[str, str]:
    with open(path, newline="", encoding="utf-8") as f:
        return {r["text"].strip(): r["label"] for r in csv.DictReader(f)}


def main(paths: list[str]) -> None:
    labelled = {p: read(p) for p in paths}
    shared = sorted(set.intersection(*(set(v) for v in labelled.values())))
    print(f"{len(shared)} shared texts")
    for a, b in itertools.combinations(paths, 2):
        kappa = cohen_kappa_score([labelled[a][t] for t in shared], [labelled[b][t] for t in shared])
        print(f"{a} vs {b}: kappa={kappa:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
