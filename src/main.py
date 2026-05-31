from __future__ import annotations

import argparse
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from db import (
    get_connection,
    load_companies,
    pending_enrichment,
    pending_scoring,
    ranked_pipeline,
    save_enrichment,
    save_score,
)
from exa_client import ExaTransientError, enrich_company
from llm_client import DEFAULT_MODEL
from models import (
    BusinessModel,
    CompanyType,
    ENRICHMENT_SCHEMA_VERSION,
    EnrichmentRecord,
    EnrichmentStatus,
    FundingStage,
    LogisticsWorkflow,
    OwnershipStatus,
    SourceQuality,
    TargetBuyer,
    TractionTier,
)
from reporting import export_ranked_pipeline
from scraper import scrape_attendees
from scoring import score_company


_DEFAULT_OUTPUT_DIR = Path("output")


def main() -> None:
    args = _parse_args()
    _load_dotenv(Path(".env"))

    attendees = scrape_attendees()
    with get_connection() as connection:
        inserted = load_companies(connection, attendees)
        _log(f"Scraped {len(attendees)} attendees; inserted {inserted} new rows.")
        backfilled = _backfill_missing_confidence(connection)
        if backfilled:
            _log(f"Enrichment: backfilled entity confidence for {backfilled} cached rows.")
        structured_backfilled = _backfill_structured_defaults(connection)
        if structured_backfilled:
            _log(f"Enrichment: backfilled structured defaults for {structured_backfilled} cached rows.")
        sample_ids = _sample_company_ids(connection, args.sample_size, args.sample_seed)
        if sample_ids is not None:
            _log(f"Sample: selected {len(sample_ids)} random companies.")

        if args.refresh_enrichment:
            _delete_enrichments(connection, sample_ids)
            connection.commit()
            _log("Enrichment: cleared cached enrichments for this scope.")
        elif args.refresh_stale_enrichment:
            refreshed = _delete_stale_enrichments(connection, sample_ids)
            connection.commit()
            _log(f"Enrichment: cleared {refreshed} stale cached enrichments for this scope.")

        if not args.skip_enrichment:
            _run_enrichment(
                connection,
                limit=None if args.full else args.enrich_limit,
                delay=args.delay,
                workers=args.workers,
                company_ids=sample_ids,
            )

        if not args.skip_scoring:
            if args.rescore:
                if sample_ids is None:
                    connection.execute("DELETE FROM scores")
                else:
                    _delete_scores_for_ids(connection, sample_ids)
                connection.commit()
                _log("Scoring: cleared existing scores.")
            _run_scoring(
                connection,
                limit=args.score_limit,
                use_llm=not args.no_llm,
                model=args.model,
                workers=args.workers,
                company_ids=sample_ids,
            )

        coverage = _pipeline_counts(connection, sample_ids)
        rows = ranked_pipeline(connection, sample_ids)

    csv_path, html_path = export_ranked_pipeline(
        rows,
        args.output_dir,
        sample_seed=args.sample_seed,
        sample_size=args.sample_size,
    )
    _log(f"Exported {len(rows)} rows:")
    _log(f"  CSV:  {csv_path}")
    _log(f"  HTML: {html_path}")
    _log(
        "Coverage: "
        f"{coverage['enriched']}/{coverage['total']} enriched, "
        f"{coverage['scored']}/{coverage['total']} scored, "
        f"{coverage['pending_enrichment']} pending enrichment."
    )
    if coverage["pending_enrichment"]:
        _log("Coverage: partial ranking; run with --full to enrich every pending row.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a ranked Wittington Ventures prospect pipeline from Manifest attendees."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Process every pending enrichment row. Without this, only --enrich-limit rows are enriched.",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=25,
        help="Maximum pending companies to enrich in this run unless --full is set. Use 0 to avoid paid Exa calls.",
    )
    parser.add_argument(
        "--score-limit",
        type=int,
        default=None,
        help="Maximum pending enriched companies to score in this run. Defaults to all pending scores.",
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip Exa calls and only score/export existing DB rows.",
    )
    parser.add_argument("--skip-scoring", action="store_true", help="Skip scoring and only export existing rows.")
    parser.add_argument("--rescore", action="store_true", help="Clear cached scores and score enriched rows again.")
    parser.add_argument(
        "--refresh-enrichment",
        action="store_true",
        help="Clear cached enrichments in scope before running. Use only for evaluation or schema changes.",
    )
    parser.add_argument(
        "--refresh-stale-enrichment",
        action="store_true",
        help="Clear only cached enrichments older than the current schema version in scope.",
    )
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic scoring only.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model for scoring judgment.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Seconds to wait between Exa calls when --workers=1.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Concurrent API workers for enrichment and LLM scoring. Default 6 balances Exa reliability and speed.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Randomly evaluate this many companies from the full source list.",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=None,
        help="Optional seed for reproducible random samples.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Directory for ranked_prospects.csv and ranked_prospects.html.",
    )
    return parser.parse_args()


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=value pairs without adding a dotenv dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        key, raw = value.split("=", 1)
        os.environ.setdefault(key.strip(), raw.strip().strip('"').strip("'"))


def _run_enrichment(
    connection,
    *,
    limit: int | None,
    delay: float,
    workers: int,
    company_ids: list[int] | None = None,
) -> None:
    pending = _pending_enrichment(connection, company_ids)
    selected = pending if limit is None else pending[: max(0, limit)]
    if not selected:
        _log(f"Enrichment: 0 processed, {len(pending)} pending.")
        return

    if not os.environ.get("EXA_API"):
        raise RuntimeError("EXA_API is required for enrichment. Add it to .env or use --skip-enrichment.")

    _log(f"Enrichment: processing {len(selected)} of {len(pending)} pending rows.")
    resolved = 0
    retry_later = 0
    if workers <= 1:
        for index, row in enumerate(selected, start=1):
            record = _enrichment_record(row["id"], row["name"])
            if record is None:
                retry_later += 1
                _log(f"  [{index}/{len(selected)}] {row['name']} -> retry_later")
                continue
            if record.status == EnrichmentStatus.RESOLVED:
                resolved += 1
            save_enrichment(connection, record)
            _log(f"  [{index}/{len(selected)}] {row['name']} -> {record.status}")
            if delay and index < len(selected):
                time.sleep(delay)
    else:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = {
                executor.submit(_enrichment_record, row["id"], row["name"]): row["name"]
                for row in selected
            }
            for index, future in enumerate(as_completed(futures), start=1):
                record = future.result()
                if record is None:
                    retry_later += 1
                    _log(f"  [{index}/{len(selected)}] {futures[future]} -> retry_later")
                    continue
                if record.status == EnrichmentStatus.RESOLVED:
                    resolved += 1
                save_enrichment(connection, record)
                _log(f"  [{index}/{len(selected)}] {futures[future]} -> {record.status}")
    _log(
        "Enrichment: saved "
        f"{len(selected) - retry_later} rows ({resolved} resolved, {retry_later} retry later)."
    )


def _enrichment_record(company_id: int, name: str) -> EnrichmentRecord | None:
    try:
        enrichment = enrich_company(name)
    except ExaTransientError:
        return None
    if enrichment is None:
        return EnrichmentRecord(company_id=company_id, status=EnrichmentStatus.UNRESOLVED)
    heuristic_confidence = _heuristic_entity_confidence(
        name,
        enrichment.resolved_domain,
        enrichment.firmographics.canonical_name,
        enrichment.title,
    )
    firmographics = enrichment.firmographics.model_dump()
    firmographics["entity_confidence"] = _calibrated_entity_confidence(
        enrichment.firmographics.entity_confidence,
        heuristic_confidence,
    )
    firmographics = _postprocess_firmographics(name, enrichment, firmographics)
    return EnrichmentRecord(
        company_id=company_id,
        status=EnrichmentStatus.RESOLVED,
        resolved_url=enrichment.resolved_url,
        resolved_domain=enrichment.resolved_domain,
        title=enrichment.title,
        **firmographics,
    )


def _postprocess_firmographics(name: str, enrichment, data: dict) -> dict:
    """Fill high-value structured fields when Exa leaves them blank or generic."""
    data["enrichment_schema_version"] = ENRICHMENT_SCHEMA_VERSION
    data["evidence_urls"] = data.get("evidence_urls") or enrichment.resolved_url

    text = _enrichment_text(name, enrichment, data)
    ownership_status = _infer_ownership_status(data, text)
    if ownership_status in (OwnershipStatus.PUBLIC, OwnershipStatus.ACQUIRED, OwnershipStatus.SUBSIDIARY):
        data["ownership_status"] = ownership_status
    else:
        _set_if_missing(data, "ownership_status", ownership_status)
    _set_if_missing(data, "business_model", _infer_business_model(data, text))
    _set_if_missing(data, "logistics_workflow", _infer_logistics_workflow(text))
    _set_if_missing(data, "target_buyer", _infer_target_buyer(text))
    _set_if_missing(data, "traction_tier", _infer_traction_tier(data, text))
    _set_if_missing(data, "wv_partner_match", _infer_wv_partner_match(text))
    _set_if_missing(data, "source_quality", _infer_source_quality(data))
    if data.get("software_led") is None:
        data["software_led"] = _infer_software_led(data)
    if data.get("venture_backed") is None:
        data["venture_backed"] = _infer_venture_backed(data)
    return data


def _enrichment_text(name: str, enrichment, data: dict) -> str:
    values = [
        name,
        enrichment.resolved_domain,
        enrichment.title,
        data.get("canonical_name"),
        data.get("description"),
        data.get("industry"),
        data.get("customer_segment"),
        data.get("logistics_function"),
        data.get("supply_chain_subsector"),
        data.get("target_customer"),
        data.get("enterprise_traction"),
        data.get("wv_edge"),
        data.get("disqualifiers"),
        data.get("evidence_snippet"),
    ]
    return " ".join(str(value).lower() for value in values if value)


def _set_if_missing(data: dict, field: str, value: object | None) -> None:
    if value is None:
        return
    current = _value(data.get(field))
    if _is_missing_value(current):
        data[field] = value


def _value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


def _is_missing_value(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in {"", "unknown", "null", "none", "n/a"})


def _infer_ownership_status(data: dict, text: str) -> OwnershipStatus:
    company_type = _value(data.get("company_type"))
    funding_stage = _value(data.get("funding_stage"))
    if data.get("is_public") or funding_stage == FundingStage.PUBLIC.value:
        return OwnershipStatus.PUBLIC
    if funding_stage == FundingStage.ACQUIRED.value or _has_any(text, ["acquired", "subsidiary of"]):
        return OwnershipStatus.ACQUIRED
    if company_type == CompanyType.NONPROFIT.value:
        return OwnershipStatus.NONPROFIT
    if company_type == CompanyType.GOVERNMENT.value:
        return OwnershipStatus.GOVERNMENT
    if company_type == CompanyType.INCUMBENT.value:
        return OwnershipStatus.INCUMBENT
    if _has_any(text, ["subsidiary", "division of", "owned by"]):
        return OwnershipStatus.SUBSIDIARY
    return OwnershipStatus.PRIVATE


def _infer_business_model(data: dict, text: str) -> BusinessModel:
    company_type = _value(data.get("company_type"))
    mapping = {
        CompanyType.SAAS.value: BusinessModel.SAAS,
        CompanyType.PLATFORM.value: BusinessModel.PLATFORM,
        CompanyType.MARKETPLACE.value: BusinessModel.MARKETPLACE,
        CompanyType.ROBOTICS.value: BusinessModel.ROBOTICS_AUTOMATION,
        CompanyType.BRAND.value: BusinessModel.BRAND,
        CompanyType.CARRIER.value: BusinessModel.CARRIER,
        CompanyType.BROKER.value: BusinessModel.BROKER,
        CompanyType.THREE_PL.value: BusinessModel.THREE_PL,
        CompanyType.SHIPPER.value: BusinessModel.TECH_ENABLED_SERVICES,
        CompanyType.CONSULTANCY.value: BusinessModel.CONSULTANCY_AGENCY,
        CompanyType.AGENCY.value: BusinessModel.CONSULTANCY_AGENCY,
        CompanyType.MANUFACTURER.value: BusinessModel.MANUFACTURER,
        CompanyType.RETAILER.value: BusinessModel.RETAILER,
        CompanyType.DISTRIBUTOR.value: BusinessModel.DISTRIBUTOR,
        CompanyType.INVESTOR.value: BusinessModel.INVESTOR,
        CompanyType.NONPROFIT.value: BusinessModel.NONPROFIT_GOVERNMENT,
        CompanyType.GOVERNMENT.value: BusinessModel.NONPROFIT_GOVERNMENT,
        CompanyType.INCUMBENT.value: BusinessModel.INCUMBENT,
        CompanyType.OTHER.value: BusinessModel.OTHER,
    }
    if company_type in mapping:
        return mapping[company_type]
    if _has_any(text, ["api", "developer platform"]):
        return BusinessModel.API
    if _has_any(text, ["robot", "automation", "autonomous"]):
        return BusinessModel.ROBOTICS_AUTOMATION
    if _has_any(text, ["software", "saas"]):
        return BusinessModel.SAAS
    if "marketplace" in text:
        return BusinessModel.MARKETPLACE
    if "platform" in text:
        return BusinessModel.PLATFORM
    if _has_any(text, ["3pl", "third-party logistics", "third party logistics"]):
        return BusinessModel.THREE_PL
    if "broker" in text:
        return BusinessModel.BROKER
    if "carrier" in text:
        return BusinessModel.CARRIER
    if _has_any(text, ["consulting", "agency"]):
        return BusinessModel.CONSULTANCY_AGENCY
    return BusinessModel.UNKNOWN


def _infer_software_led(data: dict) -> bool | None:
    company_type = _value(data.get("company_type"))
    business_model = _value(data.get("business_model"))
    software_models = {
        BusinessModel.SAAS.value,
        BusinessModel.API.value,
        BusinessModel.PLATFORM.value,
        BusinessModel.MARKETPLACE.value,
        BusinessModel.HARDWARE_SOFTWARE.value,
        BusinessModel.ROBOTICS_AUTOMATION.value,
    }
    non_software_models = {
        BusinessModel.BRAND.value,
        BusinessModel.CARRIER.value,
        BusinessModel.BROKER.value,
        BusinessModel.THREE_PL.value,
        BusinessModel.RETAILER.value,
        BusinessModel.MANUFACTURER.value,
        BusinessModel.DISTRIBUTOR.value,
        BusinessModel.CONSULTANCY_AGENCY.value,
        BusinessModel.INVESTOR.value,
        BusinessModel.NONPROFIT_GOVERNMENT.value,
        BusinessModel.INCUMBENT.value,
    }
    if company_type in {CompanyType.SAAS.value, CompanyType.PLATFORM.value, CompanyType.MARKETPLACE.value, CompanyType.ROBOTICS.value}:
        return True
    if business_model in software_models:
        return True
    if company_type in {
        CompanyType.BRAND.value,
        CompanyType.CARRIER.value,
        CompanyType.BROKER.value,
        CompanyType.THREE_PL.value,
        CompanyType.SHIPPER.value,
        CompanyType.CONSULTANCY.value,
        CompanyType.AGENCY.value,
        CompanyType.MANUFACTURER.value,
        CompanyType.RETAILER.value,
        CompanyType.DISTRIBUTOR.value,
        CompanyType.INVESTOR.value,
        CompanyType.NONPROFIT.value,
        CompanyType.GOVERNMENT.value,
        CompanyType.INCUMBENT.value,
    }:
        return False
    if business_model in non_software_models:
        return False
    return None


def _infer_venture_backed(data: dict) -> bool | None:
    stage = _value(data.get("funding_stage"))
    if stage in {
        FundingStage.SEED.value,
        FundingStage.SERIES_A.value,
        FundingStage.SERIES_B.value,
        FundingStage.SERIES_C.value,
        FundingStage.SERIES_D_PLUS.value,
    }:
        return True
    if data.get("latest_round_amount") or data.get("named_investors"):
        return True
    if stage in {FundingStage.BOOTSTRAPPED.value, FundingStage.PUBLIC.value, FundingStage.ACQUIRED.value}:
        return False
    return None


def _infer_logistics_workflow(text: str) -> LogisticsWorkflow:
    checks = [
        (LogisticsWorkflow.WAREHOUSE_AUTOMATION, ["warehouse automation", "robotic fulfillment", "autonomous mobile robot"]),
        (LogisticsWorkflow.WMS, ["wms", "warehouse management"]),
        (LogisticsWorkflow.TMS, ["tms", "transportation management"]),
        (LogisticsWorkflow.YARD_MANAGEMENT, ["yard management", "yard operations"]),
        (LogisticsWorkflow.FREIGHT_VISIBILITY, ["freight visibility", "shipment visibility", "container tracking", "tracking api"]),
        (LogisticsWorkflow.PROCUREMENT, ["procurement", "sourcing", "supplier"]),
        (LogisticsWorkflow.LAST_MILE, ["last mile", "last-mile", "delivery orchestration"]),
        (LogisticsWorkflow.MIDDLE_MILE, ["middle mile", "middle-mile", "linehaul"]),
        (LogisticsWorkflow.RETURNS, ["returns", "reverse logistics"]),
        (LogisticsWorkflow.COLD_CHAIN, ["cold chain", "temperature-controlled", "temperature controlled"]),
        (LogisticsWorkflow.CROSS_BORDER, ["cross-border", "cross border", "customs", "duties"]),
        (LogisticsWorkflow.PAYMENTS_FINTECH, ["payments", "freight audit", "invoice", "financing"]),
        (LogisticsWorkflow.INVENTORY, ["inventory", "stockout", "demand planning"]),
        (LogisticsWorkflow.FULFILLMENT, ["fulfillment", "fulfilment", "order management"]),
        (LogisticsWorkflow.SUSTAINABILITY, ["carbon", "emissions", "sustainability", "decarbon"]),
        (LogisticsWorkflow.ECOMMERCE_ENABLEMENT, ["ecommerce", "e-commerce", "online retail"]),
    ]
    for workflow, terms in checks:
        if _has_any(text, terms):
            return workflow
    if _has_any(text, ["logistics", "supply chain", "freight", "warehouse", "shipping"]):
        return LogisticsWorkflow.OTHER
    return LogisticsWorkflow.NOT_APPLICABLE


def _infer_target_buyer(text: str) -> TargetBuyer:
    checks = [
        (TargetBuyer.GROCERY, ["grocery", "grocer"]),
        (TargetBuyer.PHARMACY, ["pharmacy", "pharma"]),
        (TargetBuyer.RETAILER, ["retailer", "retail"]),
        (TargetBuyer.ECOMMERCE_BRAND, ["ecommerce brand", "e-commerce brand", "shopify", "dtc"]),
        (TargetBuyer.SHIPPER, ["shipper", "importer", "exporter"]),
        (TargetBuyer.CARRIER, ["carrier", "truckload", "fleet"]),
        (TargetBuyer.BROKER, ["broker", "freight broker"]),
        (TargetBuyer.WAREHOUSE, ["warehouse", "fulfillment center", "distribution center"]),
        (TargetBuyer.MANUFACTURER, ["manufacturer", "manufacturing"]),
        (TargetBuyer.LOGISTICS_PROVIDER, ["3pl", "logistics provider", "forwarder"]),
        (TargetBuyer.HEALTHCARE_PROVIDER, ["hospital", "clinic", "healthcare provider"]),
        (TargetBuyer.CONSUMER, ["consumer", "shopper"]),
        (TargetBuyer.SMB, ["small business", "smb"]),
        (TargetBuyer.ENTERPRISE, ["enterprise", "large companies"]),
    ]
    for buyer, terms in checks:
        if _has_any(text, terms):
            return buyer
    return TargetBuyer.UNKNOWN


def _infer_traction_tier(data: dict, text: str) -> TractionTier:
    traction = str(data.get("enterprise_traction") or "").lower()
    if _has_any(traction, ["partnership", "partnered", "strategic partner"]):
        return TractionTier.MAJOR_PARTNERSHIP
    if _has_any(traction, ["customer", "customers", "client", "clients"]):
        return TractionTier.NAMED_CUSTOMERS
    if _has_any(traction, ["pilot", "trial"]):
        return TractionTier.PILOT
    if _has_any(traction, ["revenue", "arr", "sales"]):
        return TractionTier.REVENUE_SIGNAL
    if data.get("total_funding") or _value(data.get("funding_stage")) in {
        FundingStage.SEED.value,
        FundingStage.SERIES_A.value,
        FundingStage.SERIES_B.value,
        FundingStage.SERIES_C.value,
    }:
        return TractionTier.FUNDING_SIGNAL
    if _has_any(text, ["no public traction", "no clear traction"]):
        return TractionTier.NONE
    return TractionTier.UNKNOWN


def _infer_wv_partner_match(text: str) -> str | None:
    matches = []
    if _has_any(text, ["grocery", "food retail", "retailer", "retail", "inventory", "fulfillment", "warehouse"]):
        matches.append("Loblaw")
    if _has_any(text, ["pharmacy", "healthcare", "patient", "clinic", "pharma"]):
        matches.append("Shoppers Drug Mart")
    if _has_any(text, ["real estate", "property", "store network", "retail location"]):
        matches.append("Choice Properties")
    if _has_any(text, ["payments", "fintech", "financial services", "credit"]):
        matches.append("PC Financial")
    if _has_any(text, ["apparel", "beauty", "consumer brand", "luxury", "fashion"]):
        matches.append("Holt Renfrew/Joe Fresh")
    if _has_any(text, ["supply chain", "logistics", "freight", "warehouse", "transportation"]):
        matches.append("Supply-chain network")
    return "; ".join(dict.fromkeys(matches)) if matches else None


def _infer_source_quality(data: dict) -> SourceQuality:
    confidence = data.get("entity_confidence") or 0
    has_basics = bool(data.get("description") and data.get("industry"))
    has_structure = any(
        data.get(field)
        for field in ("company_type", "business_model", "ownership_status", "logistics_workflow", "target_buyer")
    )
    has_evidence = bool(data.get("evidence_snippet") or data.get("evidence_urls"))
    if confidence >= 85 and has_basics and has_structure and has_evidence:
        return SourceQuality.HIGH
    if confidence >= 70 and has_basics:
        return SourceQuality.MEDIUM
    if confidence:
        return SourceQuality.LOW
    return SourceQuality.UNKNOWN


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _run_scoring(
    connection,
    *,
    limit: int | None,
    use_llm: bool,
    model: str,
    workers: int,
    company_ids: list[int] | None = None,
) -> None:
    pending = _pending_scoring(connection, company_ids)
    selected = pending if limit is None else pending[: max(0, limit)]
    if not selected:
        _log(f"Scoring: 0 processed, {len(pending)} pending.")
        return

    _log(f"Scoring: processing {len(selected)} of {len(pending)} pending rows.")
    if workers <= 1:
        for row in selected:
            score = score_company(row, use_llm=use_llm, model=model)
            save_score(connection, score)
    else:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(score_company, row, use_llm=use_llm, model=model) for row in selected]
            for future in as_completed(futures):
                save_score(connection, future.result())
    _log(f"Scoring: saved {len(selected)} rows.")


def _log(message: str) -> None:
    print(message, flush=True)


def _sample_company_ids(connection, sample_size: int | None, seed: int | None) -> list[int] | None:
    if sample_size is None:
        return None
    rows = connection.execute("SELECT id FROM companies ORDER BY id").fetchall()
    ids = [row["id"] for row in rows]
    rng = random.Random(seed)
    return rng.sample(ids, k=min(sample_size, len(ids)))


def _pending_enrichment(connection, company_ids: list[int] | None):
    if company_ids is None:
        return pending_enrichment(connection)
    if not company_ids:
        return []
    placeholders = ", ".join("?" for _ in company_ids)
    return connection.execute(
        f"""
        SELECT c.id, c.name
        FROM companies c
        LEFT JOIN enrichments e ON e.company_id = c.id
        WHERE e.company_id IS NULL
          AND c.id IN ({placeholders})
        ORDER BY c.id
        """,
        company_ids,
    ).fetchall()


def _pending_scoring(connection, company_ids: list[int] | None):
    if company_ids is None:
        return pending_scoring(connection)
    if not company_ids:
        return []
    placeholders = ", ".join("?" for _ in company_ids)
    return connection.execute(
        f"""
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
          AND c.id IN ({placeholders})
        ORDER BY c.id
        """,
        company_ids,
    ).fetchall()


def _delete_scores_for_ids(connection, company_ids: list[int]) -> None:
    if not company_ids:
        return
    placeholders = ", ".join("?" for _ in company_ids)
    connection.execute(f"DELETE FROM scores WHERE company_id IN ({placeholders})", company_ids)


def _delete_enrichments(connection, company_ids: list[int] | None) -> None:
    if company_ids is None:
        connection.execute("DELETE FROM enrichments")
        return
    if not company_ids:
        return
    placeholders = ", ".join("?" for _ in company_ids)
    connection.execute(f"DELETE FROM enrichments WHERE company_id IN ({placeholders})", company_ids)


def _delete_stale_enrichments(connection, company_ids: list[int] | None) -> int:
    where = "WHERE COALESCE(enrichment_schema_version, 0) < ?"
    params: list[int] = [ENRICHMENT_SCHEMA_VERSION]
    if company_ids is not None:
        if not company_ids:
            return 0
        placeholders = ", ".join("?" for _ in company_ids)
        where += f" AND company_id IN ({placeholders})"
        params.extend(company_ids)
    before = connection.total_changes
    connection.execute(f"DELETE FROM enrichments {where}", params)
    return connection.total_changes - before


def _pipeline_counts(connection, company_ids: list[int] | None) -> dict[str, int]:
    filter_clause = ""
    params: list[int] = []
    if company_ids is not None:
        if not company_ids:
            return {"total": 0, "enriched": 0, "scored": 0, "pending_enrichment": 0}
        placeholders = ", ".join("?" for _ in company_ids)
        filter_clause = f"WHERE c.id IN ({placeholders})"
        params = company_ids
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(e.company_id) AS enriched,
            COUNT(s.company_id) AS scored
        FROM companies c
        LEFT JOIN enrichments e ON e.company_id = c.id
        LEFT JOIN scores s ON s.company_id = c.id
        {filter_clause}
        """,
        params,
    ).fetchone()
    total = row["total"] or 0
    enriched = row["enriched"] or 0
    scored = row["scored"] or 0
    return {
        "total": total,
        "enriched": enriched,
        "scored": scored,
        "pending_enrichment": total - enriched,
    }


def _backfill_missing_confidence(connection) -> int:
    rows = connection.execute(
        """
        SELECT
            c.id,
            c.name,
            e.resolved_domain,
            e.canonical_name,
            e.title,
            e.entity_confidence
        FROM companies c
        JOIN enrichments e ON e.company_id = c.id
        WHERE e.status = 'resolved'
          AND (e.entity_confidence IS NULL OR e.entity_confidence < 50)
        """
    ).fetchall()
    updated = 0
    for row in rows:
        confidence = _calibrated_entity_confidence(
            row["entity_confidence"],
            _heuristic_entity_confidence(
                row["name"], row["resolved_domain"], row["canonical_name"], row["title"]
            ),
        )
        if confidence == row["entity_confidence"]:
            continue
        connection.execute(
            "UPDATE enrichments SET entity_confidence = ? WHERE company_id = ?",
            (confidence, row["id"]),
        )
        updated += 1
    connection.commit()
    return updated


def _backfill_structured_defaults(connection) -> int:
    before = connection.total_changes
    connection.execute(
        """
        UPDATE enrichments
        SET software_led = 1
        WHERE software_led IS NULL
          AND (
            company_type IN ('SaaS', 'Platform', 'Marketplace', 'Robotics')
            OR business_model IN ('SaaS', 'API', 'Platform', 'Marketplace', 'Hardware-enabled software', 'Robotics/automation')
          )
        """
    )
    connection.execute(
        """
        UPDATE enrichments
        SET software_led = 0
        WHERE software_led IS NULL
          AND (
            company_type IN ('Brand', 'Carrier', 'Broker', '3PL', 'Shipper', 'Consultancy', 'Agency', 'Manufacturer', 'Retailer', 'Distributor', 'Investor', 'Nonprofit', 'Government', 'Incumbent')
            OR business_model IN ('Brand', 'Carrier', 'Broker', '3PL', 'Retailer', 'Manufacturer', 'Distributor', 'Consultancy/agency', 'Investor', 'Nonprofit/government', 'Incumbent')
          )
        """
    )
    connection.execute(
        """
        UPDATE enrichments
        SET venture_backed = 1
        WHERE venture_backed IS NULL
          AND funding_stage IN ('Seed', 'Series A', 'Series B', 'Series C', 'Series D+')
        """
    )
    connection.execute(
        """
        UPDATE enrichments
        SET venture_backed = 0
        WHERE venture_backed IS NULL
          AND funding_stage IN ('Bootstrapped', 'Public', 'Acquired')
        """
    )
    connection.execute(
        """
        UPDATE enrichments
        SET ownership_status = 'Acquired'
        WHERE LOWER(COALESCE(disqualifiers, '') || ' ' || COALESCE(evidence_snippet, '')) LIKE '%acquired%'
        """
    )
    connection.execute(
        """
        UPDATE enrichments
        SET ownership_status = 'Public'
        WHERE is_public = 1 OR funding_stage = 'Public'
        """
    )
    connection.commit()
    return connection.total_changes - before


def _calibrated_entity_confidence(current: int | None, heuristic: int) -> int:
    """Raise legacy low confidence only when local identity evidence is strong."""
    if current is None:
        return heuristic
    if current <= 1:
        return max(current, heuristic)
    if current < 50 and heuristic >= 80:
        return heuristic
    return current


def _heuristic_entity_confidence(
    searched_name: str,
    resolved_domain: str | None,
    canonical_name: str | None,
    title: str | None,
) -> int:
    """Fallback confidence when Exa omits one from the structured summary."""
    name_compact = _compact(searched_name)
    domain_label = _compact((resolved_domain or "").split(".", 1)[0])
    canonical_compact = _compact(canonical_name or "")
    title_compact = _compact(title or "")

    if domain_label and _same_or_contains(name_compact, domain_label):
        return 95
    if canonical_compact and _same_or_contains(name_compact, canonical_compact):
        return 90

    name_tokens = _tokens(searched_name)
    haystack = " ".join(filter(None, [domain_label, canonical_compact, title_compact]))
    if any(token in haystack for token in name_tokens):
        return 80
    return 55


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _tokens(value: str) -> set[str]:
    stopwords = {"inc", "llc", "ltd", "limited", "corp", "corporation", "company", "co", "the"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 4 and token not in stopwords
    }


def _same_or_contains(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or (len(left) >= 4 and left in right) or (len(right) >= 4 and right in left)


if __name__ == "__main__":
    main()
