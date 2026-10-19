"""Produce auditable evidence candidates, NOT verified project claims.

Each candidate sentence is tagged with the campus buildings it names (OSM gazetteer shared with the
energy twin and the map), the dataset projects it names, technology mentions, status hints and dates.
Every link carries how it was made (match_reason) so a reviewer can accept or reject it.
"""
import json,re
from collections import Counter
from pathlib import Path
R=Path(__file__).resolve().parent
O=R/'v2_output';O.mkdir(exist_ok=True)
REPORTS=R.parent/'public/models/dartmouth-energy-twin/reports'

# OSM ways that are the hand-authored buildings in data/buildings.ts (see CURATED_OSM_IDS in data/campus-buildings.ts)
CURATED={'way/295888783':'baker-berry','way/295888784':'baker-berry','way/262924499':'hopkins','way/261796580':'collis','way/262912597':'foco','way/48784540':'dartmouth-hall','way/262950856':'life-sciences'}
# names too generic (or not Dartmouth facilities) to match on their own
SKIP_NAMES={'The Rock','The Pebble','The Lodge','North Hall','Hanover Park','Hanover Court','South Block','Averte','Amarna','Panarchy'}
# alias regex -> OSM building names; source text rarely uses the exact OSM name
ALIASES={
 r'Thompson (?:Ice Hockey )?Arena':['Thompson Arena'],
 r'Hopkins Center|the Hop\b':['Hopkins Center for the Arts'],
 r'Baker-Berry(?: Library)?':['Baker Library','Berry Library'],
 r'Fayerweather(?: Halls?| residence halls?)?':['North Fayerweather Hall','Middle Fayerweather Hall','South Fayerweather Hall'],
 r'Massachusetts Halls?|Mass Row':['North Massachusetts Hall','Middle Massachusetts Hall','South Massachusetts Hall'],
 r'Fairbanks Halls?':['North Fairbanks Hall','South Fairbanks Hall'],
 r'Collis(?: Center)?\b':['Collis Student Center'],
 r'Life Sciences Center':['Class of 1978 Life Sciences Center'],
 r"Foco|'53 Commons":['Class of 1953 Commons'],
 r'Hanover Inn':['Hanover Inn Dartmouth'],
 r'Hood Museum':['Hood Museum of Art'],
 r'Irving Institute for Energy and Society':['Irving Institute'],
 r'(?:central )?heating plant|Heating (?:&|and) Electric Plant|central (?:energy )?plant':['Heating & Electric Plant'],
 r'Alumni Gym\b':['Alumni Gymnasium'],
 r'Rauner (?:Special Collections )?Library':['Webster Hall'],
 r'Sanborn Library':['Sanborn House'],
 r'Leverone(?! Field House)':['Leverone Field House'],
 r'Fairchild(?: Center)?(?! Physical)':['Fairchild Physical Sciences Center'],
 r'Rockefeller Center for Public Policy':['Rockefeller Center'],
 r'Byrne Hall':['Byrne II Hall'],
}
TECH={'steam_to_hot_water':r'steam|hot[- ]water','solar':r'solar|photovoltaic','geoexchange':r'geo-?exchange|geothermal|bore ?(?:field|holes?)|test wells?','heat_pump':r'heat pumps?','chilled_water':r'chilled[- ]water','biomass':r'biomass|wood chips?|renewable natural gas|\bRNG\b','hvac':r'\bHVAC\b|ventilation|air[- ]handl','lighting':r'\bLED\b|\blighting\b','insulation':r'insulat|envelope|windows? replace','heat_recovery':r'heat recovery','electrical':r'substation|electrical (?:service|upgrade|infrastructure)|utilit(?:y|ies)','fuel_oil':r'#6 oil|fuel oil|No\. 6|residual oil','emissions':r'emissions?|carbon|net[- ]zero|greenhouse'}
# buildings named after the organization inside them; only link when the sentence is about the physical building
ORG_NAMES={'Irving Institute','Hopkins Center for the Arts','Hood Museum of Art','Rockefeller Center','Dartmouth Hall','Baker Library','Berry Library','Webster Hall'}
PHYSICAL=re.compile(r'\b(building|facility|renovat\w*|construct\w*|install\w*|upgrad\w*|roof|basement|mechanical|boiler|heated|heating|cooling|HVAC|LEED|square[- ]feet|piping|pipes|retrofit\w*|insulat\w*|windows)\b',re.I)
ENERGY=re.compile(r'\b(steam|hot.water|geo.?exchange|geothermal|solar|heat pumps?|chilled water|district (?:energy|heating)|biomass|energy transition|decarboni\w+|boilers?|utility|utilities|emissions?|retrofit|net.zero|fuel oil|substation|energy)\b',re.I)
WORK=re.compile(r'\b(renovat\w*|construct\w*|install\w*|upgrad\w*|replac\w*|complet\w*|conver\w*|expan\w*|demoli\w*|phase|work)\b',re.I)
STATUS={'completed':r'\b(?:was|were|has been|have been) (?:completed|installed|finished|converted|connected)\b|\bcompleted in\b|\bopened in\b|\bnow (?:heated|served|connected)\b',
 'in_progress':r'\bunderway\b|\b(?:is|are) being\b|\bcurrently\b|\bcontinues?\b|\bongoing\b|\bbegan\b|\bin progress\b',
 'planned':r'\bwill\b|\bplans? to\b|\bplanned\b|\bproposed\b|\banticipated\b|\bexpected to\b|\bscheduled\b|\btarget(?:ed)?\b|\bfuture\b'}
MONTH=r'(?:January|February|March|April|May|June|July|August|September|October|November|December|spring|summer|fall|autumn|winter)'
DATE=re.compile(rf'(?<!Class of )\b(?:{MONTH}(?: of)?,? (?:19|20)\d\d|(?:19|20)\d\d)\b',re.I)

def slugify(s):return re.sub(r'[^a-z0-9]+','-',s.strip().lower()).strip('-') or 'building'
def load_gazetteer():
 osm=json.loads((REPORTS/'osm-campus-names.json').read_text())['buildings']
 twin={m['osmId']:m['newName'] for m in json.loads((REPORTS/'osm-name-matches.json').read_text())['matches'] if m['category']=='building'}
 by_name={}
 for b in osm:
  if not b['hasRealName'] or b['isAddressOnly'] or b['name'] in SKIP_NAMES:continue
  by_name[b['name']]={'name':b['name'],'app_id':CURATED.get(b['osmId'],f"{slugify(b['name'])}-{b['wayId']}"),'osm_id':b['osmId'],'twin_object':twin.get(b['osmId']),'centroid':b.get('centroid')}
 patterns=[(r'\b'+re.escape(n)+r'\b',[n],'exact_name') for n in by_name]
 patterns+=[(p,[n for n in names if n in by_name],'alias') for p,names in ALIASES.items()]
 # longest pattern first so "Baker-Berry Library" wins over "Berry Library"
 return by_name,sorted([(re.compile(p),n,why) for p,n,why in patterns if n],key=lambda x:-len(x[0].pattern))
def match_buildings(sentence,patterns):
 taken=[];found={}
 for rx,names,why in patterns:
  for m in rx.finditer(sentence):
   if any(m.start()<e and s<m.end() for s,e in taken):continue
   taken.append((m.start(),m.end()))
   for n in names:found.setdefault(n,(m.group(0),why))
 return found

by_name,patterns=load_gazetteer()
projects=json.loads((R/'dataset/projects.json').read_text())
dataset_buildings={b['id']:b['name'] for b in json.loads((R/'dataset/buildings.json').read_text())}
proj_rx=[(p['id'],re.compile(r'\b'+re.escape(p['name']).replace(r'\ ',r'\s+')+r'\b',re.I)) for p in projects if p['name']!='Other Capital Projects']
page_projects={}
for p in projects:
 for u in p['source_urls']:
  if '/projects-glance/' in u:page_projects.setdefault(u.rstrip('/'),[]).append(p)

items=[];seen=set()
page_files=[O/'pages_combined.json'] if (O/'pages_combined.json').exists() else [R/'dartmouth_energy_scrape/pages.json',O/'pages_v2.json']
for file in page_files+[O/'documents_v2.json']:
 if not file.exists():continue
 for p in json.loads(file.read_text()):
  url=p['url'];content=p.get('text','')
  pub=re.search(r'/news/(\d{4})/(\d\d)/',url)
  # a project's own page: every sentence on it is about that project and its listed buildings
  ctx_projects=page_projects.get(url.rstrip('/'),[])
  ctx_buildings={}
  for proj in ctx_projects:
   for bid in proj['building_ids']:
    for n,(txt,why) in match_buildings(dataset_buildings.get(bid,''),patterns).items():ctx_buildings[n]=(txt,'project_page')
  for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])',content):
   sentence=re.sub(r'\s+',' ',sentence).strip()
   if len(sentence)<35 or len(sentence)>900:continue
   key=(url,sentence)
   if key in seen:continue
   found=match_buildings(sentence,patterns)
   # a bare "energy" mention next to a building name is not evidence about that building
   if not (WORK.search(sentence) or any(re.search(rx,sentence,re.I) for rx in TECH.values())):found={}
   found={n:v for n,v in found.items() if n not in ORG_NAMES or PHYSICAL.search(sentence)}
   named_projects=[pid for pid,rx in proj_rx if rx.search(sentence)]
   # section menus list every project/building; a sentence naming many of them is navigation, not evidence
   if len(named_projects)>=3 or len(found)>=5 or 'Additional navigation' in sentence:continue
   energy=bool(ENERGY.search(sentence))
   if not (energy or ((found or named_projects) and WORK.search(sentence))):continue
   seen.add(key)
   buildings=[{**{k:by_name[n][k] for k in ('app_id','osm_id','twin_object','name')},'matched_text':txt,'match_reason':why} for n,(txt,why) in found.items()]
   buildings+=[{**{k:by_name[n][k] for k in ('app_id','osm_id','twin_object','name')},'matched_text':txt,'match_reason':why} for n,(txt,why) in ctx_buildings.items() if n not in found]
   proj=[{'project_id':pid,'match_reason':'named_in_sentence'} for pid in named_projects]
   proj+=[{'project_id':x['id'],'match_reason':'project_page'} for x in ctx_projects if x['id'] not in named_projects]
   tech=[k for k,rx in TECH.items() if re.search(rx,sentence,re.I)]
   direct=any(b['match_reason']=='exact_name' for b in buildings) or named_projects
   items.append({'source_url':url,'source_title':p.get('title'),'published':f'{pub.group(1)}-{pub.group(2)}' if pub else None,
    'evidence':sentence,'technologies':tech,'status_hints':[k for k,rx in STATUS.items() if re.search(rx,sentence,re.I)],
    'date_mentions':sorted({m.group(0) for m in DATE.finditer(sentence)}),
    'buildings':buildings,'projects':proj,'building_ids':sorted({b['app_id'] for b in buildings}),'project_ids':sorted({x['project_id'] for x in proj}),
    'link_confidence':'high' if direct and energy else 'medium' if buildings or proj else 'none',
    'verification':'unreviewed'})
(O/'evidence_candidates.json').write_text(json.dumps(items,indent=2,ensure_ascii=False))

# per-building rollup for the map / energy twin
index={}
rank={'high':0,'medium':1,'none':2}
for it in sorted(items,key=lambda x:(rank[x['link_confidence']],-len(x['technologies']))):
 for b in it['buildings']:
  e=index.setdefault(b['app_id'],{**{k:b[k] for k in ('app_id','osm_id','twin_object','name')},'centroid':by_name[b['name']]['centroid'],'candidate_count':0,'technologies':Counter(),'project_ids':set(),'source_urls':set(),'date_mentions':set(),'twin_objects':set(),'top_evidence':[]})
  e['candidate_count']+=1;e['twin_objects'].add(b['twin_object']);e['technologies'].update(it['technologies']);e['project_ids'].update(it['project_ids']);e['source_urls'].add(it['source_url']);e['date_mentions'].update(it['date_mentions'])
  if len(e['top_evidence'])<5:e['top_evidence'].append({k:it[k] for k in ('evidence','source_url','published','technologies','status_hints','link_confidence')}|{'match_reason':b['match_reason']})
rollup=sorted(({**e,'technologies':dict(e['technologies'].most_common()),'project_ids':sorted(e['project_ids']),'source_urls':sorted(e['source_urls']),'twin_objects':sorted(t for t in e['twin_objects'] if t),'date_mentions':sorted(e['date_mentions']),'verification':'unreviewed'} for e in index.values()),key=lambda e:-e['candidate_count'])
(O/'building_evidence_index.json').write_text(json.dumps(rollup,indent=2,ensure_ascii=False))
conf=Counter(x['link_confidence'] for x in items)
print('Evidence candidates:',len(items),'->',O/'evidence_candidates.json')
print(f"  linked to a building: {sum(bool(x['buildings']) for x in items)}; to a project: {sum(bool(x['projects']) for x in items)}; confidence: {dict(conf)}")
print('Buildings with evidence:',len(rollup),'->',O/'building_evidence_index.json')

# compact, app-facing copy keyed by the map's building id (read by data/energy-evidence.ts)
project_names={p['id']:p['name'] for p in projects}
def display(text,limit=320):
 text=re.sub(r'\bImage(?: Image)+\s*|\((?:Photo|Map|Rendering|Video)[^)]*\)\s*','',text).strip()
 return text if len(text)<=limit else text[:limit].rsplit(' ',1)[0]+'…'
app={'generatedAt':__import__('datetime').date.today().isoformat(),'verification':'unreviewed','buildings':{}}
for e in rollup:
 years=sorted({int(y) for d in e['date_mentions'] for y in re.findall(r'(?:19|20)\d\d',d)})
 statuses=Counter(h for ev in e['top_evidence'] for h in ev['status_hints'])
 app['buildings'][e['app_id']]={'name':e['name'],'osmId':e['osm_id'],'twinObjects':e['twin_objects'],
  'candidateCount':e['candidate_count'],'sourceCount':len(e['source_urls']),
  'technologies':[{'id':k,'count':v} for k,v in e['technologies'].items()],
  'projects':[{'id':pid,'name':project_names.get(pid,pid)} for pid in e['project_ids']],
  'yearRange':[years[0],years[-1]] if years else None,
  'statusHints':dict(statuses.most_common()),
  'evidence':[{'text':display(ev['evidence']),'url':ev['source_url'],'published':ev['published'],'confidence':ev['link_confidence'],'technologies':ev['technologies']} for ev in e['top_evidence'][:4]]}
(R.parent/'data/energy-evidence.json').write_text(json.dumps(app,indent=1,ensure_ascii=False))
print('App evidence:',len(app['buildings']),'buildings ->',R.parent/'data/energy-evidence.json')
