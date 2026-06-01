"""Export the ranked pipeline to reviewer-friendly artifacts."""

from __future__ import annotations

import csv
import json
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
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            writer.writerow({field: _csv_value(row, field, rank) for field in fields})


def _write_html(rows: list[sqlite3.Row], path: Path) -> None:
    prospects = [_html_prospect(rank, row) for rank, row in enumerate(rows, start=1)]
    payload = json.dumps(prospects, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    path.write_text(_HTML_TEMPLATE.replace("__PROSPECTS_JSON__", payload), encoding="utf-8")


def _html_prospect(rank: int, row: sqlite3.Row) -> dict[str, object]:
    rationale = row["rationale"] or ""
    return {
        "id": rank - 1,
        "rank": rank,
        "company": row["name"] or "",
        "fit": row["fit_score"] or 0,
        "raw": row["raw_score"],
        "cap": row["cap_reason"] or "",
        "category": row["category"] or "Other",
        "rationale": rationale,
        "startup": row["startup_fit"],
        "stageScore": row["stage_fit"],
        "sector": row["sector_fit"],
        "domain": row["resolved_domain"] or "",
        "confidence": row["entity_confidence"],
        "type": row["company_type"] or "",
        "owner": row["ownership_status"] or "",
        "model": row["business_model"] or "",
        "workflow": row["logistics_workflow"] or "",
        "buyer": row["target_buyer"] or "",
        "tractionTier": row["traction_tier"] or "",
        "source": row["source_quality"] or "",
        "software": bool(row["software_led"]),
        "venture": bool(row["venture_backed"]),
        "fundingStage": row["funding_stage"] or "",
        "publicCompany": bool(row["is_public"]),
        "employees": row["employee_count"] or "",
        "hq": row["hq_location"] or "",
        "wvEdge": row["wv_edge"] or "",
        "traction": row["enterprise_traction"] or "",
        "description": row["description"] or "",
        "scored": bool(rationale and rationale != "Not scored yet."),
    }


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wittington VC Ranked Prospects</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17211c;
      --muted: #5b665f;
      --line: #d9ded8;
      --bg: #f8faf7;
      --accent: #16705a;
      --soft: #edf4f0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }
    h1 { margin: 0 0 8px; font-size: 28px; font-weight: 720; letter-spacing: 0; }
    p { margin: 0; color: var(--muted); max-width: 960px; }
    main { padding: 18px 32px 36px; }
    input, select {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #ffffff;
      color: var(--ink);
    }
    .app-shell { display: grid; gap: 12px; }
    .summary-panel {
      border: 1px solid var(--line);
      background: #ffffff;
      padding: 14px;
    }
    .status-band {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 1px;
      border: 1px solid var(--line);
      background: var(--line);
    }
    .metric {
      background: #ffffff;
      padding: 10px 12px;
      min-height: 64px;
    }
    .metric strong {
      display: block;
      font-size: 22px;
      line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 5px;
    }
    .review-note {
      border: 1px solid #e2d6ad;
      background: #fff9e8;
      color: #5e4a12;
      padding: 8px 10px;
      font-size: 13px;
    }
    .review-note[hidden] { display: none; }
    .control-bar {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) 168px 140px 150px 82px;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      background: #ffffff;
      padding: 10px;
    }
    .control-bar input { width: 100%; }
    .pager {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .pager-controls {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .control-bar button,
    .details-button,
    .pager button,
    .panel-close {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      padding: 7px 10px;
      font: inherit;
      cursor: pointer;
    }
    .control-bar button:hover,
    .details-button:hover,
    .pager button:hover,
    .panel-close:hover {
      border-color: #aeb9b1;
      background: #f7faf8;
    }
    .pager button:disabled {
      opacity: 0.45;
      cursor: default;
    }
    .compact-table-wrap {
      border: 1px solid var(--line);
      background: #ffffff;
      overflow-x: auto;
      overflow-y: hidden;
      -webkit-overflow-scrolling: touch;
    }
    .compact-table {
      width: max(100%, 1540px);
      min-width: 1540px;
      border-collapse: collapse;
      table-layout: fixed;
    }
    .compact-table th,
    .compact-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      vertical-align: middle;
    }
    .compact-table col.rank-col { width: 64px; }
    .compact-table col.fit-col { width: 74px; }
    .compact-table col.company-col { width: 270px; }
    .compact-table col.category-col { width: 112px; }
    .compact-table col.stage-col { width: 104px; }
    .compact-table col.type-col { width: 128px; }
    .compact-table col.workflow-col { width: 164px; }
    .compact-table col.buyer-col { width: 124px; }
    .compact-table col.traction-col { width: 112px; }
    .compact-table col.source-col { width: 94px; }
    .compact-table col.rationale-col { width: 286px; }
    .compact-table col.details-col { width: 78px; }
    .compact-table th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #eef4f1;
      color: #25322b;
      font-size: 12px;
      text-transform: uppercase;
    }
    .compact-table th button {
      all: unset;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      width: 100%;
    }
    .compact-table th button::after {
      content: "v";
      margin-left: auto;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      text-transform: none;
    }
    .compact-table th.locked { cursor: default; }
    .compact-table tbody tr { cursor: pointer; }
    .compact-table tbody tr:hover { background: #f8fbf9; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .company-cell { font-weight: 680; }
    .company-cell span {
      display: block;
      color: var(--muted);
      font-weight: 500;
      font-size: 12px;
      margin-top: 2px;
    }
    .fit-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 44px;
      border-radius: 6px;
      padding: 5px 8px;
      background: #e9f5ef;
      color: #0f684f;
      font-weight: 760;
      font-variant-numeric: tabular-nums;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border: 1px solid #dfe5df;
      border-radius: 6px;
      padding: 2px 7px;
      background: #ffffff;
      color: #2d3831;
      white-space: nowrap;
    }
    .tag.muted-tag {
      color: var(--muted);
      background: #f8faf8;
    }
    .rationale-clip {
      color: #344139;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .menu {
      position: fixed;
      z-index: 20;
      width: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      box-shadow: 0 16px 40px rgba(23, 33, 28, 0.16);
      padding: 10px;
    }
    .menu[hidden],
    .detail-overlay[hidden] {
      display: none;
    }
    .menu-title {
      font-weight: 720;
      margin-bottom: 8px;
    }
    .menu label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
    }
    .menu select,
    .menu input {
      width: 100%;
    }
    .detail-overlay {
      position: fixed;
      inset: 0;
      z-index: 30;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(23, 33, 28, 0.24);
      padding: 32px;
    }
    .detail-panel {
      width: min(980px, calc(100vw - 64px));
      max-height: calc(100vh - 64px);
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      overflow: hidden;
      box-shadow: 0 18px 44px rgba(23, 33, 28, 0.2);
    }
    .panel-top {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: start;
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
      margin-bottom: 8px;
    }
    .panel-top h2 {
      margin: 0 0 5px;
      font-size: 22px;
      letter-spacing: 0;
    }
    .muted { color: var(--muted); }
    .panel-section {
      border-bottom: 1px solid var(--line);
      padding: 6px 0;
    }
    .panel-section h3 {
      margin: 0 0 6px;
      font-size: 13px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0;
    }
    .score-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
    }
    .score-card,
    .fact,
    .signal {
      min-width: 0;
      border: 1px solid #dfe7df;
      border-radius: 6px;
      background: #ffffff;
      box-shadow: 0 1px 0 rgba(23, 33, 28, 0.03);
    }
    .score-card { padding: 8px 9px; }
    .score-card span,
    .fact span,
    .signal span {
      display: block;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.1;
      margin-bottom: 3px;
      text-transform: uppercase;
      letter-spacing: 0;
      font-weight: 680;
    }
    .score-card strong,
    .fact strong,
    .signal strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 15px;
      line-height: 1.15;
      font-weight: 720;
      color: var(--ink);
    }
    .score-card strong {
      color: var(--accent);
      font-variant-numeric: tabular-nums;
    }
    .score-bar {
      height: 4px;
      margin-top: 8px;
      overflow: hidden;
      border-radius: 999px;
      background: #e9eee9;
    }
    .score-bar i {
      display: block;
      width: calc(var(--score, 0) * 1%);
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
    }
    .fit-meta,
    .fact-grid,
    .signal-grid {
      display: grid;
      gap: 8px;
      margin-top: 8px;
    }
    .fit-meta { grid-template-columns: 1fr 1fr; }
    .fact-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .signal-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-top: 0;
    }
    .fact,
    .signal {
      padding: 7px 9px;
      background: #fbfdfb;
    }
    .fact-wide { grid-column: span 2; }
    .signal { border-left: 3px solid #d4e2db; }
    .signal-positive { border-left-color: var(--accent); }
    .clamped {
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      line-height: 1.45;
    }
    @media (max-width: 900px) {
      header, main { padding-left: 16px; padding-right: 16px; }
      .status-band { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
      .control-bar { grid-template-columns: 1fr 1fr; }
      .control-bar input { grid-column: 1 / -1; }
      .detail-overlay { padding: 16px; }
      .detail-panel { width: calc(100vw - 32px); }
    }
    @media (max-width: 640px) {
      h1 { font-size: 23px; }
      .score-grid,
      .fact-grid,
      .signal-grid { grid-template-columns: 1fr 1fr; }
      .fit-meta { grid-template-columns: 1fr; }
      .fact-wide { grid-column: span 2; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Wittington VC Ranked Prospects</h1>
    <p>Manifest attendee pipeline scored for Wittington's commerce, healthcare, consumer, climate, and food-adjacent investment focus.</p>
  </header>
  <main>
    <section class="app-shell">
      <div class="summary-panel">
        <div class="status-band">
          <div class="metric"><strong id="metricTotal"></strong><span>Total attendees</span></div>
          <div class="metric"><strong id="metricScored"></strong><span>Enriched and scored</span></div>
          <div class="metric"><strong id="metricVisible"></strong><span>Visible after filters</span></div>
          <div class="metric"><strong id="metricTop"></strong><span>Visible with fit >= 80</span></div>
        </div>
      </div>
      <div id="reviewNote" class="review-note" hidden></div>
      <div class="control-bar">
        <input id="appSearch" type="search" placeholder="Search company, thesis, workflow, rationale">
        <select id="appCategory"><option value="">All categories</option></select>
        <select id="appMinFit">
          <option value="0">Any fit</option>
          <option value="60">Fit >= 60</option>
          <option value="70">Fit >= 70</option>
          <option value="80">Fit >= 80</option>
          <option value="90">Fit >= 90</option>
        </select>
        <select id="appSource"><option value="">Any source</option></select>
        <button id="clearFilters" type="button">Clear</button>
      </div>
      <div class="pager">
        <span id="pageSummary"></span>
        <div class="pager-controls">
          <label>Rows
            <select id="pageSize">
              <option value="10">10</option>
              <option value="15">15</option>
              <option value="25">25</option>
              <option value="50">50</option>
            </select>
          </label>
          <button id="prevPage" type="button">Prev</button>
          <span id="pageIndex"></span>
          <button id="nextPage" type="button">Next</button>
        </div>
      </div>
      <div class="compact-table-wrap">
        <table class="compact-table">
          <colgroup>
            <col class="rank-col">
            <col class="fit-col">
            <col class="company-col">
            <col class="category-col">
            <col class="stage-col">
            <col class="type-col">
            <col class="workflow-col">
            <col class="buyer-col">
            <col class="traction-col">
            <col class="source-col">
            <col class="rationale-col">
            <col class="details-col">
          </colgroup>
          <thead><tr id="compactHead"></tr></thead>
          <tbody id="compactBody"></tbody>
        </table>
      </div>
      <div id="columnMenu" class="menu" hidden></div>
      <div id="detailOverlay" class="detail-overlay" hidden>
        <aside class="detail-panel" role="dialog" aria-modal="true" aria-labelledby="detailTitle">
          <div id="detailContent"></div>
        </aside>
      </div>
    </section>
  </main>
  <script id="prospectData" type="application/json">__PROSPECTS_JSON__</script>
  <script>
    const prospects = JSON.parse(document.querySelector("#prospectData").textContent);
    const clean = (value, fallback = "-") => value === undefined || value === null || value === "" ? fallback : value;
    const escapeHtml = (value) => String(clean(value, ""))
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
    function scoreCard(label, value) {
      const score = Math.max(0, Math.min(100, Number(value) || 0));
      return `<div class="score-card" style="--score:${score}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(clean(value))}</strong><div class="score-bar"><i></i></div></div>`;
    }
    function fact(label, value, options = {}) {
      const classes = `fact${options.wide ? " fact-wide" : ""}`;
      return `<div class="${classes}"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(clean(value))}">${escapeHtml(clean(value))}</strong></div>`;
    }
    function signal(label, value, positive = false) {
      const classes = `signal${positive ? " signal-positive" : ""}`;
      return `<div class="${classes}"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(clean(value))}">${escapeHtml(clean(value))}</strong></div>`;
    }

    const columns = [
      { key: "rank", label: "Rank", className: "num", locked: true },
      { key: "fit", label: "Fit", className: "num", filter: "range", render: (row) => `<span class="fit-pill">${row.fit}</span>` },
      { key: "company", label: "Company", className: "company-cell", filter: "search", render: (row) => `${escapeHtml(row.company)}<span>${escapeHtml(row.domain || "No resolved domain")}</span>` },
      { key: "category", label: "Category", filter: "value", render: (row) => `<span class="tag">${escapeHtml(row.category)}</span>` },
      { key: "fundingStage", label: "Stage", filter: "value", render: (row) => `<span class="tag muted-tag">${escapeHtml(clean(row.fundingStage))}</span>` },
      { key: "type", label: "Type", filter: "value" },
      { key: "workflow", label: "Workflow", filter: "value" },
      { key: "buyer", label: "Buyer", filter: "value" },
      { key: "tractionTier", label: "Traction", filter: "value" },
      { key: "source", label: "Source", filter: "value", render: (row) => `<span class="tag muted-tag">${escapeHtml(clean(row.source))}</span>` },
      { key: "rationale", label: "Rationale", className: "rationale-clip", filter: "search" },
      { key: "details", label: "Details", sortable: false, render: (row) => `<button class="details-button" data-id="${row.id}" type="button">View</button>` }
    ];

    const state = {
      search: "",
      category: "",
      minFit: 0,
      source: "",
      columnFilters: {},
      page: 1,
      pageSize: 10
    };

    const head = document.querySelector("#compactHead");
    const body = document.querySelector("#compactBody");
    const menu = document.querySelector("#columnMenu");
    const overlay = document.querySelector("#detailOverlay");
    const detailContent = document.querySelector("#detailContent");
    const reviewNote = document.querySelector("#reviewNote");

    function uniqueValues(key) {
      return Array.from(new Set(prospects.map((row) => clean(row[key], "")).filter(Boolean))).sort((a, b) => String(a).localeCompare(String(b)));
    }
    function populateSelect(id, key) {
      const select = document.querySelector(id);
      for (const value of uniqueValues(key)) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.append(option);
      }
    }
    populateSelect("#appCategory", "category");
    populateSelect("#appSource", "source");

    head.innerHTML = columns.map((column) => {
      if (column.locked || column.sortable === false) return `<th class="locked">${escapeHtml(column.label)}</th>`;
      return `<th><button type="button" data-key="${column.key}">${escapeHtml(column.label)}</button></th>`;
    }).join("");

    function filteredRows() {
      const term = state.search.toLowerCase();
      return prospects.filter((row) => {
        if (state.category && row.category !== state.category) return false;
        if (state.source && row.source !== state.source) return false;
        if (row.fit < state.minFit) return false;
        for (const [key, value] of Object.entries(state.columnFilters)) {
          if (!value) continue;
          if (key === "fit" && row.fit < Number(value)) return false;
          else if ((key === "company" || key === "rationale") && !String(row[key] || "").toLowerCase().includes(String(value).toLowerCase())) return false;
          else if (key !== "fit" && key !== "company" && key !== "rationale" && clean(row[key], "") !== value) return false;
        }
        if (!term) return true;
        return [
          row.company, row.domain, row.category, row.fundingStage, row.type, row.model,
          row.workflow, row.buyer, row.source, row.rationale, row.description, row.hq
        ].join(" ").toLowerCase().includes(term);
      });
    }

    function render() {
      const visible = filteredRows().sort((a, b) => a.rank - b.rank);
      const pageCount = Math.max(1, Math.ceil(visible.length / state.pageSize));
      state.page = Math.min(Math.max(1, state.page), pageCount);
      const start = (state.page - 1) * state.pageSize;
      const pageRows = visible.slice(start, start + state.pageSize);
      const scored = prospects.filter((row) => row.scored).length;
      const pending = prospects.length - scored;
      document.querySelector("#metricTotal").textContent = prospects.length.toLocaleString();
      document.querySelector("#metricScored").textContent = scored.toLocaleString();
      document.querySelector("#metricVisible").textContent = visible.length.toLocaleString();
      document.querySelector("#metricTop").textContent = visible.filter((row) => row.fit >= 80).length.toLocaleString();
      reviewNote.hidden = pending === 0;
      reviewNote.textContent = pending
        ? `Partial view: ${scored.toLocaleString()} enriched/scored rows; ${pending.toLocaleString()} pending enrichment rows remain visible at fit 0 for coverage.`
        : "";
      document.querySelector("#pageSummary").textContent = visible.length
        ? `Showing ${(start + 1).toLocaleString()}-${(start + pageRows.length).toLocaleString()} of ${visible.length.toLocaleString()} in rank order`
        : "No rows match the current filters";
      document.querySelector("#pageIndex").textContent = `${state.page} / ${pageCount}`;
      document.querySelector("#prevPage").disabled = state.page <= 1;
      document.querySelector("#nextPage").disabled = state.page >= pageCount;
      body.innerHTML = pageRows.map((row) => `
        <tr data-id="${row.id}" data-category="${escapeHtml(row.category)}">
          ${columns.map((column) => {
            const rendered = column.render ? column.render(row) : escapeHtml(clean(row[column.key]));
            return `<td class="${column.className || ""}">${rendered}</td>`;
          }).join("")}
        </tr>
      `).join("");
    }

    function openMenu(column, button) {
      if (column.locked || column.sortable === false) return;
      const values = uniqueValues(column.key);
      const canFilter = values.length > 1 && values.length <= 80;
      const current = state.columnFilters[column.key] || "";
      const control = column.filter === "range" ? `
        <label>Minimum fit
          <select data-filter-key="${column.key}">
            <option value="">Any fit</option>
            ${[60, 70, 80, 90, 95].map((value) => `<option value="${value}" ${String(current) === String(value) ? "selected" : ""}>Fit >= ${value}</option>`).join("")}
          </select>
        </label>
      ` : column.filter === "search" || !canFilter ? `
        <label>Contains
          <input data-filter-key="${column.key}" type="search" value="${escapeHtml(current)}" placeholder="Type to filter this column">
        </label>
      ` : `
        <label>Filter value
          <select data-filter-key="${column.key}">
            <option value="">All</option>
            ${values.map((value) => `<option value="${escapeHtml(value)}" ${current === value ? "selected" : ""}>${escapeHtml(value)}</option>`).join("")}
          </select>
        </label>
      `;
      menu.innerHTML = `
        <div class="menu-title">${escapeHtml(column.label)}</div>
        <div class="muted" style="margin-bottom: 8px;">Rank order is fixed. This menu filters only.</div>
        ${control}
      `;
      const rect = button.getBoundingClientRect();
      menu.style.left = `${Math.min(rect.left, window.innerWidth - 280)}px`;
      menu.style.top = `${rect.bottom + 8}px`;
      menu.hidden = false;
      const filter = menu.querySelector("[data-filter-key]");
      if (filter) {
        const eventName = filter.tagName === "INPUT" ? "input" : "change";
        filter.addEventListener(eventName, () => {
          state.columnFilters[column.key] = filter.value;
          state.page = 1;
          if (filter.tagName !== "INPUT") menu.hidden = true;
          render();
        });
        if (filter.tagName === "INPUT") filter.focus();
      }
    }

    function openDetails(row) {
      detailContent.innerHTML = `
        <div class="panel-top">
          <div>
            <h2 id="detailTitle">${escapeHtml(row.company)}</h2>
            <div class="muted">${escapeHtml(clean(row.domain, "No resolved domain"))}</div>
          </div>
          <button class="panel-close" type="button">Close</button>
        </div>
        <div class="panel-section">
          <h3>Fit</h3>
          <div class="score-grid">
            ${scoreCard("Fit score", row.fit)}
            ${scoreCard("Raw score", row.raw)}
            ${scoreCard("Startup", row.startup)}
            ${scoreCard("Stage", row.stageScore)}
            ${scoreCard("Sector", row.sector)}
            ${scoreCard("Confidence", row.confidence)}
          </div>
          <div class="fit-meta">
            ${fact("Category", row.category)}
            ${fact("Cap reason", row.cap)}
          </div>
        </div>
        <div class="panel-section">
          <h3>Company</h3>
          <div class="fact-grid">
            ${fact("Funding stage", row.fundingStage)}
            ${fact("Type", row.type)}
            ${fact("Ownership", row.owner)}
            ${fact("Model", row.model)}
            ${fact("Employees", row.employees)}
            ${fact("HQ", row.hq, { wide: true })}
          </div>
        </div>
        <div class="panel-section">
          <h3>Strategic Signals</h3>
          <div class="signal-grid">
            ${signal("Workflow", row.workflow)}
            ${signal("Buyer", row.buyer)}
            ${signal("Traction tier", row.tractionTier, !["-", "Unknown"].includes(String(clean(row.tractionTier))))}
            ${signal("Source quality", row.source, row.source === "High")}
            ${signal("Software-led", row.software ? "Yes" : "No", Boolean(row.software))}
            ${signal("Venture-backed", row.venture ? "Yes" : "No", Boolean(row.venture))}
          </div>
        </div>
        <div class="panel-section">
          <h3>Rationale</h3>
          <p class="clamped">${escapeHtml(clean(row.rationale))}</p>
        </div>
        <div class="panel-section">
          <h3>Description</h3>
          <p class="clamped">${escapeHtml(clean(row.description))}</p>
        </div>
      `;
      overlay.hidden = false;
      detailContent.querySelector(".panel-close").addEventListener("click", closeDetails);
    }
    function closeDetails() {
      overlay.hidden = true;
    }

    head.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-key]");
      if (!button) return;
      const column = columns.find((item) => item.key === button.dataset.key);
      openMenu(column, button);
    });
    body.addEventListener("click", (event) => {
      const rowElement = event.target.closest("tr[data-id]");
      if (!rowElement) return;
      const row = prospects.find((item) => item.id === Number(rowElement.dataset.id));
      openDetails(row);
    });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) closeDetails();
    });
    document.addEventListener("click", (event) => {
      if (!menu.hidden && !event.target.closest("#columnMenu") && !event.target.closest("th")) {
        menu.hidden = true;
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        menu.hidden = true;
        closeDetails();
      }
    });
    document.querySelector("#appSearch").addEventListener("input", (event) => {
      state.search = event.target.value.trim();
      state.page = 1;
      render();
    });
    document.querySelector("#appCategory").addEventListener("change", (event) => {
      state.category = event.target.value;
      state.page = 1;
      render();
    });
    document.querySelector("#appMinFit").addEventListener("change", (event) => {
      state.minFit = Number(event.target.value);
      state.page = 1;
      render();
    });
    document.querySelector("#appSource").addEventListener("change", (event) => {
      state.source = event.target.value;
      state.page = 1;
      render();
    });
    document.querySelector("#pageSize").addEventListener("change", (event) => {
      state.pageSize = Number(event.target.value);
      state.page = 1;
      render();
    });
    document.querySelector("#prevPage").addEventListener("click", () => {
      state.page -= 1;
      render();
    });
    document.querySelector("#nextPage").addEventListener("click", () => {
      state.page += 1;
      render();
    });
    document.querySelector("#clearFilters").addEventListener("click", () => {
      state.search = "";
      state.category = "";
      state.minFit = 0;
      state.source = "";
      state.columnFilters = {};
      state.page = 1;
      document.querySelector("#appSearch").value = "";
      document.querySelector("#appCategory").value = "";
      document.querySelector("#appMinFit").value = "0";
      document.querySelector("#appSource").value = "";
      menu.hidden = true;
      render();
    });
    render();
  </script>
</body>
</html>
"""


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
