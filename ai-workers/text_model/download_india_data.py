"""Fetch the India relevance subset of the Mendeley India–Nepal corpus."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen


DATASET_ID = "psv6b4zy9f"
DATASET_VERSION = "1"
DATASET_URL = f"https://data.mendeley.com/public-api/zip/{DATASET_ID}/download/{DATASET_VERSION}"
EXPECTED_ARCHIVE_SHA256 = "94b3b7341c6ea9c6f45c2cc2dd6d4063dfae476911284e393993e9fbb9b16d09"
EXPECTED_CSV_SHA256 = "4d29070572760c2a52c5e0d72aa8d4ecdc7071417491abc1f50f863e57d564e8"
CSV_NAME = "INDIANTWEETMASTER.csv"
DEFAULT_DESTINATION = Path(__file__).resolve().parent / "data" / "external"


def fetch(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / CSV_NAME
    if target.exists():
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual == EXPECTED_CSV_SHA256:
            print(f"Already present and verified: {target}")
            return

    print(f"Downloading Mendeley Data {DATASET_ID}, version {DATASET_VERSION}")
    request = Request(
        DATASET_URL,
        headers={"User-Agent": "ResQ-TextModel/1.0", "Accept": "application/zip"},
    )
    with urlopen(request, timeout=90) as response:  # noqa: S310 - pinned HTTPS dataset
        archive_bytes = response.read()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if archive_sha256 != EXPECTED_ARCHIVE_SHA256:
        raise ValueError(f"Dataset archive SHA-256 mismatch: got {archive_sha256}")

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as outer_zip:
        nested_name = next(
            (name for name in outer_zip.namelist() if name.endswith("/dataset.zip")),
            None,
        )
        if nested_name is None:
            raise ValueError("Pinned dataset archive does not contain the expected dataset.zip")
        with zipfile.ZipFile(io.BytesIO(outer_zip.read(nested_name))) as dataset_zip:
            try:
                data = dataset_zip.read(f"dataset/{CSV_NAME}")
            except KeyError as exc:
                raise ValueError(f"Pinned dataset archive does not contain {CSV_NAME}") from exc

    csv_sha256 = hashlib.sha256(data).hexdigest()
    if csv_sha256 != EXPECTED_CSV_SHA256:
        raise ValueError(f"{CSV_NAME} SHA-256 mismatch: got {csv_sha256}")
    target.write_bytes(data)
    print(f"Saved and verified: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    fetch(args.destination)


if __name__ == "__main__":
    main()
