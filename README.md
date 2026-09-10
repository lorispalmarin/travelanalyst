# Server MCP — Viaggiare Sicuri

Server MCP che espone le informazioni di viaggio pubblicate dall'Unità di Crisi del Ministero
degli Affari Esteri su [viaggiaresicuri.it](https://www.viaggiaresicuri.it), pensato per un
assistente interno a supporto di operatori e customer care.

Copre i temi richiesti dallo scenario: requisiti di ingresso, documenti e visti, sicurezza,
situazione sanitaria, mobilità, ambasciate e consolati, allerte recenti.

---

## Indice

- [Installazione](#installazione)
- [Esecuzione](#esecuzione)
- [Assistente: CLI e interfaccia web](#assistente-da-riga-di-comando)
- [Architettura](#architettura)
- [I tool](#i-tool)
- [Scelte progettuali](#scelte-progettuali)
- [Test](#test)
- [Script di esplorazione](#script-di-esplorazione)
- [Limiti noti](#limiti-noti)

---

## Installazione

Richiede **Python 3.11+** (sviluppato e testato su 3.12).

```bash
git clone <repo> && cd travelanalyst
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Nessuna credenziale è necessaria: le fonti sono endpoint pubblici. Le chiavi OpenAI servono
soltanto all'assistente, non a questo server.

> Nota su macOS: l'installer di python.org non installa i certificati CA, quindi `urllib` fallisce
> in SSL. Il server usa `httpx`, che porta i propri certificati, quindi non ne risente; se ne
> risentono gli script in `scripts/`, che girano con il Python di sistema.

## Esecuzione

Il server parla **stdio**, il transport standard per i client MCP.

```bash
fastmcp run server.py              # per i launcher che caricano il server da file
python server.py                   # equivalente, senza la CLI di fastmcp
python -m viaggiaresicuri_mcp.server
viaggiaresicuri-mcp                # console script, dopo `pip install -e .`
```

Configurazione per un client MCP (Claude Desktop, `mcp.json` e simili):

```json
{
  "mcpServers": {
    "viaggiaresicuri": {
      "command": "/percorso/assoluto/travelanalyst/.venv/bin/python",
      "args": ["/percorso/assoluto/travelanalyst/server.py"]
    }
  }
}
```

### Variabili d'ambiente

Tutte opzionali: servono per puntare il server a un doppio della fonte e provare gli scenari di
guasto senza toccare il codice.

| Variabile | Default | A cosa serve |
|---|---|---|
| `VS_BASE_URL` | `https://www.viaggiaresicuri.it` | base degli endpoint |
| `VS_TIMEOUT_SECONDS` | `15` | timeout per richiesta |
| `VS_MAX_ATTEMPTS` | `3` | tentativi prima di dichiarare la fonte irraggiungibile |
| `VS_BACKOFF_SECONDS` | `0.5` | base del backoff esponenziale |
| `VS_MAX_CONNECTIONS` | `8` | connessioni concorrenti verso la fonte |
| `VS_USER_AGENT` | `travelanalyst-mcp/0.1 …` | user agent dichiarato |

---

## Assistente da riga di comando


L'assistente è un agente LangChain che risponde **solo** con i tool del server MCP, disponibile
da riga di comando e da browser. Serve una chiave OpenAI:

```bash
cp .env.example .env      # poi inserire OPENAI_API_KEY
travelanalyst             # oppure: python -m assistant.cli
```

```
Assistente Viaggiare Sicuri
gpt-5.6-luna via Responses API su api.openai.com · 10 tool · /aiuto per i comandi

› Un cliente è stato derubato del passaporto a Valona, in Albania. Chi contatto?
  → find_country
  → get_embassy_contacts
  → get_practical_info

Il cliente deve contattare il Consolato Generale d'Italia a Valona e, se serve un
intervento immediato, la Polizia albanese al 112.
…
```

La riga grigia con le frecce elenca i tool man mano che vengono chiamati: serve a mostrare che
la risposta viene dalla fonte e non dalla memoria del modello. Comandi: `/nuovo` azzera la
conversazione, `/tool` elenca i tool, `/esci` chiude.

### Interfaccia web

```bash
travelanalyst-web      # oppure: python -m assistant.web
# poi http://127.0.0.1:8000
```

Una conversazione a turni, con la cronologia che resta e il contesto che si mantiene: dopo aver
chiesto dei contatti a Valona, "e i numeri di emergenza locali?" viene capito senza ripetere il
Paese.

Mentre l'assistente lavora si apre da solo un blocco di **ragionamento e strumenti**: i riassunti
di ragionamento del modello e ogni chiamata al server MCP, con un pallino che pulsa finché il
tool è in corso e diventa verde o rosso alla risposta. Cliccando una card si vedono gli
argomenti passati e il JSON restituito. A risposta conclusa il blocco si richiude in una riga —
*"Ragionamento e 2 passi · 8,0 s"* — e resta lì per chi vuole riaprirlo.

È il punto dell'interfaccia: rendere verificabile a occhio da dove viene ogni informazione. Si
vede il tool chiamato, con quali argomenti, cosa ha risposto, e come quella risposta finisce nel
testo finale.

### Configurazione

| Variabile | Default | Note |
|---|---|---|
| `OPENAI_API_KEY` | — | obbligatoria |
| `OPENAI_MODEL` | `gpt-5.6-luna` | il modello indicato dalla traccia |
| `OPENAI_BASE_URL` | vuoto | per l'endpoint Azure: `https://…/openai/v1/` |
| `OPENAI_USE_RESPONSES_API` | `true` | vedi sotto |
| `ASSISTANT_MAX_STEPS` | `12` | passi massimi per domanda |

`gpt-5.6-luna` ragiona di default, e con il reasoning attivo le chiamate a tool passano solo
dalla **Responses API**: su `/v1/chat/completions` l'API risponde 400. L'alternativa sarebbe
`reasoning_effort="none"`, che però spegne il ragionamento proprio dove serve — scegliere ed
enchainare i tool. Il modello non accetta `temperature` diversa dal default, quindi non viene
impostata.

Passare all'endpoint Azure della traccia è un cambio di `OPENAI_BASE_URL`, senza toccare codice.

### Perché non `langchain-mcp-adapters`

La libreria ufficiale di LangChain per MCP richiede `mcp<2.0`, mentre FastMCP 4 richiede
`mcp>=2`: non esiste combinazione di versioni che le tenga insieme, e installarle nello stesso
ambiente retrocede `mcp` e rompe il server. Fra retrocedere FastMCP e scrivere una cinquantina
di righe di adattatore, la seconda costa meno e non lega il server alle versioni di una libreria
di terze parti: sta in [`assistant/mcp_tools.py`](assistant/mcp_tools.py) e non definisce
nessun tool, li legge da quelli che il server pubblica.

---

## Architettura

### Componenti

```
 ┌──────────────────┐
 │ assistant/cli.py │  REPL
 ├──────────────────┤   ┌──────────────────────────┐
 │ assistant/web.py │──►│ assistant/agent.py       │  LangChain: create_agent
 │  FastAPI + SSE   │   │ + mcp_tools.py (ponte)   │  tool letti dal server
 └──────────────────┘   └────────────┬─────────────┘
                                     │ stdio, processo separato
                    ┌────────────────▼─────────────┐
   client MCP  ───► │  server.py — 10 tool FastMCP │
   (o assistente)   └───────────────┬──────────────┘
                                    │ viste sul contratto
                    ┌───────────────▼──────────────┐
                    │  sheet.py / alerts.py        │  composizione, fallback, filtri
                    └───────────────┬──────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  models.py — contratti       │  validazione Pydantic
                    │  normalize.py — HTML→testo   │  link, rimandi, stato
                    │  countries.py — nome→ISO3    │  alias, fuzzy, ambiguità
                    └───────────────┬──────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  client.py — httpx + retry   │  unico punto di rete
                    │  errors.py — errori tipizzati│
                    └───────────────┬──────────────┘
                                    ▼
                            viaggiaresicuri.it
```

| Modulo | Responsabilità |
|---|---|
| `config.py` | endpoint e parametri di rete, sovrascrivibili da ambiente |
| `client.py` | client httpx asincrono, retry con backoff, traduzione delle eccezioni |
| `errors.py` | gerarchia degli errori: nessuna eccezione di libreria arriva al modello |
| `countries.py` | risoluzione del Paese: ISO3/ISO2, nome, alias, fuzzy match, ambiguità |
| `normalize.py` | HTML → testo, estrazione link, estrazione rimandi, stato del nodo |
| `models.py` | contratti Pydantic: scheda paese, avvisi, envelope di risposta |
| `sheet.py` | recupero e composizione della scheda, fallback, filtri per argomento |
| `alerts.py` | recupero e ordinamento degli avvisi |
| `server.py` | i tool MCP, come viste sottili sul contratto |

Il modulo di rete si chiama `client.py` e non `http.py` di proposito: i launcher che caricano il
server indicando un file mettono la cartella del pacchetto in testa a `sys.path`, e un modulo
chiamato `http` maschererebbe quello della standard library facendo fallire l'avvio. Per lo stesso
motivo esiste `server.py` alla radice del progetto, che importa il pacchetto per nome.

### Flusso dei dati

1. Il client chiama un tool con il nome del Paese così come l'ha scritto l'operatore.
2. `countries.py` risolve nome → ISO3, usando l'elenco ufficiale scaricato una volta e tenuto in
   memoria. Se la richiesta è ambigua il server **non sceglie**: restituisce i candidati.
3. `client.py` interroga l'endpoint della fonte, con retry sugli errori transitori.
4. `models.py` valida il payload: i 28 nodi attesi sono campi obbligatori.
5. `normalize.py` trasforma l'HTML in testo, estrae i link e i rimandi ad altre sezioni.
6. `sheet.py` applica i fallback, filtra gli argomenti richiesti e compone la risposta.
7. Il tool restituisce l'envelope: dati, data di aggiornamento, fonti, disclaimer.

Ogni chiamata interroga la fonte dal vivo: nessuna cache dei contenuti, per non servire
informazioni di sicurezza stantie. Tutto passa da `fetch_sheet()`, quindi una cache si può
aggiungere in un punto solo senza toccare i tool.

### Le fonti

| Endpoint | Contenuto |
|---|---|
| `/schede_paese/lista_nazioni.json` | 222 Paesi con codici ISO |
| `/schede_paese/{ISO3}.json` | scheda completa: 7 sezioni, 28 nodi |
| `/ultima_ora/{ISO3}.json` | avvisi recenti del Paese |
| `/schede_paese/pdf/{ISO3}.pdf` | export PDF della scheda |
| `/schede_paese/pdf/{ISO3}_contactDetails.pdf` | export PDF dei soli contatti |

Struttura, anomalie e misure sono documentate in [`docs/schede-paese.md`](docs/schede-paese.md).
Il percorso di discovery e le alternative scartate sono in
[`docs/piano-design.md`](docs/piano-design.md); il progetto di dettaglio di questa fase è in
[`docs/piano-fase-a.md`](docs/piano-fase-a.md).

---

## I tool

| Tool | Cosa restituisce | Costo tipico |
|---|---|---|
| `find_country(query)` | ISO3 del Paese, o i candidati se ambiguo | trascurabile |
| `get_entry_requirements(country, topics?)` | passaporto, visto, minori, dogana | ~580 tok |
| `get_security_info(country, topics?)` | criminalità, terrorismo, rischi naturali, aree sconsigliate, **normative locali** | ~1.330 tok |
| `get_health_info(country, topics?)` | strutture, malattie, avvertenze, vaccinazioni | ~620 tok |
| `get_local_transport(country)` | guida, strade, trasporto pubblico | ~480 tok |
| `get_embassy_contacts(country)` | ambasciata e consolati, emergenze h24, PDF contatti | ~340 tok |
| `get_practical_info(country)` | dati Paese e numeri di emergenza locali | ~500 tok |
| `get_recent_alerts(country)` | allerte e avvisi in corso, dal più recente | variabile |
| `list_country_topics(country)` | indice dei 28 argomenti, senza testo | ~820 tok |
| `get_country_topics(country, keys)` | solo gli argomenti scelti | quanto pesano |

### Envelope di risposta

Uguale per tutti i tool:

```jsonc
{
  "country":    { "name": "Thailandia", "iso3": "THA", "iso2": "TH" },
  "topic":      "Sicurezza",
  "data":       [ /* argomenti o avvisi */ ],
  "updated_at": "2026-09-03T22:00:00Z",
  "sources":    { "page": "…/find-country/country/THA",
                  "data": "…/schede_paese/THA.json",
                  "pdf":  "…/schede_paese/pdf/THA.pdf" },
  "notice":     "Informazioni di orientamento preliminare…"
}
```

Ogni argomento porta con sé:

| Campo | Significato |
|---|---|
| `id` | chiave della fonte (`Normative-locali-rilevanti`) |
| `key` | chiave da usare nei filtri (`security.local_laws`) |
| `text` | testo normalizzato |
| `status` | `available` oppure `not_published` |
| `provenance` | `detail` oppure `summary`, se il contenuto viene dalla scheda di sintesi |
| `see_also` | sezioni a cui la fonte rimanda, per sapere quale tool chiamare dopo |
| `links` | link estratti, con tipo `web` / `email` / `phone` |

### Errori

I tool sollevano `ToolError` con un codice in testa al messaggio: `country_not_found`,
`ambiguous_country`, `unknown_topic`, `source_unavailable`, `not_found`, `unexpected_payload`.
Nessuna eccezione di httpx o di Pydantic arriva al modello.

---

## Scelte progettuali

Le decisioni che seguono sono motivate da misure sull'intera popolazione dei 222 Paesi, non su
campioni. Gli script che le producono sono in [`scripts/`](scripts/).

**Il contratto ricalca la fonte, i tool ricalcano il bisogno.** I 28 nodi sono campi obbligatori
del modello: se la fonte ne toglie uno la validazione fallisce, invece di restituire in silenzio
una scheda a metà. I nodi nuovi non rompono nulla ma restano visibili. I tool invece sono viste,
perché la tassonomia della fonte non è quella di chi fa una domanda: le regole su farmaci e alcol
stanno sotto "Sicurezza", e nessun modello lo indovinerebbe dal nome del tool. Per questo le
descrizioni elencano esplicitamente i contenuti di ogni sezione.

**"Vuoto" non è "nessun rischio".** La fonte non omette mai un nodo: lo lascia vuoto.
`Aree-di-particolare-cautela` è vuoto nel 37% dei Paesi, `Rischi-ambientali-e-naturali` nel 22%.
Un campo vuoto viene esposto come `not_published`, mai come assenza di pericolo, e la regola è
ripetuta nelle istruzioni del server perché arrivi anche al modello.

**Fallback dichiarato.** Dove il dettaglio è vuoto si usa il riassunto della scheda di sintesi,
marcato `provenance="summary"`. Copre 76 casi su 82. Nei 6 Paesi in cui anche la sintesi è solo
un rimando a una sezione vuota — un vicolo cieco della fonte — la risposta resta "non pubblicato":
meglio del silenzio travestito da rassicurazione.

**Niente parsing dei PDF.** I PDF sono export della stessa scheda: misurata una sovrapposizione
del 91–93% con il JSON, e copertura JSON 222/222. Vengono esposti come link — l'artefatto
ufficiale che l'operatore inoltra al viaggiatore — non come fonte di dati.

**Mai indovinare il Paese.** "Corea" corrisponde a due schede diverse: il server restituisce
entrambe. Un solo candidato debole non è un'ambiguità ma un match che non regge, quindi non viene
proposto: "Ibiza" somiglia a "Libia" all'80%, e suggerire la Libia a chi parte per le Baleari non
è un errore neutro. Le località che l'operatore nomina al posto del Paese (Sharm, Phuket,
Tenerife, Bali) sono risolte da una tabella di alias.

**Nessun filtro silenzioso.** Un filtro su argomenti inesistenti solleva un errore che elenca i
valori ammessi. Restituire una lista vuota sarebbe peggio: il modello la leggerebbe come "la fonte
non pubblica nulla su questo tema".

**Normalizzazione conservativa.** I link vengono estratti prima di rimuovere i tag, altrimenti i
recapiti consolari — che vivono dentro `mailto:` — andrebbero persi. I rimandi interni alla scheda
vengono estratti in `see_also`, ma solo quando la frase non contiene altro: se porta anche una
risposta, resta. Il punto non è sempre fine frase, quindi numeri di telefono, importi, email e URL
restano intatti: verificato su 5.781 nodi, zero alterazioni.

---

## Test

```bash
.venv/bin/python -m pytest -m "not network and not llm"   # offline, ~1s
.venv/bin/python -m pytest -m network                     # sulla fonte reale, ~2s
.venv/bin/python -m pytest -m llm -s                      # eval dell'assistente, ~85s
```

I test offline girano su fixture salvate e non toccano la rete. Quelli marcati `network`
scaricano e validano **tutte le 222 schede** e sorvegliano gli invarianti su cui poggia il
design: nessuna sezione o nodo fuori contratto, il riassunto disponibile quando serve come
fallback, nessun nodo `not_published` che conservi link, la quota di campi vuoti sotto una
soglia. Non verificano il nostro codice: avvisano quando cambia la fonte.

L'eval marcata `llm` fa dieci domande reali all'assistente e verifica **la traccia delle
chiamate**, che è deterministica, più presenze e assenze precise nel testo: che il numero di
emergenza consolare compaia esatto, che davanti a un campo vuoto non compaia mai "nessun
rischio", che su "Corea" chieda quale dei due Paesi, che su una domanda fuori tema non chiami
nessun tool. Tre casi sono quelli che avevano fatto emergere bug nel server: restano nella eval
perché non rientrino da un'altra porta.

## Script di esplorazione

Indipendenti dal server e senza dipendenze esterne, servono a ispezionare le fonti a mano.

```bash
python scripts/lista_nazioni.py --search thai
python scripts/scheda_paese.py Thailandia --section infoSicurezza --full
python scripts/ultima_ora.py Perù
python scripts/approfondimenti.py saluteinviaggio
python scripts/report_campi_vuoti.py --csv report.csv    # censimento su tutti i Paesi
```

## Limiti noti

- **Approfondimenti non esposti.** In diversi Paesi il nodo sui minori non contiene la norma ma
  un rinvio all'approfondimento "Documenti di viaggio", che oggi il server non serve.
- **Nessuna cache.** Ogni chiamata interroga la fonte: la latenza a freddo si paga a ogni Paese.
- **Nessuno storico.** Il server risponde sul presente; il confronto fra due momenti servirà
  all'agente proattivo, non a questo assistente.
- **Aggiornamento disomogeneo.** Le schede vanno da gennaio 2025 a settembre 2026: la data è
  sempre esposta, ma il server non può renderle più fresche di così.

Le informazioni servite sono di orientamento preliminare, possono variare e non sostituiscono le
indicazioni ufficiali applicabili al singolo caso.
