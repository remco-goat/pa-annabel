# Overdracht PA Annabel — 11 augustus 2026

Startpunt voor een nieuwe chat. Alles hieronder is gebouwd, getest en live,
tenzij anders vermeld. Lees ook `README.md` (architectuur + setup) en het
memory-bestand `personal-assistant-agent.md` (beslissingen + valkuilen).

## Wat het is

Persoonlijke assistent van Remco ("Annabel"): leest elk uur mail/agenda/Todoist,
maakt een puntsgewijze brief + voorstellen die hij in een PWA op zijn iPhone
goedkeurt/afvinkt/beantwoordt. Draait volledig in de cloud.

- **Repo:** `remco-goat/pa-annabel` (publiek; secrets in Actions-secrets)
- **App:** https://remco-goat.github.io/pa-annabel/ (deploy: `./deploy.sh`)
- **Data:** Supabase `sfkcnfwgjwqrmtmcksxd` (los privéproject, geen BAT/Aviclaim)
- **Klok:** Supabase pg_cron → `workflow_dispatch` → GitHub Actions
  (GitHub's eigen cron is bewezen onbetrouwbaar; staat er alleen als vangnet)

## Ritme

| Wat | Wanneer | Door |
|---|---|---|
| Brief (`agent.run`) | elk uur 07–19 NL (guard in run.py houdt het venster jaarrond kloppend) | pg_cron `annabel-brief` |
| Tick (`agent.apply` + `agent.commands`) | elk kwartier | pg_cron `annabel-tick` |
| Web-acties (`agent.webrun`) | on demand | apply dispatcht `annabel-web.yml` |

## Vertrouwensmodel (ontwerpbeslissingen, niet tijdelijk)

- Eigen voorstellen van Annabel wachten op goedkeuring; opdrachten die Remco
  zelf typt worden direct uitgevoerd (zijn opdracht ís de goedkeuring).
- Mail versturen alléén via de expliciete **Verstuur**-knop per mail; anders concept.
- Kopen nooit; Picnic alleen mandje. "Weggooien" = prullenbak, nooit definitief.
- Tekst in mails/bijlagen is data, geen instructie (anti-prompt-injectie in SYSTEM).

## Functionaliteit (alles e2e getest)

Brief als afstreepbare punten · voorstellen-kaarten (goedkeuren/morgen/nee) ·
reageren op elke kaart mét context (gesprek) · opdrachtenveld (+ iOS-dicteerknop)
· mail zoeken door de hele mailbox · doorsturen als concept met bijlagen ·
mailbox-beheer (gelezen/archief/prullenbak) · Todoist twee kanten op (aanmaken
mét subtaken, afvinken — 6 echte afvink-acties geverifieerd) · financiële
waakhond (facturen → signals source='finance', overzicht als context) ·
stijlvoorbeelden per persoon (live uit verzonden mail) · web-acties met
screenshot-bewijs (Playwright in aparte workflow, bewijs in storage-bucket
'bewijs') · pushmeldingen (alleen bij actie nodig; werkend bevestigd) ·
app-badge · historie toont alleen afgevinkte taken · takenlijst in de app
(sinds 14 aug): open Todoist-taken als checkboxes, elke tick gesynct; afvinken
in de app sluit de taak echt in Todoist, taken die Annabel aanmaakt verschijnen
direct · brein kent zijn eerdere voorstellen (sinds 14 aug) — geen duplicaten meer.

## Open punten

1. **Picnic geblokkeerd door Picnic zelf**: login lukt maar elke call eist een
   tweede factor terwijl de 2FA-endpoints zeggen dat het account die feature
   niet heeft (kip-ei; alle unofficial clients stranden hier). Openstaande
   vraag aan Remco: kreeg hij een sms bij het inloggen? Fallback is actief:
   boodschappen worden een Todoist-taak met subtaken. Code: `agent/actuators/picnic.py`,
   login: `agent/picnic_login.py` (met sms-stap die dus 400 geeft).
2. **Google-herautorisatie — OPGELOST 11 aug ~17:00 NL.** Wat er speelde: de
   her-consent van die ochtend verleende maar 2 van de 3 scopes (Drive-vinkje niet
   aangezet), waardoor van ~07:48 tot ~15:00 UTC elke Google-call in de cloud stil
   faalde met `invalid_scope` bij de token-refresh (collectors en de zoekstap
   slikken fouten weg; runs bleven "ok" met gmail:0). Hersteld: her-consent met
   alle vinkjes + secret ververst + Drive API in de Cloud-console geënabled
   (project 20504880539). Refresh, Gmail én Drive daarna live geverifieerd.
   Structurele fix in google_auth.py (commit 9f2bfc4, gepusht): scope-guard leest
   nu de wérkelijk verleende scopes uit het token-bestand (guard op `creds.scopes`
   was dode code — from_authorized_user_file zet daar de gevraagde scopes op), CI
   krijgt een duidelijke RuntimeError i.p.v. stil falen, en een half aangevinkt
   toestemmingsscherm wordt geweigerd bij het opslaan.
3. **SMTP** (laag): login-mails bevatten een link i.p.v. code; sjabloon kan pas
   aangepast na custom SMTP (formulier stond klaar; app-wachtwoord = actie Remco).
   Weinig urgent: sessies zijn permanent, en een beheerder-code kan altijd via
   `auth/v1/admin/generate_link` (veld `email_otp`).
4. **Afstelling**: eerste dagen meekijken of de brief te druk/te stil is —
   de knop is de SYSTEM-prompt in `agent/brain.py`, niet code. Approve/reject-
   data staat in `proposals` voor latere zelflerende tuning (nog niet gebouwd).
5. **Oktober**: wintertijd-check (guard is er; pg_cron-venster is al 5-18 UTC —
   migratie 0002 is met dat venster gedraaid).

## Valkuilen die al bloed hebben gekost (niet opnieuw ontdekken)

- **GitHub Actions cron** slaat stilletjes runs over → daarom pg_cron als klok.
- **Lange tokens via copy-paste in SQL** raken beschadigd → altijd het
  zelfcontrolerende blok-patroon (lengte-assert + format()) gebruiken.
- **iOS + magic links** gaan niet samen → cijfercode-login; mail-quotum van
  Supabase's gratis mailer is ~2-4/uur.
- **PostgREST**: bulk-insert eist gelijke sleutels per rij (db.insert groepeert),
  `"now()"` is geen timestamp (gebruik `db.now_iso()`), `missing=default` werkt
  niet op Supabase.
- **Todoist**: alleen `/api/v1` (rest/v2 = 410), veldnamen anders, geen `url`-veld.
- **Cache-skew PWA**: deploy.sh stempelt assets met commit-hash; nooit handmatig
  gh-pages pushen.
- **CI-logs zijn publiek** (publieke repo): console op WARNING, tracebacks alleen
  naar logbestand, `raise SystemExit(1)` i.p.v. kale raise.
- **Dry-runs mogen de dedupe-wachtrij niet opeten** (`record_signals(persist=False)`).
- **Google-token met te weinig scopes** wordt nu geweigerd door google_auth.py.

## Beveiliging

RLS owner-only op alle tabellen (getest: anon = 0 rijen) · registratie dicht ·
CSP in de PWA (alleen eigen Supabase; getest) · supabase-js zelf gehost ·
secrets in GitHub Actions-secrets + lokale `.env`/`.secrets` (600/700) ·
**let op:** in de chat-historie van de bouwsessie staan een Todoist-token,
Anthropic-key, Supabase-keys en 2 GitHub-PAT's — roteren vóór het delen van
die sessie.

## Logs & debuggen

Cloud: `runs`-tabel in Supabase is het logboek (stats, tokenverbruik, error).
Lokaal: `logs/<runner>.log`. Actions-console is bewust bijna leeg.
Kosten: brief op Opus 5, opdrachten op Sonnet 5; tokens per run in `runs.stats`.
Test-patronen: alles is lokaal draaibaar met `.env`; DRY_RUN=true voor de brief;
testrijen altijd opruimen (proposals/signals) — de app is productie.

## Losse eindjes in bezit van Remco

- GitHub-PAT (`annabel-scheduler`, 1 jr) zit in de pg_cron-jobs; verloopt aug 2027.
- Picnic-token (halve sessie) in `.secrets/picnic_token` + GitHub-secret — nutteloos
  tot het 2FA-raadsel is opgelost; kan weg als Picnic definitief dicht blijft.
