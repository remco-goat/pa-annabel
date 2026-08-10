-- Betrouwbare klok voor Annabel.
-- GitHub's eigen cron is best-effort (vannacht: 3 van de ~30 runs gedraaid);
-- Supabase pg_cron triggert de GitHub-workflow voortaan op tijd.
--
-- VOOR HET DRAAIEN: vervang <GITHUB_PAT> hieronder (2x) door een fine-grained
-- Personal Access Token. Maken op https://github.com/settings/personal-access-tokens/new
--   Repository access : Only select repositories -> remco-goat/pa-annabel
--   Permissions       : Actions -> Read and write   (verder niets)
--   Expiration        : 1 jaar
--
-- LET OP: het brief-venster is verruimd naar '0 5-18 * * *'. Draai deze
-- migratie opnieuw om dat actief te maken (het script is herdraaibaar).
-- De uurvenster-guard in agent/run.py werkt ook zonder herdraaien; alleen
-- het extra winteruur (18 UTC = 19:00 NL) mist dan nog.

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

-- Elk uur de brief, 05-18 UTC: bewust één uur ruimer dan het gewenste
-- NL-venster 07-19, omdat pg_cron geen tijdzones/zomertijd kent. De guard
-- in agent/run.py (ANNABEL_SCHEDULED=1) filtert de randen weg:
--   zomer : 05 UTC = 07 NL draait,  18 UTC = 20 NL wordt overgeslagen
--   winter: 05 UTC = 06 NL wordt overgeslagen,  18 UTC = 19 NL draait
-- Zo klopt het venster 07-19 NL het hele jaar.
select cron.schedule(
  'annabel-brief',
  '0 5-18 * * *',
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
