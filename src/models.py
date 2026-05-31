"""Pydantic models and enums shared across the pipeline stages.

These are the single source of truth for the shape of the data: the firmographic
fields Exa must return, the typed record persisted to the database, and the
constrained string values (the enums double as the DB CHECK constraints).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


def _coerce_enum(value: object, enum_cls: type[StrEnum]):
    """Map blank values to null and out-of-vocabulary values to UNKNOWN."""
    if value is None or value == "":
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return enum_cls.UNKNOWN


class EnrichmentStatus(StrEnum):
    """Outcome of the enrichment stage for a company."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class FundingStage(StrEnum):
    """Constrained funding-stage vocabulary (also enforced as a DB CHECK)."""

    BOOTSTRAPPED = "Bootstrapped"
    PRE_SEED = "Pre-Seed"
    SEED = "Seed"
    SERIES_A = "Series A"
    SERIES_B = "Series B"
    SERIES_C = "Series C"
    SERIES_D_PLUS = "Series D+"
    PUBLIC = "Public"
    ACQUIRED = "Acquired"
    UNKNOWN = "Unknown"


class CompanyType(StrEnum):
    """Structured company archetype used to separate startups from services."""

    SAAS = "SaaS"
    PLATFORM = "Platform"
    MARKETPLACE = "Marketplace"
    ROBOTICS = "Robotics"
    BRAND = "Brand"
    CARRIER = "Carrier"
    BROKER = "Broker"
    THREE_PL = "3PL"
    SHIPPER = "Shipper"
    CONSULTANCY = "Consultancy"
    AGENCY = "Agency"
    MANUFACTURER = "Manufacturer"
    RETAILER = "Retailer"
    DISTRIBUTOR = "Distributor"
    INVESTOR = "Investor"
    NONPROFIT = "Nonprofit"
    GOVERNMENT = "Government"
    INCUMBENT = "Incumbent"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class OwnershipStatus(StrEnum):
    """Company ownership state, separated from funding stage."""

    PRIVATE = "Private"
    PUBLIC = "Public"
    ACQUIRED = "Acquired"
    SUBSIDIARY = "Subsidiary"
    NONPROFIT = "Nonprofit"
    GOVERNMENT = "Government"
    INCUMBENT = "Incumbent"
    UNKNOWN = "Unknown"


class BusinessModel(StrEnum):
    """How the company primarily makes money."""

    SAAS = "SaaS"
    API = "API"
    PLATFORM = "Platform"
    MARKETPLACE = "Marketplace"
    HARDWARE_SOFTWARE = "Hardware-enabled software"
    ROBOTICS_AUTOMATION = "Robotics/automation"
    TECH_ENABLED_SERVICES = "Tech-enabled services"
    CARRIER = "Carrier"
    BROKER = "Broker"
    THREE_PL = "3PL"
    BRAND = "Brand"
    RETAILER = "Retailer"
    MANUFACTURER = "Manufacturer"
    DISTRIBUTOR = "Distributor"
    CONSULTANCY_AGENCY = "Consultancy/agency"
    INVESTOR = "Investor"
    NONPROFIT_GOVERNMENT = "Nonprofit/government"
    INCUMBENT = "Incumbent"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class LogisticsWorkflow(StrEnum):
    """Normalized logistics/supply-chain workflow served."""

    FREIGHT_VISIBILITY = "Freight visibility"
    TMS = "TMS"
    WMS = "WMS"
    YARD_MANAGEMENT = "Yard management"
    PROCUREMENT = "Procurement"
    LAST_MILE = "Last-mile"
    MIDDLE_MILE = "Middle-mile"
    WAREHOUSE_AUTOMATION = "Warehouse automation"
    RETURNS = "Returns"
    COLD_CHAIN = "Cold chain"
    CROSS_BORDER = "Cross-border"
    PAYMENTS_FINTECH = "Payments/fintech"
    INVENTORY = "Inventory"
    FULFILLMENT = "Fulfillment"
    SUSTAINABILITY = "Sustainability"
    ECOMMERCE_ENABLEMENT = "Ecommerce enablement"
    NOT_APPLICABLE = "Not applicable"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class TargetBuyer(StrEnum):
    """Primary buyer or beneficiary of the product."""

    RETAILER = "Retailer"
    GROCERY = "Grocery"
    PHARMACY = "Pharmacy"
    ECOMMERCE_BRAND = "Ecommerce brand"
    SHIPPER = "Shipper"
    CARRIER = "Carrier"
    BROKER = "Broker"
    WAREHOUSE = "Warehouse"
    MANUFACTURER = "Manufacturer"
    LOGISTICS_PROVIDER = "Logistics provider"
    HEALTHCARE_PROVIDER = "Healthcare provider"
    CONSUMER = "Consumer"
    ENTERPRISE = "Enterprise"
    SMB = "SMB"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class TractionTier(StrEnum):
    """Publicly visible traction signal strength."""

    NONE = "None"
    PILOT = "Pilot"
    NAMED_CUSTOMERS = "Named customers"
    ENTERPRISE_CUSTOMERS = "Enterprise customers"
    MAJOR_PARTNERSHIP = "Major partnership"
    REVENUE_SIGNAL = "Revenue signal"
    FUNDING_SIGNAL = "Funding signal"
    UNKNOWN = "Unknown"


class SourceQuality(StrEnum):
    """Confidence in the enrichment source material, not the entity match."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    UNKNOWN = "Unknown"


class FitStatus(StrEnum):
    """Outcome of the scoring stage for a company."""

    SCORED = "scored"
    SKIPPED = "skipped"


class WittingtonCategory(StrEnum):
    """Wittington-aligned sector tags."""

    COMMERCE = "Commerce"
    HEALTHCARE = "Healthcare"
    CONSUMER = "Consumer"
    CLIMATE = "Climate"
    FOOD = "Food"
    OTHER = "Other"


ENRICHMENT_SCHEMA_VERSION = 3


class Firmographics(BaseModel):
    """Firmographic profile extracted from a resolved company page.

    This model's JSON schema is what we ask Exa to populate, and Exa's response
    is validated back into it. Required fields (no default) are the ones Exa must
    always return; the rest are best-effort.
    """

    description: str = Field(description="One sentence on what the company does.")
    industry: str = Field(description="Primary industry or sector.")
    is_public: bool = Field(
        description="True only if the company is publicly traded on a stock exchange."
    )
    founded_year: int | None = Field(default=None, description="Year the company was founded.")
    employee_count: str | None = Field(
        default=None, description="Approximate employee count or range, e.g. '11-50', '1000+'."
    )
    funding_stage: FundingStage | None = Field(default=None, description="Latest funding stage.")
    total_funding: str | None = Field(
        default=None, description="Total funding raised, with currency, if known."
    )
    hq_location: str | None = Field(default=None, description="Headquarters location (city, country).")
    canonical_name: str | None = Field(default=None, description="Canonical company name.")
    entity_confidence: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Confidence from 0-100 that the resolved entity matches the searched name.",
    )
    company_type: CompanyType | None = Field(
        default=None,
        description="Best company archetype: SaaS, Platform, Carrier, Broker, Brand, Incumbent, etc.",
    )
    software_led: bool | None = Field(
        default=None,
        description="True when the company primarily sells software, data, AI, or a scalable platform.",
    )
    venture_backed: bool | None = Field(
        default=None,
        description="True when public evidence suggests venture funding or venture-scale backing.",
    )
    north_america_presence: bool | None = Field(
        default=None,
        description="True when the company is headquartered in or materially operates in North America.",
    )
    customer_segment: str | None = Field(default=None, description="Primary customer segment.")
    logistics_function: str | None = Field(
        default=None,
        description="Supply-chain/logistics function served, if applicable.",
    )
    supply_chain_subsector: str | None = Field(
        default=None,
        description="Supply-chain subsector such as warehouse, freight, last-mile, cold-chain, procurement, or visibility.",
    )
    target_customer: str | None = Field(
        default=None,
        description="Primary customer such as retailer, grocery, pharmacy, warehouse, shipper, carrier, or broker.",
    )
    enterprise_traction: str | None = Field(
        default=None,
        description="Named customers, pilots, partnerships, ARR proxy, or other enterprise traction evidence.",
    )
    wv_edge: str | None = Field(
        default=None,
        description="Where Wittington's retail, grocery, pharmacy, real estate, financial services, or supply-chain network could help.",
    )
    disqualifiers: str | None = Field(
        default=None,
        description="Reasons this may not be a venture prospect, such as public, acquired, broker, consultancy, or incumbent.",
    )
    evidence_snippet: str | None = Field(
        default=None,
        description="Short factual evidence used for the structured fields.",
    )
    enrichment_schema_version: int | None = Field(
        default=ENRICHMENT_SCHEMA_VERSION,
        description="Version of this enrichment schema. Use 3 for this schema.",
    )
    ownership_status: OwnershipStatus | None = Field(
        default=None,
        description="Private, Public, Acquired, Subsidiary, Nonprofit, Government, Incumbent, or Unknown.",
    )
    business_model: BusinessModel | None = Field(
        default=None,
        description="Primary business model such as SaaS, API, Platform, Carrier, Broker, 3PL, Brand, or services.",
    )
    latest_round_date: str | None = Field(
        default=None,
        description="Latest financing round date if clearly public, in YYYY-MM or YYYY-MM-DD when available.",
    )
    latest_round_amount: str | None = Field(
        default=None,
        description="Latest financing round amount with currency if clearly public.",
    )
    named_investors: str | None = Field(
        default=None,
        description="Named investors from the latest or most relevant public financing evidence.",
    )
    logistics_workflow: LogisticsWorkflow | None = Field(
        default=None,
        description="Normalized logistics workflow served, or Not applicable for non-logistics companies.",
    )
    target_buyer: TargetBuyer | None = Field(
        default=None,
        description="Primary buyer such as Retailer, Grocery, Pharmacy, Shipper, Carrier, Broker, Warehouse, Manufacturer, or Enterprise.",
    )
    traction_tier: TractionTier | None = Field(
        default=None,
        description="Best public traction signal: pilot, named customers, enterprise customers, major partnership, revenue signal, funding signal, none, or unknown.",
    )
    wv_partner_match: str | None = Field(
        default=None,
        description="Specific Wittington strategic assets that may help: Loblaw, Shoppers Drug Mart, Choice Properties, PC Financial, Holt Renfrew, Joe Fresh, or supply-chain network.",
    )
    source_quality: SourceQuality | None = Field(
        default=None,
        description="High, Medium, Low, or Unknown quality of evidence supporting the enrichment fields.",
    )
    evidence_urls: str | None = Field(
        default=None,
        description="Semicolon-separated URLs used for the enrichment evidence, at minimum the resolved company URL.",
    )

    @field_validator("funding_stage", mode="before")
    @classmethod
    def _coerce_funding_stage(cls, value: object) -> FundingStage | None:
        """Map any out-of-vocabulary stage to UNKNOWN instead of failing."""
        if value is None or value == "":
            return None
        try:
            return FundingStage(value)
        except ValueError:
            return FundingStage.UNKNOWN

    @field_validator("company_type", mode="before")
    @classmethod
    def _coerce_company_type(cls, value: object) -> CompanyType | None:
        """Map any out-of-vocabulary type to UNKNOWN instead of failing."""
        return _coerce_enum(value, CompanyType)

    @field_validator("ownership_status", mode="before")
    @classmethod
    def _coerce_ownership_status(cls, value: object) -> OwnershipStatus | None:
        """Map any out-of-vocabulary ownership status to UNKNOWN."""
        return _coerce_enum(value, OwnershipStatus)

    @field_validator("business_model", mode="before")
    @classmethod
    def _coerce_business_model(cls, value: object) -> BusinessModel | None:
        """Map any out-of-vocabulary business model to UNKNOWN."""
        return _coerce_enum(value, BusinessModel)

    @field_validator("logistics_workflow", mode="before")
    @classmethod
    def _coerce_logistics_workflow(cls, value: object) -> LogisticsWorkflow | None:
        """Map any out-of-vocabulary logistics workflow to UNKNOWN."""
        return _coerce_enum(value, LogisticsWorkflow)

    @field_validator("target_buyer", mode="before")
    @classmethod
    def _coerce_target_buyer(cls, value: object) -> TargetBuyer | None:
        """Map any out-of-vocabulary target buyer to UNKNOWN."""
        return _coerce_enum(value, TargetBuyer)

    @field_validator("traction_tier", mode="before")
    @classmethod
    def _coerce_traction_tier(cls, value: object) -> TractionTier | None:
        """Map any out-of-vocabulary traction tier to UNKNOWN."""
        return _coerce_enum(value, TractionTier)

    @field_validator("source_quality", mode="before")
    @classmethod
    def _coerce_source_quality(cls, value: object) -> SourceQuality | None:
        """Map any out-of-vocabulary source quality to UNKNOWN."""
        return _coerce_enum(value, SourceQuality)

    @field_validator("entity_confidence", mode="before")
    @classmethod
    def _coerce_entity_confidence(cls, value: object) -> int | None:
        """Treat boolean confidence as missing; Exa can otherwise coerce it to 0/1."""
        if isinstance(value, bool):
            return None
        return value

    @field_validator(
        "employee_count",
        "total_funding",
        "hq_location",
        "canonical_name",
        "customer_segment",
        "logistics_function",
        "supply_chain_subsector",
        "target_customer",
        "enterprise_traction",
        "wv_edge",
        "disqualifiers",
        "evidence_snippet",
        "latest_round_date",
        "latest_round_amount",
        "named_investors",
        "wv_partner_match",
        "evidence_urls",
        mode="before",
    )
    @classmethod
    def _coerce_nullish_text(cls, value: object) -> object | None:
        """Treat common LLM null strings as missing optional text."""
        if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "unknown"}:
            return None
        return value


class ExaEnrichment(BaseModel):
    """What `exa_client.enrich_company` returns: resolution + firmographics."""

    resolved_url: str | None = None
    resolved_domain: str | None = None
    title: str | None = None
    firmographics: Firmographics


class EnrichmentRecord(BaseModel):
    """One row of the `enrichments` stage table -- the input to `save_enrichment`.

    The caller is responsible for building this (e.g. from an `ExaEnrichment`);
    the data layer persists it verbatim without any parsing.
    """

    company_id: int
    status: EnrichmentStatus
    resolved_url: str | None = None
    resolved_domain: str | None = None
    title: str | None = None
    description: str | None = None
    industry: str | None = None
    is_public: bool | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    funding_stage: FundingStage | None = None
    total_funding: str | None = None
    hq_location: str | None = None
    canonical_name: str | None = None
    entity_confidence: int | None = None
    company_type: CompanyType | None = None
    software_led: bool | None = None
    venture_backed: bool | None = None
    north_america_presence: bool | None = None
    customer_segment: str | None = None
    logistics_function: str | None = None
    supply_chain_subsector: str | None = None
    target_customer: str | None = None
    enterprise_traction: str | None = None
    wv_edge: str | None = None
    disqualifiers: str | None = None
    evidence_snippet: str | None = None
    enrichment_schema_version: int | None = ENRICHMENT_SCHEMA_VERSION
    ownership_status: OwnershipStatus | None = None
    business_model: BusinessModel | None = None
    latest_round_date: str | None = None
    latest_round_amount: str | None = None
    named_investors: str | None = None
    logistics_workflow: LogisticsWorkflow | None = None
    target_buyer: TargetBuyer | None = None
    traction_tier: TractionTier | None = None
    wv_partner_match: str | None = None
    source_quality: SourceQuality | None = None
    evidence_urls: str | None = None


class FitJudgment(BaseModel):
    """LLM judgment layered on top of deterministic scoring."""

    score_adjustment: int = Field(
        default=0,
        ge=-20,
        le=20,
        description="Adjustment to the deterministic score from -20 to +20.",
    )
    category: WittingtonCategory = Field(description="Best Wittington sector fit.")
    rationale: str = Field(description="One concise sentence explaining the score.")


class ScoreRecord(BaseModel):
    """One row of the `scores` stage table."""

    company_id: int
    status: FitStatus
    fit_score: int = Field(ge=0, le=100)
    raw_score: int | None = Field(default=None, ge=0, le=100)
    cap_reason: str | None = None
    category: WittingtonCategory
    startup_fit: int = Field(ge=0, le=100)
    stage_fit: int = Field(ge=0, le=100)
    sector_fit: int = Field(ge=0, le=100)
    rationale: str
    deterministic_notes: str
    llm_model: str | None = None
