# MapWRLD Dartmouth Energy Scraper V2

Includes the original 35-page crawl, the unverified Pass 1 dataset, the runnable V2 collector, and saved live-crawl outputs in `v2_output/`. See `v2_output/coverage_report.md` and `errors_v2.json` for coverage limits and failed or skipped URLs.

## Mac setup

```bash
cd energy_v2
python3 -m venv .venv
source .venv/bin/activate
pip install requests beautifulsoup4 pymupdf
python scrape_v2.py --max-pages 400 --delay 1.5   # --min-score, --max-depth, --no-sitemaps
python extract_candidates.py
```

How the collector finds pages: it reads the sitemaps of the seed hosts (campus-services, climate, home, sustainability, irving, engineering), the seed queue, the previous run's leftover queue, and links on every page fetched so far. URLs are fetched in priority order. The score comes from energy and infrastructure terms in the URL and link text (steam, geo-exchange, heat pump, utilities, projects-glance…), weighted by host: campus operations sites rank higher than research institutes. Profile, admissions, course and degree pages are skipped. Links are only followed from pages whose text is about energy or infrastructure. Listing pagination (`?page=N`) is kept. A 404 on a moved page is retried at the sitemap URL with the same slug. A news article syndicated across subsites is fetched once. Each record has a `priority` (URL score) and a `relevance` (distinct energy terms in its text). `crawl_state.json` keeps the scored remaining queue, so a re-run continues where the last one stopped.

Outputs in `v2_output/`: `pages_v2.json`, `documents_v2.json`, downloaded `pdfs/`, `errors_v2.json`, and `evidence_candidates.json`. Re-running preserves collected records. It respects robots.txt and only crawls relevant HTTPS Dartmouth domains; it does not log in or bypass restrictions. Inspect `errors_v2.json` for missing pages.

`extract_candidates.py` writes `evidence_candidates.json` and `building_evidence_index.json`. Each candidate sentence is tagged with campus buildings, matched against the OSM list the energy twin uses (`public/models/dartmouth-energy-twin/reports/osm-campus-names.json`), plus an alias table. For each building it records the map `app_id`, the `osm_id` and the `twin_object` name. It is also tagged with dataset projects, technologies, status hints, dates and a `link_confidence`. Each link records a `match_reason` (`exact_name`, `alias`, `project_page`) for review. Run `audit_coverage.py` first so `pages_combined.json` is current.

The extractor also writes `data/energy-evidence.json` at the repo root, a compact copy keyed by map building ID. `/api/buildings` attaches it to each building (`data/attach-energy-evidence.ts`), and the building panel's Energy tab shows it under "Public records". The full refresh is `python scrape_v2.py && python audit_coverage.py && python extract_candidates.py`.

## Data integrity

The extractor creates **unreviewed evidence candidates**, not confirmed building-to-project links. Manually validate project names, actual completion dates, building IDs, network links, and infrastructure geometry before displaying them as facts. Source URLs and excerpts are preserved for review. Coverage cannot be considered exhaustive without reviewing discovered URLs, search/sitemaps, archival sources, and non-HTML interactive maps.
