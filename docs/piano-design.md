# Design MCP server "Viaggiare Sicuri" — discovery fonti + opzioni di design

## Context

Colloquio tecnico (giovedì prossimo) per posizione AI Engineer. Traccia: assistente interno
che risponde su destinazioni internazionali (requisiti ingresso, visti, sicurezza, salute,
trasporti, ambasciate/consolati, allerte recenti), usando **esclusivamente** tool esposti da
un MCP server (FastMCP) costruito sopra le fonti pubbliche (non documentate) di Viaggiare
Sicuri. L'assistente è LangChain-based, interrogabile via CLI o web UI semplice. La sezione
"agente autonomo proattivo" è per ora fuori scope (design obbligatorio, implementazione
facoltativa).

Repo vuoto (solo `.git`): fase di scelta architetturale prima di scrivere codice. Ho svolto
una discovery reale sugli endpoint (curl + analisi del bundle Angular del sito, che è una SPA:
l'HTML non contiene i contenuti, le chiamate XHR sono nei bundle `/build/main.*.js`).

---

## Mappa endpoint verificata

Base URL: `https://www.viaggiaresicuri.it`

| Endpoint | Contenuto | Verificato |
|---|---|---|
| `GET /schede_paese/lista_nazioni.json` | 222 paesi: `Nome` (IT), `Codice-3`, `Codice-2`, coordinate | 222 record, 0 duplicati |
| `GET /schede_paese/{COD3}.json` | Scheda paese completa, 7 sezioni | 222/222 disponibili, 12–124 KB (mediana 34 KB) |
| `GET /ultima_ora/{COD3}.json` | Allerte del paese: `{ultima_ora: [], focus: []}` | OK, autorevole per paese |
| `GET /ultima_ora/totale.json` | Feed globale: `{ultima_ora(25), focus(1), aggiornamentiSchedaPaese(16)}` | OK, **troncato** |
| `GET /schede_paese/pdf/{COD3}.pdf` | Export PDF della scheda (33 KB per ALB) | 200, `application/pdf` |
| `GET /schede_paese/pdf/{COD3}_contactDetails.pdf` | Export PDF contatti sede diplomatica | 200, `application/pdf` |
| `GET /approfondimenti/{avvertenze,documentidiviaggio,preparaunviaggio,saluteinviaggio}.json` | Guide generali non per-paese (11–210 KB) | OK |
| `GET /marker/marker_{COD3}.json` | Pin mappa | Vuoto (`[]`) per ALB — non utile |

### Struttura `schede_paese/{COD3}.json`

Due livelli, schema uniforme:

```
{ updateDate: "2026-07-30T22:00:00Z",
  <sezione>: { id, titolo, ordinamento, nodi: { <nodo>: { titolo, contenuto(HTML), ordinamento } } } }
```

7 sezioni, presenti in **25/25** paesi campionati (nessuna variazione di chiavi per paese):
`infoCronologiaAggiornamenti`, `infoPrimopiano`, `infoGenerali`, `infoRequisitiIngresso`,
`infoSicurezza`, `infoSituazioneSanitaria`, `infoMobilita`. Anche i 28 nodi foglia sono
presenti in 25/25 (elenco completo in `docs/schede-paese.md`).

Mappatura sui 7 temi della traccia (copertura piena tranne le allerte):
- requisiti ingresso → `infoRequisitiIngresso` (Passaporto, Visto-di-ingresso, Viaggi-all-estero-dei-minori, Formalit--doganali-e-valutarie, Altre-informazioni)
- documenti/visti → `infoRequisitiIngresso.Passaporto` + `.Visto-di-ingresso` + `infoPrimopiano.Documenti-e-visti`
- sicurezza → `infoSicurezza` (Indicazioni-generali, Rischio-terrorismo, Rischi-ambientali-e-naturali, Aree-di-particolare-cautela, Avvertenze, Normative-locali-rilevanti, Informazioni-per-le-aziende)
- sanità → `infoSituazioneSanitaria` (Strutture-sanitarie, Malattie-presenti, Avvertenze, Vaccinazioni-obbligatorie)
- mobilità → `infoMobilita.Mobilita` (nodo unico, molto lungo: 9,3 KB per ALB)
- ambasciate/consolati → `infoGenerali.Ambasciate-e-Consolati` (+ `infoPrimopiano.Ambasciata`)
- allerte recenti → **non qui**: `ultima_ora/{COD3}.json`

### Struttura endpoint allerte

Item: `{id, nazione, tipologia, titolo, testo(HTML), follow, url, tsModifica}` — la versione
per-paese aggiunge `lat`/`lon`. `id` è stabile (`ULTIMORA_MARKER_35404`) → chiave di dedup
naturale per il futuro agente proattivo; `tsModifica` è unix timestamp (stringa).

`totale.json` ha tre liste: `ultima_ora` (allerte), `focus` (contenuto editoriale non
per-paese, es. "I consigli dell'Unità di Crisi", `nazione` vuoto),
`aggiornamentiSchedaPaese` (notifiche "la scheda X è stata aggiornata",
id `AGGIORNAMENTO_SCHEDA_{COD3}`, `titolo` = elenco sezioni modificate).

### Anomalie reali rilevate (da usare come giustificazione delle scelte di robustezza)

1. **`totale.json` NON è un superset dei per-paese**: il solo Perù ha 7 allerte, `totale.json`
   ne contiene 25 in tutto e solo 3 di quelle del Perù. È un feed globale recente, non un archivio.
2. **Lo stesso alert differisce tra i due endpoint**: per `ULTIMORA_MARKER_35345`,
   `tipologia` = `"sicurezza"` nel per-paese ma `""` in `totale.json`; `follow` è l'opposto
   (`""` vs `"PER"`); il campo `testo` ha encoding HTML diverso (entità `&#039;` vs tag `<p>`).
   → La normalizzazione non è cosmetica: serve un modello unico a valle dei due endpoint.
3. **"Presente ma vuoto" ≠ "assente"**: nessun nodo manca mai, ma molti sono stringa vuota —
   `infoGenerali.Documentazione-necessaria` vuoto in **25/25**,
   `infoSicurezza.Rischi-ambientali-e-naturali` in 9/25,
   `infoSicurezza.Aree-di-particolare-cautela` in 8/25,
   `infoSicurezza.Informazioni-per-le-aziende` in 5/25,
   `infoSicurezza.Rischio-terrorismo` in 1/25.
   → **Rischio di sicurezza**: un campo "Rischio terrorismo" vuoto non significa "nessun
   rischio". I tool devono restituire esplicitamente "informazione non pubblicata dalla fonte"
   e il system prompt deve vietare di inferire assenza di rischio da assenza di testo.
4. **Freschezza disomogenea**: `updateDate` va da 2025-10-19 a 2026-09-06 (mediana 2026-06-10);
   3/25 schede più vecchie di 8 mesi. → Esporre sempre la data, mai promettere freschezza.
5. **HTML sporco ovunque**: `contenuto`/`testo` contengono tag + entità HTML non decodificate
   → serve unescape + conversione a testo/markdown preservando i link (i contatti delle
   ambasciate sono dentro `<a href="mailto:...">`).
6. **Dimensione**: scheda mediana 34 KB → mai riversare la scheda intera nel contesto dell'LLM;
   giustifica tool granulari per sezione.
7. `Nome` è solo in italiano e include territori non sovrani (es. "Isole Marianne
   Settentrionali", "Sint Maarten") → risoluzione nome→`Codice-3` con normalizzazione accenti,
   alias EN e fuzzy match.

### Documentazione ufficiale (trovata) e sua inaffidabilità

`GET /contenuti/JSON.pdf` (77 KB, last-modified **2021-11-02**) è un documento dell'Unità di
Crisi, linkato nel **footer di ogni pagina** del sito con l'etichetta *"Web Services Viaggiare
Sicuri"* (accanto a "Mappa del sito", con il sottotitolo "Le informazioni relative ad
Approfondimenti, Destinazioni e Avvisi"). Documenta esplicitamente gli endpoint JSON: avvisi (`/ultima_ora/totale.json` e
`/ultima_ora/{ISO3}.json`), schede paese (`/schede_paese/{ISO3}.json`), `lista_nazioni.json` e
gli approfondimenti. Quindi le fonti *sono* documentate, contrariamente a quanto assume la
traccia — ma la documentazione è del 2021, parziale e in un punto **errata**:

- non menziona affatto gli endpoint PDF né `preparaunviaggio.json`;
- non descrive campi, semantica, frequenza di aggiornamento né le tre liste di `totale.json`;
- documenta `/approfondimenti/sicurezzaaerea.json` come "Sicurezza aerea": l'endpoint risponde
  200 ma **restituisce il contenuto di "Preparare un viaggio"** (stesse 3 sezioni:
  `saluteinviaggio`, `assicurazionediviaggio`, `pacchittituristici` — con il typo nell'id
  originale). Nessun contenuto sulla sicurezza aerea.

→ Argomento forte in colloquio: la doc è stata trovata **e verificata**, non presa per buona.
La discovery resta necessaria proprio perché la fonte ufficiale è incompleta e in parte falsa.

### Verifica empirica sui PDF (decide se vale la pena parsarli)

PDF generati con iText 5.5.13 (`Creator: Noovle Srl`): sono render server-side dello stesso CMS.
Estratto il testo e confrontato con il JSON, normalizzando entrambi:

- `ALB.pdf` (11 pagine) ↔ JSON della scheda: **91,4%** del PDF ritrovato nel JSON, **93,4%** del
  JSON ritrovato nel PDF. Il residuo è intestazione e rumore di estrazione, non contenuto nuovo.
- `ALB_contactDetails.pdf` (1 pagina): **94,1%** già contenuto nel PDF principale, 82,4% nel JSON.
- Unico dato presente solo nel PDF: l'intestazione "Valida al 31/07/2026", che coincide con la
  data di generazione del file (`last-modified`), quindi non è informazione aggiuntiva.

→ Parsare i PDF significherebbe **ri-derivare con perdita** dati già disponibili con chiavi
strutturate, aggiungendo una dipendenza (nessun tool PDF è presente nell'ambiente) e la
fragilità dell'estrazione layout. Decisione: **nessun parsing**, i PDF si espongono come URL.

### Misure che vincolano il contratto dei tool

Testo ripulito dall'HTML, campione di 16 paesi (~token = char/4):

| Sezione | mediana | max |
|---|---|---|
| `infoSicurezza` | ~1.260 tok | ~4.270 tok |
| `infoGenerali` | ~710 tok | ~2.620 tok |
| `infoSituazioneSanitaria` | ~570 tok | ~2.910 tok |
| `infoRequisitiIngresso` | ~430 tok | **~6.290 tok** |
| `infoPrimopiano` | ~380 tok | ~680 tok |
| `infoMobilita` | ~270 tok | ~1.530 tok |
| **scheda intera** | **~4.590 tok** | **~13.880 tok** (India) |

→ A livello di *sezione* il costo è trascurabile (poche centinaia di token): non serve
spezzettare oltre. A livello di *scheda intera* no: il caso peggiore vale ~14k token in un solo
tool result, e una conversazione che tocca due paesi va fuori controllo. Quindi **un solo
contratto Pydantic per la scheda, ma tool che ne restituiscono viste**, non il documento intero.

### `infoPrimopiano` è uno strato di sintesi con rimandi espliciti

Un primo confronto per sovrapposizione letterale suggeriva che fosse testo originale: **era un
artefatto della misura**. Leggendo i testi (THA, BRA) e verificando il pattern su 35 paesi, il
quadro reale è che `infoPrimopiano` è un digest delle altre sezioni, ogni nodo chiuso da un
rimando del tipo *"consultare la Sezione Sicurezza di questa Scheda"*. È il rimando (boilerplate
non presente altrove) ad abbassare la sovrapposizione, non l'informazione nuova.

| nodo di `infoPrimopiano` | contiene un rimando | lunghezza mediana |
|---|---|---|
| `Vaccinazioni` | 35/35 (100%) | 424 char |
| `Documenti-e-visti` | 34/35 (97%) | 426 char |
| `Aree-di-particolare-cautela` | 32/35 (91%) | 182 char |
| `Ambasciata` | 6/35 (17%) | 336 char |
| `Moneta` | 0/35 (0%) | **16 char** |

Casi limite: per la Thailandia `Aree-di-particolare-cautela` è **solo** il rimando, senza alcun
contenuto (245 char di puntatore); per il Brasile invece il digest è **più ricco del dettaglio**
(`Documenti-e-visti` 886 char contro 317+172 di Passaporto+Visto).

Conseguenze per il contratto:
1. `infoPrimopiano` è lo strato "risposta breve" (~380 token per l'intera sezione): utile e
   sicuro, ma non è la fonte per una domanda puntuale.
2. **Non vale `dettaglio ⊇ sintesi`** (caso Brasile): scartare il primo piano può produrre una
   risposta più povera di quella che l'operatore leggerebbe sul sito.
3. I rimandi sono istruzioni rivolte a un umano che naviga il sito: in chat sono rumore. In
   normalizzazione vanno estratti in un campo strutturato (es. `vedi_anche: ["sicurezza"]`),
   che per l'agente diventa un'affordance — sa quale tool chiamare dopo.
4. `Moneta` ha mediana 16 caratteri: è un dato, non prosa. Il modello non deve trattare tutti i
   nodi come testo lungo.

---

## Cosa la traccia valuta davvero (lettura critica, incide sulla scelta)

La traccia elenca come responsabilità: *identificare gli endpoint*, *definire i tool MCP più
adeguati*, *gestire la validazione di input e output*, *normalizzare i dati*, con "gestione
robusta delle possibili anomalie delle risposte". **Non chiede un database né un vector store.**
La parola "ingestion" compare solo nella nota sulle credenziali ("da utilizzare per
l'assistente/agente e per eventuali attività di ingestion") — è un *permesso d'uso*, non un
requisito. Idem per `text-embedding-3-large`: è messo a disposizione, non richiesto.

Conseguenza: gli assi di valutazione sono qualità della discovery, disegno dei tool,
validazione, normalizzazione, robustezza. Le anomalie che ho trovato (§ sopra) sono quindi il
terreno dove si guadagnano punti — non la scelta dello storage.

---

## Opzioni di design

### Opzione A — Live pass-through con cache "data-aware"

**Come funziona.** Ogni tool MCP: risolve il paese → fetch dell'endpoint → validazione Pydantic
→ normalizzazione HTML → risposta con `fonte`, `aggiornato_al`, `disclaimer`. Cache in-memory
invalidata confrontando i campi reali della fonte (`updateDate` per le schede, `tsModifica` per
le allerte) invece che con un TTL arbitrario; TTL breve per le allerte, lungo per le schede.

**Punti di forza**
- Freschezza reale sulle allerte, che è il dato dove la staleness fa danno.
- Nessuno stato da mantenere, nessun primo popolamento, nessuna migrazione: superficie di bug
  minima e demo che non può "partire vuota" davanti all'esaminatore.
- Costo stimato: ~1 giornata per un nucleo curato. Lascia tempo per assistente, UI e documentazione.
- La strategia di cache è ancorata a campi che esistono davvero nel payload: è una scelta che
  puoi mostrare, non da raccontare.

**Punti di debolezza**
- Latenza a freddo su ogni primo accesso a un paese (scheda mediana 34 KB).
- Dipendenza dall'uptime della fonte a runtime: se viaggiaresicuri.it è giù, l'assistente è muto.
- Non abilita nulla di cross-paese ("quali paesi hanno allerte sicurezza attive?") né lo storico.
- Da sola non prepara il terreno per l'agente proattivo (che ha bisogno di memoria del "già visto").

**Giustificabilità in colloquio: alta.** L'argomento è che il dominio è un lookup deterministico
(paese × argomento), non un problema di retrieval: la fonte è già indicizzata per gli stessi
assi dei tool. Il rischio è che, presentata da sola e senza enfasi su validazione/normalizzazione,
somigli a "un wrapper HTTP" — va difesa mostrando il lavoro sulle anomalie.

### Opzione B — Ingestion pipeline + store locale (SQLite)

**Come funziona.** Script di ingestion: 222 schede (~7 MB totali) + allerte → parsing →
normalizzazione HTML → tabelle (`countries`, `sections`, `alerts`, `ingestion_runs`). I tool
leggono lo store. Refresh schedulato con upsert incrementale guidato da `updateDate` /
`tsModifica` / `aggiornamentiSchedaPaese`.

**Punti di forza**
- È la sola opzione che produce il segnale "cosa è cambiato dall'ultima volta": nuovi `id` di
  allerta e `updateDate` avanzato. **È esattamente l'input dell'agente proattivo richiesto dalla
  traccia** — la parte 1 e la parte 2 si tengono, invece di essere due esercizi scollegati.
- Abilita query impossibili in A: cross-paese, storico, deduplica, "novità delle ultime 24h".
- Latenza costante e indipendenza dal sito a runtime (utile nell'inquadramento "customer care").
- Dimostra idempotenza, upsert, tracciamento dei run: pratiche di data engineering vere.

**Punti di debolezza**
- Il costo più alto in assoluto: schema, ingestion, refresh, gestione del primo popolamento,
  più test. Con pochi giorni è l'opzione con il maggior rischio di consegna incompleta.
- Sulle allerte introduce staleness proprio dove fa più male, a meno di tenerle live — e a quel
  punto l'architettura è già ibrida, quindi tanto vale dichiararlo.
- Su 222 file JSON piccoli, ben strutturati e serviti da CDN, un DB può essere letto come
  sovra-ingegnerizzazione.

**Giustificabilità: alta ma condizionata.** Regge se il criterio dichiarato è "il DB serve al
monitoraggio e al diff, non alla query". Regge male se la motivazione è "volevo mostrare una
pipeline": l'esaminatore può chiedere perché, e non c'è una risposta basata sui dati.

### Opzione C — Ibrida: nucleo live + RAG mirato sugli approfondimenti

**Come funziona.** Nucleo identico ad A per i 7 temi. In più un tool `search_general_guidance`
con embedding (`text-embedding-3-large`) **solo** sui 4 file `/approfondimenti/*` (~250 KB di
prosa non per-paese: documenti di viaggio, salute in viaggio, avvertenze, preparare un viaggio),
che sono l'unico contenuto non indicizzabile per chiave.

**Punti di forza**
- Usa ogni tecnologia dove è motivata dai dati e non per abitudine: il messaggio implicito è
  "so quando *non* serve un RAG", che per un ruolo AI Engineer pesa più di un vector store in più.
- Copre domande generali ("serve l'assicurazione sanitaria?", "documenti per minori") che le
  schede paese non coprono, senza far inventare nulla al modello.
- Modulo isolato: se il tempo finisce si taglia senza toccare il nucleo.

**Punti di debolezza**
- Nessuno dei 7 temi obbligatori lo richiede: è una funzionalità in più, e "in più" costa tempo
  che potrebbe andare su robustezza e documentazione.
- Corpus minuscolo e con contenuti sovrapposti tra file (`preparaunviaggio.json` contiene una
  sezione `saluteinviaggio`): il RAG è quasi un giocattolo, e va deduplicato.
- Due meccanismi di accesso ai dati da spiegare e documentare invece di uno.

**Giustificabilità: molto alta se presentata come scelta esplicita**, cioè "ho valutato il RAG
sulle schede paese e l'ho escluso perché *questi* dati sono già chiavi; l'ho usato solo qui,
dove il testo è libero". Diventa debole se sembra un pretesto per usare il modello di embedding
fornito.

---

## Raccomandazione (aggiornata dopo la discovery)

Prima della discovery avevo indicato la C secca. Con i dati in mano la sposto: **A come nucleo
non negoziabile, poi estensioni a fasi**, perché gli assi di valutazione sono discovery, tool,
validazione, normalizzazione e robustezza — e su tutti e cinque il valore si costruisce nel
nucleo, non nello storage.

1. **Fase 1 — nucleo (A fatta bene).** Tool granulari per argomento, risoluzione paese con
   fuzzy match, normalizzazione HTML, modelli Pydantic in ingresso e uscita, cache data-aware,
   e soprattutto la gestione esplicita di "presente ma vuoto" con la regola anti-inferenza sui
   campi di rischio. È qui che stanno i punti.
2. **Fase 2 — store leggero delle allerte (B ridotta all'osso).** Una sola tabella di allerte
   viste (`id`, `nazione`, `tsModifica`, `first_seen`). Costa poco e trasforma il design
   dell'agente proattivo da teorico a "ecco il segnale, è già persistito".
3. **Fase 3 — RAG sugli approfondimenti (C), solo se resta tempo.** Da presentare come scelta
   consapevole e circoscritta, mai come componente centrale.

Se il tempo dovesse stringere, tagliare dalla fase 3 all'indietro: la 1 da sola è già una
consegna coerente e difendibile.

**Decisione sui PDF: esporli come artefatti, non parsarli.** Misurata una sovrapposizione del
91–93% col JSON (§ Verifica empirica) e copertura JSON 222/222: come *fonte di dati* i PDF non
aggiungono nulla. Il loro valore è nel flusso di lavoro del customer care, dove servono come
*artefatto da consegnare*: documento del Ministero, datato, inoltrabile al cliente o allegabile
a una pratica, che sposta l'autorevolezza dall'operatore alla fonte ufficiale. Per tutti questi
usi serve l'URL, non il testo estratto.

Distinzione utile tra i due PDF: `_contactDetails.pdf` è ridondante come *contenuto* (94% già
nel PDF principale) ma è il più utile come *forma* — una pagina, 2,6 KB, solo recapiti e numero
di emergenza h24. Nello scenario "passaporto rubato a Valona" si inoltra quello, non 11 pagine.
Quindi `get_embassy_contacts` restituisce i contatti normalizzati dal JSON **più** il link al
PDF di una pagina.

Regola generale che ne deriva, da dichiarare nel README: **il server MCP espone dati dal JSON e
artefatti come URL.** Documentare la misura (91–93%, 222/222) è una risposta più forte che
parsare i PDF per obbligo, se in sede di colloquio viene chiesto perché non sono stati elaborati.

---

## Decisioni prese

1. **PDF**: solo URL nelle risposte, nessun parsing, nessuna dipendenza PDF.
2. **Punto di partenza**: il contratto Pydantic di `schede_paese/{COD3}.json`. I tool sono
   *viste* su quel contratto, non parser separati.
3. **Granularità**: si scende fino alla sezione, non oltre. Una sezione costa poche centinaia di
   token e l'LLM distingue benissimo visto e requisiti generali dentro lo stesso blocco.
4. **`infoPrimopiano`**: si tiene, come strato "risposta breve".
5. **Rimandi**: estratti dal testo e strutturati in `vedi_anche`, così diventano un suggerimento
   di navigazione per l'agente.
6. **`ultima_ora`**: rimandato, ma l'envelope di risposta si fissa ora per non riaprire il
   contratto dopo.

## Contratto proposto

```python
class Link(BaseModel):        # i recapiti delle ambasciate vivono dentro <a href="mailto:...">
    testo: str
    url: str

class Nodo(BaseModel):
    id: str                    # "Visto-di-ingresso"
    titolo: str
    testo: str                 # HTML normalizzato, entità decodificate
    stato: Literal["disponibile", "non_pubblicato"]
    vedi_anche: list[str] = [] # ["sicurezza"] estratto dai rimandi
    link: list[Link] = []

class Sezione(BaseModel):
    id: str                    # "infoRequisitiIngresso"
    titolo: str
    nodi: list[Nodo]

class SchedaPaese(BaseModel):
    paese: str
    codice3: str
    aggiornato_al: datetime    # da updateDate
    sezioni: dict[str, Sezione]

class RispostaTool(BaseModel): # envelope condiviso, vale anche per le allerte future
    dati: ...
    aggiornato_al: datetime | None
    fonti: list[str]           # pagina web + PDF ufficiale
    disclaimer: str
```

Regola non negoziabile: `stato="non_pubblicato"` non significa "nessun rischio". Vale per
`Rischio-terrorismo`, `Rischi-ambientali-e-naturali` e `Aree-di-particolare-cautela`, vuoti
rispettivamente in 1/25, 9/25 e 8/25 dei paesi campionati. Va imposto nel campo *e* nel system
prompt dell'assistente.

## Superficie dei tool (viste sul contratto)

| Tool | Sorgente | Costo tipico |
|---|---|---|
| `resolve_country(query)` | `lista_nazioni.json` + fuzzy match | trascurabile |
| `get_country_overview(paese)` | `infoPrimopiano` | ~380 tok |
| `get_entry_requirements(paese, nodo=None)` | `infoRequisitiIngresso` | ~430 tok (max 6.3k → filtro `nodo`) |
| `get_security_info(paese)` | `infoSicurezza` | ~1.260 tok |
| `get_health_info(paese)` | `infoSituazioneSanitaria` | ~570 tok |
| `get_local_transport(paese)` | `infoMobilita` | ~270 tok |
| `get_embassy_contacts(paese)` | `infoGenerali.Ambasciate-e-Consolati` + link PDF contatti | ~340 tok |
| *(fase 2)* `get_recent_alerts(paese)` | `ultima_ora/{COD3}.json` | variabile |

Input: nome italiano, alias inglese o ISO3. Se la risoluzione è ambigua il tool non indovina —
restituisce i candidati e lascia decidere all'agente.

## File da creare

```
viaggiaresicuri_mcp/
  client.py       # HTTP, retry, cache invalidata su updateDate/tsModifica
  models.py       # il contratto qui sopra
  normalize.py    # HTML→testo, estrazione link e vedi_anche, stato del nodo
  countries.py    # lista_nazioni, alias, fuzzy match
  server.py       # FastMCP: i tool come viste
assistant/
  agent.py        # LangChain, system prompt con le regole di sicurezza
  cli.py
README.md         # architettura, discovery, scelte (inclusa quella sui PDF, con i numeri)
```

## Verifica

- `resolve_country`: "thailandia", "Thailand", "THA", "tailandia" (typo) → THA; input ambiguo →
  lista di candidati, nessuna scelta arbitraria.
- Paesi di controllo: **BRA** (digest più ricco del dettaglio), **THA** (nodo di primo piano che
  è solo rimando), **IND** (scheda più pesante, ~13.9k token: verificare che nessun tool la
  restituisca intera), un paese con `Rischio-terrorismo` vuoto (deve rispondere
  "non pubblicato", mai "nessun rischio").
- Robustezza: 404 su codice inesistente, timeout della fonte, payload con sezione inattesa →
  errore gestito, mai eccezione grezza.
- End-to-end: l'assistente risponde a "documenti per la Thailandia" citando fonte e data, e
  include il disclaimer.
