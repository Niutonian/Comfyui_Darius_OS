"""Fill missing generated-asset display names without changing media or custom names."""
from pathlib import Path

from sqlalchemy import select

from darius_api.config import Settings
from darius_api.database import Asset, GenerationRecord, make_engine, make_session_factory
from darius_api.generation_identity import output_name
from darius_api.services import add_event


def repair(session):
    count = 0
    rows = session.execute(select(Asset, GenerationRecord).join(
        GenerationRecord, GenerationRecord.job_id == Asset.workflow_run_id
    ).where(Asset.role == "generation"))
    for asset, generation in rows:
        if asset.metadata_json.get("display_name"):
            continue
        name = output_name(generation.prompt, asset.id, 1, Path(asset.path).suffix)
        asset.metadata_json = {**asset.metadata_json, "display_name": name}
        add_event(session, asset.project_id, "asset.renamed", "asset", asset.id,
                  {"name": name, "reason": "Fill missing generation display name"})
        count += 1
    return count


if __name__ == "__main__":
    settings = Settings.from_env()
    with make_session_factory(make_engine(settings.database_url)).begin() as session:
        count = repair(session)
    print(f"Updated {count} missing asset names. Existing display names preserved.")
