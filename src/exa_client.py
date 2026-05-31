"""Company resolution + firmographic enrichment via the Exa API.

A single Exa ``/search`` call (``category="company"``) does two jobs at once:
  1. Resolves a verbatim scraped string to the right company's site (top result).
  2. Extracts structured firmographics from that page via a schema-constrained
     LLM summary, where the schema is derived from the ``Firmographics`` model.

Search the string EXACTLY as scraped -- do not normalize it. The scrape's own
specificity (e.g. "Pando.ai", not "Pando") is what disambiguates the entity.

Reads the API key from the ``EXA_API`` environment variable.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from pydantic import ValidationError

from models import ExaEnrichment, Firmographics, SourceQuality

_SEARCH_URL = "https://api.exa.ai/search"

_SUMMARY_QUERY = (
    "Resolve the searched company exactly and return a venture-screening profile. "
    "Include firmographics plus structured signals that separate software-led "
    "startups from carriers, brokers, 3PLs, shippers, consultancies, incumbents, "
    "public companies, acquired companies, and subsidiaries. Also extract ownership "
    "status, business model, latest round date and amount, named investors, logistics "
    "workflow, target buyer, traction tier, Wittington partner match, source quality, "
    "and evidence URLs when public evidence is available. Be conservative: use "
    "Unknown/null when evidence is weak, include disqualifiers, and cite a short "
    "evidence snippet."
)

# Cached once: the flattened schema Exa's structured summary accepts.
_FIRMOGRAPHICS_SCHEMA = None


class ExaTransientError(RuntimeError):
    """Raised when Exa fails transiently and the row should remain pending."""


def _exa_schema(model: type) -> dict:
    """Flatten a Pydantic JSON schema into the shape Exa's summary accepts.

    Exa silently returns no summary when the schema contains ``$ref``/``$defs``,
    ``anyOf: [X, null]`` unions, or ``title``/``default`` keys. This inlines refs,
    collapses optional unions to their non-null type (preserving inline enums),
    and drops the noise keys.
    """
    full = model.model_json_schema()
    defs = full.get("$defs", {})

    def simplify(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                return simplify(defs[node["$ref"].rsplit("/", 1)[-1]])
            if "anyOf" in node:
                options = [opt for opt in node["anyOf"] if opt.get("type") != "null"]
                if len(options) == 1:
                    return simplify(options[0])
                return {"anyOf": [simplify(opt) for opt in options]}
            return {k: simplify(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [simplify(item) for item in node]
        return node

    return simplify({k: v for k, v in full.items() if k != "$defs"})


def enrich_company(name: str) -> ExaEnrichment | None:
    """Resolve a verbatim company string and return its enrichment, or ``None``.

    Returns ``None`` only when Exa successfully responds with no company result.
    Transient API/network failures raise ``ExaTransientError`` so callers do not
    cache them as real unresolved companies.
    """
    api_key = os.environ.get("EXA_API")
    if not api_key:
        raise RuntimeError("EXA_API environment variable is not set.")

    global _FIRMOGRAPHICS_SCHEMA
    if _FIRMOGRAPHICS_SCHEMA is None:
        _FIRMOGRAPHICS_SCHEMA = _exa_schema(Firmographics)

    payload = json.dumps(
        {
            "query": name,
            "type": "auto",
            "category": "company",
            "numResults": 1,
            "contents": {
                "summary": {"query": _SUMMARY_QUERY, "schema": _FIRMOGRAPHICS_SCHEMA}
            },
        }
    ).encode()

    request = urllib.request.Request(
        _SEARCH_URL,
        data=payload,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    body = _open_json_with_retries(request)
    if body is None:
        return None

    results = body.get("results") or []
    if not results:
        return None
    top = results[0]
    url = top.get("url") or ""

    summary = top.get("summary")
    if not summary:
        firmographics = _fallback_firmographics(name, top, url)
        return ExaEnrichment(
            resolved_url=url or None,
            resolved_domain=_domain(url),
            title=top.get("title"),
            firmographics=firmographics,
        )
    try:
        firmographics = (
            Firmographics.model_validate_json(summary)
            if isinstance(summary, str)
            else Firmographics.model_validate(summary)
        )
    except ValidationError:
        firmographics = _fallback_firmographics(name, top, url)

    return ExaEnrichment(
        resolved_url=url or None,
        resolved_domain=_domain(url),
        title=top.get("title"),
        firmographics=firmographics,
    )


def _open_json_with_retries(request: urllib.request.Request) -> dict:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"Exa HTTP {error.code}") from error
            if attempt == 2:
                raise ExaTransientError(f"Exa transient HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                raise ExaTransientError("Exa transient network or JSON failure")
        time.sleep(0.8 * (attempt + 1))
    raise ExaTransientError("Exa transient failure")


def _fallback_firmographics(name: str, top: dict, url: str) -> Firmographics:
    title = top.get("title") or name
    return Firmographics(
        description=f"Resolved company page for {name}; structured Exa summary unavailable.",
        industry="Unknown",
        is_public=False,
        canonical_name=title,
        source_quality=SourceQuality.LOW,
        evidence_urls=url or None,
        disqualifiers="Structured Exa summary unavailable; refresh or second-source before relying on this row.",
    )


def _domain(url: str) -> str | None:
    netloc = urllib.parse.urlparse(url).netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None
