# Fase A — MCP server live sulla scheda paese

Prima fase: i tool interrogano Viaggiare Sicuri a ogni chiamata. Niente cache, niente
persistenza, niente RAG. L'obiettivo è avere un server MCP corretto e robusto su cui l'assistente
LangChain possa già rispondere, e da cui valutare *dopo* se serve altro.

Riferimento sui dati della fonte: [`schede-paese.md`](schede-paese.md).
Contesto e alternative scartate: [`piano-design.md`](piano-design.md).

---

## La domanda preliminare: i tool seguono la fonte o i nostri bisogni?

Né l'uno né l'altro in modo puro. La separazione che regge è:

- **Il contratto interno è fedele alla fonte.** Tutte e 7 le sezioni e tutti i 28 nodi vengono
  scaricati, validati e modellati con i loro id originali — anche quelli che l'agente non vedrà
  mai. È lo strato dove la fedeltà conta e dove una divergenza silenziosa sarebbe un problema.
- **La superficie dei tool è modellata sul bisogno dell'operatore.** È un'interfaccia, e il suo
  compito è farsi scegliere correttamente da un LLM e restituire il minimo utile.
- **In mezzo, una mappa dichiarativa** tema → (sezione, nodi). È l'unica cosa che può divergere
  dalla fonte, sta in una ventina di righe in un file solo, e si verifica a colpo d'occhio.

Il caso che dimostra perché serve la mappa è `get_embassy_contacts`: i recapiti stanno in
`infoGenerali.Ambasciate-e-Consolati`, ma esporre `infoGenerali` "così com'è" costringerebbe a
restituire anche `Dati-paese`, `Informazioni-utili` e `Indicazioni-per-operatori-economici` —
circa il doppio dei token, per una domanda su un numero di telefono.

Il caso opposto è altrettanto istruttivo: la traccia elenca *"requisiti di ingresso"* e
*"documenti di viaggio e visti"* come due temi, ma nella fonte sono un'unica sezione da ~430
token mediani. Qui **la fonte ha ragione e la traccia no**: due tool con descrizioni sovrapposte
si farebbero concorrenza in fase di selezione, per risparmiare niente. Un tool solo.

Regola operativa: si segue la fonte per default, si devia solo quando la deviazione si giustifica
con un numero (token risparmiati) o con un confine sbagliato della fonte.

### Lingua degli identificatori

Nomi di tool, campi e funzioni in inglese; **descrizioni dei tool in italiano**, perché sono ciò
che l'LLM legge per scegliere e perché il vocabolario è quello della fonte ("requisiti di
ingresso", "situazione sanitaria"). I contenuti restituiti restano ovviamente in italiano.

---

## `infoPrimopiano` non è un tema: è il fallback del dettaglio

Misurato su 36 paesi quanto spesso il nodo di primo piano è più lungo del dettaglio
corrispondente (rimandi esclusi): `Moneta` 0%, `Ambasciata` 3%, `Documenti-e-visti` 8%,
`Vaccinazioni` 42% ma con testo quasi identico, `Aree-di-particolare-cautela` 50%. È uno strato
di sintesi: **non viene esposto come tool**, non esiste un `get_country_overview`.

Viene però usato come **fallback quando il nodo di dettaglio è vuoto**. La fonte non omette mai
un nodo, lo lascia vuoto: sul censimento dei 222 paesi
`infoSicurezza.Aree-di-particolare-cautela` è vuoto in **82 casi (37%)**, mentre il nodo di
primo piano corrispondente **non è mai vuoto in nessun paese**. In quei casi il primo piano dice
*"Si raccomanda di adottare le normali precauzioni richieste da un viaggio all'estero"* (Austria,
Belgio, Francia, Lussemburgo, Stati Uniti) o, per Paraguay e Mayotte, indicazioni specifiche.
Senza fallback quei paesi otterrebbero "non pubblicato dalla fonte" quando la fonte, in realtà,
si è espressa — e sono le destinazioni europee su cui il customer care lavora di più.

Mappa del fallback — regola unica, nessuna eccezione da spiegare:

| Nodo di primo piano | Sostituisce, se vuoto |
|---|---|
| `Documenti-e-visti` | `infoRequisitiIngresso.Passaporto` + `.Visto-di-ingresso` |
| `Vaccinazioni` | `infoSituazioneSanitaria.Vaccinazioni-obbligatorie` |
| `Aree-di-particolare-cautela` | `infoSicurezza.Aree-di-particolare-cautela` |
| `Ambasciata` | `infoGenerali.Ambasciate-e-Consolati` |
| `Moneta` | `infoGenerali.Dati-paese` |

Per costruzione non c'è mai duplicazione: il primo piano compare **solo** dove il dettaglio tace.
Con i dati attuali scatta quasi soltanto sulle aree di cautela, ma la regola regge se domani la
fonte svuota qualcos'altro. Ogni contenuto servito per fallback dichiara la provenienza.

---

## Contratti

### Ingresso

Ogni tool di contenuto accetta un solo parametro paese, che tollera nome italiano, alias inglese
o codice ISO. La risoluzione è un problema a sé e ha un tool dedicato.

```python
class CountryRef(BaseModel):
    name: str      # "Thailandia"
    iso3: str      # "THA"  <- la chiave usata da tutti gli endpoint
    iso2: str      # "TH"

class CountryMatch(BaseModel):
    match: CountryRef | None
    candidates: list[CountryRef] = []          # valorizzato se ambiguo
    confidence: Literal["exact", "alias", "fuzzy"]
```

In caso di ambiguità il tool **non sceglie**: restituisce i candidati e lascia decidere
all'agente, che può chiedere all'operatore.

### Dominio (fedele alla fonte, tutti i 28 nodi)

```python
class Link(BaseModel):
    text: str
    url: str
    kind: Literal["web", "email", "phone"]

class Topic(BaseModel):
    id: str                                     # "Visto-di-ingresso", slug della fonte
    title: str                                  # "Visto di ingresso"
    text: str                                   # HTML normalizzato
    status: Literal["available", "not_published"]
    provenance: Literal["detail", "summary"]    # "summary" = servito per fallback
    see_also: list[str] = []                    # ["infoSicurezza"], dai rimandi
    links: list[Link] = []

class Section(BaseModel):
    id: str
    title: str
    topics: list[Topic]

class CountrySheet(BaseModel):
    country: CountryRef
    updated_at: datetime                        # da updateDate
    sections: dict[str, Section]                # tutte, anche quelle non esposte
```

`status="not_published"` è il cuore del contratto: la fonte non omette mai un nodo, lo lascia
vuoto. Va distinto esplicitamente, perché `Rischio-terrorismo` vuoto **non significa** assenza
di rischio. Il vincolo va ripetuto nel system prompt dell'assistente.

`provenance` esiste perché una risposta costruita sul riassunto non è una risposta di pari
livello: l'assistente deve poterlo dire.

### Risposta dei tool

Envelope unico, generico, così le allerte della fase B ci entrano senza riaprire il contratto.

```python
class Source(BaseModel):
    page: str                                   # pagina web ufficiale, da citare all'operatore
    data: str                                   # endpoint JSON effettivamente interrogato
    pdf: str | None                             # scheda PDF, da inoltrare al cliente

T = TypeVar("T")

class ToolResponse(BaseModel, Generic[T]):
    country: CountryRef
    topic: str                                  # "Requisiti di ingresso"
    data: T
    updated_at: datetime | None
    sources: Source
    notice: str                                 # disclaimer, sempre presente
```

### Errori

Distinzione netta fra "non ho capito la domanda" e "la fonte non risponde":

| situazione | comportamento |
|---|---|
| paese ambiguo | risposta normale con `candidates`, nessuna scelta arbitraria |
| paese inesistente | errore `country_not_found`, con suggerimento dei più simili |
| fonte irraggiungibile / timeout | errore `source_unavailable`, messaggio esplicito |
| payload con struttura inattesa | errore `unexpected_payload`, **mai** un parse silenzioso a vuoto |

L'ultimo caso è quello che conta: se la fonte cambia forma, il server deve fallire in modo
rumoroso, non restituire una scheda mezza vuota che l'assistente presenterebbe come "nessuna
informazione disponibile".

---

## Superficie dei tool

Costi da censimento su 222 paesi (mediana, e massimo dove conta):

| Tool | Mappa su | Costo tipico |
|---|---|---|
| `find_country(query)` | `lista_nazioni.json` | trascurabile |
| `get_entry_requirements(country, topics=None)` | `infoRequisitiIngresso` (copre 2 temi della traccia) | ~583 tok, max ~6.3k |
| `get_security_info(country, topics=None)` | `infoSicurezza` | ~1.333 tok, max ~8.6k |
| `get_health_info(country)` | `infoSituazioneSanitaria` | ~621 tok |
| `get_local_transport(country)` | `infoMobilita` | ~480 tok |
| `get_embassy_contacts(country)` | `infoGenerali.Ambasciate-e-Consolati` | ~340 tok |
| `get_practical_info(country)` | `infoGenerali.Dati-paese` + `.Informazioni-utili` | ~500 tok |
| `get_recent_alerts(country)` | `/ultima_ora/{iso3}.json` | variabile (7 avvisi THA ≈ 2.070 tok) |

`get_practical_info` non copre un tema della traccia ma vale il suo costo: `Informazioni-utili`
contiene i **numeri di emergenza locali** (pronto soccorso, polizia) e `Dati-paese` moneta, fuso
orario, prefissi e copertura di rete — le domande che un operatore riceve di continuo.

Il parametro `topics` esiste sulle tre sezioni che possono esplodere — sicurezza (~8.6k token nel
caso peggiore), requisiti di ingresso (~6.3k) e situazione sanitaria (~3k) — contro mediane di
1.3k, 0.6k e 0.6k. Sulle altre sarebbe complessità senza guadagno. Sull'India, chiedere i soli
vaccini invece dell'intera sezione sanitaria costa 306 token invece di 4.501.

Il filtro accetta tre forme dello stesso valore — `local_laws`, `security.local_laws` e l'id
della fonte `Normative-locali-rilevanti` — perché sono tutte stringhe che il modello vede nelle
risposte. Un valore non riconosciuto è un errore esplicito: una lista vuota verrebbe letta come
"la fonte non pubblica nulla su questo tema", che è esattamente la bugia che il progetto vuole
evitare.

**Scaricati e contrattualizzati ma non esposti**: `infoPrimopiano` (solo fallback),
`infoCronologiaAggiornamenti` (changelog redazionale, tornerà utile come segnale per l'agente
proattivo), `infoGenerali.Indicazioni-per-operatori-economici` (ICE e camere di commercio: fuori
scope per un viaggiatore), `infoGenerali.Documentazione-necessaria` (vuoto in 25/25).

Fuori fase A, già previsto dall'envelope: `get_recent_alerts(country)` su
`/ultima_ora/{iso3}.json`. Da fare comunque prima della consegna, perché "allerte e avvisi
recenti" è uno dei temi richiesti: l'endpoint è piccolo e piatto, è lavoro contenuto.

---

## Normalizzazione

Quattro operazioni, nell'ordine, in `normalize.py`:

1. **Estrarre i link prima di toccare i tag.** I recapiti delle ambasciate vivono dentro
   `<a href="mailto:...">`: strippare l'HTML per primo li perde. `kind` si deduce dallo schema
   dell'URL (`mailto:` → email, `tel:` → phone, altrimenti web).
2. **HTML → testo.** Decodifica delle entità (la fonte serve `&rsquo;` e `&#039;` non decodificati),
   rimozione dei tag preservando gli a capo di paragrafo, collasso degli spazi.
3. **Estrarre i rimandi in `see_also`.** Frasi tipo "consultare la Sezione Sicurezza di questa
   Scheda", presenti in 35/35 paesi. Non è cosmesi: quando un nodo di primo piano viene servito
   per fallback dentro `get_security_info`, il suo rimando punta proprio alla sezione che
   l'operatore ha appena chiesto (caso reale: Slovacchia). Lasciarlo nel testo produrrebbe una
   risposta che rimanda a se stessa.
4. **Determinare `status`.** Contenuto vuoto o di soli spazi → `not_published`, e a quel punto
   scatta il fallback sul primo piano se esiste una coppia mappata.

---

## Struttura dei file

```
server.py             # entry point per i launcher che caricano il server per path
pyproject.toml        # pacchetto + comando `viaggiaresicuri-mcp`
viaggiaresicuri_mcp/
  config.py           # endpoint e parametri, sovrascrivibili da variabile d'ambiente
  client.py           # httpx async, retry con backoff, traduzione degli errori
  errors.py           # gerarchia degli errori del server
  countries.py        # lista_nazioni, alias, fuzzy match, ambiguità
  normalize.py        # HTML -> testo, link, rimandi, stato del nodo
  models.py           # i contratti: scheda, avvisi, envelope
  sheet.py            # fetch_sheet(iso3) -> CountrySheet, fallback, topic_map
  alerts.py           # fetch_alerts(iso3) -> list[Alert]
  server.py           # FastMCP: i tool come viste sul contratto
tests/                # 115 test offline + 8 sulla fonte reale
```

Il modulo di rete si chiama `client.py` e non `http.py` per una ragione concreta: i launcher che
caricano il server indicando un file mettono la cartella del pacchetto in testa a `sys.path`, e
un modulo chiamato `http` maschera quello della standard library facendo fallire l'avvio.
Per lo stesso motivo esiste `server.py` alla radice: `fastmcp run` importa il file come modulo
isolato, quindi gli import relativi interni al pacchetto non funzionerebbero.

**Tutto passa da `fetch_sheet(iso3)`.** Un solo punto di rete, un solo punto di parsing: è lì che
in fase B si appoggia la cache, con un decoratore e senza toccare i tool. La giuntura si prepara
adesso anche se la cache non si scrive.

---

## Ordine di lavoro

1. `models.py` + `mapping.py` — i contratti prima di tutto, così il resto ha un bersaglio.
2. `http.py` + `countries.py` — rete e risoluzione paese, verificabili da soli.
3. `normalize.py` + test — è la parte con più logica e più casi limite, va testata isolata.
4. `sheet.py` — composizione: fetch, validazione, normalizzazione, fallback, `CountrySheet`.
5. `server.py` — i tool, che a questo punto sono viste sottili sul modello.
6. Test di aderenza della mappa e prova end-to-end sui paesi di controllo.

---

## Verifica

**Test automatici**

- `test_mapping.py`: per ogni voce di `TOPIC_MAP` e `FALLBACK_MAP`, scaricare 2–3 schede reali e
  verificare che sezione e nodo esistano davvero. È la rete di sicurezza contro la deriva della
  mappa: se la fonte rinomina un nodo, il test rompe invece che restituire silenziosamente il
  vuoto.
- `test_normalize.py`: entità HTML decodificate; link `mailto:` e `tel:` estratti con `kind`
  giusto; rimando riconosciuto e rimosso dal testo; contenuto vuoto → `not_published`.

**Paesi di controllo**

| Paese | Perché |
|---|---|
| **AUT** o **FRA** | dettaglio aree di cautela vuoto: deve scattare il fallback con `provenance="summary"`, non "non pubblicato" |
| **PRY** | fallback con contenuto specifico (Ciudad del Este, centro storico di Assunzione): non deve andare perso |
| **SVK** | il testo di fallback contiene un rimando alla sezione Sicurezza: dopo la normalizzazione non deve rimandare a se stesso |
| **BRA** | contatti consolari su sei città: `get_embassy_contacts` deve restituirli tutti, non solo Brasilia |
| **USA** | scheda più pesante (~18.7k token): nessun tool deve restituirla intera |
| un paese con `Rischio-terrorismo` vuoto | nessun fallback mappato: deve dire "non pubblicato dalla fonte", mai "nessun rischio" |

**Robustezza**

ISO3 inesistente → `country_not_found`; timeout della fonte → `source_unavailable`; payload
alterato (togliere una sezione da una copia locale) → `unexpected_payload`. In nessun caso
un'eccezione grezza deve arrivare all'agente.

**Fine fase A**: l'assistente risponde a "che documenti servono per la Thailandia" citando fonte,
data di aggiornamento e disclaimer, e sa dire "non pubblicato" senza inventare rassicurazioni.

---

## Cosa resta fuori, e dove sono le giunture

| Rimandato | Perché | Giuntura già pronta |
|---|---|---|
| Cache | prima misuriamo se la latenza dà davvero fastidio | `fetch_sheet()`, punto unico |
| Persistenza / storico | serve all'agente proattivo, non all'assistente | — |
| Approfondimenti (`/approfondimenti/*.json`) | vedi sotto: non è più un "nice to have" | envelope generico `ToolResponse[T]` |

Le allerte non sono più rimandate: `get_recent_alerts` è implementato, perché senza non si può
rispondere a "posso partire adesso" — per la Thailandia ci sono 7 avvisi attivi, fra cui
inondazioni nel nord, e nella scheda paese quelle parole non compaiono mai.

**Gli approfondimenti sono il buco che resta.** In molti Paesi `entry.minors` non contiene la
norma ma un rinvio all'approfondimento "Documenti di viaggio": alla domanda "che documenti
servono per mio figlio di 8 anni" oggi si può solo rimandare l'operatore al sito.
`documentidiviaggio.json` pesa 14 KB e ha 4 sezioni con nomi espliciti: basta un tool che
restituisce l'indice e la sezione scelta, senza bisogno di RAG.
