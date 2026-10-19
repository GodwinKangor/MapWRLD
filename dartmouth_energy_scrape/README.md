# Dartmouth Energy Transition — MapWRLD dataset starter

This is an initial, source-backed project inventory, **not an exhaustive completed scrape**.
`seed_projects.json` contains 10 entries transcribed from Dartmouth's publicly visible Projects-at-a-Glance directory (checked 2026-10-14). Its `directory_status` is the website's categorization, not a field-verified status. The Housing entries are included as possible energy-related leads, not confirmed energy retrofits.

## Run a broader crawl on your Mac

```bash
cd dartmouth_energy_scrape
python3 -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4
python scrape.py
```

Outputs: `pages.json` (text + URLs), `pages.csv` (index), `links.csv` (page relationships), `errors.json` (skipped/failed pages). The crawler checks robots.txt, rate-limits requests, stays on two Dartmouth domains, and caps pages at 300. It does not bypass login or access restrictions. This is a **bounded discovery crawl**, not a guarantee of every relevant page. Extend to news, PDF documents, sitemap discovery, and archival records after validating this run.

## Next data-model steps

1. Extract candidate project records from individual pages.
2. Assign stable building and project IDs.
3. Record `project_id`, `building_id`, `relationship_type`, `evidence_url`, and `evidence_quote_or_span` in a connections table.
4. Separate planned/ongoing/completed statuses and attach dates to status claims.
5. Manually verify every building relationship before publishing it on MapWRLD.

Sources:
- https://climate.dartmouth.edu/operational-goals/energy-transition
- https://campus-services.dartmouth.edu/construction-campus/projects-glance
