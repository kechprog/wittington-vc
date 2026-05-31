# Wittington VC Prospect Ranker

Ranks Manifest attendees for Wittington Ventures by scraping attendee names, resolving companies with Exa, enriching venture-relevant fields, scoring fit, and exporting a sortable prospect list.

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
uv run wittington-vc --enrich-limit 10 --workers 6
```

Fresh sample run:

```bash
uv run wittington-vc --sample-size 100 --sample-seed 20260609 --full --workers 6 --refresh-enrichment --rescore
```

Full fresh run:

```bash
rm -f src/db/wittington.db
uv run wittington-vc --full --workers 6 --rescore
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
uv run wittington-vc --refresh-stale-enrichment --full --rescore --workers 6
```

Use `--workers 6` for final runs. In probes, `8` was faster but missed one company that `6` resolved; `6` is the better reliability-speed tradeoff under deadline pressure.

## Limitations And Future Improvements

Exa is useful for entity resolution and company summaries, but it is inconsistent on latest round dates, round amounts, named investors, acquired/subsidiary status, traction, and precise buyer/workflow labels. The code treats those fields as helpful signals, not mandatory facts.

The next improvement should be a targeted second enrichment pass only for high-potential rows with weak evidence: for example, `raw_score >= 80` with low source quality, missing ownership status, or missing funding context. Funding/news APIs and Wittington first-party CRM or meeting data would improve investor, stage, relationship, and strategic-fit signals without over-enriching every attendee.
