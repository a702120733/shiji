#!/usr/bin/env python3
"""Copy data-free application screens into the static cloud site."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'shiji'
TARGET = ROOT / 'cloud' / 'ui'
ASSETS = ('import.html', 'import.css', 'import.js',
          'bookmarks.html', 'products.html', 'local.css', 'local.js')


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copy2(SOURCE / name, TARGET / name)
    print(f'Cloud UI: {len(ASSETS)} public files')


if __name__ == '__main__':
    main()
