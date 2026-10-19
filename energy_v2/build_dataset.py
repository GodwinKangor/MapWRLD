import csv,json,re,collections,pathlib,urllib.parse,datetime
root=pathlib.Path(__file__).parent
src=root/'dartmouth_energy_scrape'; out=root/'dataset';out.mkdir(exist_ok=True)
pages=json.loads((src/'pages.json').read_text()); seeds=json.loads((src/'seed_projects.json').read_text())['projects']; byurl={p['url']:p for p in pages}
links=list(csv.DictReader(open(src/'links.csv')))
def slug(s):return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')
def evidence(text,words):
 sentences=re.split(r'(?<=[.!?])\s+',text)
 return [s.strip()[:550] for s in sentences if any(re.search(r'\b'+re.escape(w)+r'\b',s,re.I) for w in words)][:14]
tech={'steam_to_hot_water':['steam','hot water','hot-water'],'solar':['solar','photovoltaic'],'geoexchange':['geo-exchange','geothermal','borefield'],'hvac':['hvac','ventilation','air handling'],'heat_pump':['heat pump'],'lighting':['lighting','LED'],'insulation':['insulation'],'chilled_water':['chilled water','chilled-water'],'heat_recovery':['heat recovery']}
projects=[]; buildings={};connections=[]; sources=[]
for p in pages:
 sources.append({'id':'source-'+slug(urllib.parse.urlparse(p['url']).path or 'root'),'url':p['url'],'title':p.get('title'),'type':'webpage','retrieved_from':'uploaded_crawl','publication_date':None})
for p in pages:
 url=p['url']; path=urllib.parse.urlparse(url).path
 if '/projects-glance/' not in path:continue
 name=p['title'].split(' | ')[0].strip(); pid='project-'+slug(name)
 found=[k for k,words in tech.items() if any(w.lower() in p['text'].lower() for w in words)]
 matches=[s for s in seeds if slug(s['name'])==slug(name) or (slug(s['name'])=='thompson-arena' and 'thompson' in name.lower())]
 status=matches[0].get('directory_status') if matches else 'unclassified'
 ev=evidence(p['text'],['steam','hot water','solar','energy','heating','cooling','piping','thermal','construction','complete','anticipated','scheduled'])
 building_ids=[]
 for b in (matches[0].get('buildings',[]) if matches else []):
  bid='building-'+slug(b);building_ids.append(bid)
  buildings.setdefault(bid,{'id':bid,'name':b,'coordinates':None,'energy_system':None,'verification':'mentioned_in_seed_directory','source_urls':[url]})
 projects.append({'id':pid,'name':name,'category':'campus_construction','directory_status':status,'actual_status':'unverified','building_ids':building_ids,'technology_mentions':found,'start_date':None,'expected_completion':None,'actual_completion':None,'source_urls':[url],'evidence_excerpts':ev,'review_required':True})
 for bid in building_ids:connections.append({'project_id':pid,'building_id':bid,'relationship':'listed_building','source_url':url,'verification':'seed_mapping_needs_review'})
# Preserve seeds not mapped to project detail pages
for s in seeds:
 if not any(slug(s['name'])==slug(p['name']) or (slug(s['name'])=='thompson-arena' and 'thompson' in p['name'].lower()) for p in projects):
  projects.append({'id':'project-'+slug(s['name']),'name':s['name'],'category':s.get('category'),'directory_status':s.get('directory_status'),'actual_status':'unverified','building_ids':[],'technology_mentions':[],'start_date':None,'expected_completion':None,'actual_completion':None,'source_urls':[ 'https://campus-services.dartmouth.edu/construction-campus/projects-glance'],'evidence_excerpts':[],'review_required':True})
allowed=('dartmouth.edu',)
candidates={}
for l in links:
 u=l['target_url'];host=urllib.parse.urlparse(u).hostname or ''
 if u in byurl or not host.endswith('dartmouth.edu'):continue
 score=sum(w in (u+' '+l['label']).lower() for w in ['energy','climate','construction','renew','heat','building','sustain','solar','project','campus','utility','carbon','geo'])
 if score:
  d=candidates.setdefault(u,{'url':u,'anchor_text':l['label'],'linked_from':set(),'relevance_score':score});d['linked_from'].add(l['source_url']);d['relevance_score']=max(score,d['relevance_score'])
queue=sorted([{**v,'linked_from':sorted(v['linked_from'])} for v in candidates.values()],key=lambda x:-x['relevance_score'])
for name,data in [('projects.json',projects),('buildings.json',list(buildings.values())),('connections.json',connections),('sources.json',sources),('next_crawl_queue.json',queue),('coverage.json',{'pages_scraped':len(pages),'project_records':len(projects),'buildings_seeded':len(buildings),'links_discovered':len(links),'relevant_uncrawled_dartmouth_links':len(queue),'limitations':['No fresh website requests performed in this pass','Project dates and actual status not verified','Technology mentions are keyword matches, not confirmed installations','Building list is incomplete','PDFs and images not extracted']})]:
 (out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False))
print('pages',len(pages),'projects',len(projects),'buildings',len(buildings),'queue',len(queue))
