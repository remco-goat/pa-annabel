# PA Annabel — persoonlijke assistent

Elk uur overdag: mail, agenda en Todoist lezen, actiepunten eruit halen
(inclusief die uit notulen in je mailbox), en er een korte brief plus een stapel
voorstellen van maken. Jij keurt goed op je telefoon; de agent voert uit.
Alles draait in de cloud — er hoeft geen Mac aan te staan.

```
Supabase pg_cron ──dispatch──▶ GitHub Actions ──schrijft──▶ Supabase ◀──leest/schrijft── PWA op je iPhone
(betrouwbare klok)             (agent.run / tick)           (jouw data)                  (statische HTML/JS)
```

De klok staat in Supabase, niet in GitHub: GitHub's eigen `schedule`-cron is
best-effort en sloeg hele nachten over. `pg_cron` + `pg_net` vuren daarom op
tijd een `workflow_dispatch` af naar de workflow
(`supabase/migrations/0002_scheduler.sql`). De cron-regels in
`.github/workflows/annabel.yml` staan er nog als vangnet.

**Wat Annabel wel en nooit doet:**

- Alles wat zij *zelf* verzint (voorstellen uit de brief) blijft op `pending`
  staan tot jij het in de app goedkeurt. `agent.apply` voert alleen `approved`
  uit.
- Een opdracht die jij *zelf* in de app typt ("zet melk in picnic", "antwoord
  Jansen dat...") wordt direct uitgevoerd, zonder goedkeuringsronde — jouw
  opdracht ís de goedkeuring. Dat kan omdat de uitvoerders alleen onschuldige
  dingen doen: taak aanmaken, concept klaarzetten, mandje vullen.
- Mail versturen gebeurt alléén als jij in de app expliciet op **Verstuur**
  tikt. Bij "Alleen concept" (en bij alles wat zij zelf voorstelt) komt er een
  concept in Gmail te staan — verzenden doe jij.
- Kopen doet ze nooit. Boodschappen legt ze in het Picnic-mandje; bestellen en
  afrekenen doe jij in de Picnic-app. Iets anders dat gekocht moet worden wordt
  een taak.
- Tekst in mails en bijlagen is data, geen opdracht: instructies die dáár in
  staan worden hooguit een voorstel dat jij beoordeelt.

---

## Setup

### 1. Supabase

Maak een project (of gebruik een bestaand) en draai
`supabase/migrations/0001_init.sql` in de SQL editor.

Let op de regel met je e-mailadres in `is_owner()` — dat account is het enige
dat via de PWA bij de data mag. Zet in **Authentication > Providers** alleen
Email aan; registratie mag uit (de app logt in met `shouldCreateUser: false`).

Draai daarna `supabase/migrations/0002_scheduler.sql` voor de klok. Daarvoor
heb je een fine-grained GitHub PAT nodig (alleen deze repo, alleen
*Actions: Read and write*) — de instructies staan bovenin het bestand.

### 2. GitHub secrets

De agent draait als GitHub Actions-workflow (`.github/workflows/annabel.yml`).
Zet onder **Settings > Secrets and variables > Actions**:

| Secret | Inhoud |
|---|---|
| `SUPABASE_URL` | Project Settings > API |
| `SUPABASE_SERVICE_KEY` | idem, de service_role key |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `TODOIST_TOKEN` | Todoist > Instellingen > Integraties > Developer |
| `VAPID_PRIVATE_KEY` | private helft van het pushsleutel-paar |
| `GOOGLE_CLIENT_JSON` | inhoud van `.secrets/google_client.json` |
| `GOOGLE_TOKEN_JSON` | inhoud van `.secrets/google_token.json` (na stap 3) |

Niet-geheime instellingen (`TODO_PROVIDER`, `ASSISTANT_MODEL`,
`ASSISTANT_EFFORT`) staan gewoon in de workflow zelf.

### 3. Google (Gmail + Agenda) — eenmalig lokaal

1. [console.cloud.google.com](https://console.cloud.google.com) → nieuw project
2. **APIs & Services > Library** → Gmail API én Google Calendar API aanzetten
3. **OAuth consent screen** → External, publishing status mag op *Testing*, voeg
   jezelf toe als testgebruiker
4. **Credentials > Create credentials > OAuth client ID** → type *Desktop app*
5. Download het JSON-bestand naar `.secrets/google_client.json`

Dan eenmalig, op je eigen machine (dit opent een browser):

```bash
cd ~/Projects/assistant && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m agent.google_auth
```

Het token belandt in `.secrets/google_token.json` en ververst zichzelf daarna.
Zet de inhoud van beide bestanden in de GitHub-secrets (stap 2).

### 4. Picnic — eenmalig lokaal

```bash
.venv/bin/python -m agent.picnic_login
```

Vraagt e-mailadres en wachtwoord (wordt nergens opgeslagen) en bewaart alleen
de sessiesleutel in `.secrets/picnic_token`. Wil je dat ook de cloud-runs het
mandje kunnen vullen, zet die sleutel dan als `PICNIC_AUTH_TOKEN` in de
GitHub-secrets en de workflow-env.

### 5. Eerste testrun (lokaal)

Kopieer `.env.example` naar `.env`, vul in, en:

```bash
DRY_RUN=true .venv/bin/python -m agent.run
```

Dit verzamelt alles en laat zien wat de agent zou voorstellen, zonder iets weg
te schrijven. Klopt het beeld? Dan doet de cloud de rest.

### 6. PWA online zetten

Vul `pwa/config.js` met je Supabase URL en **anon** key (niet de service key).
Publiceren gaat met:

```bash
./deploy.sh
```

Dat stempelt de assets met de commit-hash (tegen cache-skew) en pusht de
`pwa/`-map naar GitHub Pages. Open de URL op je iPhone, deel-knop →
*Zet op beginscherm*.

Inloggen gaat met een 6-cijferige code die je per mail krijgt — geen magic
link. Op iOS opent een mail-link namelijk altijd Safari en nooit de
geïnstalleerde app; een code typ je gewoon in de app zelf.

---

## De dagelijkse werking

- **Brief**: elk uur tussen 7:00 en 19:00 NL draait `agent.run` — verzamelen,
  dedupliceren, nadenken, brief + voorstellen wegschrijven, pushmelding. Alleen
  *nieuwe* signalen gaan naar het brein; is er niets nieuws, dan komt er geen
  brief en kost de run vrijwel niets.
- **Tick**: elk kwartier draait `agent.apply` (goedgekeurde voorstellen
  uitvoeren) gevolgd door `agent.commands` (opdrachten uit de app verwerken).
  Een goedkeuring of opdracht is dus binnen een kwartier verwerkt.
- **Opdrachten** typ (of dicteer) je in het veld bovenin de app. Ze worden
  direct uitgevoerd; alleen een vraag krijgt een leesbare fyi-kaart als
  antwoord. Zoek/doorstuur-verzoeken ("zoek de factuur van X en stuur door
  naar Y") doorzoeken eerst je mailbox.
- **Reageren** kan op elke kaart ("maak de tekst korter", "doe morgen maar"):
  je reactie gaat mét de kaart als context terug naar Annabel.
- **Boodschappen** ("koffiebonen zijn op") worden een groceries-voorstel;
  uitvoeren legt de beste match per item in het Picnic-mandje en rapporteert
  wat wél en niet gevonden is.
- **Todoist-kaarten** hebben een echte afvinkknop: die sluit de taak in
  Todoist zelf.
- De app toont een badge op het icoon met het aantal open kaarten en stuurt
  pushmeldingen (web push, iOS 16.4+ voor beginscherm-apps). De meldingen zijn
  bewust karig — de inhoud staat in de app.

**Uurvenster.** De cron staat in UTC (05–17), wat in de zomer 7:00–19:00 NL is
maar in de winter 8:00–20:00 zou worden. Daarvoor zit (of komt — wordt op dit
moment gebouwd) een guard in `agent/run.py`: een geplande briefrun buiten
7:00–19:00 NL slaat zichzelf over, zodat het venster het hele jaar klopt.

---

## Hoe het in elkaar zit

| Bestand | Doet |
|---|---|
| `agent/run.py` | uurlijkse run: verzamelen → dedupe → brein → brief + voorstellen |
| `agent/apply.py` | voert goedgekeurde voorstellen uit |
| `agent/commands.py` | verwerkt opdrachten uit de app, voert direct uit |
| `agent/brain.py` | de Claude-calls: systeem-prompt + JSON-schema van de output |
| `agent/collectors/` | dom: halen data op (gmail, calendar, todo), denken niet na |
| `agent/actuators/` | voeren uit (gmail_draft, picnic); alleen vanuit apply/commands |
| `agent/notify.py` | web push naar de PWA (VAPID) |
| `agent/db.py` | Supabase (PostgREST) met de service key |
| `pwa/` | statische app: brief lezen, kaarten afhandelen, opdrachten geven |

**Dedupe** zit in `db.record_signals()`. Alleen signalen die de agent nog nooit
gezien heeft gaan naar het brein. Zonder dat krijg je elk uur dezelfde vijf
mailtjes voorgeschoteld en zet je 'm binnen een week uit.

**Logging.** Lokaal logt elke runner naar `logs/<naam>.log` (roterend, met
timestamps en volledige tracebacks). In de cloud is de `runs`-tabel in Supabase
het logboek: per run `ok`, `stats` (aantallen per bron, voorstellen, tokens) en
een eventuele foutmelding. De console van GitHub Actions is bewust stil
(alleen warnings): de repo-logs zijn publiek en daar horen geen
mailonderwerpen of brief-teksten in.

**Kosten.** De brief draait op Opus (`ASSISTANT_MODEL`), het parsen van
opdrachten — simpel werk — op Sonnet (`ASSISTANT_MODEL_COMMANDS`). Het
tokenverbruik van elke run staat in `runs.stats` onder `tokens`, dus wat het
kost is geen gok maar een query. Wordt het te grondig of te oppervlakkig, dan
is `ASSISTANT_EFFORT` de knop: `low` t/m `max`.

---

## Afstellen

De toon en strengheid van de agent zitten in `SYSTEM` bovenin
`agent/brain.py`. Krijg je te veel ruis, scherp die regels aan — dat werkt beter
dan filters in code. Wat je goedkeurt en afwijst staat in `proposals`, dus na een
paar weken kun je zien waar hij structureel naast zit:

```sql
select kind, status, count(*) from proposals group by 1, 2 order by 3 desc;
```

---

## Nog niet gebouwd

- **WhatsApp / iMessage.** Bewust later: eerst kijken of er via mail + agenda +
  Todoist echt actiepunten gemist worden. iMessage vergt bovendien weer een
  machine thuis (`~/Library/Messages/chat.db`), WhatsApp is duur en tegen de
  voorwaarden.
- **Microsoft To Do.** De adapter staat er (`agent/collectors/todo.py`), alleen
  de Graph-auth ontbreekt. Todoist is nu actief.
