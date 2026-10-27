"""Open/reset this installation's console code locally; never print the secret."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from darius_api.config import Settings
from darius_api.diagnostics import access_key, reset_access_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    path = settings.data_dir / 'diagnostics' / 'access-code.txt'
    if args.reset:
        reset_access_key(settings)
    access_key(settings)
    # Caller opens this file locally in Notepad; no key enters setup transcripts.
    print(path)


if __name__ == '__main__':
    main()
