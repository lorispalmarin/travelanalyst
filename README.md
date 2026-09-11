# Viaggiare Sicuri — server MCP e assistente

Un server MCP che espone le informazioni di viaggio della Farnesina come tool granulari, e un
assistente LangChain che risponde **solo** attraverso quei tool, citando fonte e data.

## Quickstart

Serve **Python 3.11+** (sviluppato su 3.12). Per il solo server MCP non serve alcuna credenziale:
le fonti sono endpoint pubblici.

```bash
git clone <repo> && cd travelanalyst
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env        # e compila OPENAI_API_KEY
```

Nel `.env` una sola variabile è obbligatoria, e serve all'assistente, non al server:

| Variabile | Default | A cosa serve |
|---|---|---|
| `OPENAI_API_KEY` | — | **obbligatoria** per l'assistente |
| `OPENAI_MODEL` | `gpt-5.6-luna` | modello di chat |
| `OPENAI_BASE_URL` | vuoto (OpenAI) | endpoint alternativo, es. quello Azure |
| `EMBEDDING_API_KEY` | `OPENAI_API_KEY` | vettorizza le query di ricerca |
| `VS_CACHE_TTL_SECONDS` | `21600` (6 h) | soglia di rivalidazione della cache |
| `VS_ALERTS_TTL_SECONDS` | `900` (15 min) | la stessa soglia, per i soli avvisi |

L'elenco completo è in [.env.example](.env.example), con il significato di ciascuna.

```bash
.venv/bin/travelanalyst              # assistente da riga di comando
.venv/bin/travelanalyst-web          # stessa cosa via browser, http://127.0.0.1:8000
.venv/bin/python server.py           # solo il server MCP, su stdio
make test                            # 212 test offline, nessuna rete
make test-all                        # aggiunge 8 test sulla fonte reale e 2 sul modello
```

L'indice della ricerca semantica è committato in `data/`, quindi il server parte già completo di
tutti e 11 i tool: `make ingest` serve solo a ricostruirlo, e richiede una chiave di embedding.

## Una sessione vera

Copiata da un'esecuzione reale. Ho tolto i codici colore e le righe di log, e riportato la
domanda sulla riga del prompt — nella cattura arrivava da stdin, quindi non veniva riecheggiata.
Il resto è testuale. La domanda parla **solo di documenti**: l'allerta in testa è il sistema che
fa il suo lavoro.

```
$ .venv/bin/travelanalyst
avvio del server MCP…
INFO:viaggiaresicuri_mcp.server:indice degli approfondimenti: 124 chunk

Assistente Viaggiare Sicuri
gpt-5.6-luna via Responses API su api.openai.com · 11 tool · /aiuto per i comandi

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
- **"Non pubblicato" non diventa mai "nessun rischio"**, né sui campi vuoti della scheda né
  sull'assenza di avvisi. È imposto dallo schema, non solo dal prompt.

## Cosa non funziona

- **Nessuno storico e nessuna query cross-Paese.** "Quali Paesi hanno allerte attive" non si può
  chiedere: ogni tool guarda un Paese alla volta.
- **Il retrieval sugli approfondimenti ha un difetto misurato**: per "smarrimento del passaporto"
  il chunk giusto arriva secondo, battuto da uno sui documenti rinvenuti all'estero.
- **L'indice semantico è uno snapshot**, ricostruito a mano con `make ingest`.
- **La qualità delle risposte non è valutata**: la eval verifica quali tool vengono chiamati e la
  presenza o assenza di stringhe precise, non se la risposta è scritta bene.
- **L'agente proattivo è solo progettato**, non implementato: vedi [PROACTIVE_AGENT.md](PROACTIVE_AGENT.md).

## I test

| Suite | Comando | Copre | Esito |
|---|---|---|---|
| offline | `make test` | 212 test su contratto, normalizzazione, cache, tool, prompt | verdi |
| fonte reale | `pytest -m network` | 8 test: tutte le 222 schede validate, invarianti sui campi vuoti | verdi |
| eval del modello | `pytest -m llm -s` | 12 casi sull'assistente vero + riuso su due turni | 12/12 |

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
| [ARCHITECTURE.md](ARCHITECTURE.md) | componenti, percorso di una query, design dei tool, envelope `meta`, cache |
| [DISCOVERY.md](DISCOVERY.md) | come sono stati trovati gli endpoint, le anomalie, cosa non esiste |
| [DECISIONS.md](DECISIONS.md) | sette ADR brevi: perché le cose stanno così |
| [PROACTIVE_AGENT.md](PROACTIVE_AGENT.md) | il design dell'agente autonomo, non implementato |
| [docs/schede-paese.md](docs/schede-paese.md) | la mappa dei 28 nodi di una scheda paese |
| `docs/piano-*.md` | i piani di lavoro, storici: raccontano come sono state prese le decisioni, ma i documenti qui sopra sono gli unici aggiornati |

## Limiti noti e cosa farei con più tempo

1. **Rivalidazione condizionale.** La fonte espone `ETag` e `Last-Modified` su tutti gli endpoint
   e risponde `304` a zero byte — verificato. Oggi non li uso: alla scadenza del TTL riscarico il
   payload intero. Implementarli renderebbe la rivalidazione quasi gratuita, e con essa un TTL
   molto più corto. È la prima cosa da fare.
2. **TTL differenziati per tipo di contenuto.** Oggi ce n'è uno solo, sei ore, più una sola
   eccezione dichiarata a 15 minuti sugli avvisi. Requisiti d'ingresso e mobilità potrebbero
   averne uno molto più lungo, il primo piano molto più corto.
3. **Misurare il retrieval invece di aneddotarlo.** Serve un set di query con il chunk atteso e
   un recall@k, non due esempi. Il difetto noto suggerisce che un ibrido lessicale aiuterebbe,
   ma senza misura è un'ipotesi.
4. **Persistere gli `id` degli avvisi già visti.** È la primitiva che manca all'agente proattivo:
   una tabella `(id, nazione, tsModifica, first_seen)` e il "cosa è cambiato" diventa una query.
5. **Dieci domande scritte da qualcun altro.** È il modo più rapido per scoprire dove il sistema
   si rompe davvero, e l'unico che non eredita i miei presupposti.

---

Le informazioni servite sono di orientamento preliminare, possono variare e non sostituiscono le
indicazioni ufficiali applicabili al singolo caso.
