#!/usr/bin/env python3
"""Encode JPEG images in the data directory as SSDV packet files."""

import os
from pathlib import Path
import subprocess
import sys

PACKET_SIZE = 195
CALLSIGN = "KC3VVW"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ENCODER = Path(__file__).resolve().parent / (
    "ssdv-win.exe" if os.name == "nt" else "ssdv"
)


def generate_ssdv_files(data_dir: Path, encoder: Path) -> int:
    jpeg_files = sorted(
        path
        for path in data_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )
    if not jpeg_files:
        print(f"No JPEG files found in {data_dir}", file=sys.stderr)
        return 1

    for image_id, jpeg_file in enumerate(jpeg_files):
        output_file = jpeg_file.with_suffix(".bin")
        command = [
            str(encoder),
            "-e",
            "-l",
            str(PACKET_SIZE),
            "-c",
            CALLSIGN,
            "-i",
            str((image_id+1) % 256),
            str(jpeg_file),
            str(output_file),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            details = error.stderr.strip() or error.stdout.strip()
            print(
                f"Failed to encode {jpeg_file}"
                + (f": {details}" if details else f" (exit code {error.returncode})"),
                file=sys.stderr,
            )
            return 1
        print(f"Encoded {jpeg_file.name} as {output_file.name} (image ID {image_id % 256})")

    return 0


def main() -> int:
    if not ENCODER.is_file():
        print(f"SSDV encoder not found: {ENCODER}", file=sys.stderr)
        return 1
    return generate_ssdv_files(DATA_DIR, ENCODER)


if __name__ == "__main__":
    raise SystemExit(main())
