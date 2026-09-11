# Discovery delle fonti

Il sito è una SPA Angular: l'HTML servito non contiene i contenuti, e cercarli lì non porta da
nessuna parte. Le chiamate XHR stanno nei bundle `/build/main.*.js`, e da lì è uscita la mappa
degli endpoint. Tutto quello che segue è stato verificato con richieste reali; i numeri di questo
documento sono stati ricontrollati l'11 settembre 2026.

## Il percorso

Il primo endpoint utile è `lista_nazioni.json`: 222 Paesi con `Nome` (solo in italiano),
`Codice-3`, `Codice-2` e coordinate. È la chiave di tutto il resto, perché ogni altro endpoint
per Paese si indirizza con l'ISO3.

Da lì, per tentativi guidati dal bundle: `schede_paese/{ISO3}.json` risponde per **tutti e 222**
i codici della lista — nessun buco, che è il motivo per cui la risoluzione del nome può essere
severa invece di tollerante. Poi `ultima_ora/{ISO3}.json` per gli avvisi, `approfondimenti/*.json`
per le guide non legate a un Paese, e i due export PDF.

## Gli endpoint

| Endpoint | Forma del payload | Note |
|---|---|---|
| `/schede_paese/lista_nazioni.json` | lista di 222 oggetti | 72 KB, nessun duplicato |
| `/schede_paese/{ISO3}.json` | `{updateDate, <7 sezioni>}`, ogni sezione `{id, titolo, ordinamento, nodi:{...}}` | 12–124 KB, mediana 34 KB |
| `/ultima_ora/{ISO3}.json` | `{ultima_ora: [...], focus: [...]}` | 28 byte quando entrambi sono vuoti |
| `/ultima_ora/totale.json` | `{ultima_ora: 25, focus: 1, aggiornamentiSchedaPaese: 16}` | feed globale **troncato** |
| `/approfondimenti/{nome}.json` | `{<nome>: [ {nome, contenuto, sezioni:[...]} ]}`, albero ricorsivo | 12–216 KB |
| `/schede_paese/pdf/{ISO3}.pdf` | PDF della scheda | 11 pagine per ALB |
| `/schede_paese/pdf/{ISO3}_contactDetails.pdf` | PDF dei soli recapiti | 1 pagina, 2,6 KB |
| `/marker/marker_{ISO3}.json` | lista | **sempre `[]`** nei campioni: inutile |

Dentro una scheda: 7 sezioni (`infoCronologiaAggiornamenti`, `infoPrimopiano`, `infoGenerali`,
`infoRequisitiIngresso`, `infoSicurezza`, `infoSituazioneSanitaria`, `infoMobilita`) e 28 nodi
foglia, presenti in tutti i Paesi campionati. L'elenco completo è in
[docs/schede-paese.md](docs/schede-paese.md).

## La documentazione ufficiale esiste, ed è in parte sbagliata

La traccia assume fonti non documentate. Non è vero: nel **footer di ogni pagina** del sito, con
l'etichetta *"Web Services Viaggiare Sicuri"*, c'è un link a `/contenuti/JSON.pdf` — 77 KB,
`last-modified` **2 novembre 2021**, tuttora servito con 200. È un documento dell'Unità di Crisi
che elenca gli endpoint JSON: avvisi, schede paese, lista nazioni, approfondimenti.

Trovarla non ha reso inutile la discovery, perché la documentazione è vecchia di cinque anni,
parziale e in un punto **falsa**:

- non menziona gli endpoint PDF né `preparaunviaggio.json`;
- non descrive un solo campo, né la semantica, né la frequenza di aggiornamento, né le tre liste
  dentro `totale.json`;
- documenta `/approfondimenti/sicurezzaaerea.json` come **"Sicurezza aerea"**. L'endpoint risponde
  200, ma il contenuto è quello di "Preparare un viaggio" — stesse tre sezioni
  (`saluteinviaggio`, `assicurazionediviaggio`, `pacchittituristici`), 12.137 byte contro i 12.169
  di `preparaunviaggio.json`. Di sicurezza aerea non c'è una riga.

La lezione che porto in sede di colloquio non è "non c'era documentazione": è che la
documentazione è stata trovata **e verificata**, e verificarla ha prodotto più informazione che
leggerla.

## Le anomalie

**HTML annidato dentro il JSON.** Ogni campo `contenuto` e `testo` è HTML con entità non
decodificate (`&#039;`, `&rsquo;`, `&nbsp;`). Non è cosmesi: i recapiti delle ambasciate esistono
**solo** dentro `<a href="mailto:...">` e `tel:`, quindi una conversione a testo che scarta i tag
butta via il dato più operativo che il sistema serve. La normalizzazione estrae i link prima di
appiattire.

**`tsModifica` è una stringa, non un numero.** `"1787042700"`, non `1787042700`. Un parser che si
fida del tipo fallisce, e un parser che fallisce in silenzio ordina gli avvisi per stringa: con
timestamp a dieci cifre funziona quasi sempre, e smette di funzionare senza dirlo.

**"Presente ma vuoto" non è "assente".** Nessun nodo manca mai, ma molti sono stringa vuota.
`infoGenerali.Documentazione-necessaria` è vuoto in tutti i Paesi campionati;
`infoSicurezza.Rischi-ambientali-e-naturali` e `Aree-di-particolare-cautela` in circa un terzo.
È il rischio di sicurezza più serio dell'intero progetto: un campo "Rischio terrorismo" vuoto
**non** significa "nessun rischio terroristico". Da qui lo stato `not_published` nel contratto, e
il test di rete che sorveglia la quota (soglia al 20%, contro il 7,6% misurato quando è stato
scritto): se la fonte cambia politica editoriale, va rivisto il design, non il testo.

**Array vuoti come caso normale.** `ultima_ora/ALB.json` pesa 28 byte: entrambe le liste vuote.
Non è un errore né un'anomalia, è la condizione della maggioranza dei Paesi — e trattarla come un
errore avrebbe prodotto la risposta peggiore possibile, cioè nessuna risposta dove invece la fonte
ha semplicemente taciuto.

**`totale.json` non è un superset dei per-Paese.** Il solo Perù aveva 7 avvisi mentre `totale.json`
ne conteneva 25 in totale, di cui 3 peruviani. È un feed globale recente, non un archivio: per
Paese fa fede l'endpoint per Paese, e infatti è l'unico che il server usa.

**Lo stesso avviso differisce tra i due endpoint.** Per `ULTIMORA_MARKER_35345`, `tipologia` vale
`"sicurezza"` nella versione per Paese e `""` in `totale.json`; `follow` è l'opposto; il campo
`testo` ha una codifica HTML diversa nei due. Non esiste "il" formato: esiste un formato per
endpoint, e serve un modello unico a valle.

**Gli approfondimenti si smentiscono da soli.** Il payload di `saluteinviaggio.json` (216 KB,
quattro sezioni sulla salute) dichiara al primo livello `nome: "Preparare un viaggio"` — lo stesso
titolo di `preparaunviaggio.json`, che è un altro documento da 12 KB. I titoli dei documenti,
nell'indice semantico, sono quindi una mappa nostra, non un campo della fonte. E gli `id` delle
sezioni contengono refusi di redazione che vanno accettati come sono: `pacchittituristici`,
`prepareraunafarmacia`, `restituzionecarateidenta`.

**Nomi solo in italiano, e territori non sovrani.** "Isole Marianne Settentrionali", "Sint
Maarten". La risoluzione normalizza gli accenti, accetta alias inglesi e fa fuzzy match sui
refusi, ma sull'ambiguità non sceglie: "Corea" restituisce due candidati.

## Cosa ho cercato e non ho trovato

**Un endpoint dedicato ai recapiti di ambasciate e consolati: non esiste.** Ho cercato nel bundle
Angular, nella documentazione del 2021, in `marker/` (che risponde `[]`) e per analogia con gli
altri percorsi. Il tema è comunque coperto, perché i recapiti stanno dentro la scheda paese, nel
nodo `infoGenerali.Ambasciate-e-Consolati`, come prosa HTML con i contatti dentro i link — ed è
per questo che la normalizzazione li preserva invece di appiattire tutto a testo. In più,
`{ISO3}_contactDetails.pdf` è l'artefatto di una pagina, 2,6 KB, con i soli recapiti e il numero
di emergenza h24: è quello che un operatore inoltra a un cliente che ha perso il passaporto, non
le undici pagine della scheda intera. `get_embassy_contacts` restituisce entrambi.

**Un contratto d'uso per client automatici: non esiste.** `robots.txt` dice `Allow: /` senza un
solo `Disallow` e senza `Crawl-delay`; non c'è API key, non c'è rate limit dichiarato, non ci sono
termini d'uso per l'accesso programmatico. Il permesso tecnico c'è, la regola no — ed è la ragione
per cui il limite se lo impone il client: vedi l'ADR 4 in [DECISIONS.md](DECISIONS.md).

**Uno storico degli avvisi: non esiste.** Gli endpoint restituiscono lo stato di adesso. Il "cosa
è cambiato" va costruito conservando quello che si è già visto, ed è il primo mattone dell'agente
proattivo.

## ETag e Last-Modified: ci sono, e cambiano le cose

Tutti gli endpoint espongono entrambi gli header, e rispondono alle richieste condizionali:

```
$ curl -I .../schede_paese/ALB.json
etag: "166d88ad70ef24114ac6cde5d62bdc31"
last-modified: Fri, 31 Jul 2026 12:19:25 GMT
cache-control: public,max-age=0

$ curl -H 'If-None-Match: "166d88ad…"' .../schede_paese/ALB.json
HTTP 304 — 0 byte scaricati
```

La conseguenza è concreta e non è a favore dell'implementazione attuale. Oggi, alla scadenza del
TTL, il client riscarica il payload intero: 34 KB in mediana per una scheda. Con `If-None-Match`
la stessa verifica costerebbe un round-trip e zero byte, e renderebbe possibile un TTL molto più
corto senza pesare sulla fonte — cioè toglierebbe quasi per intero il limite che l'ADR 3 dichiara.

Vale anche la lettura opposta: `cache-control: public, max-age=0` dice che l'origine **si aspetta**
che i client rivalidino, e che considera la rivalidazione condizionale il comportamento normale.
Non implementarla è una scelta di tempo, non di design, ed è per questo che sta in cima a "cosa
farei con più tempo" nel README e non fra i limiti accettati.

## I PDF: misurati, poi esclusi

Prima di decidere se parsarli ho confrontato il testo estratto con il JSON: il **91,4%** del PDF
della scheda albanese si ritrova nel JSON e il **93,4%** del JSON nel PDF; il resto è intestazione
e rumore di estrazione. L'unico dato esclusivo del PDF è l'intestazione "Valida al 31/07/2026",
che coincide con la data di generazione del file.

Parsarli significherebbe ri-derivare con perdita dati già disponibili con chiavi strutturate, in
cambio di una dipendenza in più e della fragilità dell'estrazione di layout. Restano quindi
**artefatti esposti come URL**, che è anche il loro uso reale: un documento del Ministero, datato
e inoltrabile, sposta l'autorevolezza dall'operatore alla fonte.
