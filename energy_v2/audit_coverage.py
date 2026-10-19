"""Build a reproducible coverage audit; keyword hits are discovery evidence only."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'v2_output'

def read(path):
    return json.loads(path.read_text()) if path.exists() else []

old = read(ROOT / 'dartmouth_energy_scrape/pages.json')
new = read(OUT / 'pages_v2.json')
docs = read(OUT / 'documents_v2.json')
by_url = {p['url'].strip().rstrip('/'): p for p in old + new}
pages = list(by_url.values())
(OUT / 'pages_combined.json').write_text(json.dumps(pages, indent=2, ensure_ascii=False))
items = pages + docs
areas = [
    ('Energy Transition', r'energy transition|energy renewal|decarbon|geo.exchange',
     'Goals, funding, technologies, plans and progress statements appear in collected pages.',
     'Complete progress-report series and milestone history are not established.'),
    ('Ongoing projects', r'currently happening|in progress|under construction|construction is underway',
     'Project pages contain descriptions, goals, work updates and some timing statements.',
     'Affected buildings, phases and estimated completion have not been consistently extracted or verified.'),
    ('Completed projects', r'completed|completion|project is complete',
     'Collected pages include completion statements and historical construction summaries.',
     'Actual completion dates, installed technologies and measured outcomes need project-by-project review.'),
    ('Planned projects', r'planned|anticipated|scheduled|future|will convert',
     'Future work and anticipated timing are described in project and energy pages.',
     'A complete inventory of planned conversions and expansions is not established.'),
    ('Campus buildings', r'building|hall|arena|field house|athletic center',
     'Building names and selected energy-system improvements appear in source text.',
     'No complete building inventory, coordinates or current heating/cooling system register was produced.'),
    ('Infrastructure', r'hot.water|steam|geo.exchange|geothermal|solar|distribution pip|borefield',
     'Network and technology descriptions were collected.',
     'Locations, installed-versus-planned status and network geometry remain incomplete.'),
    ('Historical records', r'\b20(?:0\d|1\d|2[0-5])\b',
     'Linked news articles and historical summaries extend the original two-domain crawl.',
     'Archives, sitemaps and historical progress-report series were not exhaustively searched.'),
    ('Documentation', r'.',
     'HTML text, source links and fetched PDFs are saved; available PDF text is extracted.',
     'Photographs and diagrams were not downloaded. Interactive maps were not extracted. PDF discovery is bounded.'),
]
audit = []
for name, pattern, captured, missing in areas:
    matches = [p for p in items if re.search(pattern, p.get('text', ''), re.I)]
    if name == 'Historical records':
        matches = [p for p in matches if '/news/' in p['url'] or 'other-capital-projects' in p['url']]
    samples = []
    for p in matches[:8]:
        match = re.search(pattern, p.get('text', ''), re.I)
        text = p.get('text', '')
        samples.append({'url': p['url'], 'title': p.get('title'),
                        'excerpt': text[max(0, match.start()-100):match.end()+350]})
    audit.append({'area': name, 'coverage': 'partial', 'keyword_candidate_sources': len(matches),
                  'captured': captured, 'missing': missing, 'sample_sources': samples})

errors = read(OUT / 'errors_v2.json')
state = read(OUT / 'crawl_state.json')
pdf_no_text = [p['url'] for p in docs if not p.get('text', '').strip()]
summary = {'original_html_records': len(old), 'v2_html_records': len(new),
           'combined_unique_html_urls': len(pages), 'pdf_records': len(docs),
           'pdfs_with_text': len(docs)-len(pdf_no_text), 'pdfs_without_text': pdf_no_text,
           'v2_errors': len(errors), 'crawl_state': state,
           'verification': 'Unreviewed sources and keyword candidates; not an exhaustive inventory.',
           'areas': audit}
(OUT / 'coverage_audit.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
with (OUT / 'sources_combined.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['url', 'title', 'type', 'retrieved_at', 'file'])
    writer.writeheader()
    for p in items:
        writer.writerow({'url': p['url'], 'title': p.get('title', ''),
                         'type': 'pdf' if p in docs else 'html',
                         'retrieved_at': p.get('fetched_at', p.get('checked_at', '')),
                         'file': p.get('file', '')})
report = ['# Dartmouth energy collection coverage', '',
          f"Collected {len(pages)} unique HTML URLs (including the original {len(old)} records) and {len(docs)} PDFs. V2 recorded {len(errors)} failed/skipped URLs.", '',
          'All eight areas remain partially covered. Counts below are keyword discovery candidates, not validated facts. Distinct URLs can contain duplicate content after site migrations.', '',
          '| Area | Captured | Still missing |', '| --- | --- | --- |']
for area in audit:
    report.append(f"| {area['area']} | {area['captured']} | {area['missing']} |")
report += ['', '## Collection limits', '',
           'HTTPS Dartmouth domains only; relevant links only; depth capped at 3; at most 250 successful responses in this run. No exhaustive sitemap or archive search. Images and non-Dartmouth interactive maps are excluded.', '',
           f"Successful-response limit reached: {state.get('limit_reached', 'unknown')}.", '',
           'The bundled dataset/projects.json, buildings.json and connections.json remain the supplied first-pass dataset. They were not refreshed or verified by this crawl.', '',
           '## Failed/skipped URLs', '']
for error in errors:
    report.append(f"- {error['url']}: {error['reason']}")
(OUT / 'coverage_report.md').write_text('\n'.join(report) + '\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('areas','crawl_state')}, indent=2))
