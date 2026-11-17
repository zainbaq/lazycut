"""SQLite engine, table creation and the forward-only migration hook."""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine, event, text
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401 - registers the tables on SQLModel.metadata

SCHEMA_VERSION = 4


def _add_event_edited(conn) -> None:
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(event)"))}
    if "edited" not in columns:
        conn.execute(text("ALTER TABLE event ADD COLUMN edited BOOLEAN NOT NULL DEFAULT 0"))
        # Model events already moved before this column existed count as edited.
        conn.execute(text(
            "UPDATE event SET edited = 1 WHERE source = 'model' AND t_model_start IS NOT NULL"
            " AND abs(t_start - t_model_start) > 1e-6"
        ))


def _add_columns(conn, table: str, columns: dict[str, str]) -> None:
    have = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    for name, ddl in columns.items():
        if name not in have:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _add_clip_columns(conn) -> None:
    """Phase 2: what clips and exports need beyond the columns declared in Phase 0."""
    _add_columns(conn, "clip", {
        "platform": "VARCHAR", "source": "VARCHAR NOT NULL DEFAULT 'user'",
        "orig_start": "FLOAT", "orig_end": "FLOAT", "created_at": "VARCHAR NOT NULL DEFAULT ''",
    })
    # Clips stored before this version came from importing a pre-trimmed video (kind = clip).
    conn.execute(text(
        "UPDATE clip SET source = 'import', orig_start = t_start, orig_end = t_end WHERE orig_start IS NULL"
    ))
    _add_columns(conn, "clip_export", {
        "t_start": "FLOAT", "t_end": "FLOAT", "real_start": "FLOAT", "real_end": "FLOAT",
        "duration_s": "FLOAT", "size_bytes": "INTEGER",
    })


# version -> step that brings the schema from version - 1 to version. New tables come
# from create_all; a step is only needed for a change to an existing table.
MIGRATIONS: dict[int, Callable] = {3: _add_event_edited, 4: _add_clip_columns}


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        current = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar_one()
        if current is None:
            conn.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": SCHEMA_VERSION})
            return
        for version in range(current + 1, SCHEMA_VERSION + 1):
            if step := MIGRATIONS.get(version):
                step(conn)
        if current < SCHEMA_VERSION:
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": SCHEMA_VERSION})


def session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def db_status(engine: Engine) -> dict:
    """Write and read one row so a broken mount shows up as an error, not later as lost data."""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS health_probe (n INTEGER NOT NULL)"))
            conn.execute(text("DELETE FROM health_probe"))
            conn.execute(text("INSERT INTO health_probe (n) VALUES (1)"))
            ok = conn.execute(text("SELECT n FROM health_probe")).scalar_one() == 1
            mode = conn.execute(text("PRAGMA journal_mode")).scalar_one()
            version = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar_one()
        return {"ok": ok, "journal_mode": mode, "schema_version": version}
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        return {"ok": False, "error": str(exc)}
