# Viaggiare Sicuri — server MCP e assistente

Un server MCP che espone le informazioni di viaggio della Farnesina come tool granulari, e un
assistente LangChain che risponde **solo** attraverso quei tool, citando fonte e data.

## Quickstart

Serve **Python 3.11+** (sviluppato su 3.12). Per il solo server MCP non serve alcuna credenziale:
le fonti sono endpoint pubblici.

```bash
git clone <repo> && cd travelanalyst
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[server,dev]"
python3.12 -m venv .venv-assistant
.venv-assistant/bin/python -m pip install -e ".[assistant,dev]"
cp .env.example .env        # e compila OPENAI_API_KEY
```

Nel `.env` una sola variabile è obbligatoria, e serve all'assistente, non al server:

| Variabile | Default | A cosa serve |
|---|---|---|
| `OPENAI_API_KEY` | — | **obbligatoria** per l'assistente |
| `OPENAI_MODEL` | `gpt-5.6-luna` | modello di chat |
| `OPENAI_BASE_URL` | vuoto (OpenAI) | endpoint alternativo, es. quello Azure |
| `MCP_SERVER_URL` | `http://127.0.0.1:8001/mcp` | server MCP a cui si collega l’assistente |
| `VS_CACHE_TTL_SECONDS` | `21600` (6 h) | soglia di rivalidazione della cache |
| `VS_ALERTS_TTL_SECONDS` | `900` (15 min) | la stessa soglia, per i soli avvisi |

L'elenco completo è in [.env.example](.env.example), con il significato di ciascuna.

Avvia prima il server MCP in un terminale e lascialo in esecuzione:

```bash
.venv/bin/python server.py           # MCP HTTP: http://127.0.0.1:8001/mcp
```

In un altro terminale avvia una delle interfacce:

```bash
.venv-assistant/bin/travelanalyst              # assistente da riga di comando
.venv-assistant/bin/travelanalyst-web          # browser: http://127.0.0.1:8000
```

L'assistente apre una connessione al server già avviato; chiudendolo il server resta acceso.
`MCP_HOST` e `MCP_PORT` configurano il server, `MCP_SERVER_URL` configura il client.
Entrambi leggono `.env` in sviluppo; le variabili `VS_*` devono essere impostate sul server.

I due ambienti sono separati: FastMCP 4 usa MCP 2, mentre `langchain-mcp-adapters`
usa MCP 1. Comunicano tramite HTTP; non installare gli extra `server` e `assistant`
nello stesso ambiente. `mcp_tools.py` usa [l'adapter LangChain](https://github.com/langchain-ai/langchain-mcp-adapters)
per caricare i tool senza conversioni manuali.

```bash
# Suite server e modelli condivisi
.venv/bin/python -m pytest -q -m "not network and not llm"
# Suite assistente e integrazione HTTP (avvia un server di test con fixture locali)
.venv-assistant/bin/python -m pytest -q tests/test_assistant.py tests/test_mcp_http.py tests/test_packaging.py
# Test sulla fonte reale
.venv/bin/python -m pytest -m network
# Eval: richiedono server HTTP già avviato e credenziali del modello
.venv-assistant/bin/python -m pytest tests/test_assistant_eval.py -m llm -s
```

La raccolta dei test esclude le suite del componente non installato nell'ambiente.
Il test HTTP usa `.venv/bin/python` per il server; puoi cambiarlo con `MCP_TEST_SERVER_PYTHON`.
La configurazione della cache per le eval è quella del server indipendente.

Il server MCP non ha bisogno di credenziali: legge endpoint pubblici. La chiave serve solo
all'assistente, per parlare con il modello.

### Con Docker

Il Dockerfile produce due immagini con dipendenze separate, collegate dalla stessa rete Docker:

```bash
docker build --build-arg COMPONENT=server -t travelanalyst-mcp:dev .
docker build --build-arg COMPONENT=assistant -t travelanalyst-assistant:dev .
docker network create travelanalyst-net

# Server MCP: la cache appartiene a questo servizio
docker run -d --rm --name travelanalyst-mcp --network travelanalyst-net \
  -e MCP_HOST=0.0.0.0 -e MCP_PORT=8001 \
  -v travelanalyst-cache:/var/lib/travelanalyst \
  travelanalyst-mcp:dev python -m viaggiaresicuri_mcp.server

# Assistente web: si collega al server tramite il nome del container
docker run --rm --network travelanalyst-net -p 8000:8000 --env-file .env \
  -e MCP_SERVER_URL=http://travelanalyst-mcp:8001/mcp travelanalyst-assistant:dev

# Arresto del server quando non serve più
docker stop travelanalyst-mcp
```

La chiave del modello viene passata soltanto all'assistente. Il volume conserva la cache
anche dopo la rimozione del container MCP. Il server MCP non pubblica una porta sull'host:
è raggiungibile dall'assistente sulla rete Docker. In locale ascolta solo su `127.0.0.1`.

### Struttura

```
README.md              questo file
Dockerfile             immagini separate: assistente e server MCP HTTP
pyproject.toml         dipendenze, console script e configurazione di pytest
server.py              entry point del server MCP HTTP
viaggiaresicuri_mcp/   il server: tool, contratto, normalizzazione, client, cache
assistant/             l'agente LangChain: CLI, UI web, system prompt
tests/                 189 test offline, 8 sulla fonte reale, 2 sul modello (13 casi)
scripts/discovery/     gli script con cui sono state esplorate le fonti
docs/                  architettura, discovery, decisioni, agente proattivo
    storico/           i piani di lavoro, non più aggiornati
```

## Una sessione vera

Copiata da un'esecuzione reale. Ho tolto i codici colore e le righe di log, e riportato la
domanda sulla riga del prompt — nella cattura arrivava da stdin, quindi non veniva riecheggiata.
Il resto è testuale. La domanda parla **solo di documenti**: l'allerta in testa è il sistema che
fa il suo lavoro.

```
$ .venv-assistant/bin/travelanalyst
avvio del server MCP…

Assistente Viaggiare Sicuri
gpt-5.6-luna via Responses API su api.openai.com · 8 tool · /aiuto per i comandi

› Che documenti servono per andare in Ucraina?
  → find_country
  → get_entry_requirements
  → get_allerte

**Attenzione:** la Farnesina sconsiglia **assolutamente tutti i viaggi verso l'Ucraina**, a
qualsiasi titolo, a causa della situazione di sicurezza e degli attacchi aerei in corso.

Per un cittadino italiano:

- **Passaporto:** necessario, con almeno **3 (tre) mesi di validità residua**. All'ingresso
  possono essere richiesti i dati biometrici, comprese le impronte digitali.
- **Visto:** non necessario per i cittadini UE per soggiorni inferiori a **90 giorni**. Per
  soggiorni più lunghi occorre rivolgersi agli Uffici diplomatico/consolari dell'Ucraina in Italia.
- **Minori:** la scheda rimanda alla pagina ministeriale sui documenti per i viaggi all'estero
  dei minori: https://www.viaggiaresicuri.it/approfondimenti-insights/documentidiviaggio
- **Doppia cittadinanza italiana e ucraina:** in Ucraina la persona è considerata dalle autorità
  locali esclusivamente cittadina ucraina. I cittadini italiani di sesso maschile tra 18 e 60
  anni, se anche cittadini ucraini o con pratica di cittadinanza in corso, possono essere
  impossibilitati a lasciare il Paese. Per l'espatrio è richiesto un passaporto ucraino valido;
  il solo passaporto italiano non è sufficiente.

**Fonte:** scheda Ucraina – viaggiaresicuri.it, aggiornata al **17 agosto 2026**; avviso
Farnesina, aggiornato al **18 agosto 2026**.

Le informazioni sono di orientamento preliminare e possono variare: prima della partenza vanno
verificate le indicazioni ufficiali applicabili al caso specifico. Non sostituiscono pareri
legali o sanitari.
```

Le tre righe grigie sono le chiamate al server MCP: la risposta viene da lì, non dalla memoria del
modello. `get_allerte` non era stato chiesto — l'assistente decide se consultarlo, e qui un avviso
in corso cambiava l'inquadramento della risposta.

## Cosa funziona

- **Tutti e 7 i temi della traccia**, su 222 Paesi: requisiti d'ingresso, documenti e visti,
  sicurezza, salute, mobilità, ambasciate e consolati, allerte.
- **Il contratto regge sulla fonte vera.** Un test di rete scarica e valida tutte e 222 le schede
  contro i modelli Pydantic: se la Farnesina cambia una chiave, lo dice il test.
- **La fonte irraggiungibile non azzittisce l'assistente**: si serve l'ultima copia locale,
  dichiarata come tale nella risposta.
- **Scaduto il TTL non si riscarica, si chiede.** Richiesta condizionale con `If-None-Match`: se
  il contenuto non è cambiato la fonte risponde 304 e la verifica costa **9 ms e zero byte**
  invece di 148 ms e 48 KB.
- **"Non pubblicato" non diventa mai "nessun rischio"**, né sui campi vuoti della scheda né
  sull'assenza di avvisi. È imposto dallo schema, non solo dal prompt.

## Cosa non funziona

- **Nessuno storico e nessuna query cross-Paese.** "Quali Paesi hanno allerte attive" non si può
  chiedere: ogni tool guarda un Paese alla volta.
- **La data esposta è quella della scheda, non della sezione.** `updated_at` viene da
  `updateDate`, che copre il documento intero. La cronologia interna dice altro: per l'Albania la
  scheda risulta aggiornata al 31/07/2026, ma la Situazione sanitaria non cambia dal **07/02/2025**
  — diciassette mesi prima. La data che citiamo è quindi corretta ma ottimista sul singolo
  contenuto.
- **20 dei 28 nodi sono raggiungibili.** Fuori restano la cronologia, le indicazioni per operatori
  economici e i cinque nodi di primo piano, che arrivano solo come fallback quando il dettaglio è
  vuoto. Nessuno dei 7 temi della traccia passa da lì.
- **Le domande generali non hanno risposta.** Ogni tool parla di un Paese specifico: "come si
  rinnova il passaporto" o "che cos'è la dengue" non sono coperte. Il prompt impone di dirlo e di
  rimandare alla fonte, non di rispondere a memoria. La fonte quelle guide le pubblica: vedi il
  primo punto dei limiti noti.
- **La qualità delle risposte non è valutata**: la eval verifica quali tool vengono chiamati e la
  presenza o assenza di stringhe precise, non se la risposta è scritta bene.
- **L'agente proattivo è solo progettato**, non implementato: vedi [PROACTIVE_AGENT.md](docs/PROACTIVE_AGENT.md).

## I test

| Suite | Comando | Copre | Esito |
|---|---|---|---|
| offline | comandi separati sopra | contratto, cache, tool, assistente, adapter HTTP e packaging | verificare entrambe le suite |
| fonte reale | `.venv/bin/python -m pytest -m network` | 8 test: tutte le 222 schede validate, invarianti sui campi vuoti | verdi |
| eval del modello | `.venv-assistant/bin/python -m pytest tests/test_assistant_eval.py -m llm -s` | 12 casi sull'assistente vero + riuso su due turni | 12/12 |

I 12 casi asseriscono sulla traccia delle chiamate, che è deterministica, e sul testo solo per
presenze e assenze precise: che un'allerta compaia nei primi 400 caratteri e prima della prima
menzione di "passaporto"; che un numero di emergenza sia riportato cifra per cifra; che
l'assenza di avvisi non diventi mai "il Paese è sicuro"; che una domanda puntuale **non** paghi
una chiamata alle allerte; che un Paese ambiguo non venga scelto d'ufficio.

Sono però casi che ho scritto io, partendo dai difetti che avevo già trovato: sono copertura di
regressione, non una misura indipendente della qualità.

## I documenti

| File | Cosa contiene |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | componenti, percorso di una query, design dei tool, envelope `meta`, cache |
| [DISCOVERY.md](docs/DISCOVERY.md) | come sono stati trovati gli endpoint, le anomalie, cosa non esiste |
| [DECISIONS.md](docs/DECISIONS.md) | sette ADR brevi: perché le cose stanno così |
| [PROACTIVE_AGENT.md](docs/PROACTIVE_AGENT.md) | il design dell'agente autonomo, non implementato |
| [docs/schede-paese.md](docs/schede-paese.md) | la mappa dei 28 nodi di una scheda paese |
| [docs/storico/](docs/storico/) | i piani di lavoro, storici: raccontano come sono state prese le decisioni, ma i documenti qui sopra sono gli unici aggiornati |

## Limiti noti e cosa farei con più tempo

1. **Esporre le due guide tematiche** — "Salute in viaggio" e "Documenti di viaggio" — con gli
   stessi due tool che già esistono per i 28 nodi della scheda paese: `list` delle sezioni e `get`
   di una sezione. Le ho misurate: **52 sezioni foglia** con un nome parlante (`Dengue`, `Rabbia`,
   `Furto o smarrimento di documenti`), un sommario di sole intestazioni costa ~876 token e una
   sezione ~725 in mediana, cioè esattamente il costo degli altri tool. Avevo costruito una
   ricerca semantica su questo corpus e l'ho rimossa: un catalogo con un sommario si consulta, non
   si cerca (ADR 2). Questa è la versione che scriverei con più tempo, ed è mezz'ora — ma non è
   scritta, quindi sta qui e non fra le cose fatte.
2. **Portare la data per sezione dentro `meta`.** La scheda pubblica una cronologia degli
   aggiornamenti riga per riga ("07/02/2025 - Situazione sanitaria"): basta leggerla e associare a
   ogni nodo la sua data reale, invece di ripetere quella del documento. È la correzione del primo
   limite noto qui sopra, e renderebbe la citazione onesta al livello a cui la risposta la usa.
3. **TTL differenziati per tipo di contenuto.** Oggi ce n'è uno solo, sei ore, più una sola
   eccezione dichiarata a 15 minuti sugli avvisi. Requisiti d'ingresso e mobilità potrebbero
   averne uno molto più lungo, il primo piano molto più corto. Da quando la rivalidazione è
   condizionale costa meno di prima, ma resta il limite più visibile: una scheda aggiornata dieci
   minuti fa può essere servita nella versione di sei ore prima.
4. **Persistere gli `id` degli avvisi già visti.** È la primitiva che manca all'agente proattivo:
   una tabella `(id, nazione, tsModifica, first_seen)` e il "cosa è cambiato" diventa una query.
5. **Dieci domande scritte da qualcun altro.** È il modo più rapido per scoprire dove il sistema
   si rompe davvero, e l'unico che non eredita i miei presupposti.

---

Le informazioni servite sono di orientamento preliminare, possono variare e non sostituiscono le
indicazioni ufficiali applicabili al singolo caso.
