-- Field capture coordinator (see docs/field-capture/SPEC.md and lib/field/state.ts).
-- Every table is private: RLS is enabled with NO policies, so only the service role
-- (used server-side by Next.js API routes) can read or write. Phones and the Mac
-- worker never hold Supabase keys; they authenticate to the API with hashed bearer tokens.
-- Status: written to mirror lib/field/fs-repo.ts; NOT yet run against a Supabase project.

create table if not exists public.field_devices (
  id text primary key,
  label text not null,
  token_hash text not null unique,
  revoked boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.field_workers (
  id text primary key,
  label text not null,
  token_hash text not null unique,
  revoked boolean not null default false,
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.field_sessions (
  id text primary key default encode(gen_random_bytes(16), 'hex'),
  device_id text not null references public.field_devices(id),
  client_session_id text not null,
  building_id text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  unique (device_id, client_session_id)
);

create table if not exists public.field_captures (
  id text primary key,                         -- client UUID: idempotency key
  session_id text not null references public.field_sessions(id),
  device_id text not null references public.field_devices(id),
  building_id text not null,
  surface_ids text[] not null,
  image_sha256 text not null,
  files jsonb not null,                        -- [{name, sha256, bytes, contentType, storagePath, stored}]
  metadata jsonb not null,                     -- capture.json
  state text not null check (state in ('registered','uploaded','processing','processed','failed','reviewed')),
  duplicate_of text references public.field_captures(id),
  error text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists field_captures_building_idx on public.field_captures(building_id);
create index if not exists field_captures_surface_idx on public.field_captures using gin(surface_ids);
create index if not exists field_captures_sha_idx on public.field_captures(building_id, image_sha256);

create table if not exists public.field_jobs (
  id text primary key default encode(gen_random_bytes(16), 'hex'),
  kind text not null default 'surface-texture',
  building_id text not null,
  surface_id text not null,
  capture_ids text[] not null default '{}',
  state text not null check (state in ('queued','leased','succeeded','failed')),
  attempts int not null default 0,
  max_attempts int not null default 3,
  worker_id text references public.field_workers(id),
  lease_token text,
  lease_expires_at timestamptz,
  progress jsonb,
  error text,
  result_prefix text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- at most one queued job per surface (coalescing)
create unique index if not exists field_jobs_one_queued on public.field_jobs(building_id, surface_id) where state = 'queued';
create index if not exists field_jobs_queue_idx on public.field_jobs(state, created_at);

create table if not exists public.field_surfaces (
  building_id text not null,
  surface_id text not null,
  rerun_requested boolean not null default false,
  latest jsonb,
  review jsonb,
  primary key (building_id, surface_id)
);

alter table public.field_devices enable row level security;
alter table public.field_workers enable row level security;
alter table public.field_sessions enable row level security;
alter table public.field_captures enable row level security;
alter table public.field_jobs enable row level security;
alter table public.field_surfaces enable row level security;

-- private bucket for originals and results; access only through signed URLs minted server-side
insert into storage.buckets (id, name, public) values ('field-captures', 'field-captures', false)
on conflict (id) do nothing;

-- queue (or coalesce) a job for one surface
create or replace function public.field_enqueue(p_building text, p_surface text) returns void
language plpgsql as $$
begin
  if exists (select 1 from field_jobs where building_id = p_building and surface_id = p_surface and state = 'queued') then
    return;
  end if;
  if exists (select 1 from field_jobs where building_id = p_building and surface_id = p_surface and state = 'leased') then
    insert into field_surfaces (building_id, surface_id, rerun_requested) values (p_building, p_surface, true)
    on conflict (building_id, surface_id) do update set rerun_requested = true;
    return;
  end if;
  insert into field_jobs (building_id, surface_id, state) values (p_building, p_surface, 'queued')
  on conflict do nothing;
end $$;

create or replace function public.field_complete_upload(p_capture text, p_stored text[]) returns jsonb
language plpgsql as $$
declare c field_captures; s text;
begin
  select * into c from field_captures where id = p_capture for update;
  if not found then raise exception 'unknown capture'; end if;
  update field_captures set files = (
    select jsonb_agg(case when f->>'name' = any(p_stored) then jsonb_set(f, '{stored}', 'true') else f end)
    from jsonb_array_elements(files) f), updated_at = now()
  where id = p_capture returning * into c;
  if c.state = 'registered' and not exists (select 1 from jsonb_array_elements(c.files) f where not (f->>'stored')::boolean) then
    update field_captures set state = 'uploaded', updated_at = now() where id = p_capture returning * into c;
    if c.duplicate_of is null then
      foreach s in array c.surface_ids loop perform field_enqueue(c.building_id, s); end loop;
    end if;
  end if;
  return to_jsonb(c);
end $$;

-- settle captures held by a job (mirrors state.ts settledState)
create or replace function public.field_settle(p_job field_jobs) returns void
language plpgsql as $$
begin
  update field_captures set
    state = case p_job.state
      when 'succeeded' then case when reviewed_at is not null then 'reviewed' else 'processed' end
      when 'failed' then 'failed'
      when 'queued' then 'uploaded' end,
    error = case when p_job.state = 'failed' then p_job.error else null end,
    updated_at = now()
  where id = any(p_job.capture_ids) and state = 'processing' and p_job.state in ('succeeded','failed','queued');
end $$;

create or replace function public.field_claim_job(p_worker text, p_lease_token text, p_lease_seconds int default 120) returns jsonb
language plpgsql as $$
declare j field_jobs; ids text[];
begin
  for j in select * from field_jobs where state = 'leased' and lease_expires_at <= now() for update skip locked loop
    update field_jobs set
      state = case when attempts >= max_attempts then 'failed' else 'queued' end,
      error = case when attempts >= max_attempts then 'lease expired ' || attempts || ' times; giving up' else error end,
      worker_id = null, lease_token = null, lease_expires_at = null, updated_at = now()
    where id = j.id returning * into j;
    perform field_settle(j);
  end loop;
  select * into j from field_jobs where state = 'queued' order by created_at limit 1 for update skip locked;
  if not found then return null; end if;
  select coalesce(array_agg(id), '{}') into ids from field_captures
    where building_id = j.building_id and j.surface_id = any(surface_ids) and duplicate_of is null
      and state in ('uploaded','processing','processed','reviewed','failed');
  update field_jobs set state = 'leased', worker_id = p_worker, lease_token = p_lease_token, attempts = attempts + 1,
    capture_ids = ids, lease_expires_at = now() + make_interval(secs => p_lease_seconds), updated_at = now()
  where id = j.id returning * into j;
  update field_captures set state = 'processing', updated_at = now() where id = any(ids);
  update field_surfaces set rerun_requested = false where building_id = j.building_id and surface_id = j.surface_id;
  return jsonb_build_object('job', to_jsonb(j),
    'captures', (select coalesce(jsonb_agg(to_jsonb(c)), '[]') from field_captures c where c.id = any(ids)));
end $$;

create or replace function public.field_touch_job(p_job text, p_lease_token text, p_progress jsonb, p_lease_seconds int default 120) returns jsonb
language plpgsql as $$
declare j field_jobs;
begin
  update field_jobs set progress = p_progress, lease_expires_at = now() + make_interval(secs => p_lease_seconds), updated_at = now()
  where id = p_job and state = 'leased' and lease_token = p_lease_token and lease_expires_at > now() returning * into j;
  if not found then return '"lease-lost"'::jsonb; end if;
  return to_jsonb(j);
end $$;

create or replace function public.field_finish_job(p_job text, p_lease_token text, p_outcome jsonb) returns jsonb
language plpgsql as $$
declare j field_jobs; ok boolean := (p_outcome->>'ok')::boolean; rerun boolean;
begin
  select * into j from field_jobs where id = p_job and state = 'leased' and lease_token = p_lease_token and lease_expires_at > now() for update;
  if not found then return '"lease-lost"'::jsonb; end if;
  update field_jobs set
    state = case when ok then 'succeeded'
                 when (p_outcome->>'retryable')::boolean and attempts < max_attempts then 'queued' else 'failed' end,
    worker_id = case when not ok and (p_outcome->>'retryable')::boolean and attempts < max_attempts then null else worker_id end,
    error = case when ok then null else p_outcome->>'error' end,
    result_prefix = case when ok then p_outcome->>'resultPrefix' else result_prefix end,
    lease_token = null, lease_expires_at = null, updated_at = now()
  where id = p_job returning * into j;
  perform field_settle(j);
  insert into field_surfaces (building_id, surface_id) values (j.building_id, j.surface_id) on conflict do nothing;
  if ok then
    update field_surfaces set latest = jsonb_build_object('jobId', j.id, 'prefix', p_outcome->>'resultPrefix',
      'files', p_outcome->'files', 'coverage', p_outcome->'coverage', 'summary', p_outcome->'summary', 'finishedAt', now())
    where building_id = j.building_id and surface_id = j.surface_id;
  end if;
  select rerun_requested into rerun from field_surfaces where building_id = j.building_id and surface_id = j.surface_id;
  if rerun and j.state <> 'queued' then
    update field_surfaces set rerun_requested = false where building_id = j.building_id and surface_id = j.surface_id;
    perform field_enqueue(j.building_id, j.surface_id);
  end if;
  return to_jsonb(j);
end $$;

create or replace function public.field_review_surface(p_building text, p_surface text, p_review jsonb) returns jsonb
language plpgsql as $$
declare s field_surfaces;
begin
  insert into field_surfaces (building_id, surface_id, review) values (p_building, p_surface, p_review)
  on conflict (building_id, surface_id) do update set review = excluded.review returning * into s;
  update field_captures set state = 'reviewed', reviewed_at = now(), updated_at = now()
  where building_id = p_building and p_surface = any(surface_ids) and state = 'processed';
  perform field_enqueue(p_building, p_surface);
  return to_jsonb(s);
end $$;

revoke all on function public.field_enqueue, public.field_complete_upload, public.field_settle, public.field_claim_job,
  public.field_touch_job, public.field_finish_job, public.field_review_surface from public, anon, authenticated;
