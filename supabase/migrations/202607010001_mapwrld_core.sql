create table if not exists public.buildings (
  id text primary key,
  name text not null,
  short_code text not null,
  category text not null,
  subtitle text not null default '',
  description text not null default '',
  longitude double precision not null,
  latitude double precision not null,
  is_open boolean not null default false,
  hours_summary text not null default '',
  image_class text not null default 'building',
  features text[] not null default '{}',
  gallery_labels text[] not null default '{}',
  model_status text not null default 'Queued' check (model_status in ('Queued', 'In progress', 'Ready', 'Needs review')),
  meter_status text not null default 'Missing' check (meter_status in ('Missing', 'Estimated', 'Connected')),
  data_quality text not null default 'Draft' check (data_quality in ('Draft', 'Field check', 'Verified')),
  asset_priority text not null default 'Medium' check (asset_priority in ('Low', 'Medium', 'High')),
  last_inspection text not null default 'Needs visit',
  next_step text not null default 'Add model and meter metadata',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.entrances (
  id text primary key,
  building_id text not null references public.buildings(id) on delete cascade,
  label text not null,
  kind text not null check (kind in ('main', 'accessible', 'exit')),
  longitude double precision not null,
  latitude double precision not null,
  approach_longitude double precision not null,
  approach_latitude double precision not null,
  heading double precision not null default 0,
  is_primary boolean not null default false,
  verified boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists one_primary_entrance_per_building
  on public.entrances(building_id) where is_primary;
create index if not exists entrances_building_id_idx on public.entrances(building_id);

create table if not exists public.building_media (
  id bigint generated always as identity primary key,
  building_id text not null references public.buildings(id) on delete cascade,
  entrance_id text references public.entrances(id) on delete set null,
  media_type text not null check (media_type in ('image', 'panorama', 'video')),
  storage_path text,
  external_url text,
  caption text not null default '',
  alt_text text not null default '',
  attribution text,
  sort_order integer not null default 0,
  is_published boolean not null default false,
  created_at timestamptz not null default now(),
  check (storage_path is not null or external_url is not null)
);
create index if not exists building_media_building_id_idx on public.building_media(building_id);

alter table public.buildings enable row level security;
alter table public.entrances enable row level security;
alter table public.building_media enable row level security;

drop policy if exists "Public buildings are readable" on public.buildings;
create policy "Public buildings are readable" on public.buildings for select using (true);
drop policy if exists "Public entrances are readable" on public.entrances;
create policy "Public entrances are readable" on public.entrances for select using (true);
drop policy if exists "Published media is readable" on public.building_media;
create policy "Published media is readable" on public.building_media for select using (is_published);

insert into public.buildings (id,name,short_code,category,subtitle,description,longitude,latitude,is_open,hours_summary,image_class,features,gallery_labels,model_status,meter_status,data_quality,asset_priority,last_inspection,next_step) values
('baker-berry','Baker-Berry Library','BB','Study','The heart of scholarship on campus','Dartmouth''s iconic library brings historic architecture and bright, modern study spaces together under one clock tower.',-72.28913,43.70535,true,'Open until 2:00 AM','baker',array['Accessible entrance','Quiet floors','Café','Printers'],array['The Tower Room','Berry Main Street','Orozco Murals'],'In progress','Estimated','Field check','High','2026-07-14','Replace placeholder tower mass with optimized GLB'),
('hopkins','Hopkins Center for the Arts','HOP','Arts','Performance, film, music, and making','Known simply as the Hop, this is Dartmouth''s creative crossroads—home to performances, studios, galleries, and spontaneous encounters.',-72.28858,43.70187,true,'Open until 11:00 PM','hop',array['Wheelchair access','Box office','Gallery','Restrooms'],array['Top of the Hop','The Moore Theater','Jewelry Studio'],'Queued','Estimated','Draft','Medium','Needs visit','Confirm roofline and theater volume before export'),
('collis','Collis Center','COL','Campus life','Dartmouth''s student living room','A warm, lively center for food, student organizations, gatherings, and the everyday rhythm of campus life.',-72.2899353,43.7027887,true,'Open until 1:00 AM','collis',array['Elevator','Dining','Study space','Gender-neutral restroom'],array['Common Ground','Collis Café','Student Involvement'],'Needs review','Estimated','Field check','Medium','2026-07-13','Check entrances and service-side geometry'),
('foco','Class of 1953 Commons','53','Dining','Campus dining with something for everyone','Dartmouth''s main dining hall offers a wide variety of stations and a sociable gathering space overlooking the heart of campus.',-72.29044,43.70456,true,'Open until 8:30 PM','foco',array['Accessible entrance','Vegan options','Allergen station','Seating'],array['The Hearth','Main Dining Hall','Courtyard'],'Queued','Estimated','Draft','High','Needs visit','Capture dining/service massing for the first model pass'),
('dartmouth-hall','Dartmouth Hall','DH','History','A campus landmark since 1784','The beloved white-columned landmark anchors the east side of the Green and houses language and humanities classrooms.',-72.28658,43.70371,false,'Opens tomorrow at 8:00 AM','dartmouth',array['Historic building','Classrooms','Accessible entrance','Restrooms'],array['Front Portico','Language Commons','The Green View'],'In progress','Estimated','Field check','High','2026-07-14','Preserve front facade proportions in GLB export'),
('life-sciences','Class of 1978 Life Sciences','LSC','Study','Research inspired by the natural world','A modern, high-performance research building with expansive lab spaces and a greenhouse overlooking the north campus.',-72.28578,43.70887,true,'Open until 10:00 PM','lsc',array['LEED Platinum','Accessible entrance','Greenhouse','Study nooks'],array['Atrium','Greenhouse','Teaching Lab'],'Queued','Estimated','Draft','High','Needs visit','Include north-campus lab massing and greenhouse zone')
on conflict (id) do update set name=excluded.name, updated_at=now();

insert into public.entrances (id,building_id,label,kind,longitude,latitude,approach_longitude,approach_latitude,heading,is_primary) values
('baker-berry-main','baker-berry','Green-facing main entrance','main',-72.28912,43.70491,-72.28912,43.70434,0,true),
('hopkins-main','hopkins','Hop plaza entrance','main',-72.28855,43.70212,-72.28854,43.70258,180,true),
('collis-north-main','collis','North main entrance','main',-72.28995,43.70299,-72.28995,43.70340,180,true),
('collis-east-accessible','collis','Main Street accessible entrance','accessible',-72.28969,43.70279,-72.28930,43.70279,270,false),
('collis-south-exit','collis','South exit','exit',-72.28995,43.70258,-72.28995,43.70225,0,false),
('collis-west-exit','collis','West exit','exit',-72.29023,43.70276,-72.29058,43.70276,90,false),
('foco-main','foco','Massachusetts Row entrance','main',-72.29003,43.70442,-72.28950,43.70442,270,true),
('dartmouth-hall-main','dartmouth-hall','Front portico entrance','main',-72.28687,43.70371,-72.28743,43.70370,90,true),
('life-sciences-main','life-sciences','South atrium entrance','main',-72.28605,43.70854,-72.28632,43.70814,34,true)
on conflict (id) do update set label=excluded.label, longitude=excluded.longitude, latitude=excluded.latitude, updated_at=now();
