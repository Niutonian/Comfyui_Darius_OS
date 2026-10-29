"""Private backups and offline restore rehearsals; use a new destination each time."""
from pathlib import Path
import argparse
from darius_api.config import Settings
from darius_api.installation_backup import backup as create_backup, restore_rehearsal

def backup(destination: Path, *, include_media=False):
    result = create_backup(destination, Settings.from_env(), include_media=include_media)
    print((destination / 'BACKUP_REPORT.txt').read_text(encoding='utf-8'))
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--include-media', action='store_true')
    parser.add_argument('--restore-from', type=Path)
    args = parser.parse_args()
    if args.restore_from:
        restore_rehearsal(args.restore_from, args.destination)
        print((args.destination / 'RESTORE_REPORT.txt').read_text(encoding='utf-8'))
    else: backup(args.destination, include_media=args.include_media)
