# Wittington VC Prospect Ranker

Ranks Manifest attendees for Wittington Ventures by scraping attendee names, resolving companies with Exa, enriching venture-relevant fields, scoring fit, and exporting a sortable prospect list.

## Hosted Report

View the latest generated report at https://kechprog.github.io/wittington-vc/.

## How To Run

```bash
brew install uv
uv sync
uv run playwright install chromium
```

Create `.env`:

```bash
EXA_API=...
OPENROUTER_API=...
```

`EXA_API` is required for fresh enrichment. `OPENROUTER_API` is optional; without it, deterministic scoring still works, but rationales and bounded score adjustments are weaker.

Smoke test:

```bash
uv run wittington-vc --enrich-limit 10 --workers 4
```

Fresh sample run:

```bash
uv run wittington-vc --sample-size 100 --sample-seed 20260609 --full --workers 4 --refresh-enrichment --rescore
```

Full fresh run:

```bash
rm -f src/db/wittington.db
uv run wittington-vc --full --workers 4 --rescore
```

The main outputs are `output/ranked_prospects.html`, `output/ranked_prospects.csv`, and the local SQLite cache at `src/db/wittington.db`.

## Scoring Logic

Scores run from 0 to 100. The deterministic base score evaluates stage, company type, sector fit, geography, venture readiness, and Wittington strategic relevance across commerce, healthcare, consumer, climate, and food-adjacent themes.

Hard caps protect the ranking from obvious false positives: public companies, acquired companies, non-software service providers, stale enrichment, weak entity resolution, and off-thesis companies cannot quietly rank as top prospects. The export includes both `raw_score` and `cap_reason` so reviewers can see whether a prospect was held down by a rule rather than by lack of fit.

The exact weights and caps are code-level assumptions based on the prompt's broad fit criteria, and should be tuned if Wittington provides more precise partner preferences, known relationships, or current deal appetite.

When `OPENROUTER_API` is present, the LLM may make a bounded adjustment and write a short rationale. It cannot override the hard caps.

## Enrichment Strategy

The pipeline queries Exa with `category="company"` and asks for structured firmographics: resolved URL, canonical name, description, industry, location, employee count, funding stage, ownership status, business model, software-led status, venture backing, logistics workflow, target buyer, traction tier, Wittington partner match, source quality, evidence URLs, and disqualifiers.

Rows are cached in SQLite, including unresolved rows, so reruns are incremental and auditable. The current enrichment schema is versioned; stale cached rows can be refreshed with:

```bash
uv run wittington-vc --refresh-stale-enrichment --full --rescore --workers 4
```

Use `--workers 4` for final full runs. Smaller probes tolerated `6`, but the sustained full-list run exposed transient Exa misses; transient API failures stay pending for retry rather than being cached as real unresolved companies.

## Future Capabilities

The next UX step would be turning the static ranked table into a weekly review workflow: saved filters, reviewer notes, status tags such as review / pass / intro requested, and side-by-side evidence for why a company ranked highly. I would also add explainable score breakdowns and exportable shortlists so the tool supports both quick triage and partner discussion.

For enrichment, I would keep the current cached, staged workflow rather than enriching every field with expensive APIs by default. Exa is useful for first-pass company resolution and structured web evidence; targeted second-pass APIs would be added only for promising or ambiguous companies. Crunchbase or funding/news APIs would improve round, investor, acquisition, and traction signals. People Data Labs, Apollo, or similar company-data APIs could improve employee count, headquarters, domain matching, and ownership fields where web summaries are weak.

The highest-impact improvement would be first-party Wittington data. CRM records would show whether a company is already known, previously passed, or owned by another partner. Meeting notes and email/calendar activity would signal relationship strength and recency. Past deal history would let the ranking learn what Wittington actually acts on, not just what broadly matches the website thesis. Those signals should adjust rank and confidence, while preserving the external evidence trail so reviewers can see both why a company fits and why it matters now.
