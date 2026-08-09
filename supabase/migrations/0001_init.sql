-- Persoonlijke assistent — datamodel
-- Draai dit in de Supabase SQL editor van het project dat je voor de assistent gebruikt.

-- ---------------------------------------------------------------------------
-- 1. signals — alles wat de collectors ophalen, met dedupe
-- ---------------------------------------------------------------------------
create table if not exists public.signals (
  id            bigint generated always as identity primary key,
  source        text        not null,          -- gmail | calendar | todo | notulen
  external_id   text        not null,          -- stabiele id bij de bron (gmail msg id, task id, ...)
  kind          text        not null,          -- email | event | task | minutes
  title         text        not null,
  summary       text,
  occurred_at   timestamptz,                   -- wanneer het bij de bron gebeurde
  payload       jsonb       not null default '{}'::jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  status        text        not null default 'new'
                check (status in ('new','briefed','handled','ignored')),
  constraint signals_source_external_id_key unique (source, external_id)
);

create index if not exists signals_status_idx on public.signals (status, first_seen_at desc);
create index if not exists signals_source_idx on public.signals (source, occurred_at desc);

-- ---------------------------------------------------------------------------
-- 2. proposals — wat de agent voorstelt; jij keurt goed in de PWA
-- ---------------------------------------------------------------------------
create table if not exists public.proposals (
  id           bigint generated always as identity primary key,
  run_id       bigint,
  signal_id    bigint      references public.signals (id) on delete set null,
  kind         text        not null,           -- create_task | draft_reply | buy | reminder | fyi
  title        text        not null,
  detail       text,
  urgency      text        not null default 'normal'
               check (urgency in ('now','today','week','someday')),
  action       jsonb       not null default '{}'::jsonb,  -- machine-leesbare payload voor de actuator
  status       text        not null default 'pending'
               check (status in ('pending','approved','rejected','snoozed','done','failed')),
  result       text,                            -- uitvoer/foutmelding van de actuator
  created_at   timestamptz not null default now(),
  decided_at   timestamptz,
  executed_at  timestamptz,
  snooze_until timestamptz
);

create index if not exists proposals_status_idx on public.proposals (status, created_at desc);

-- ---------------------------------------------------------------------------
-- 3. briefs — de dagelijkse tekst die bovenaan de PWA staat
-- ---------------------------------------------------------------------------
create table if not exists public.briefs (
  id         bigint generated always as identity primary key,
  run_id     bigint,
  brief_date date        not null default (now() at time zone 'Europe/Amsterdam')::date,
  headline   text        not null,
  body       text        not null,
  created_at timestamptz not null default now()
);

create index if not exists briefs_date_idx on public.briefs (brief_date desc);

-- ---------------------------------------------------------------------------
-- 4. runs — logboek van elke agent-run
-- ---------------------------------------------------------------------------
create table if not exists public.runs (
  id          bigint generated always as identity primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  ok          boolean,
  stats       jsonb       not null default '{}'::jsonb,
  error       text
);

-- ---------------------------------------------------------------------------
-- 5. RLS — alleen jouw ingelogde account mag lezen/schrijven vanuit de PWA.
--    De agent draait met de service_role key en omzeilt RLS.
-- ---------------------------------------------------------------------------
alter table public.signals   enable row level security;
alter table public.proposals enable row level security;
alter table public.briefs    enable row level security;
alter table public.runs      enable row level security;

-- Pas dit e-mailadres aan als je een ander account gebruikt om in te loggen.
create or replace function public.is_owner() returns boolean
language sql stable as $$
  select coalesce(auth.jwt() ->> 'email', '') = 'r.kuilman@aviclaim.nl'
$$;

do $$
declare t text;
begin
  foreach t in array array['signals','proposals','briefs','runs'] loop
    execute format('drop policy if exists owner_all on public.%I', t);
    execute format(
      'create policy owner_all on public.%I for all to authenticated
         using (public.is_owner()) with check (public.is_owner())', t);
  end loop;
end $$;
