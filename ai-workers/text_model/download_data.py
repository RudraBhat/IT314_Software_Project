"""Fetch the pinned, openly licensed disaster response messages corpus."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen


DATASET_COMMIT = "1657e1c4e11acbfa56241d2b5cd627adbd989ca2"
BASE_URL = (
    "https://raw.githubusercontent.com/rmunro/disaster_response_messages/"
    f"{DATASET_COMMIT}"
)
FILES = {
    "disaster_response_training.csv": "3fd06465488100a51f97f60b3e27eb58bf8dfda568ee92ec6e574e78c84b12dd",
    "disaster_response_validation.csv": "2c6d4424e812b068ca2486a3c1b35bc0aea445643d922657e3023ae60387bc0b",
    "disaster_response_test.csv": "566402713139ad7c910737cf5f18f3fef9ba6cc711b6aa5054c65e3fa0ecfc48",
}
DEFAULT_DESTINATION = Path(__file__).resolve().parent / "data" / "external"


def fetch(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename, expected_sha256 in FILES.items():
        target = destination / filename
        if target.exists():
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual == expected_sha256:
                print(f"Already present and verified: {target}")
                continue

        url = f"{BASE_URL}/{filename}"
        print(f"Downloading {url}")
        # The URL uses a fixed HTTPS host/revision and the downloaded bytes are hashed.
        with urlopen(url, timeout=60) as response:  # noqa: S310  # nosec B310
            data = response.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {filename}: got {actual}")
        target.write_bytes(data)
        print(f"Saved and verified: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    fetch(args.destination)


if __name__ == "__main__":
    main()
