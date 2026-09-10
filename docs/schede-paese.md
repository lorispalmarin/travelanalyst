# Endpoint scheda paese — struttura di riferimento

Fonte: `https://www.viaggiaresicuri.it` — dati rilevati il 2026-09-09.

```bash
curl --request GET --url https://www.viaggiaresicuri.it/schede_paese/ALB.json
```

Il path usa il **codice ISO a 3 lettere** (`Codice-3` di `lista_nazioni.json`), non il codice a 2.
Tutti i 222 paesi in lista rispondono 200.

---

## Forma generale

Due livelli fissi: `sezione → nodi → nodo foglia`.

```jsonc
{
  "updateDate": "2026-07-30T22:00:00Z",     // unico campo scalare al top level

  "infoRequisitiIngresso": {                 // una delle 7 sezioni
    "id": "infoRequisitiIngresso",
    "titolo": "Requisiti di ingresso",
    "ordinamento": 2,
    "nodi": {
      "Passaporto": {                        // chiave del nodo = slug, non leggibile
        "titolo": "Passaporto",              // titolo leggibile
        "contenuto": "<p>E' necessario viaggiare con un <strong>Passaporto oppure CIE</strong>...</p>",
        "ordinamento": 0
      },
      "Visto-di-ingresso": { "titolo": "...", "contenuto": "...", "ordinamento": 1 }
    }
  }
}
```

**Schema del nodo foglia**: sempre e solo `titolo`, `contenuto`, `ordinamento`.
`contenuto` è HTML come stringa, con entità non decodificate (`&rsquo;`, `&#039;`).

---

## Le 7 sezioni e i loro 28 nodi

Censiti su **tutti i 222 paesi** (`scripts/report_campi_vuoti.py`): nessun nodo manca mai,
nessuna variazione di chiavi tra paesi, nessuna sezione inattesa. La colonna "vuoto" indica in
quanti paesi il nodo esiste ma `contenuto` è "".

| Sezione (`ordinamento`) | Nodo | Vuoto |
|---|---|---|
| `infoCronologiaAggiornamenti` (0) | `Cronologia-aggiornamenti` | 0/222 |
| `infoPrimopiano` (0) | `Documenti-e-visti` | 0/222 |
| | `Vaccinazioni` | 0/222 |
| | `Moneta` | 0/222 |
| | `Aree-di-particolare-cautela` | 0/222 |
| | `Ambasciata` | 0/222 |
| `infoGenerali` (1) | `Dati-paese` | 0/222 |
| | `Ambasciate-e-Consolati` | 0/222 |
| | `Informazioni-utili` | 2/222 |
| | `Indicazioni-per-operatori-economici` | 6/222 |
| | `Documentazione-necessaria` | **222/222** |
| `infoRequisitiIngresso` (2) | `Passaporto` | 0/222 |
| | `Visto-di-ingresso` | 0/222 |
| | `Viaggi-all-estero-dei-minori` | 0/222 |
| | `Formalit--doganali-e-valutarie` | 2/222 |
| | `Altre-informazioni` | 14/222 |
| `infoSicurezza` (3) | `Indicazioni-generali` | 1/222 |
| | `Rischio-terrorismo` | 1/222 |
| | `Rischi-ambientali-e-naturali` | **48/222 (22%)** |
| | `Aree-di-particolare-cautela` | **82/222 (37%)** |
| | `Avvertenze` | 1/222 |
| | `Normative-locali-rilevanti` | 4/222 |
| | `Informazioni-per-le-aziende` | **34/222 (15%)** |
| `infoSituazioneSanitaria` (4) | `Strutture-sanitarie` | 2/222 |
| | `Malattie-presenti` | 10/222 |
| | `Avvertenze` | 6/222 |
| | `Vaccinazioni-obbligatorie` | 0/222 |
| `infoMobilita` (5) | `Mobilita` | 0/222 |

**I cinque nodi di `infoPrimopiano` non sono mai vuoti in nessun paese**, mentre i nodi di
dettaglio corrispondenti lo sono fino al 37%: il riassunto è disponibile esattamente quando
serve come fallback.

Con un'eccezione che si vede solo dopo la normalizzazione: **26 nodi di primo piano su 1.110
(2,3%) contengono soltanto un rimando ad altre sezioni**, quindi una volta tolto il rimando non
resta niente — 12 su `Aree-di-particolare-cautela`, 11 su `Documenti-e-visti`, 3 su
`Vaccinazioni`. Per sei paesi (**Polonia, Nuova Zelanda, Dominica, Madagascar, Gambia, Timor
Est**) questo si combina col dettaglio vuoto e produce un **vicolo cieco della fonte**: il primo
piano dice "consultare la Sezione Sicurezza", e quella sezione è vuota. Lì la risposta corretta è
"non pubblicato", non una rassicurazione. Il fallback copre comunque 76 casi su 82 (93%).

I campi vuoti si concentrano sulle destinazioni europee più battute — Paesi Bassi 6 nodi vuoti
su 28, Francia, Belgio e Andorra 5, Austria, Giappone, Malta e Monaco 4 — cioè proprio i paesi
di cui un customer care parla più spesso.

Note sui nomi: `Formalit--doganali-e-valutarie` ha il doppio trattino al posto di "à".
`Vaccinazioni-obbligatorie` ha `titolo` "Vaccinazioni". Le chiavi sono slug della fonte, non
identificatori stabili per contratto: vanno mappate, non usate direttamente in risposta.

---

## Mappatura sui temi richiesti

| Tema | Dove sta |
|---|---|
| Requisiti di ingresso | `infoRequisitiIngresso` (tutti i nodi) |
| Documenti di viaggio e visti | `infoRequisitiIngresso.Passaporto` + `.Visto-di-ingresso` |
| Avvisi e sicurezza | `infoSicurezza` (tutti i nodi) |
| Situazione sanitaria | `infoSituazioneSanitaria` (tutti i nodi) |
| Mobilità e trasporti | `infoMobilita.Mobilita` |
| Ambasciate e consolati | `infoGenerali.Ambasciate-e-Consolati` |
| Allerte e avvisi recenti | **altro endpoint**: `/ultima_ora/{COD3}.json` |

---

## Dimensioni (testo ripulito dall'HTML, censimento su 222 paesi)

| Sezione | Mediana | Max |
|---|---|---|
| `infoSicurezza` | ~1.333 tok | ~8.581 tok |
| `infoGenerali` | ~738 tok | ~6.026 tok |
| `infoSituazioneSanitaria` | ~621 tok | ~2.986 tok |
| `infoRequisitiIngresso` | ~583 tok | ~6.293 tok |
| `infoMobilita` | ~480 tok | ~2.817 tok |
| `infoPrimopiano` | ~364 tok | ~1.150 tok |
| `infoCronologiaAggiornamenti` | ~143 tok | ~763 tok |
| **scheda intera** | **~4.930 tok** | **~18.681 tok** (Stati Uniti) |

Payload grezzo: 12–124 KB, mediana 34 KB. Il rapporto fra mediana e massimo è quasi 4×: una
scheda "tipica" costa poco, il caso peggiore no.

---

## Trappole da ricordare

1. **"Vuoto" non vuol dire "nessun rischio".** `Aree-di-particolare-cautela` è vuoto nel 37% dei
   paesi, `Rischi-ambientali-e-naturali` nel 22%, `Informazioni-per-le-aziende` nel 15%. Vanno
   esposti come "non pubblicato dalla fonte", mai come assenza di pericolo.
2. **`infoPrimopiano` è lo strato di sintesi**, con un rimando esplicito ad altre sezioni
   ("consultare la Sezione Sicurezza di questa Scheda"): presente in 35/35 paesi per
   `Vaccinazioni`, 34/35 per `Documenti-e-visti`, 32/35 per `Aree-di-particolare-cautela`.
   In un paio di casi il nodo è *solo* il rimando (Thailandia, `Aree-di-particolare-cautela`).
3. **Non vale `dettaglio ⊇ sintesi`.** Per il Brasile `infoPrimopiano.Documenti-e-visti` (886
   char) è più ricco di `Passaporto` + `Visto-di-ingresso` messi insieme (489 char).
4. **`Moneta` non è prosa**: mediana 16 caratteri, è un valore.
5. **HTML da normalizzare**: i recapiti delle ambasciate stanno dentro
   `<a href="mailto:...">`, quindi togliere i tag senza estrarre i link perde i contatti.
6. **`updateDate` è disomogeneo** tra paesi: da 2025-01-06 a 2026-09-09, mediana 2026-06-04, con
   5 schede su 222 più vecchie di un anno rispetto alla più recente. Va sempre esposto in
   risposta.

---

## Endpoint collegati

| URL | Contenuto |
|---|---|
| `/schede_paese/lista_nazioni.json` | 222 paesi: `Nome` (IT), `Codice-3`, `Codice-2`, coordinate |
| `/ultima_ora/{COD3}.json` | allerte del paese: `{ultima_ora: [], focus: []}` |
| `/ultima_ora/totale.json` | feed globale: `ultima_ora`, `focus`, `aggiornamentiSchedaPaese` |
| `/schede_paese/pdf/{COD3}.pdf` | export PDF della scheda (11 pagine) |
| `/schede_paese/pdf/{COD3}_contactDetails.pdf` | export PDF dei soli contatti (1 pagina) |
| `/approfondimenti/{nome}.json` | guide generali non per-paese |
| `/contenuti/JSON.pdf` | documentazione ufficiale dell'Unità di Crisi (2021, parziale) |

Item di `ultima_ora`: `{id, nazione, tipologia, titolo, testo (HTML), follow, url, tsModifica}`,
più `lat`/`lon` nella versione per-paese. `id` stabile (`ULTIMORA_MARKER_35404`), `tsModifica`
unix timestamp come stringa.
