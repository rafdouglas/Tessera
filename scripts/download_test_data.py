#!/usr/bin/env python3
"""Download Natural Earth 110m Admin 0 Countries test dataset."""

import os
import sys
import urllib.request
import zipfile
import shutil
from pathlib import Path


def download_test_data():
    """Download and extract Natural Earth 110m countries shapefile."""

    # Configuration
    url = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"

    # Determine project root (parent of scripts/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # Output paths
    output_dir = project_root / "test_data" / "ne_110m_admin_0_countries"
    shapefile_path = output_dir / "ne_110m_admin_0_countries.shp"
    zip_path = project_root / "test_data" / "ne_110m_admin_0_countries.zip"

    # Check if already exists
    if shapefile_path.exists():
        print(f"✓ Test data already exists at {shapefile_path}")
        print("  Skipping download.")
        return 0

    # Create test_data directory if needed
    test_data_dir = project_root / "test_data"
    test_data_dir.mkdir(exist_ok=True)

    try:
        # Download
        print(f"Downloading Natural Earth 110m countries from:")
        print(f"  {url}")
        print(f"  → {zip_path}")

        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('content-length', 0))

            with open(zip_path, 'wb') as f:
                downloaded = 0
                chunk_size = 8192

                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break

                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"  Progress: {downloaded:,} / {total_size:,} bytes ({percent:.1f}%)", end='\r')

        print()  # New line after progress
        print(f"✓ Download complete ({downloaded:,} bytes)")

        # Extract
        print(f"Extracting to {output_dir}...")
        output_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # List members for verification
            members = zip_ref.namelist()
            print(f"  Archive contains {len(members)} files")

            # Extract all
            zip_ref.extractall(output_dir)

        print(f"✓ Extraction complete")

        # Verify shapefile exists
        if not shapefile_path.exists():
            print(f"✗ ERROR: Expected shapefile not found at {shapefile_path}", file=sys.stderr)
            return 1

        # Clean up zip file
        print(f"Cleaning up temporary file {zip_path.name}...")
        zip_path.unlink()
        print(f"✓ Cleanup complete")

        # Success summary
        print()
        print("=" * 60)
        print("✓ Test data ready:")
        print(f"  {shapefile_path}")
        print("=" * 60)

        return 0

    except urllib.error.URLError as e:
        print(f"✗ ERROR: Network failure", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(f"  URL: {url}", file=sys.stderr)

        # Clean up partial download
        if zip_path.exists():
            zip_path.unlink()

        return 1

    except zipfile.BadZipFile as e:
        print(f"✗ ERROR: Corrupt ZIP file", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)

        # Clean up corrupt zip
        if zip_path.exists():
            print(f"  Removing corrupt file {zip_path}")
            zip_path.unlink()

        return 1

    except Exception as e:
        print(f"✗ ERROR: Unexpected failure", file=sys.stderr)
        print(f"  {type(e).__name__}: {e}", file=sys.stderr)

        # Clean up on any error
        if zip_path.exists():
            zip_path.unlink()

        return 1


if __name__ == "__main__":
    sys.exit(download_test_data())
