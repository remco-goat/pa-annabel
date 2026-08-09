# PA Annabel — persoonlijke assistent

Eén keer per dag: mail, agenda en Todoist lezen, actiepunten eruit halen
(inclusief die uit notulen in je mailbox), en er een korte brief plus een stapel
voorstellen van maken. Jij keurt goed op je telefoon; de agent voert uit.

```
Mac (cron, 1x per dag)  ──schrijft──▶  Supabase  ◀──leest/schrijft──  PWA op je iPhone
   agent.run                          (jouw data)                    (statische HTML/JS)
   agent.apply
```

De agent doet zelf niets zonder jouw tik. `agent.run` zet voorstellen op
`pending`; `agent.apply` voert alleen uit wat op `approved` staat.

**Wat de agent nooit doet:** iets kopen, een mail versturen, iets verwijderen.
Bij een concept-antwoord maakt hij een concept in Gmail — verzenden doe jij. Bij
iets dat gekocht moet worden maakt hij een taak — afrekenen doe jij.

---

## Setup

### 1. Python

```bash
cd ~/Projects/assistant && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

### 2. Supabase

Maak een project (of gebruik een bestaand) en draai
`supabase/migrations/0001_init.sql` in de SQL editor.

Let op de regel met je e-mailadres in `is_owner()` — dat account is het enige
dat via de PWA bij de data mag. Zet in **Authentication > Providers** alleen
Email aan (magic link), en zet **Authentication > URL Configuration >
Site URL** op de URL waar je de PWA host.

Kopieer daarna `.env.example` naar `.env` en vul in:
- `SUPABASE_URL` en `SUPABASE_SERVICE_KEY` (Project Settings > API)
- `ANTHROPIC_API_KEY`

### 3. Google (Gmail + Agenda)

1. [console.cloud.google.com](https://console.cloud.google.com) → nieuw project
2. **APIs & Services > Library** → Gmail API én Google Calendar API aanzetten
3. **OAuth consent screen** → External, publishing status mag op *Testing*, voeg
   jezelf toe als testgebruiker
4. **Credentials > Create credentials > OAuth client ID** → type *Desktop app*
5. Download het JSON-bestand naar `.secrets/google_client.json`

Dan eenmalig:

```bash
.venv/bin/python -m agent.google_auth
```

Je browser opent, je geeft toestemming, klaar. Het token ververst zichzelf.

### 4. Todoist

Todoist → Instellingen → Integraties → Developer → **API token** kopiëren naar
`TODOIST_TOKEN` in `.env`.

### 5. Eerste testrun

```bash
cd ~/Projects/assistant && DRY_RUN=true .venv/bin/python -m agent.run
```

Dit verzamelt alles en laat zien wat de agent zou voorstellen, zonder iets weg
te schrijven. Klopt het beeld? Haal `DRY_RUN=true` weg en draai opnieuw.

### 6. PWA online zetten

Vul `pwa/config.js` met je Supabase URL en **anon** key (niet de service key).

```bash
cd ~/Projects/assistant/pwa && npx wrangler pages deploy . --project-name assistent
```

Of sleep de map naar [Cloudflare Pages](https://dash.cloudflare.com) /
[Netlify Drop](https://app.netlify.com/drop). Je krijgt een HTTPS-URL; open die
op je iPhone, deel-knop → *Zet op beginscherm*.

Zet die URL daarna in Supabase onder **Authentication > URL Configuration**,
anders werkt de magic link niet.

### 7. Dagelijks laten draaien

```bash
crontab -e
```

```
# ochtendbrief
5 7 * * * cd ~/Projects/assistant && .venv/bin/python -m agent.run
# elk half uur: goedgekeurde voorstellen uitvoeren + opdrachten uit de app verwerken
*/30 * * * * cd ~/Projects/assistant && .venv/bin/python -m agent.apply && .venv/bin/python -m agent.commands
```

De halfuur-regel kost niets als er niets te doen is: `apply` doet geen
Claude-call, en `commands` alleen als er echt een opdracht staat. Zo is een
goedkeuring of opdracht binnen een half uur verwerkt in plaats van morgenochtend.

Alle runners loggen zelf naar `logs/<naam>.log` (met timestamps en volledige
tracebacks), dus cron hoeft niets te redirecten.

Slaapt je Mac om 7:00, gebruik dan `launchd` in plaats van cron — die haalt een
gemiste run in zodra de Mac wakker wordt. De agent kijkt standaard 36 uur terug,
dus één gemiste run kost je niets.

---

## Hoe het in elkaar zit

| Bestand | Doet |
|---|---|
| `agent/run.py` | dagelijkse run: verzamelen → dedupe → brein → voorstellen wegschrijven |
| `agent/apply.py` | voert goedgekeurde voorstellen uit |
| `agent/brain.py` | de enige Claude-call: systeem-prompt + JSON-schema van de output |
| `agent/collectors/` | dom: halen data op, denken niet na |
| `agent/actuators/` | voeren uit; alleen aangeroepen vanuit `apply.py` |
| `agent/db.py` | Supabase (PostgREST) met de service key |
| `pwa/` | statische app: brief lezen, voorstellen goedkeuren |

**Dedupe** zit in `db.record_signals()`. Alleen signalen die de agent nog nooit
gezien heeft gaan naar het brein. Zonder dat krijg je elke ochtend dezelfde vijf
mailtjes voorgeschoteld en zet je 'm binnen een week uit.

**Kosten.** Eén run is ruwweg 20–60k input tokens (afhankelijk van hoeveel mail
er is) en een paar duizend output. Met `ASSISTANT_EFFORT=medium` kom je op de
orde van een dubbeltje tot een kwartje per dag. Wordt het te grondig of te
oppervlakkig, dan is `ASSISTANT_EFFORT` de knop: `low` t/m `max`.

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

- **WhatsApp / iMessage.** Bewust later: eerst twee weken mail + agenda + Todoist
  gebruiken en kijken of er echt actiepunten gemist worden. iMessage is daarna
  goedkoop (`~/Library/Messages/chat.db` is gewoon SQLite), WhatsApp is duur en
  tegen de voorwaarden.
- **Push-notificaties.** De PWA moet je nu zelf openen. Web push werkt op iOS
  vanaf 16.4 voor apps op het beginscherm, dus dit kan erbij zonder iets weg te
  gooien.
- **Microsoft To Do.** De adapter staat er (`agent/collectors/todo.py`), alleen
  de Graph-auth ontbreekt. Todoist is nu actief.
