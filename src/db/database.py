"""SQLite data layer for the enrichment pipeline.

Staged design: each processing stage writes its OWN table, and every downstream
row keys back to the source row by its unique id. This lets each stage run
independently and idempotently -- a stage only does work for source rows that
don't yet have a row in that stage's table, so completed (paid) work is never
repeated on a re-run.

Stages:
  1. `companies`   -- raw verbatim names from the scrape (the source of truth).
  2. `enrichments` -- one row per company from Exa; its primary key IS the
                      foreign key to companies, so a company is enriched at most
                      once. Future stages (e.g. `scores`) follow the same shape.

Constrained text columns (`status`, `funding_stage`) carry CHECK constraints
generated directly from the enums in `models`, so the DB vocabulary can never
drift from the Python one. The database file lives next to this module and is
created on first connect.
"""

from __future__ import annotations

import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from models import (
    BusinessModel,
    CompanyType,
    EnrichmentRecord,
    EnrichmentStatus,
    FitStatus,
    FundingStage,
    LogisticsWorkflow,
    OwnershipStatus,
    ScoreRecord,
    SourceQuality,
    TargetBuyer,
    TractionTier,
    WittingtonCategory,
)

DB_PATH = Path(__file__).resolve().parent / "wittington.db"


def _check(column: str, enum_cls: type[StrEnum], *, nullable: bool) -> str:
    """Render a CHECK clause restricting `column` to the enum's values."""
    allowed = ", ".join(f"'{member.value}'" for member in enum_cls)
    null_clause = f"{column} IS NULL OR " if nullable else ""
    return f"CHECK ({null_clause}{column} IN ({allowed}))"


_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS companies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    source     TEXT    NOT NULL DEFAULT 'manifest',
    scraped_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enrichments (
    company_id      INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    status          TEXT    NOT NULL {_check("status", EnrichmentStatus, nullable=False)},
    resolved_url    TEXT,
    resolved_domain TEXT,
    title           TEXT,
    description     TEXT,
    industry        TEXT,
    is_public       INTEGER,
    founded_year    INTEGER,
    employee_count  TEXT,
    funding_stage   TEXT    {_check("funding_stage", FundingStage, nullable=True)},
    total_funding   TEXT,
    hq_location     TEXT,
    canonical_name  TEXT,
    entity_confidence INTEGER CHECK (entity_confidence IS NULL OR entity_confidence BETWEEN 0 AND 100),
    company_type    TEXT    {_check("company_type", CompanyType, nullable=True)},
    software_led    INTEGER,
    venture_backed  INTEGER,
    north_america_presence INTEGER,
    customer_segment TEXT,
    logistics_function TEXT,
    supply_chain_subsector TEXT,
    target_customer TEXT,
    enterprise_traction TEXT,
    wv_edge         TEXT,
    disqualifiers   TEXT,
    evidence_snippet TEXT,
    enrichment_schema_version INTEGER,
    ownership_status TEXT {_check("ownership_status", OwnershipStatus, nullable=True)},
    business_model TEXT {_check("business_model", BusinessModel, nullable=True)},
    latest_round_date TEXT,
    latest_round_amount TEXT,
    named_investors TEXT,
    logistics_workflow TEXT {_check("logistics_workflow", LogisticsWorkflow, nullable=True)},
    target_buyer TEXT {_check("target_buyer", TargetBuyer, nullable=True)},
    traction_tier TEXT {_check("traction_tier", TractionTier, nullable=True)},
    wv_partner_match TEXT,
    source_quality TEXT {_check("source_quality", SourceQuality, nullable=True)},
    evidence_urls TEXT,
    enriched_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scores (
    company_id          INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    status              TEXT    NOT NULL {_check("status", FitStatus, nullable=False)},
    fit_score           INTEGER NOT NULL CHECK (fit_score BETWEEN 0 AND 100),
    raw_score           INTEGER CHECK (raw_score IS NULL OR raw_score BETWEEN 0 AND 100),
    cap_reason          TEXT,
    category            TEXT    NOT NULL {_check("category", WittingtonCategory, nullable=False)},
    startup_fit         INTEGER NOT NULL CHECK (startup_fit BETWEEN 0 AND 100),
    stage_fit           INTEGER NOT NULL CHECK (stage_fit BETWEEN 0 AND 100),
    sector_fit          INTEGER NOT NULL CHECK (sector_fit BETWEEN 0 AND 100),
    rationale           TEXT    NOT NULL,
    deterministic_notes TEXT    NOT NULL,
    llm_model           TEXT,
    scored_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    """Open the local database, creating the file and schema if absent."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    init_db(connection)
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    """Create the stage tables if they do not already exist."""
    connection.executescript(_SCHEMA)
    _ensure_enrichment_columns(connection)
    _ensure_score_columns(connection)
    connection.commit()


def _ensure_enrichment_columns(connection: sqlite3.Connection) -> None:
    """Add structured enrichment columns to older local DBs."""
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(enrichments)").fetchall()
    }
    additions = {
        "canonical_name": "TEXT",
        "entity_confidence": "INTEGER CHECK (entity_confidence IS NULL OR entity_confidence BETWEEN 0 AND 100)",
        "company_type": "TEXT",
        "software_led": "INTEGER",
        "venture_backed": "INTEGER",
        "north_america_presence": "INTEGER",
        "customer_segment": "TEXT",
        "logistics_function": "TEXT",
        "supply_chain_subsector": "TEXT",
        "target_customer": "TEXT",
        "enterprise_traction": "TEXT",
        "wv_edge": "TEXT",
        "disqualifiers": "TEXT",
        "evidence_snippet": "TEXT",
        "enrichment_schema_version": "INTEGER",
        "ownership_status": "TEXT",
        "business_model": "TEXT",
        "latest_round_date": "TEXT",
        "latest_round_amount": "TEXT",
        "named_investors": "TEXT",
        "logistics_workflow": "TEXT",
        "target_buyer": "TEXT",
        "traction_tier": "TEXT",
        "wv_partner_match": "TEXT",
        "source_quality": "TEXT",
        "evidence_urls": "TEXT",
    }
    for column, ddl in additions.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE enrichments ADD COLUMN {column} {ddl}")


def _ensure_score_columns(connection: sqlite3.Connection) -> None:
    """Add scoring audit columns to older local DBs."""
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(scores)").fetchall()
    }
    additions = {
        "raw_score": "INTEGER CHECK (raw_score IS NULL OR raw_score BETWEEN 0 AND 100)",
        "cap_reason": "TEXT",
    }
    for column, ddl in additions.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE scores ADD COLUMN {column} {ddl}")


# --- Stage 1: source -------------------------------------------------------


def load_companies(connection: sqlite3.Connection, names: Iterable[str]) -> int:
    """Insert scraped names into `companies`. Idempotent (existing names ignored).

    Returns the number of newly inserted rows.
    """
    before = connection.total_changes
    connection.executemany(
        "INSERT OR IGNORE INTO companies (name) VALUES (?)",
        [(name,) for name in names],
    )
    connection.commit()
    return connection.total_changes - before


# --- Stage 2: enrichment ---------------------------------------------------


def pending_enrichment(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Companies with no enrichment row yet -- the work still to be done."""
    return connection.execute(
        """
        SELECT c.id, c.name
        FROM companies c
        LEFT JOIN enrichments e ON e.company_id = c.id
        WHERE e.company_id IS NULL
        ORDER BY c.id
        """
    ).fetchall()


def save_enrichment(connection: sqlite3.Connection, record: EnrichmentRecord) -> None:
    """Persist one enrichment row from a typed record (no parsing here).

    Columns are taken directly from the model's fields, so adding or removing a
    field only requires touching `EnrichmentRecord` and the schema -- nothing is
    hardcoded to a particular enrichment source.
    """
    data = record.model_dump(mode="json")
    columns = ", ".join(data)
    placeholders = ", ".join(f":{column}" for column in data)
    connection.execute(
        f"INSERT OR REPLACE INTO enrichments ({columns}) VALUES ({placeholders})",
        data,
    )
    connection.commit()


# --- Stage 3: scoring ------------------------------------------------------


def pending_scoring(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Enriched companies with no score row yet."""
    return connection.execute(
        """
        SELECT
            c.id AS company_id,
            c.name,
            e.status,
            e.resolved_url,
            e.resolved_domain,
            e.title,
            e.description,
            e.industry,
            e.is_public,
            e.founded_year,
            e.employee_count,
            e.funding_stage,
            e.total_funding,
            e.hq_location,
            e.canonical_name,
            e.entity_confidence,
            e.company_type,
            e.software_led,
            e.venture_backed,
            e.north_america_presence,
            e.customer_segment,
            e.logistics_function,
            e.supply_chain_subsector,
            e.target_customer,
            e.enterprise_traction,
            e.wv_edge,
            e.disqualifiers,
            e.evidence_snippet,
            e.enrichment_schema_version,
            e.ownership_status,
            e.business_model,
            e.latest_round_date,
            e.latest_round_amount,
            e.named_investors,
            e.logistics_workflow,
            e.target_buyer,
            e.traction_tier,
            e.wv_partner_match,
            e.source_quality,
            e.evidence_urls
        FROM companies c
        JOIN enrichments e ON e.company_id = c.id
        LEFT JOIN scores s ON s.company_id = c.id
        WHERE s.company_id IS NULL
        ORDER BY c.id
        """
    ).fetchall()


def save_score(connection: sqlite3.Connection, record: ScoreRecord) -> None:
    """Persist one score row from a typed record."""
    data = record.model_dump(mode="json")
    columns = ", ".join(data)
    placeholders = ", ".join(f":{column}" for column in data)
    connection.execute(
        f"INSERT OR REPLACE INTO scores ({columns}) VALUES ({placeholders})",
        data,
    )
    connection.commit()


def ranked_pipeline(
    connection: sqlite3.Connection, company_ids: list[int] | None = None
) -> list[sqlite3.Row]:
    """Sortable ranked view over all scraped companies."""
    filter_clause = ""
    params: list[int] = []
    if company_ids is not None:
        if not company_ids:
            return []
        placeholders = ", ".join("?" for _ in company_ids)
        filter_clause = f"WHERE c.id IN ({placeholders})"
        params = company_ids

    return connection.execute(
        f"""
        SELECT
            c.id,
            c.name,
            COALESCE(s.fit_score, 0) AS fit_score,
            s.raw_score,
            s.cap_reason,
            COALESCE(s.category, 'Other') AS category,
            COALESCE(s.rationale, 'Not scored yet.') AS rationale,
            s.startup_fit,
            s.stage_fit,
            s.sector_fit,
            e.status AS enrichment_status,
            e.resolved_url,
            e.resolved_domain,
            e.title,
            e.description,
            e.industry,
            e.is_public,
            e.founded_year,
            e.employee_count,
            e.funding_stage,
            e.total_funding,
            e.hq_location,
            e.canonical_name,
            e.entity_confidence,
            e.company_type,
            e.software_led,
            e.venture_backed,
            e.north_america_presence,
            e.customer_segment,
            e.logistics_function,
            e.supply_chain_subsector,
            e.target_customer,
            e.enterprise_traction,
            e.wv_edge,
            e.disqualifiers,
            e.evidence_snippet,
            e.enrichment_schema_version,
            e.ownership_status,
            e.business_model,
            e.latest_round_date,
            e.latest_round_amount,
            e.named_investors,
            e.logistics_workflow,
            e.target_buyer,
            e.traction_tier,
            e.wv_partner_match,
            e.source_quality,
            e.evidence_urls,
            s.deterministic_notes,
            s.llm_model,
            c.scraped_at
        FROM companies c
        LEFT JOIN enrichments e ON e.company_id = c.id
        LEFT JOIN scores s ON s.company_id = c.id
        {filter_clause}
        ORDER BY fit_score DESC, sector_fit DESC, startup_fit DESC, c.name ASC
        """,
        params,
    ).fetchall()
