import os
import sys
import shutil
import subprocess
import re
import urllib.request
import zipfile
from pathlib import Path


def get_chromium_revision() -> str | None:
    """Run playwright install --dry-run to find the expected chromium revision."""
    cmd = [sys.executable, "-m", "playwright", "install", "chromium", "--dry-run"]
    try:
        # Prevent localized output issues by setting env? Playwright output seems standard.
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        # Look for url pattern: .../builds/chromium/<REV>/...
        # Example: https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1200/chromium-win64.zip
        match = re.search(r"builds/chromium/(\d+)/chromium-", output)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Error running playwright dry-run: {e}")
    return None


def download_and_extract(url: str, dest_folder: Path) -> None:
    print(f"Downloading {url}...")
    filename = url.split("/")[-1]
    zip_path = dest_folder / filename

    try:
        with urllib.request.urlopen(url) as response, open(zip_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
    except Exception as e:
        print(f"Download failed: {e}")
        return

    print(f"Extracting {filename}...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(dest_folder)
    except Exception as e:
        print(f"Extraction failed: {e}")
    finally:
        if zip_path.exists():
            os.remove(zip_path)


def main() -> None:
    # Default: install to 'libs/browsers' in the project root
    project_root = Path(__file__).resolve().parent.parent
    target_root = project_root / "libs" / "browsers"

    print("Detecting required Chromium revision...")
    revision = get_chromium_revision()
    if not revision:
        print("Could not detect Chromium revision from playwright.")
        print("Ensure 'playwright' is installed in your environment.")
        sys.exit(1)

    print(f"Target Chromium revision: {revision}")

    # The folder name MUST be chromium-<revision> for Playwright to find it
    rev_folder = target_root / f"chromium-{revision}"
    rev_folder.mkdir(parents=True, exist_ok=True)
    print(f"Install location: {rev_folder}")

    # CDN Base URL
    # We use the azureedge CDN as seen in dry-run, which is standard for Playwright
    base_url = f"https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/{revision}"

    targets = [
        ("Windows (win64)", f"{base_url}/chromium-win64.zip"),
        ("Linux (linux)", f"{base_url}/chromium-linux.zip"),
    ]

    for name, url in targets:
        print(f"\nProcessing {name}...")
        download_and_extract(url, rev_folder)

    # Create a marker file or similar if needed? No, Playwright just checks dir existence.

    print("\n" + "=" * 60)
    print("Download Complete!")
    print("=" * 60)
    print("To use these browsers in an offline environment:")
    print("1. Copy the 'libs/browsers' folder to your offline machine.")
    print("2. Set the environment variable before running mcp-fetch:")
    print(f"   export PLAYWRIGHT_BROWSERS_PATH={target_root}")
    print("-" * 60)
    print("Directory Structure Check:")
    if rev_folder.exists():
        print(f"  {rev_folder.name}/")
        for item in rev_folder.iterdir():
            if item.is_dir():
                print(f"    {item.name}/")
    print("-" * 60)


if __name__ == "__main__":
    main()
