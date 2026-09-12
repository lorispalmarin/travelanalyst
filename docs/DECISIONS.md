# Decisioni

Sette scelte che spiegano perché il codice è come è. Le misure citate stanno in
[DISCOVERY.md](DISCOVERY.md).

## 1. Tool granulari, non un tool per endpoint

**Contesto.** Gli endpoint sono tre: lista Paesi, scheda, avvisi. Un tool per endpoint sarebbe
stata la mappatura più diretta, ma la scheda intera pesa in mediana ~4.600 token e arriva a
~13.900 per l'India.

**Decisione.** Un solo contratto Pydantic per la scheda, e tool che ne restituiscono **viste**
per sezione: requisiti d'ingresso, sicurezza, salute, mobilità, ambasciate, informazioni
pratiche. Più due tool sull'indice dei 28 nodi per le domande che non stanno in nessun tema. Il
taglio si ferma alla sezione: una sezione costa poche centinaia di token, e dentro
`infoRequisitiIngresso` il modello distingue benissimo passaporto e visto.

**Conseguenze.** Il contesto resta pulito anche su conversazioni che toccano due Paesi. Il routing
diventa una proprietà delle docstring, che vanno scritte come istruzioni operative e non come
descrizioni. In cambio ci sono 11 tool da tenere coerenti invece di 3, e ogni nuova sezione della
fonte richiede una scelta esplicita su dove esporla.

## 2. Deterministico sulle schede, semantico solo sugli approfondimenti

**Contesto.** Entrambe le fonti sono JSON. La tentazione è trattarle allo stesso modo, in un verso
(tutto RAG) o nell'altro (tutto chiavi).

**Decisione.** Le schede paese si interrogano per chiave: Paese × sezione. Gli approfondimenti
passano da un indice semantico. **La regola non è il formato, è la forma del contenuto e il suo
volume.** Le schede sono già indicizzate sugli stessi assi su cui arrivano le domande — c'è una
chiave per "Paese" e una per "requisiti d'ingresso" — quindi un embedding non aggiungerebbe nulla
e toglierebbe determinismo: 222 documenti, struttura identica, risposta esatta. Gli approfondimenti
sono due documenti di prosa, 230 KB, dove la risposta a "cosa faccio se perdo il passaporto" sta
in un paragrafo che non ha una chiave.

**Conseguenze.** Il grosso delle risposte è riproducibile e verificabile riga per riga. Il RAG
esiste dove serve e resta piccolo: 124 chunk in una matrice numpy, nessun vector database. Il
prezzo è che ci sono due modalità di accesso da spiegare, e che il routing fra le due va imposto
nelle docstring e verificato sull'agente vero — cosa che la eval fa.

## 3. Un TTL solo, ma la rivalidazione è condizionale

**Contesto.** I contenuti della fonte si muovono a ritmi diversi: i requisiti d'ingresso a mesi,
il primo piano a settimane, gli avvisi in modo imprevedibile. Un TTL unico è quindi sempre
sbagliato per qualcuno.

**Decisione.** Un TTL unico, sei ore, configurabile (`VS_CACHE_TTL_SECONDS`), con **una sola**
eccezione dichiarata (ADR 5) — e, alla scadenza, una richiesta **condizionale** invece di un
nuovo scaricamento: `If-None-Match` con l'ETag memorizzato, o `If-Modified-Since` quando l'ETag
manca. La fonte risponde 304 se non è cambiato niente, e allora si aggiorna solo il momento
della verifica.

**Conseguenze.** Il costo della soglia scaduta passa da 48 KB a zero byte e da 148 ms a 9 ms
(misure in [DISCOVERY.md](DISCOVERY.md)). Il limite che resta cambia natura: non è più banda
sprecata, è **latenza** — un round trip su ogni tool call che supera la soglia, e quella è la
ragione per non scendere a TTL di minuti su tutto. Resta vero che una scheda modificata dieci
minuti fa può essere servita nella versione di sei ore prima; TTL differenziati per tipo di
contenuto sarebbero preferibili e restano non implementati, ma ora costano molto meno di prima.

C'è anche una ragione che non è di efficienza: `cache-control: public, max-age=0` più i validator
è il modo in cui l'origine dice "rivalida, non riscaricare". Farlo è rispettare una politica che
la fonte dichiara — che è l'altra metà dell'ADR 4.

## 4. Il TTL non cancella niente: stale-if-error, e una ragione etica

**Contesto.** Una cache-library normale sfratta le entry scadute. Qui la fonte è un servizio
pubblico che può essere irraggiungibile proprio nel momento in cui serve.

**Decisione.** Il TTL è una **soglia di rivalidazione, non una scadenza**: nessuna entry viene mai
cancellata. Scaduta la soglia si *tenta* il refetch; se fallisce si serve comunque la copia
vecchia, dichiarata `stale` nel campo `meta`, qualunque sia la sua età. Se il sito è giù da otto
ore e il TTL è sei, la risposta arriva lo stesso. Solo la combinazione "entry assente **e** fonte
irraggiungibile" produce un errore esplicito — mai un ripiego sulla memoria del modello.

**Conseguenze.** L'assistente sopravvive a un'interruzione della fonte, ma non può farlo in
silenzio: da qui il banner in testa alla risposta e i campi `cache_status` e `age_seconds`.

**E la ragione che viene prima dell'uptime.** Viaggiare Sicuri è un servizio del Ministero degli
Affari Esteri finanziato con risorse pubbliche, che non espone API documentate né alcun contratto
d'uso per client automatici: `robots.txt` non dichiara né limiti né cadenze. Un agente che
rigenera traffico a ogni tool call × turno di conversazione × sviluppatore impone un costo a
un'infrastruttura pubblica in cambio di niente, visto che quei contenuti si muovono su scala di
settimane. Il permesso tecnico non è un'autorizzazione: il limite se lo mette il client.

Un contratto d'uso non c'è, ma una **politica di cache** sì, e va letta come tale: gli header
della fonte dicono `cache-control: public, max-age=0` e portano ETag e Last-Modified. Tradotto:
"rivalida quando vuoi, ma non ripeterti il download". È l'unica indicazione che l'origine dà su
come vuole essere interrogata, e il client la segue (ADR 3). Autolimitarsi scegliendo un TTL
mentre si ignora ciò che la fonte chiede sarebbe stato un rispetto solo dichiarato.

## 5. Sugli avvisi il TTL scende a 15 minuti

**Contesto.** La misura dice il contrario dell'intuizione. I `tsModifica` reali mettono gli avvisi
sulla scala delle settimane: Ucraina 18 agosto 2026, Israele 6 maggio 2026, i sette della
Thailandia distribuiti fra giugno e settembre; `ultima_ora/ALB.json` ha `last-modified` 27 luglio.
Con numeri così, un TTL di sei ore sarebbe stato statisticamente quasi innocuo.

**Decisione.** 15 minuti lo stesso, implementati come parametro sulla singola chiamata —
`client.fetch(path, ttl_seconds=...)`, un solo chiamante — e non come una tassonomia di TTL.

**Conseguenze.** La scelta non viene dalla frequenza ma dall'**asimmetria del costo d'errore**:
servire una scheda paese vecchia di sei ore non cambia nulla, servire "nessuna allerta" sei ore
dopo che ne è stata pubblicata una su un'emergenza in corso è il peggior guasto che questo sistema
possa produrre. Quando le probabilità sono basse e le conseguenze asimmetriche si paga per la
coda, non per la media — e qui il prezzo è minimo, perché il payload pesa poche decine di byte nel
caso comune. Resta un'eccezione singola e dichiarata: la seconda richiederebbe l'infrastruttura
che l'ADR 3 ha rimandato.

## 6. Grounding per prevenzione strutturale, non un judge a runtime

**Contesto.** Il rischio principale non è che il modello inventi un numero di telefono: è che
trasformi un silenzio della fonte in una rassicurazione. "Rischio terrorismo" vuoto letto come
"nessun rischio", array di avvisi vuoto letto come "Paese sicuro", copia locale vecchia letta come
situazione di adesso. La contromisura ovvia è un secondo modello che giudichi la risposta.

**Decisione.** Nessun judge. Le distinzioni che contano stanno **nello schema**, dove non possono
essere dimenticate: `status="not_published"` invece di una stringa vuota; `provenance="summary"`
quando il contenuto viene dal primo piano perché il dettaglio manca; `Avvisi.stato` con tre valori
distinti — avvisi presenti, nessun avviso pubblicato, non verificabile — e `Avvisi.messaggio` che
contiene la frase **già scritta** per ciascuno; `meta.cache_status` con il banner anteposto dal
codice, non dal modello.

**Conseguenze.** Il costo è zero a runtime e il comportamento è deterministico: un campo non
compete con il resto del prompt e non si degrada quando il contesto si allunga. Un judge avrebbe
aggiunto una chiamata per risposta, latenza, e un secondo modello da valutare — per controllare a
valle una proprietà che si può garantire a monte. Quello che lo schema non può impedire è che il
modello parafrasi male ciò che riceve, ed è esattamente ciò che la eval verifica: che in stato
`non_verificabile` la risposta contenga "non posso verificare" e **non** "nessun avviso".

## 7. Valutato e non implementato

Elencato qui perché "non c'è" e "non ci ho pensato" sono due cose diverse.

- **Vector database** (Chroma, Qdrant, FAISS, pgvector): 124 chunk stanno in una matrice numpy da
  1,2 MB. Un servizio in più non avrebbe comprato niente.
- **BM25, ricerca ibrida, reciprocal rank fusion**: è l'unica voce di questa lista con una prova a
  favore. Per "smarrimento del passaporto" il chunk giusto arriva **secondo**, battuto da quello
  sulla restituzione di documenti rinvenuti all'estero: un segnale lessicale lo rimetterebbe primo.
  Prima però serve un set di query con recall misurato, altrimenti si ottimizza su un aneddoto.
- **Reranking, cross-encoder, LLM-as-judge sui risultati**: costo per query su un corpus dove il
  primo risultato è quasi sempre giusto.
- **Query rewriting, HyDE, query expansion**: le domande arrivano da operatori e sono già
  specifiche.
- **LlamaIndex, retriever LangChain**: l'intera ricerca è `matrice @ vettore` più un `argsort`.
- **Chunking a finestra scorrevole con overlap**: l'albero delle sezioni dà già confini semantici
  veri, e il breadcrumb li rende leggibili nella risposta.
- **Parsing dei PDF**: misurata una sovrapposizione del 91–93% con il JSON. Si esporrebbero come
  URL comunque, che è anche il loro uso reale.
- **Classificazione di severità con LLM, deduplica, notifiche, scheduling**: appartengono
  all'agente proattivo, e in buona parte non vanno costruite — la fonte fornisce già `id` stabile,
  `tsModifica` e `tipologia`. Vedi [PROACTIVE_AGENT.md](PROACTIVE_AGENT.md).
