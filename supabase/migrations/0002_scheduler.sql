-- Betrouwbare klok voor Annabel.
-- GitHub's eigen cron is best-effort (vannacht: 3 van de ~30 runs gedraaid);
-- Supabase pg_cron triggert de GitHub-workflow voortaan op tijd.
--
-- VOOR HET DRAAIEN: vervang <GITHUB_PAT> hieronder (2x) door een fine-grained
-- Personal Access Token. Maken op https://github.com/settings/personal-access-tokens/new
--   Repository access : Only select repositories -> remco-goat/pa-annabel
--   Permissions       : Actions -> Read and write   (verder niets)
--   Expiration        : 1 jaar

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Oude versies opruimen zodat dit script herdraaibaar is.
do $$
begin
  perform cron.unschedule('annabel-brief');
exception when others then null;
end $$;
do $$
begin
  perform cron.unschedule('annabel-tick');
exception when others then null;
end $$;

-- Elk uur de brief, 05-17 UTC = 07-19 NL in de zomer (winter: 08-20 NL).
select cron.schedule(
  'annabel-brief',
  '0 5-17 * * *',
  $$
  select net.http_post(
    url     := 'https://api.github.com/repos/remco-goat/pa-annabel/actions/workflows/annabel.yml/dispatches',
    body    := '{"ref": "main", "inputs": {"job": "run"}}'::jsonb,
    headers := '{"Authorization": "Bearer <GITHUB_PAT>",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "annabel-scheduler",
                 "Content-Type": "application/json"}'::jsonb
  );
  $$
);

-- Elk kwartier de tick (uitvoeren + opdrachten).
select cron.schedule(
  'annabel-tick',
  '*/15 * * * *',
  $$
  select net.http_post(
    url     := 'https://api.github.com/repos/remco-goat/pa-annabel/actions/workflows/annabel.yml/dispatches',
    body    := '{"ref": "main", "inputs": {"job": "tick"}}'::jsonb,
    headers := '{"Authorization": "Bearer <GITHUB_PAT>",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "annabel-scheduler",
                 "Content-Type": "application/json"}'::jsonb
  );
  $$
);

-- Controle: beide jobs moeten hier staan.
select jobname, schedule from cron.job order by jobname;
