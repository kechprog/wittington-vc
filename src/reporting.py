"""Export the ranked pipeline to reviewer-friendly artifacts."""

from __future__ import annotations

import csv
import html
import sqlite3
from pathlib import Path

from models import ENRICHMENT_SCHEMA_VERSION


def export_ranked_pipeline(
    rows: list[sqlite3.Row],
    output_dir: Path,
    *,
    sample_seed: int | None = None,
    sample_size: int | None = None,
) -> tuple[Path, Path]:
    """Write CSV and sortable HTML exports, returning their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "ranked_prospects.csv"
    html_path = output_dir / "ranked_prospects.html"

    _write_csv(rows, csv_path)
    _write_html(rows, html_path)
    if sample_size is not None:
        _write_sample_report(rows, output_dir / "sample_evaluation.md", sample_size, sample_seed)
    return csv_path, html_path


def _write_csv(rows: list[sqlite3.Row], path: Path) -> None:
    fields = [
        "rank",
        "name",
        "fit_score",
        "raw_score",
        "cap_reason",
        "category",
        "rationale",
        "startup_fit",
        "stage_fit",
        "sector_fit",
        "enrichment_status",
        "resolved_url",
        "resolved_domain",
        "canonical_name",
        "entity_confidence",
        "description",
        "industry",
        "company_type",
        "software_led",
        "venture_backed",
        "north_america_presence",
        "is_public",
        "founded_year",
        "employee_count",
        "funding_stage",
        "total_funding",
        "hq_location",
        "logistics_function",
        "supply_chain_subsector",
        "target_customer",
        "enterprise_traction",
        "wv_edge",
        "disqualifiers",
        "evidence_snippet",
        "enrichment_schema_version",
        "ownership_status",
        "business_model",
        "latest_round_date",
        "latest_round_amount",
        "named_investors",
        "logistics_workflow",
        "target_buyer",
        "traction_tier",
        "wv_partner_match",
        "source_quality",
        "evidence_urls",
        "deterministic_notes",
        "llm_model",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            writer.writerow({field: _csv_value(row, field, rank) for field in fields})


def _write_html(rows: list[sqlite3.Row], path: Path) -> None:
    body = "\n".join(_html_row(rank, row) for rank, row in enumerate(rows, start=1))
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wittington VC Ranked Prospects</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17211c;
      --muted: #5b665f;
      --line: #d9ded8;
      --bg: #f8faf7;
      --accent: #16705a;
      --soft: #edf4f0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 720; letter-spacing: 0; }}
    p {{ margin: 0; color: var(--muted); max-width: 960px; }}
    main {{ padding: 18px 32px 36px; }}
    .toolbar {{
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }}
    input, select {{
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #ffffff;
      color: var(--ink);
    }}
    input {{ width: min(420px, 100%); }}
    .count {{ color: var(--muted); font-size: 14px; }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      background: #ffffff;
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1280px; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 11px;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      position: sticky;
      top: 0;
      background: var(--soft);
      cursor: pointer;
      white-space: nowrap;
      z-index: 1;
    }}
    tbody tr:hover {{ background: #fbfdfb; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .score {{ font-weight: 760; color: var(--accent); }}
    .muted {{ color: var(--muted); }}
    .rationale {{ min-width: 280px; max-width: 460px; }}
    .desc {{ min-width: 260px; max-width: 420px; }}
    @media (max-width: 720px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      h1 {{ font-size: 23px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Wittington VC Ranked Prospects</h1>
    <p>Sortable Manifest attendee pipeline scored for Wittington's commerce, healthcare, consumer, climate, and food-adjacent investment focus.</p>
  </header>
  <main>
    <div class="toolbar">
      <input id="search" type="search" placeholder="Search company, category, sector, rationale">
      <select id="category">
        <option value="">All categories</option>
        <option>Commerce</option>
        <option>Healthcare</option>
        <option>Consumer</option>
        <option>Climate</option>
        <option>Food</option>
        <option>Other</option>
      </select>
      <span class="count" id="count"></span>
    </div>
    <div class="table-wrap">
      <table id="prospects">
        <thead>
          <tr>
            <th data-type="number">Rank</th>
            <th>Company</th>
            <th data-type="number">Fit</th>
            <th data-type="number">Raw</th>
            <th>Cap</th>
            <th>Category</th>
            <th class="rationale">Rationale</th>
            <th data-type="number">Startup</th>
            <th data-type="number">Stage</th>
            <th data-type="number">Sector</th>
            <th>Domain</th>
            <th data-type="number">Confidence</th>
            <th>Type</th>
            <th>Owner</th>
            <th>Model</th>
            <th>Workflow</th>
            <th>Buyer</th>
            <th>Traction</th>
            <th>Source</th>
            <th data-type="number">Software</th>
            <th data-type="number">Venture</th>
            <th>Stage</th>
            <th data-type="number">Public</th>
            <th>Employees</th>
            <th>HQ</th>
            <th>WV Edge</th>
            <th>Traction</th>
            <th class="desc">Description</th>
          </tr>
        </thead>
        <tbody>
{body}
        </tbody>
      </table>
    </div>
  </main>
  <script>
    const table = document.querySelector("#prospects");
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const search = document.querySelector("#search");
    const category = document.querySelector("#category");
    const count = document.querySelector("#count");

    function applyFilters() {{
      const term = search.value.trim().toLowerCase();
      const cat = category.value;
      let shown = 0;
      for (const row of rows) {{
        const text = row.innerText.toLowerCase();
        const ok = (!term || text.includes(term)) && (!cat || row.dataset.category === cat);
        row.style.display = ok ? "" : "none";
        if (ok) shown += 1;
      }}
      count.textContent = `${{shown}} of ${{rows.length}} rows`;
    }}

    function cellValue(row, index, numeric) {{
      const value = row.children[index].dataset.sort || row.children[index].innerText;
      return numeric ? Number(value || 0) : value.toLowerCase();
    }}

    table.querySelectorAll("th").forEach((th, index) => {{
      th.addEventListener("click", () => {{
        const numeric = th.dataset.type === "number";
        const direction = th.dataset.direction === "asc" ? -1 : 1;
        th.dataset.direction = direction === 1 ? "asc" : "desc";
        rows.sort((a, b) => {{
          const av = cellValue(a, index, numeric);
          const bv = cellValue(b, index, numeric);
          return av > bv ? direction : av < bv ? -direction : 0;
        }});
        tbody.replaceChildren(...rows);
        applyFilters();
      }});
    }});

    search.addEventListener("input", applyFilters);
    category.addEventListener("change", applyFilters);
    applyFilters();
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )


def _html_row(rank: int, row: sqlite3.Row) -> str:
    cells = [
        _td(rank, "num", rank),
        _td(row["name"]),
        _td(row["fit_score"], "num score", row["fit_score"]),
        _td(row["raw_score"], "num", row["raw_score"]),
        _td(row["cap_reason"], "muted"),
        _td(row["category"]),
        _td(row["rationale"], "rationale"),
        _td(row["startup_fit"], "num", row["startup_fit"]),
        _td(row["stage_fit"], "num", row["stage_fit"]),
        _td(row["sector_fit"], "num", row["sector_fit"]),
        _td(row["resolved_domain"], "muted"),
        _td(row["entity_confidence"], "num", row["entity_confidence"]),
        _td(row["company_type"]),
        _td(row["ownership_status"]),
        _td(row["business_model"]),
        _td(row["logistics_workflow"]),
        _td(row["target_buyer"]),
        _td(row["traction_tier"]),
        _td(row["source_quality"]),
        _td(row["software_led"], "num", row["software_led"]),
        _td(row["venture_backed"], "num", row["venture_backed"]),
        _td(row["funding_stage"]),
        _td(row["is_public"], "num", row["is_public"]),
        _td(row["employee_count"]),
        _td(row["hq_location"]),
        _td(row["wv_edge"]),
        _td(row["enterprise_traction"]),
        _td(row["description"], "desc"),
    ]
    return f'          <tr data-category="{html.escape(str(row["category"] or ""))}">' + "".join(cells) + "</tr>"


def _td(value: object, class_name: str | None = None, sort_value: object | None = None) -> str:
    attrs = []
    if class_name:
        attrs.append(f'class="{class_name}"')
    if sort_value is not None:
        attrs.append(f'data-sort="{html.escape(str(sort_value))}"')
    attr = " " + " ".join(attrs) if attrs else ""
    display = "" if value is None else str(value)
    return f"<td{attr}>{html.escape(display)}</td>"


def _csv_value(row: sqlite3.Row, field: str, rank: int) -> object:
    if field == "rank":
        return rank
    return row[field]


def _write_sample_report(
    rows: list[sqlite3.Row], path: Path, sample_size: int, sample_seed: int | None
) -> None:
    scored = [row for row in rows if row["enrichment_status"]]
    top = rows[:20]
    service_types = {"3PL", "Carrier", "Broker", "Consultancy", "Agency", "Distributor", "Manufacturer", "Retailer"}
    service_high = [
        row
        for row in scored
        if row["company_type"] in service_types and (row["fit_score"] or 0) >= 60
        and row["software_led"] != 1
    ]
    missing_high = [
        row
        for row in scored
        if (row["fit_score"] or 0) >= 80
        and _missing_structured(row)
    ]
    public_high = [
        row for row in scored if row["is_public"] and (row["fit_score"] or 0) >= 30
    ]
    stale_enrichment = [
        row for row in scored if (row["enrichment_schema_version"] or 0) < ENRICHMENT_SCHEMA_VERSION
    ]
    low_source_quality = [
        row for row in scored if row["source_quality"] in ("Low", "Unknown", None, "")
    ]
    low_confidence_high = [
        row
        for row in scored
        if (row["fit_score"] or 0) >= 80 and (row["entity_confidence"] is None or row["entity_confidence"] < 75)
    ]
    likely_false_negative = [row for row in scored if _likely_false_negative(row)]
    capped_high_raw = [
        row
        for row in scored
        if row["cap_reason"] and (row["raw_score"] or 0) >= 80 and (row["fit_score"] or 0) < 80
    ]
    capped_by_delta = sorted(
        [row for row in scored if row["cap_reason"] and (row["raw_score"] or 0) > (row["fit_score"] or 0)],
        key=lambda row: (row["raw_score"] or 0) - (row["fit_score"] or 0),
        reverse=True,
    )
    lines = [
        "# Sample Evaluation",
        "",
        f"- Sample size requested: {sample_size}",
        f"- Sample seed: {sample_seed if sample_seed is not None else 'random'}",
        f"- Rows exported: {len(rows)}",
        f"- Enriched/scored rows in export: {len(scored)}",
        f"- Top-score rows (>=80): {sum(1 for row in scored if (row['fit_score'] or 0) >= 80)}",
        f"- High non-software service-provider rows (service type, not software-led, score >=60): {len(service_high)}",
        f"- High rows with missing structured facts (score >=80): {len(missing_high)}",
        f"- High rows with missing/low entity confidence (score >=80): {len(low_confidence_high)}",
        f"- Likely false negatives from caps (raw >=70, final <=65, reviewable signals): {len(likely_false_negative)}",
        f"- Capped rows with raw score >=80 and final score <80: {len(capped_high_raw)}",
        f"- Public rows scoring >=30: {len(public_high)}",
        f"- Stale enrichment schema rows: {len(stale_enrichment)}",
        f"- Rows with low/unknown source quality: {len(low_source_quality)}",
        "",
        "## Top 20",
        "",
        "| Rank | Company | Score | Raw | Cap | Category | Type | Model | Workflow | Buyer | Stage | Source | Rationale |",
        "|---:|---|---:|---:|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, row in enumerate(top, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    _md(row["name"]),
                    str(row["fit_score"]),
                    _md(row["raw_score"]),
                    _md(row["cap_reason"]),
                    _md(row["category"]),
                    _md(row["company_type"]),
                    _md(row["business_model"]),
                    _md(row["logistics_workflow"]),
                    _md(row["target_buyer"]),
                    _md(row["funding_stage"]),
                    _md(row["source_quality"]),
                    _md(row["rationale"]),
                ]
            )
            + " |"
        )
    if service_high:
        lines.extend(["", "## Non-Software Service Provider Rows >=60", ""])
        for row in service_high[:20]:
            lines.append(f"- {row['name']}: {row['fit_score']} ({row['company_type']}) - {row['rationale']}")
    if missing_high:
        lines.extend(["", "## Missing Structured Facts >=80", ""])
        for row in missing_high[:20]:
            lines.append(f"- {row['name']}: {row['fit_score']} - refresh needed")
    if low_confidence_high:
        lines.extend(["", "## Missing Or Low Confidence >=80", ""])
        for row in low_confidence_high[:20]:
            lines.append(f"- {row['name']}: {row['fit_score']} (confidence={row['entity_confidence']})")
    if likely_false_negative:
        lines.extend(["", "## Likely False Negatives From Caps", ""])
        for row in likely_false_negative[:20]:
            lines.append(
                "- "
                f"{row['name']}: final={row['fit_score']}, raw={row['raw_score']}, "
                f"cap={row['cap_reason']}, confidence={row['entity_confidence']}, "
                f"type={row['company_type']}, stage={row['funding_stage']}"
            )
    if capped_by_delta:
        lines.extend(["", "## Largest Score Caps", ""])
        for row in capped_by_delta[:20]:
            delta = (row["raw_score"] or 0) - (row["fit_score"] or 0)
            lines.append(
                "- "
                f"{row['name']}: delta={delta}, final={row['fit_score']}, raw={row['raw_score']}, "
                f"cap={row['cap_reason']}, type={row['company_type']}, stage={row['funding_stage']}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _missing_structured(row: sqlite3.Row) -> bool:
    return (
        (row["enrichment_schema_version"] or 0) < ENRICHMENT_SCHEMA_VERSION
        or row["company_type"] in (None, "", "Unknown")
        or row["ownership_status"] in (None, "", "Unknown")
        or row["business_model"] in (None, "", "Unknown")
        or row["software_led"] is None
        or row["venture_backed"] is None
        or row["source_quality"] in (None, "", "Unknown")
    )


def _likely_false_negative(row: sqlite3.Row) -> bool:
    cap_reason = row["cap_reason"]
    reviewable_cap = cap_reason in {
        "low_entity_confidence",
        "missing_entity_confidence",
        "core_structured_gap",
    }
    reviewable_signals = (
        row["software_led"] == 1
        or row["venture_backed"] == 1
        or row["funding_stage"] in {"Seed", "Series A", "Series B", "Series C"}
    )
    return (
        reviewable_cap
        and (row["raw_score"] or 0) >= 70
        and (row["fit_score"] or 0) <= 65
        and row["category"] != "Other"
        and reviewable_signals
    )


def _md(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")
