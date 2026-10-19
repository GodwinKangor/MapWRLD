"""Public Dartmouth energy/construction page discovery and extraction.
Run: pip install requests beautifulsoup4 && python scrape.py
Respect robots.txt, throttle requests, and review output before treating as facts.
"""
import csv, json, re, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
SEEDS = [
 'https://climate.dartmouth.edu/operational-goals/energy-transition',
 'https://campus-services.dartmouth.edu/construction-campus/projects-glance',
 'https://campus-services.dartmouth.edu/construction-campus',
]
ALLOWED = {'climate.dartmouth.edu', 'campus-services.dartmouth.edu'}
KEYWORDS = ('energy', 'transition', 'steam', 'hot-water', 'construction', 'projects-glance', 'solar', 'geothermal', 'renewal', 'building', 'heating', 'cooling', 'sustainab')
MAX_PAGES = 300
DELAY = 1.5
AGENT = 'MapWRLDResearchBot/0.1 (educational research; respectful crawling)'
session = requests.Session(); session.headers.update({'User-Agent': AGENT})
robots = {}
def allowed(url):
 p=urlparse(url)
 if p.scheme not in ('http','https') or p.hostname not in ALLOWED: return False
 if p.hostname not in robots:
  rp=RobotFileParser(); rp.set_url(f'{p.scheme}://{p.hostname}/robots.txt')
  try:
   response=session.get(rp.url,timeout=25)
   response.raise_for_status()
   rp.parse(response.text.splitlines())
  except requests.RequestException as exc:
   print(f'Robots check failed for {p.hostname}: {exc}',flush=True)
   return False  # fail closed
  robots[p.hostname]=rp
 return robots[p.hostname].can_fetch(AGENT,url)
def clean(url):
 url=urldefrag(url.strip())[0]; p=urlparse(url)
 return p._replace(query='',fragment='').geturl().rstrip('/')
def relevant(url, label=''):
 return any(k in (url+' '+label).lower() for k in KEYWORDS)

def run():
 q=deque((clean(x),0) for x in SEEDS); seen=set(); pages=[]; links=[]; errors=[]
 while q and len(seen)<MAX_PAGES:
  url,depth=q.popleft()
  if url in seen: continue
  seen.add(url)
  if not allowed(url): errors.append({'url':url,'reason':'robots_or_access_denied'}); continue
  try:
   r=session.get(url,timeout=25); r.raise_for_status()
   if 'text/html' not in r.headers.get('content-type',''): continue
   soup=BeautifulSoup(r.text,'html.parser')
   for t in soup(['script','style','nav','footer','header']):t.decompose()
   main=soup.find('main') or soup.find('article') or soup
   title=(soup.title.get_text(' ',strip=True) if soup.title else '')
   text=main.get_text(' ',strip=True)
   pages.append({'url':url,'title':title,'text':text,'checked_at':datetime.now(timezone.utc).isoformat(),'depth':depth})
   for a in main.select('a[href]'):
    target=clean(urljoin(url,a['href'].strip())); label=a.get_text(' ',strip=True)
    links.append({'source_url':url,'target_url':target,'label':label})
    if target not in seen and urlparse(target).hostname in ALLOWED and (depth<2 or relevant(target,label)):
     if relevant(target,label): q.append((target,depth+1))
   print(len(pages),url)
  except requests.RequestException as exc: errors.append({'url':url,'reason':str(exc)})
  time.sleep(DELAY)
 (ROOT/'pages.json').write_text(json.dumps(pages,indent=2,ensure_ascii=False))
 (ROOT/'errors.json').write_text(json.dumps(errors,indent=2))
 for name,rows in [('links.csv',links),('pages.csv',[{k:v for k,v in p.items() if k!='text'} for p in pages])]:
  with (ROOT/name).open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=(list(rows[0]) if rows else ['url']))
   writer.writeheader();writer.writerows(rows)
 print(f'Done: {len(pages)} pages; {len(errors)} skipped/failed. Inspect pages.json before extracting project claims.')
if __name__=='__main__':run()
