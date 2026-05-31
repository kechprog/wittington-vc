from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from db import init_db, load_companies, pending_enrichment, pending_scoring, ranked_pipeline
from db.database import save_enrichment, save_score
from exa_client import ExaTransientError, _exa_schema, _fallback_firmographics
from llm_client import judge_fit
from main import _calibrated_entity_confidence, _enrichment_record
from models import (
    BusinessModel,
    EnrichmentRecord,
    EnrichmentStatus,
    Firmographics,
    FitStatus,
    LogisticsWorkflow,
    OwnershipStatus,
    ScoreRecord,
    SourceQuality,
    TargetBuyer,
    TractionTier,
    WittingtonCategory,
)
from reporting import export_ranked_pipeline
from scraper import _parse_company_names
from scoring import score_company


class PipelineTests(unittest.TestCase):
    def test_parser_keeps_verbatim_specific_names_and_dedupes(self) -> None:
        block = """
        LOGISTICS
        Pando.ai
        Pando.ai
        GoRamp
        Ramp Systems
        """
        self.assertEqual(_parse_company_names(block), ["Pando.ai", "GoRamp", "Ramp Systems"])

    def test_exa_schema_is_flattened_for_structured_summary(self) -> None:
        schema = _exa_schema(Firmographics)
        rendered = str(schema)
        self.assertNotIn("$defs", rendered)
        self.assertNotIn("$ref", rendered)
        self.assertNotIn("anyOf", rendered)
        self.assertIn("funding_stage", schema["properties"])
        self.assertIn("company_type", schema["properties"])
        self.assertIn("software_led", schema["properties"])
        self.assertIn("venture_backed", schema["properties"])
        self.assertIn("ownership_status", schema["properties"])
        self.assertIn("business_model", schema["properties"])
        self.assertIn("logistics_workflow", schema["properties"])
        self.assertIn("target_buyer", schema["properties"])
        self.assertIn("source_quality", schema["properties"])

        profile = Firmographics(
            description="Test",
            industry="Software",
            is_public=False,
            entity_confidence=True,
        )
        self.assertIsNone(profile.entity_confidence)

    def test_db_stages_are_idempotent_and_cache_unresolved_rows(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        init_db(connection)

        self.assertEqual(load_companies(connection, ["Pando.ai", "Pando.ai", "3M"]), 2)
        self.assertEqual(load_companies(connection, ["Pando.ai"]), 0)
        self.assertEqual(len(pending_enrichment(connection)), 2)

        save_enrichment(
            connection,
            EnrichmentRecord(company_id=1, status=EnrichmentStatus.UNRESOLVED),
        )
        self.assertEqual([row["name"] for row in pending_enrichment(connection)], ["3M"])
        self.assertEqual(len(pending_scoring(connection)), 1)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(enrichments)").fetchall()
        }
        self.assertIn("enrichment_schema_version", columns)
        self.assertIn("business_model", columns)
        self.assertIn("source_quality", columns)

    def test_scoring_penalizes_public_incumbents_and_rewards_series_b_commerce(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        startup = connection.execute(
            """
            SELECT
                1 AS company_id,
                'Pando.ai' AS name,
                'resolved' AS status,
                'pando.ai' AS resolved_domain,
                NULL AS resolved_url,
                NULL AS title,
                'Supply chain execution software for manufacturers and retailers.' AS description,
                'Software' AS industry,
                0 AS is_public,
                2018 AS founded_year,
                '188' AS employee_count,
                'Series B' AS funding_stage,
                'USD 41M' AS total_funding,
                'Chicago, United States' AS hq_location,
                'Pando.ai' AS canonical_name,
                95 AS entity_confidence,
                'SaaS' AS company_type,
                1 AS software_led,
                1 AS venture_backed,
                1 AS north_america_presence,
                'Manufacturers and retailers' AS customer_segment,
                'Supply chain execution' AS logistics_function,
                'Visibility' AS supply_chain_subsector,
                'Retailers' AS target_customer,
                'Series B funding' AS enterprise_traction,
                'Supply chain network' AS wv_edge,
                NULL AS disqualifiers,
                'Helps manufacturers and retailers drive agility.' AS evidence_snippet
                ,3 AS enrichment_schema_version,
                'Private' AS ownership_status,
                'SaaS' AS business_model,
                '2024-01' AS latest_round_date,
                'USD 41M' AS latest_round_amount,
                'Test Ventures' AS named_investors,
                'Freight visibility' AS logistics_workflow,
                'Retailer' AS target_buyer,
                'Named customers' AS traction_tier,
                'Loblaw; Supply-chain network' AS wv_partner_match,
                'High' AS source_quality,
                'https://pando.ai' AS evidence_urls
            """
        ).fetchone()
        incumbent = connection.execute(
            """
            SELECT
                2 AS company_id,
                'AB InBev' AS name,
                'resolved' AS status,
                'ab-inbev.com' AS resolved_domain,
                NULL AS resolved_url,
                NULL AS title,
                'Multinational drink and brewing company.' AS description,
                'Manufacturing' AS industry,
                1 AS is_public,
                2008 AS founded_year,
                '17,402' AS employee_count,
                'Public' AS funding_stage,
                NULL AS total_funding,
                'Leuven, Belgium' AS hq_location,
                'AB InBev' AS canonical_name,
                95 AS entity_confidence,
                'Incumbent' AS company_type,
                0 AS software_led,
                0 AS venture_backed,
                1 AS north_america_presence,
                'Consumers' AS customer_segment,
                NULL AS logistics_function,
                NULL AS supply_chain_subsector,
                NULL AS target_customer,
                NULL AS enterprise_traction,
                NULL AS wv_edge,
                'Public incumbent' AS disqualifiers,
                'Multinational brewing company.' AS evidence_snippet
                ,3 AS enrichment_schema_version,
                'Public' AS ownership_status,
                'Incumbent' AS business_model,
                NULL AS latest_round_date,
                NULL AS latest_round_amount,
                NULL AS named_investors,
                'Not applicable' AS logistics_workflow,
                'Consumer' AS target_buyer,
                'Unknown' AS traction_tier,
                NULL AS wv_partner_match,
                'High' AS source_quality,
                'https://ab-inbev.com' AS evidence_urls
            """
        ).fetchone()

        startup_score = score_company(startup, use_llm=False)
        incumbent_score = score_company(incumbent, use_llm=False)
        self.assertGreaterEqual(startup_score.fit_score, 90)
        self.assertIsNone(startup_score.cap_reason)
        self.assertEqual(startup_score.raw_score, startup_score.fit_score)
        self.assertEqual(startup_score.category, WittingtonCategory.COMMERCE)
        self.assertLessEqual(incumbent_score.fit_score, 25)
        self.assertEqual(incumbent_score.cap_reason, "public_company")

    def test_scoring_caps_non_software_service_providers(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        carrier = connection.execute(
            """
            SELECT
                3 AS company_id,
                'Example Freight' AS name,
                'resolved' AS status,
                'examplefreight.com' AS resolved_domain,
                NULL AS resolved_url,
                NULL AS title,
                'Truckload carrier and freight services for retailers.' AS description,
                'Transportation' AS industry,
                0 AS is_public,
                2020 AS founded_year,
                '25' AS employee_count,
                'Series A' AS funding_stage,
                NULL AS total_funding,
                'Dallas, United States' AS hq_location,
                'Example Freight' AS canonical_name,
                95 AS entity_confidence,
                'Carrier' AS company_type,
                0 AS software_led,
                1 AS venture_backed,
                1 AS north_america_presence,
                'Retailers' AS customer_segment,
                'Freight' AS logistics_function,
                'Freight' AS supply_chain_subsector,
                'Retailers' AS target_customer,
                NULL AS enterprise_traction,
                'Supply chain' AS wv_edge,
                NULL AS disqualifiers,
                'Carrier services.' AS evidence_snippet
                ,3 AS enrichment_schema_version,
                'Private' AS ownership_status,
                'Carrier' AS business_model,
                NULL AS latest_round_date,
                NULL AS latest_round_amount,
                NULL AS named_investors,
                'Freight visibility' AS logistics_workflow,
                'Retailer' AS target_buyer,
                'Funding signal' AS traction_tier,
                'Loblaw; Supply-chain network' AS wv_partner_match,
                'High' AS source_quality,
                'https://examplefreight.com' AS evidence_urls
            """
        ).fetchone()

        carrier_score = score_company(carrier, use_llm=False)
        self.assertLessEqual(carrier_score.fit_score, 55)
        self.assertEqual(carrier_score.cap_reason, "non_software_service_provider")
        self.assertIn("Service provider", carrier_score.rationale)

    def test_scoring_caps_acquired_disqualifier_even_if_stage_is_wrong(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                4 AS company_id,
                'Rippey AI' AS name,
                'resolved' AS status,
                'rippey.ai' AS resolved_domain,
                NULL AS resolved_url,
                NULL AS title,
                'AI automation for logistics teams.' AS description,
                'Software' AS industry,
                0 AS is_public,
                2019 AS founded_year,
                '25' AS employee_count,
                'Series A' AS funding_stage,
                NULL AS total_funding,
                'Austin, United States' AS hq_location,
                'Rippey AI' AS canonical_name,
                95 AS entity_confidence,
                'SaaS' AS company_type,
                1 AS software_led,
                1 AS venture_backed,
                1 AS north_america_presence,
                'Logistics teams' AS customer_segment,
                'Automation' AS logistics_function,
                'Freight visibility' AS supply_chain_subsector,
                'Shippers' AS target_customer,
                'Series A funding' AS enterprise_traction,
                'Supply chain' AS wv_edge,
                'Acquired by PayCargo' AS disqualifiers,
                'Acquired by PayCargo.' AS evidence_snippet,
                3 AS enrichment_schema_version,
                'Private' AS ownership_status,
                'SaaS' AS business_model,
                NULL AS latest_round_date,
                NULL AS latest_round_amount,
                NULL AS named_investors,
                'Freight visibility' AS logistics_workflow,
                'Shipper' AS target_buyer,
                'Funding signal' AS traction_tier,
                'Supply-chain network' AS wv_partner_match,
                'High' AS source_quality,
                'https://rippey.ai' AS evidence_urls
            """
        ).fetchone()

        score = score_company(row, use_llm=False)
        self.assertLessEqual(score.fit_score, 45)
        self.assertEqual(score.cap_reason, "acquired_company")

    def test_entity_confidence_calibration_raises_only_strong_legacy_lows(self) -> None:
        self.assertEqual(_calibrated_entity_confidence(None, 55), 55)
        self.assertEqual(_calibrated_entity_confidence(1, 95), 95)
        self.assertEqual(_calibrated_entity_confidence(25, 90), 90)
        self.assertEqual(_calibrated_entity_confidence(25, 55), 25)

    def test_models_accept_new_structured_enrichment_fields(self) -> None:
        profile = Firmographics(
            description="API for freight visibility.",
            industry="Software",
            is_public=False,
            latest_round_amount="null",
            ownership_status=OwnershipStatus.PRIVATE,
            business_model=BusinessModel.API,
            logistics_workflow=LogisticsWorkflow.FREIGHT_VISIBILITY,
            target_buyer=TargetBuyer.SHIPPER,
            traction_tier=TractionTier.FUNDING_SIGNAL,
            source_quality=SourceQuality.HIGH,
        )
        self.assertEqual(profile.business_model, BusinessModel.API)
        self.assertEqual(profile.logistics_workflow, LogisticsWorkflow.FREIGHT_VISIBILITY)
        self.assertIsNone(profile.latest_round_amount)

    def test_exa_summary_fallback_is_low_quality_but_resolved(self) -> None:
        profile = _fallback_firmographics("ExampleCo", {"title": "ExampleCo"}, "https://example.com")
        self.assertEqual(profile.source_quality, SourceQuality.LOW)
        self.assertEqual(profile.evidence_urls, "https://example.com")
        self.assertIn("structured exa summary unavailable", (profile.disqualifiers or "").lower())

    def test_transient_exa_failure_stays_pending(self) -> None:
        with patch("main.enrich_company", side_effect=ExaTransientError("rate limited")):
            self.assertIsNone(_enrichment_record(1, "Oracle"))

        with patch("main.enrich_company", return_value=None):
            record = _enrichment_record(1, "UnknownCo")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, EnrichmentStatus.UNRESOLVED)

    def test_llm_client_validates_json_response(self) -> None:
        os.environ["OPENROUTER_API"] = "test"
        with patch(
            "llm_client._chat_completion",
            return_value='{"score_adjustment": 4, "category": "Commerce", "rationale": "Strong retail supply-chain fit."}',
        ):
            judgment = judge_fit("prompt")
        self.assertIsNotNone(judgment)
        self.assertEqual(judgment.category, WittingtonCategory.COMMERCE)
        self.assertEqual(judgment.score_adjustment, 4)

    def test_ranked_export_contains_sortable_full_list(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        init_db(connection)
        load_companies(connection, ["Pando.ai", "3M"])
        save_score(
            connection,
            ScoreRecord(
                company_id=1,
                status=FitStatus.SCORED,
                fit_score=95,
                category=WittingtonCategory.COMMERCE,
                startup_fit=95,
                stage_fit=100,
                sector_fit=95,
                rationale="Strong commerce fit.",
                deterministic_notes="test",
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            csv_path, html_path = export_ranked_pipeline(ranked_pipeline(connection), Path(directory))
            csv_text = csv_path.read_text()
            self.assertIn("Pando.ai", csv_text)
            self.assertIn("raw_score", csv_text)
            self.assertIn("cap_reason", csv_text)
            html_text = html_path.read_text()
            self.assertIn("Wittington VC Ranked Prospects", html_text)
            self.assertIn("data-category", html_text)


if __name__ == "__main__":
    unittest.main()
