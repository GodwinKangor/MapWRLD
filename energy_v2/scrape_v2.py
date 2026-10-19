#!/usr/bin/env python3
"""Respectful, resumable public Dartmouth energy source collector.

Discovery: sitemaps of the seed hosts + links from previously fetched pages + seed queue.
Ordering: a priority queue scored by energy-specific URL/anchor terms, so project and
energy pages are fetched before generic campus pages. Links are only expanded from pages
whose text is actually about energy/infrastructure, which keeps the crawl from drifting.
"""
import argparse, csv, hashlib, heapq, itertools, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
AGENT='MapWRLDResearchBot/0.3 (educational public-data research; contact via project owner)'
SEED_HOSTS=('campus-services.dartmouth.edu','climate.dartmouth.edu','home.dartmouth.edu','www.sustainability.dartmouth.edu','irving.dartmouth.edu','engineering.dartmouth.edu','www.dartmouth.edu')
# (pattern, weight) scored against url path + anchor text
TERMS=[
 (r'steam|hot.?water|geo.?exchange|geothermal|heat.?pump|chilled.?water|district.?(?:energy|heat)|biomass|heating.?plant|power.?plant|boiler|decarboni',5),
 (r'energy|solar|utilit|emission|net.?zero|carbon|thermal|electrif|hvac|retrofit|conversion',3),
 (r'projects?.?glance|project.?management|capital.?project|construction|renovation|renewal|expansion|crosby.?street|thayer.?drive',3),
 (r'sustainab|climate|infrastructure|facilit|operations|progress|plan',1),
]
# campus operations sites describe the physical projects; research institutes mostly cover energy policy/academics
HOST_BONUS={'campus-services.dartmouth.edu':3,'climate.dartmouth.edu':2,'home.dartmouth.edu':1,'irving.dartmouth.edu':-3,'engineering.dartmouth.edu':-3,'tuck.dartmouth.edu':-3}
# pages that matched loose keywords in v1 but never carry project/infrastructure data
DENY=re.compile(r'/(?:people|profiles?|directory|user|login|register|apply|admissions?|giving|calendar|taxonomy|tag|search|class-20\d\d-profiles|careers?|alumni-careers|mentorship|info-sessions|career-treks|faculty|courses?-curriculum|frequently-asked-questions)(?:/|$)|/education/|master-energy-transition|/mba|/node/\d+$',re.I)
DENY_HOSTS=('apply.gs.dartmouth.edu','admissions.dartmouth.edu','graduate.dartmouth.edu','giving.dartmouth.edu')
TEXT_TERMS=re.compile(r'\b(steam|hot[- ]water|geo-?exchange|geothermal|heat pumps?|chilled water|district energy|biomass|heating plant|energy transition|decarboni[sz]\w*|solar|boilers?|emissions|retrofit|utility|utilities|kilowatt|MW|MMBtu|construction)\b',re.I)
SKIP_EXT=re.compile(r'\.(?:zip|docx?|xlsx?|pptx?|mp[34]|mov|jpe?g|png|gif|svg|webp|ics|css|js)(?:$|\?)',re.I)

def eligible(url):
 p=urlparse(url);h=p.hostname or ''
 return p.scheme=='https' and (h=='dartmouth.edu' or h.endswith('.dartmouth.edu')) and h not in DENY_HOSTS and not SKIP_EXT.search(p.path)
def normalize(url):
 url=urldefrag(url.strip())[0]
 p=urlparse(url)
 if p.scheme=='http':p=p._replace(scheme='https')
 # keep pagination so listing pages beyond the first are reachable; drop tracking params
 q=[(k,v) for k,v in parse_qsl(p.query) if k=='page' or 'search' in p.path]
 return p._replace(query=urlencode(q)).geturl().rstrip('/')
def url_score(url,label=''):
 if DENY.search(urlparse(url).path):return 0
 s=(urlparse(url).path+' '+label).lower().replace('_','-')
 score=sum(w for pat,w in TERMS if re.search(pat,s))
 if urlparse(url).path.lower().endswith('.pdf'):score+=2
 if re.search(r'[?&]page=\d',url):score+=2
 return score+HOST_BONUS.get(urlparse(url).hostname,0) if score else 0
def news_key(url):
 # home.dartmouth.edu news is syndicated onto other subsites under the same /news/YYYY/MM/slug path
 m=re.search(r'/news/(\d{4}/\d\d/[^/]+)',urlparse(url).path)
 return m.group(1) if m else None
def text_score(text):
 return len({m.lower() for m in TEXT_TERMS.findall(text)})
def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False));tmp.replace(path)
def load(path,default):
 return json.loads(path.read_text()) if path.exists() else default

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--max-pages',type=int,default=400)
 ap.add_argument('--delay',type=float,default=1.5)
 ap.add_argument('--max-depth',type=int,default=4)
 ap.add_argument('--min-score',type=int,default=3,help='minimum url/anchor score to enqueue a link')
 ap.add_argument('--no-sitemaps',action='store_true')
 args=ap.parse_args()
 out=ROOT/'v2_output';out.mkdir(exist_ok=True)
 pages_file=out/'pages_v2.json'; docs_file=out/'documents_v2.json'; errors_file=out/'errors_v2.json'; state_file=out/'crawl_state.json'
 pages=load(pages_file,[]); docs=load(docs_file,[]); errors=load(errors_file,[])
 existing=load(ROOT/'dartmouth_energy_scrape/pages.json',[])
 seen={normalize(x['url']) for x in pages+docs+existing}
 text_hashes={hashlib.sha256(x.get('text','').encode()).hexdigest() for x in pages if x.get('text')}
 news_seen={news_key(x['url']) for x in pages+docs+existing}-{None}
 session=requests.Session();session.headers.update({'User-Agent':AGENT})
 robots={};last={};queued={};heap=[];tie=itertools.count()
 sitemap_urls={}  # url -> lastmod, all sitemap entries (used for relevance + stale-URL recovery)

 def push(u,depth,parents,score=None,label=''):
  u=normalize(u)
  if not eligible(u) or u in seen or depth>args.max_depth:return
  score=url_score(u,label) if score is None else score
  if score<args.min_score:return
  if queued.get(u,-1)>=score:return
  queued[u]=score;heapq.heappush(heap,(-score,depth,next(tie),u,parents))

 def throttle(host):
  wait=args.delay-(time.monotonic()-last.get(host,0))
  if wait>0:time.sleep(wait)
  last[host]=time.monotonic()

 def robots_for(base):
  if base in robots:return robots[base]
  r=RobotFileParser();r.set_url(base+'/robots.txt');throttle(urlparse(base).netloc)
  try:
   resp=session.get(r.url,timeout=25)
   if resp.status_code in (404,410):r.parse([]);robots[base]=(r,'')       # no robots.txt => allowed (RFC 9309)
   elif resp.ok and 'cloudflare' not in resp.text[:2000].lower():r.parse(resp.text.splitlines());robots[base]=(r,resp.text)
   else:robots[base]=(None,f'robots.txt returned HTTP {resp.status_code} at {resp.url}')
  except requests.RequestException as e:robots[base]=(None,f'robots.txt unreachable: {e}')
  return robots[base]

 def fetch_sitemap(url,depth=0):
  if depth>2:return
  throttle(urlparse(url).netloc)
  try:
   resp=session.get(url,timeout=30)
   if not resp.ok or '<' not in resp.text[:200]:return
  except requests.RequestException:return
  body=resp.text
  if '<sitemapindex' in body:
   for loc in re.findall(r'<sitemap>\s*<loc>([^<]+)</loc>',body):fetch_sitemap(loc.strip().replace('&amp;','&'),depth+1)
  else:
   for block in re.findall(r'<url>(.*?)</url>',body,re.S):
    loc=re.search(r'<loc>([^<]+)</loc>',block);mod=re.search(r'<lastmod>([^<]+)</lastmod>',block)
    if loc:sitemap_urls[normalize(loc.group(1).replace('&amp;','&'))]=mod.group(1) if mod else None

 # 1. sitemaps
 if not args.no_sitemaps:
  for host in SEED_HOSTS:
   base=f'https://{host}';rp,txt=robots_for(base)
   if rp is None:print('skip host:',host,txt);continue
   maps=re.findall(r'(?im)^\s*sitemap:\s*(\S+)',txt) or [base+'/sitemap.xml']
   before=len(sitemap_urls)
   for m in maps:fetch_sitemap(m)
   print(f'sitemap {host}: {len(sitemap_urls)-before} urls')
  for u in sitemap_urls:push(u,0,['sitemap'])
 # 2. seed queue, previous run's leftovers, and links from everything already fetched
 for x in load(ROOT/'dataset/next_crawl_queue.json',[]):push(x['url'],0,x.get('linked_from',[]),score=max(url_score(x['url']),args.min_score))
 for x in load(state_file,{}).get('remaining_queue',[]):push(x['url'],x.get('depth',1),x.get('linked_from',[]))
 for x in existing+pages:
  for link in x.get('links',[]):
   u=link.get('url','') if isinstance(link,dict) else str(link)
   push(u,1,[x['url']],label=link.get('anchor_text','') if isinstance(link,dict) else '')
 if (ROOT/'dartmouth_energy_scrape/links.csv').exists():
  with (ROOT/'dartmouth_energy_scrape/links.csv').open() as f:
   for link in csv.DictReader(f):push(link['target_url'],1,[link['source_url']],label=link['label'])
 print('initial queue:',len(heap))

 # slug -> sitemap urls, so stale links (pages that moved in a site migration) can be recovered
 by_slug={}
 for u in sitemap_urls:by_slug.setdefault(urlparse(u).path.rstrip('/').rsplit('/',1)[-1],[]).append(u)
 count=0;dupes=0
 while heap and count<args.max_pages:
  negscore,depth,_,url,parents=heapq.heappop(heap)
  if url in seen:continue
  seen.add(url)
  if news_key(url) in news_seen:dupes+=1;continue
  base=f'https://{urlparse(url).netloc}';rp,why=robots_for(base)
  if rp is None:errors.append({'url':url,'reason':why});continue
  if not rp.can_fetch(AGENT,url):errors.append({'url':url,'reason':'disallowed by robots.txt'});continue
  throttle(urlparse(url).netloc)
  try:
   resp=session.get(url,timeout=25,allow_redirects=True)
   if resp.status_code==404:
    slug=urlparse(url).path.rstrip('/').rsplit('/',1)[-1]
    moved=[u for u in by_slug.get(slug,[]) if u not in seen]
    for u in moved:push(u,depth,parents+[url],score=-negscore)
    errors.append({'url':url,'reason':'404 Not Found'+(f'; relocated candidates queued: {moved}' if moved else '')});continue
   resp.raise_for_status()
   final=normalize(resp.url)
   if not eligible(final):continue
   if final!=url:
    if final in seen:continue
    seen.add(final)
   ctype=resp.headers.get('Content-Type','').lower()
   meta={'url':final,'linked_from':parents,'fetched_at':datetime.now(timezone.utc).isoformat(),'content_type':ctype,'sha256':hashlib.sha256(resp.content).hexdigest(),'priority':-negscore,'depth':depth}
   if final in sitemap_urls:meta['sitemap_lastmod']=sitemap_urls[final]
   if 'pdf' in ctype or final.lower().endswith('.pdf'):
    filename=hashlib.sha256(final.encode()).hexdigest()[:18]+'.pdf';(out/'pdfs').mkdir(exist_ok=True)
    (out/'pdfs'/filename).write_bytes(resp.content)
    meta['file']='pdfs/'+filename;meta['text']=''
    try:
     import fitz
     with fitz.open(stream=resp.content,filetype='pdf') as pdf:meta['text']='\n'.join(page.get_text() for page in pdf)
    except ImportError:meta['extraction_note']='Install pymupdf to extract PDF text'
    meta['relevance']=text_score(meta['text'])
    docs.append(meta)
   elif 'html' in ctype:
    soup=BeautifulSoup(resp.text,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    # collect links from the whole page first: Drupal section menus/sidebars list the project pages
    links=[];link_seen=set()
    for a in soup.find_all('a',href=True):
     u=normalize(urljoin(final,a['href'].strip()));label=a.get_text(' ',strip=True)
     if eligible(u) and u not in link_seen:link_seen.add(u);links.append({'url':u,'anchor_text':label})
    for tag in soup(['script','style','nav','footer','header','noscript']):tag.decompose()
    main=soup.find('main') or soup.find('article') or soup.body or soup
    text=main.get_text(' ',strip=True)
    th=hashlib.sha256(text.encode()).hexdigest()
    if th in text_hashes:dupes+=1;print('  duplicate content, skipped:',final);continue
    text_hashes.add(th);news_seen.add(news_key(final))
    rel=text_score(text)
    meta.update({'title':title,'text':text,'links':links,'relevance':rel})
    pages.append(meta)
    # only expand from pages that are actually about energy/infrastructure, or are strong hubs
    if rel>=2 or -negscore>=5:
     bonus=min(rel,4)//2
     for l in links:
      s=url_score(l['url'],l['anchor_text'])
      if s:push(l['url'],depth+1,[final],score=s+bonus,label=l['anchor_text'])
   else:continue
   count+=1;print(count,f'[p{-negscore} r{meta.get("relevance",0)}]',final)
   if count%10==0:save(pages_file,pages);save(docs_file,docs);save(errors_file,errors)
  except requests.RequestException as e:
   errors.append({'url':url,'reason':str(e)})
 save(pages_file,pages);save(docs_file,docs);save(errors_file,errors)
 remaining=sorted(((-n,u,d,p) for n,d,_,u,p in heap if u not in seen),reverse=True)
 save(state_file,{'fetched_this_run':count,'duplicates_skipped':dupes,'sitemap_urls_found':len(sitemap_urls),'limit_reached':bool(remaining and count>=args.max_pages),'remaining_queue':[{'url':u,'score':s,'depth':d,'linked_from':p} for s,u,d,p in remaining],'max_pages':args.max_pages,'max_depth':args.max_depth,'min_score':args.min_score})
 print(f'Fetched this run: {count}; total pages: {len(pages)}; PDFs: {len(docs)}; errors: {len(errors)}; duplicates skipped: {dupes}; still queued: {len(remaining)}')
if __name__=='__main__':main()
