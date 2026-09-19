"""
Ingestion pipeline: runs a connector, upserts results into `documents`,
and updates `sync_state` with the new cursor so the next run is incremental.

Usage:
    python -m scripts.run_sync --source github
"""

import argparse
import os

from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import insert as pg_insert

from connectors.github_connector import GitHubConnector
from db.models import Document, SyncState
from db.session import get_session

load_dotenv()


def get_cursor(session, source: str):
    row = session.query(SyncState).filter_by(source=source).first()
    return row.cursor if row else None


def set_cursor(session, source: str, cursor: str):
    row = session.query(SyncState).filter_by(source=source).first()
    if row:
        row.cursor = cursor
    else:
        row = SyncState(source=source, cursor=cursor)
        session.add(row)
    session.commit()


def upsert_document(session, raw_item) -> int:
    stmt = pg_insert(Document).values(
        source=raw_item.source,
        source_id=raw_item.source_id,
        title=raw_item.title,
        raw_content=raw_item.content,
        cleaned_content=raw_item.content,
        permission_scope=raw_item.permission_scope,
        created_at=raw_item.created_at,
        updated_at=raw_item.updated_at,
        doc_metadata=raw_item.metadata,
    ).on_conflict_do_update(
        index_elements=["source", "source_id"],
        set_={
            "title": raw_item.title,
            "raw_content": raw_item.content,
            "cleaned_content": raw_item.content,
            "updated_at": raw_item.updated_at,
            "doc_metadata": raw_item.metadata,
        },
    ).returning(Document.id)

    result = session.execute(stmt)
    session.commit()
    return result.scalar()


def run_github_sync():
    token = os.environ["GITHUB_TOKEN"]
    repos = os.environ.get("GITHUB_REPOS", "psf/requests").split(",")
    connector = GitHubConnector(token=token, repos=[r.strip() for r in repos])

    session = get_session()
    cursor = get_cursor(session, "github")
    print(f"[run_sync] starting github sync, cursor={cursor}")

    count = 0
    for raw_item in connector.fetch_since(cursor):
        upsert_document(session, raw_item)
        count += 1
        if count % 10 == 0:
            print(f"[run_sync] upserted {count} documents so far...")

    new_cursor = connector.get_next_cursor()
    set_cursor(session, "github", new_cursor)
    print(f"[run_sync] done. {count} documents upserted. new cursor={new_cursor}")
    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["github", "slack"], required=True)
    args = parser.parse_args()

    if args.source == "github":
        run_github_sync()
    else:
        raise NotImplementedError("Slack connector comes in a later step")