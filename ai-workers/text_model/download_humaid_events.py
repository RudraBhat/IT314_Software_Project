"""Download the public HumAID event set for local humanitarian research.

HumAID's terms require tweet text to remain confidential and be used only for
humanitarian-computing research. Keep the external data directory out of Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


DATASET_ID = "QCRI/HumAID-events"
DATASET_REVISION = "2e7ea23332006f075068b90d401b178d847b447a"
FILES = Path(__file__).resolve().with_name("humaid_checksums.json")
DEFAULT_DESTINATION = Path(__file__).resolve().parent / "data" / "external" / "humaid_events"


def fetch(destination: Path) -> None:
    expected = json.loads(FILES.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    for relative_path, expected_sha256 in sorted(expected.items()):
        target = destination / relative_path
        if target.is_file():
            actual_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_sha256 == expected_sha256:
                print(f"Already present and verified: {relative_path}")
                continue

        url = (
            f"https://huggingface.co/datasets/{DATASET_ID}/resolve/"
            f"{DATASET_REVISION}/{relative_path}"
        )
        request = Request(url, headers={"User-Agent": "DRCH-Humanitarian-Research/1.0"})
        # The URL uses a fixed HTTPS host/revision and the downloaded bytes are hashed.
        with urlopen(request, timeout=90) as response:  # noqa: S310  # nosec B310
            data = response.read()
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {relative_path}: {actual_sha256}")
        parsed = json.loads(data)
        if not isinstance(parsed, list) or any(
            not {"tweet_id", "tweet_text", "class_label"}.issubset(row)
            for row in parsed
        ):
            raise ValueError(f"Unexpected HumAID row format in {relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
        print(f"Downloaded and verified: {relative_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    fetch(args.destination)


if __name__ == "__main__":
    main()
