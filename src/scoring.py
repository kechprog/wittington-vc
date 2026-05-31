"""Wittington Ventures fit scoring.

The score is deterministic first, then optionally nudged by an LLM for judgment
and a cleaner one-line rationale. This keeps cost bounded and reruns cacheable.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from llm_client import DEFAULT_MODEL, judge_fit
from models import (
    BusinessModel,
    CompanyType,
    ENRICHMENT_SCHEMA_VERSION,
    EnrichmentStatus,
    FitStatus,
    FundingStage,
    OwnershipStatus,
    ScoreRecord,
    SourceQuality,
    TractionTier,
    WittingtonCategory,
)


_COMMERCE = {
    "supply chain",
    "logistics",
    "freight",
    "warehouse",
    "warehousing",
    "fulfillment",
    "fulfilment",
    "ecommerce",
    "e-commerce",
    "retail",
    "commerce",
    "inventory",
    "procurement",
    "transportation",
    "shipping",
    "delivery",
    "last mile",
    "middle mile",
    "returns",
    "3pl",
    "order management",
}
_HEALTHCARE = {
    "health",
    "healthcare",
    "clinical",
    "patient",
    "pharma",
    "biotech",
    "medical",
    "care",
    "therapy",
    "diagnostic",
    "hospital",
}
_CONSUMER = {
    "consumer",
    "beauty",
    "wellness",
    "food",
    "beverage",
    "nutrition",
    "grocery",
    "apparel",
    "brand",
    "personal care",
    "cpg",
}
_CLIMATE = {
    "climate",
    "carbon",
    "emission",
    "sustainability",
    "renewable",
    "energy",
    "electric",
    "ev",
    "fleet efficiency",
    "waste",
    "circular",
    "decarbon",
    "clean",
}
_FOOD = {"food", "agriculture", "agtech", "restaurant", "grocery", "farm", "protein"}

_NON_STARTUP_TERMS = {
    "association",
    "university",
    "college",
    "government",
    "ministry",
    "department",
    "authority",
    "consulting",
    "consultants",
    "brokerage",
    "capital",
    "private equity",
    "investment bank",
    "securities",
    "ventures",
    "venture capital",
    "retirement system",
    "media",
    "magazine",
    "conference",
    "chamber of commerce",
}
_INCUMBENT_TERMS = {
    "global",
    "worldwide",
    "group",
    "corporation",
    "corp",
    "inc.",
    "limited",
}
_SOFTWARE_TYPES = {
    CompanyType.SAAS,
    CompanyType.PLATFORM,
    CompanyType.MARKETPLACE,
    CompanyType.ROBOTICS,
}
_SOFTWARE_BUSINESS_MODELS = {
    BusinessModel.SAAS,
    BusinessModel.API,
    BusinessModel.PLATFORM,
    BusinessModel.MARKETPLACE,
    BusinessModel.HARDWARE_SOFTWARE,
    BusinessModel.ROBOTICS_AUTOMATION,
}
_SERVICE_TYPES = {
    CompanyType.CARRIER,
    CompanyType.BROKER,
    CompanyType.THREE_PL,
    CompanyType.SHIPPER,
    CompanyType.CONSULTANCY,
    CompanyType.AGENCY,
    CompanyType.DISTRIBUTOR,
    CompanyType.MANUFACTURER,
    CompanyType.RETAILER,
}
_SERVICE_BUSINESS_MODELS = {
    BusinessModel.TECH_ENABLED_SERVICES,
    BusinessModel.CARRIER,
    BusinessModel.BROKER,
    BusinessModel.THREE_PL,
    BusinessModel.RETAILER,
    BusinessModel.MANUFACTURER,
    BusinessModel.DISTRIBUTOR,
    BusinessModel.CONSULTANCY_AGENCY,
}
_HARD_NONFIT_TYPES = {
    CompanyType.INVESTOR,
    CompanyType.NONPROFIT,
    CompanyType.GOVERNMENT,
    CompanyType.INCUMBENT,
}
_HARD_NONFIT_OWNERSHIP = {
    OwnershipStatus.PUBLIC,
    OwnershipStatus.NONPROFIT,
    OwnershipStatus.GOVERNMENT,
    OwnershipStatus.INCUMBENT,
}
_EMPLOYEE_PATTERN = re.compile(r"\d[\d,]*")


@dataclass(frozen=True)
class ScoreParts:
    startup_fit: int
    stage_fit: int
    sector_fit: int
    category: WittingtonCategory
    notes: list[str]

    @property
    def base_score(self) -> int:
        return round(self.startup_fit * 0.4 + self.stage_fit * 0.25 + self.sector_fit * 0.35)


def score_company(row: sqlite3.Row, *, use_llm: bool = True, model: str = DEFAULT_MODEL) -> ScoreRecord:
    """Build a cached score row for one enrichment row."""
    if row["status"] != EnrichmentStatus.RESOLVED:
        return ScoreRecord(
            company_id=row["company_id"],
            status=FitStatus.SKIPPED,
            fit_score=0,
            raw_score=0,
            cap_reason="unresolved_enrichment",
            category=WittingtonCategory.OTHER,
            startup_fit=0,
            stage_fit=0,
            sector_fit=0,
            rationale="Skipped because the company could not be resolved or enriched.",
            deterministic_notes="No validated firmographics available.",
            llm_model=None,
        )

    parts = _deterministic_score(row)
    adjustment = 0
    category = parts.category
    rationale = _fallback_rationale(row, parts)
    llm_model = None

    if use_llm and _should_use_llm(row, parts):
        judgment = judge_fit(_judgment_prompt(row, parts), model=model)
        if judgment is not None:
            adjustment = judgment.score_adjustment
            category = judgment.category
            rationale = _clean_sentence(judgment.rationale)
            llm_model = model

    raw_score = max(0, min(100, parts.base_score + adjustment))
    fit_score = raw_score
    cap_reason = None

    def cap(limit: int, reason: str) -> None:
        nonlocal cap_reason, fit_score
        if fit_score > limit:
            fit_score = limit
            cap_reason = reason

    if _is_stale_enrichment(row):
        cap(65, "stale_enrichment_schema")
    if _has_core_structured_gap(row):
        cap(65, "core_structured_gap")
    elif row["company_type"] in (None, "", CompanyType.UNKNOWN):
        cap(78, "unknown_company_type")
    if row["entity_confidence"] is None:
        cap(82, "missing_entity_confidence")
    elif row["entity_confidence"] < 50:
        cap(60, "low_entity_confidence")
    if row["is_public"] or row["funding_stage"] == FundingStage.PUBLIC:
        cap(25, "public_company")
    if _ownership_status(row) in _HARD_NONFIT_OWNERSHIP:
        cap(35 if _ownership_status(row) != OwnershipStatus.PUBLIC else 25, "non_private_ownership")
    if row["funding_stage"] == FundingStage.ACQUIRED:
        cap(45, "acquired_company")
    if _ownership_status(row) == OwnershipStatus.ACQUIRED:
        cap(45, "acquired_company")
    if _has_acquired_disqualifier(row):
        cap(45, "acquired_company")
    if _ownership_status(row) == OwnershipStatus.SUBSIDIARY:
        cap(55, "subsidiary")
    if row["funding_stage"] == FundingStage.SEED:
        cap(90, "seed_stage")
    if row["funding_stage"] in (FundingStage.PRE_SEED, FundingStage.BOOTSTRAPPED):
        cap(75, "too_early_stage")
    if row["funding_stage"] == FundingStage.SERIES_C:
        cap(85, "later_stage")
    if row["funding_stage"] == FundingStage.SERIES_D_PLUS:
        cap(70, "late_stage")
    if _company_type(row) in _HARD_NONFIT_TYPES:
        cap(35, "hard_nonfit_type")
    if _company_type(row) in _SERVICE_TYPES and not _is_true(row["software_led"]):
        cap(55, "non_software_service_provider")
    if _business_model(row) in _SERVICE_BUSINESS_MODELS and not _is_true(row["software_led"]):
        cap(55, "non_software_business_model")
    if _is_false(row["software_led"]) and _company_type(row) != CompanyType.BRAND:
        cap(65, "not_software_led")
    if _is_false(row["software_led"]) and not _is_true(row["venture_backed"]):
        cap(65 if _company_type(row) == CompanyType.BRAND else 55, "not_software_or_venture_backed")
    if _is_false(row["north_america_presence"]):
        cap(70, "outside_north_america")
    if _has_geo_disqualifier(row):
        cap(55, "geo_disqualifier")
    if row["funding_stage"] in (None, FundingStage.UNKNOWN) and not _is_true(row["venture_backed"]):
        cap(78, "unknown_stage_without_venture_signal")
    if category == WittingtonCategory.OTHER:
        cap(60, "other_category")
    if category == WittingtonCategory.OTHER and row["disqualifiers"]:
        cap(55, "other_category_with_disqualifier")
    if _source_quality(row) == SourceQuality.LOW:
        cap(82, "low_source_quality")
    rationale = _cap_rationale(row) or rationale
    status = FitStatus.SCORED if fit_score > 0 else FitStatus.SKIPPED
    return ScoreRecord(
        company_id=row["company_id"],
        status=status,
        fit_score=fit_score,
        raw_score=raw_score,
        cap_reason=cap_reason,
        category=category,
        startup_fit=parts.startup_fit,
        stage_fit=parts.stage_fit,
        sector_fit=parts.sector_fit,
        rationale=rationale,
        deterministic_notes="; ".join(parts.notes),
        llm_model=llm_model,
    )


def _deterministic_score(row: sqlite3.Row) -> ScoreParts:
    text = _company_text(row)
    notes: list[str] = []

    category, sector_fit = _sector_fit(text)
    notes.append(f"sector={category.value}:{sector_fit}")

    stage = row["funding_stage"]
    stage_fit = _stage_fit(stage)
    notes.append(f"stage={stage or 'Unknown'}:{stage_fit}")

    startup_fit = _startup_fit(row, text)
    notes.append(f"startup={startup_fit}")

    return ScoreParts(
        startup_fit=startup_fit,
        stage_fit=stage_fit,
        sector_fit=sector_fit,
        category=category,
        notes=notes,
    )


def _company_text(row: sqlite3.Row) -> str:
    values = [
        row["name"],
        row["title"],
        row["description"],
        row["industry"],
        row["resolved_domain"],
        row["hq_location"],
        row["canonical_name"],
        row["company_type"],
        row["customer_segment"],
        row["logistics_function"],
        row["supply_chain_subsector"],
        row["target_customer"],
        row["wv_edge"],
        _row_value(row, "ownership_status"),
        _row_value(row, "business_model"),
        _row_value(row, "latest_round_date"),
        _row_value(row, "latest_round_amount"),
        _row_value(row, "named_investors"),
        _row_value(row, "logistics_workflow"),
        _row_value(row, "target_buyer"),
        _row_value(row, "traction_tier"),
        _row_value(row, "wv_partner_match"),
        _row_value(row, "source_quality"),
        row["disqualifiers"],
    ]
    return " ".join(str(value).lower() for value in values if value)


def _sector_fit(text: str) -> tuple[WittingtonCategory, int]:
    buckets = [
        (WittingtonCategory.COMMERCE, _COMMERCE, 95),
        (WittingtonCategory.CLIMATE, _CLIMATE, 88),
        (WittingtonCategory.HEALTHCARE, _HEALTHCARE, 88),
        (WittingtonCategory.CONSUMER, _CONSUMER, 78),
        (WittingtonCategory.FOOD, _FOOD, 75),
    ]
    best = (WittingtonCategory.OTHER, 20)
    for category, terms, score in buckets:
        matches = sum(1 for term in terms if _contains_term(text, term))
        if matches:
            weighted_score = min(100, score + (matches - 1) * 3)
            if weighted_score > best[1]:
                best = (category, weighted_score)
    return best


def _stage_fit(stage: str | None) -> int:
    if stage in (FundingStage.SERIES_A, FundingStage.SERIES_B):
        return 100
    if stage == FundingStage.SERIES_C:
        return 72
    if stage == FundingStage.SEED:
        return 70
    if stage in (FundingStage.PRE_SEED, FundingStage.BOOTSTRAPPED):
        return 45
    if stage == FundingStage.SERIES_D_PLUS:
        return 35
    if stage in (FundingStage.PUBLIC, FundingStage.ACQUIRED):
        return 5
    return 40


def _startup_fit(row: sqlite3.Row, text: str) -> int:
    if row["is_public"]:
        return 0

    employees = _employee_count(row["employee_count"])
    founded = row["founded_year"]
    confidence = row["entity_confidence"]
    company_type = _company_type(row)
    business_model = _business_model(row)
    score = 70
    if _is_stale_enrichment(row) or _has_core_structured_gap(row):
        score -= 25

    if employees is not None:
        if employees <= 250:
            score += 16
        elif employees <= 1000:
            score += 4
        elif employees > 3000:
            score -= 34
        else:
            score -= 16

    if founded is not None:
        if founded >= 2012:
            score += 8
        elif founded < 2000:
            score -= 20

    if confidence is not None:
        if confidence < 50:
            score -= 30
        elif confidence < 75:
            score -= 10

    if company_type in _SOFTWARE_TYPES:
        score += 18
    elif company_type == CompanyType.BRAND:
        score += 2
    elif company_type in _SERVICE_TYPES:
        score -= 18
    elif company_type in _HARD_NONFIT_TYPES:
        score -= 45

    if business_model in _SOFTWARE_BUSINESS_MODELS:
        score += 8
    elif business_model in _SERVICE_BUSINESS_MODELS:
        score -= 8
    elif business_model in (BusinessModel.INVESTOR, BusinessModel.NONPROFIT_GOVERNMENT, BusinessModel.INCUMBENT):
        score -= 25

    if _is_true(row["software_led"]):
        score += 16
    elif _is_false(row["software_led"]):
        score -= 22

    if _is_true(row["venture_backed"]):
        score += 10
    elif _is_false(row["venture_backed"]):
        score -= 4

    if _is_false(row["north_america_presence"]):
        score -= 8

    if row["disqualifiers"]:
        score -= 12

    if row["enterprise_traction"]:
        score += 5

    traction_tier = _traction_tier(row)
    if traction_tier in (TractionTier.NAMED_CUSTOMERS, TractionTier.ENTERPRISE_CUSTOMERS, TractionTier.MAJOR_PARTNERSHIP):
        score += 6
    elif traction_tier == TractionTier.REVENUE_SIGNAL:
        score += 4
    elif traction_tier == TractionTier.PILOT:
        score += 2
    elif traction_tier == TractionTier.NONE:
        score -= 4

    if any(_contains_term(text, term) for term in _NON_STARTUP_TERMS):
        score -= 35
    if any(_contains_term(text, term) for term in _INCUMBENT_TERMS) and employees and employees > 1000:
        score -= 12

    return max(0, min(100, score))


def _should_use_llm(row: sqlite3.Row, parts: ScoreParts) -> bool:
    if parts.base_score < 35 or parts.sector_fit < 50:
        return False
    if row["is_public"] or row["funding_stage"] in (FundingStage.PUBLIC, FundingStage.ACQUIRED):
        return False
    if _ownership_status(row) in _HARD_NONFIT_OWNERSHIP or _ownership_status(row) == OwnershipStatus.ACQUIRED:
        return False
    if _is_stale_enrichment(row) or _has_core_structured_gap(row):
        return False
    if _company_type(row) in _HARD_NONFIT_TYPES:
        return False
    return True


def _company_type(row: sqlite3.Row) -> CompanyType | None:
    value = row["company_type"]
    if not value:
        return None
    try:
        return CompanyType(value)
    except ValueError:
        return CompanyType.UNKNOWN


def _business_model(row: sqlite3.Row) -> BusinessModel | None:
    value = _row_value(row, "business_model")
    if not value:
        return None
    try:
        return BusinessModel(value)
    except ValueError:
        return BusinessModel.UNKNOWN


def _ownership_status(row: sqlite3.Row) -> OwnershipStatus | None:
    value = _row_value(row, "ownership_status")
    if not value:
        return None
    try:
        return OwnershipStatus(value)
    except ValueError:
        return OwnershipStatus.UNKNOWN


def _traction_tier(row: sqlite3.Row) -> TractionTier | None:
    value = _row_value(row, "traction_tier")
    if not value:
        return None
    try:
        return TractionTier(value)
    except ValueError:
        return TractionTier.UNKNOWN


def _source_quality(row: sqlite3.Row) -> SourceQuality | None:
    value = _row_value(row, "source_quality")
    if not value:
        return None
    try:
        return SourceQuality(value)
    except ValueError:
        return SourceQuality.UNKNOWN


def _row_value(row: sqlite3.Row, field: str) -> object | None:
    return row[field] if field in row.keys() else None


def _is_true(value: object) -> bool:
    return value is True or value == 1 or value == "1" or value == "true" or value == "True"


def _is_false(value: object) -> bool:
    return value is False or value == 0 or value == "0" or value == "false" or value == "False"


def _employee_count(value: str | None) -> int | None:
    if not value:
        return None
    numbers = [int(match.group(0).replace(",", "")) for match in _EMPLOYEE_PATTERN.finditer(value)]
    return max(numbers) if numbers else None


def _contains_term(text: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def _fallback_rationale(row: sqlite3.Row, parts: ScoreParts) -> str:
    if row["is_public"]:
        return "Public company, so it is not a strong venture prospect despite any sector relevance."
    if _company_type(row) in _SERVICE_TYPES and not _is_true(row["software_led"]):
        return "Service provider rather than software-led startup, so the venture fit is limited."
    if _is_false(row["software_led"]) and not _is_true(row["venture_backed"]):
        return "Not software-led and no venture-backing signal, so it is a low-priority prospect."
    if parts.sector_fit < 50:
        return "Weak Wittington sector fit based on the available company description."
    stage = row["funding_stage"] or "unknown stage"
    return (
        f"{parts.category.value} fit with {stage} maturity; worth review if the product is software-led "
        "and commercially scalable."
    )


def _cap_rationale(row: sqlite3.Row) -> str | None:
    company_type = _company_type(row)
    if _is_stale_enrichment(row):
        return "Enrichment used an older schema, so refresh before ranking as a top prospect."
    if _has_core_structured_gap(row):
        return "Structured enrichment is incomplete, so hold for refresh before ranking as a top prospect."
    if row["entity_confidence"] is not None and row["entity_confidence"] < 50:
        return "Low entity-resolution confidence, so this should be reviewed before ranking highly."
    if _has_geo_disqualifier(row):
        return "Headquarters geography is outside the target profile, so it should not rank as a top prospect."
    if _ownership_status(row) in _HARD_NONFIT_OWNERSHIP:
        return "Non-private ownership limits fit for this venture pipeline."
    if row["is_public"] or row["funding_stage"] == FundingStage.PUBLIC:
        return "Public company, so it is not a strong venture prospect despite any sector relevance."
    if row["funding_stage"] == FundingStage.ACQUIRED:
        return "Acquired company, so it is lower priority for new venture investment."
    if _has_acquired_disqualifier(row):
        return "Acquired company, so it is lower priority for new venture investment."
    if _ownership_status(row) == OwnershipStatus.SUBSIDIARY:
        return "Subsidiary ownership makes this lower priority for new venture investment."
    if company_type in _HARD_NONFIT_TYPES:
        return "Not an operating startup prospect for Wittington's venture pipeline."
    if company_type in _SERVICE_TYPES and not _is_true(row["software_led"]):
        return "Service provider rather than software-led startup, so the venture fit is limited."
    if _is_false(row["software_led"]) and company_type != CompanyType.BRAND:
        return "Not software-led, so it is a lower-priority prospect for this tech-focused pipeline."
    return None


def _has_core_structured_gap(row: sqlite3.Row) -> bool:
    company_type = row["company_type"]
    missing_type = company_type is None or company_type == "" or company_type == CompanyType.UNKNOWN
    return missing_type and row["software_led"] is None and row["venture_backed"] is None


def _is_stale_enrichment(row: sqlite3.Row) -> bool:
    if "enrichment_schema_version" not in row.keys():
        return False
    version = _row_value(row, "enrichment_schema_version") or 0
    return int(version) < ENRICHMENT_SCHEMA_VERSION


def _has_geo_disqualifier(row: sqlite3.Row) -> bool:
    location = (row["hq_location"] or "").lower()
    return "russia" in location


def _has_acquired_disqualifier(row: sqlite3.Row) -> bool:
    text = f"{row['disqualifiers'] or ''} {row['evidence_snippet'] or ''}".lower()
    return "acquired" in text or "no longer independent" in text


def _judgment_prompt(row: sqlite3.Row, parts: ScoreParts) -> str:
    return f"""
Wittington Ventures invests in technology-oriented North American start-ups across Commerce, Healthcare, Consumer, Climate, and food-adjacent markets. They primarily invest at Series A/B, can invest earlier/later, and have strategic access through retail, grocery, pharmacy, real estate, and financial-services relationships.

Score this Manifest attendee as a venture prospect. Deterministic base score is {parts.base_score}/100 with notes: {'; '.join(parts.notes)}.

Company: {row['name']}
Website/domain: {row['resolved_domain'] or 'unknown'}
Description: {row['description'] or 'unknown'}
	Industry: {row['industry'] or 'unknown'}
	Company type: {row['company_type'] or 'unknown'}
	Software-led: {_known_bool(row['software_led'])}
	Venture-backed: {_known_bool(row['venture_backed'])}
	North America presence: {_known_bool(row['north_america_presence'])}
	Customer segment: {row['customer_segment'] or 'unknown'}
	Logistics function: {row['logistics_function'] or 'unknown'}
	Supply-chain subsector: {row['supply_chain_subsector'] or 'unknown'}
	Target customer: {row['target_customer'] or 'unknown'}
	Ownership status: {_row_value(row, 'ownership_status') or 'unknown'}
	Business model: {_row_value(row, 'business_model') or 'unknown'}
	Logistics workflow: {_row_value(row, 'logistics_workflow') or 'unknown'}
	Target buyer: {_row_value(row, 'target_buyer') or 'unknown'}
	Latest round: {_row_value(row, 'latest_round_amount') or 'unknown'} on {_row_value(row, 'latest_round_date') or 'unknown'}
	Named investors: {_row_value(row, 'named_investors') or 'unknown'}
	Traction tier: {_row_value(row, 'traction_tier') or 'unknown'}
	WV partner match: {_row_value(row, 'wv_partner_match') or 'unknown'}
	Source quality: {_row_value(row, 'source_quality') or 'unknown'}
	Enterprise traction: {row['enterprise_traction'] or 'unknown'}
	Wittington edge: {row['wv_edge'] or 'unknown'}
	Disqualifiers: {row['disqualifiers'] or 'none'}
	Evidence: {row['evidence_snippet'] or 'unknown'}
	Public: {bool(row['is_public'])}
Founded: {row['founded_year'] or 'unknown'}
Employees: {row['employee_count'] or 'unknown'}
Funding stage: {row['funding_stage'] or 'unknown'}
Total funding: {row['total_funding'] or 'unknown'}
HQ: {row['hq_location'] or 'unknown'}

Return JSON only:
{{
  "score_adjustment": integer from -20 to 20,
  "category": "Commerce" | "Healthcare" | "Consumer" | "Climate" | "Food" | "Other",
  "rationale": "one sentence, maximum 24 words"
}}
""".strip()


def _clean_sentence(value: str) -> str:
    text = " ".join(value.split())
    if len(text) > 220:
        text = text[:217].rstrip() + "..."
    return text


def _known_bool(value: object) -> str:
    if _is_true(value):
        return "true"
    if _is_false(value):
        return "false"
    return "unknown"
