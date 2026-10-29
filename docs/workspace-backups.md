# Private workspace backups and restore rehearsal

Open **Darius.bat** for the Windows manager. These are private recovery copies;
settings may contain credentials, and conversations/media are personal data.
They are not shareable project exports.

## Backup choices

- **Automatic install/update backup:** verified SQLite snapshot, settings and
  runtime workflow definitions/graphs. It reports all catalogued media as
  excluded or missing. It does not copy large image/video libraries silently.
- **Back up workspace:** stop Darius first, then select this manager action.
  It also copies the media referenced by the asset catalogue and verifies their
  recorded content hashes. It can need substantial storage and time. This
  includes both generated assets and imported references; unrelated files such
  as screenshots elsewhere in `data/` are not swept into the backup.
- **Backup reports:** opens `data/backups`. Each completed recovery backup has
  `BACKUP_REPORT.txt` and a private `backup-report.json` with checksums, asset
  inclusion/exclusion/missing-file details and workflow mappings. Early setup
  can also create a settings-only report before Python dependencies are ready.

Models, custom nodes, ComfyUI, voice runtimes, GPU drivers, LAN certificates,
import ZIP originals and model-access approvals remain separate dependencies.
A fresh installation must use the matching Darius release and its bundled
versioned templates. SQLite database integrity checking alone does not establish
that all media or external dependencies are available.

## Rehearse restoration

Choose **Restore rehearsal**, select a completed backup, then choose a parent
folder. The manager creates a new dated `Darius-Restore-*` folder. Nothing in the
original installation or backup is overwritten, no service starts and saved
credentials are not activated. The report/checksums and path mappings are
validated before creating the destination. A changed/missing backup file stops
restoration.

The result contains:

- `data/darius.db` and included media under `data/media/`, with asset paths rebased.
- `workflows/definitions/` and saved graphs, with matching workflow references rebased. External workflow files not included in the backup are reported and their restored definitions are disabled; they cannot silently read files from the original installation.
- `settings/backend.env` and `settings/frontend.env` for private manual review;
  they are not loaded automatically as `.env` files.
- `RESTORE_REPORT.txt` and `restore-report.json`, including every excluded or
  missing asset and the external dependencies still needed.

Missing/excluded assets get a missing path in the restored tree; Darius cannot
silently open them from the original installation. Unfinished jobs are marked
failed with `RestoreReviewRequired` in the restored database. Successful receipts
and conversation/board history remain intact. Original database/job states and
backup files stay unchanged. Historical execution snapshots retain their
original provenance; restoration does not make old jobs safe to replay.

For a hands-on rehearsal, use a fresh copy of the matching Darius code. Set its
local configuration to the restored `data` folder, `data/darius.db`, and
`workflows/definitions` via `DARIUS_DATA_DIR`, `DARIUS_DATABASE_URL`, and
`DARIUS_WORKFLOW_DEFINITIONS_DIR`. Configure its own services and ports explicitly;
do not load the old credentials blindly. Start only the API/web services for
inspection, open the project, conversation and board history, and play/open a
restored asset. Reconnect and review external dependencies before generating.
Do not replace the original installation until this separate copy is verified.

Equivalent commands, from an installed checkout with Darius stopped:

```powershell
.venv/Scripts/python.exe scripts/backup-installation.py <new-backup-folder> --include-media
.venv/Scripts/python.exe scripts/backup-installation.py <new-restore-folder> --restore-from <backup-folder>
```

Restoration refuses an existing target. If a disk error leaves an incomplete
rehearsal folder, inspect it and choose another new destination for the next
attempt. The tool never deletes the only good backup to retry.

`tests/test_installation_backup.py` rehearses this with a synthetic project,
conversation, board, generation receipt, image and pending job. It opens restored
history and media through an isolated API and checks exclusions, corruption,
unsafe paths and overwrite refusal without starting a renderer.
