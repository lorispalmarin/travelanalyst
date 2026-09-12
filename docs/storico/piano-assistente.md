# Piano — assistente LangChain

Secondo pezzo della consegna: l'assistente che gli operatori interrogano, costruito **solo** sui
tool del server MCP. Il server è completo e testato ([README](../README.md)); questo documento
progetta ciò che gli sta davanti.

---

## Cosa chiede la traccia, e dove viene soddisfatto

| Requisito | Dove |
|---|---|
| Sviluppo con **LangChain** | `create_agent` di LangChain 1.4 |
| Interrogabile via **CLI o web** | CLI interattiva (la traccia chiede l'una *o* l'altra); web solo se avanza tempo |
| Usa **esclusivamente** i tool del server MCP | nessun altro tool registrato, e il system prompt vieta di rispondere a memoria |
| I 7 temi dello scenario | coperti dai 10 tool del server |
| Informazioni aggiornate e da **fonti verificabili** | ogni risposta cita URL e data di aggiornamento presi dall'envelope |
| Non sostituirsi alle autorità, niente pareri legali o sanitari | regola nel system prompt, verificata nella eval |
| Evidenziare che le informazioni **possono variare** | disclaimer presente in ogni envelope e ripetuto in chiusura di risposta |

Resta fuori da questo piano l'agente autonomo proattivo, che la traccia richiede solo come
progetto: sarà un documento a parte.

---

## Architettura

```
   operatore
      │  domanda in linguaggio naturale
      ▼
 ┌─────────────────────┐
 │  cli.py — REPL      │  storico di sessione, output con fonti e data
 └──────────┬──────────┘
            ▼
 ┌─────────────────────┐
 │  agent.py           │  create_agent(model, tools, system_prompt)
 │  LangChain 1.4      │  ciclo: ragiona → chiama tool → risponde
 └──────────┬──────────┘
            │ tool caricati a runtime
            ▼
 ┌─────────────────────┐
 │ MultiServerMCPClient│  langchain-mcp-adapters, transport stdio
 └──────────┬──────────┘
            │ processo separato
            ▼
 ┌─────────────────────┐
 │  server.py (MCP)    │  10 tool → viaggiaresicuri.it
 └─────────────────────┘
```

**Il server gira come processo separato, non in-process.** Costa un subprocess in più, ma è la
configurazione che un cliente userebbe davvero, ed è l'unica che dimostra che il server funziona
anche fuori dal nostro codice. In-process resta comodo per i test, dove il subprocess sarebbe solo
lentezza.

I tool non sono scritti a mano: `MultiServerMCPClient.get_tools()` li genera dagli schemi
pubblicati dal server. Se domani aggiungiamo un tool al server, l'assistente lo vede senza
modifiche — ed è anche la garanzia che l'assistente non possa usare nient'altro.

### Modello e credenziali

L'endpoint fornito (`https://genai-colloqui.openai.azure.com/openai/v1/`) è il percorso
OpenAI-compatibile di Azure, quindi si usa `ChatOpenAI` con `base_url`, senza bisogno del client
Azure specifico:

```python
ChatOpenAI(model="gpt-5.6-luna", base_url=..., api_key=..., temperature=0)
```

`temperature=0` perché qui non serve varietà: la stessa domanda deve dare la stessa risposta.
Credenziali in `.env` (già coperto da `.gitignore`), con `.env.example` versionato.

**`text-embedding-3-large` non viene usato**, ed è una scelta dichiarata: i dati sono già
indicizzati per Paese e argomento, e il server espone un indice a 820 token che fa da retrieval
deterministico. Un vector store qui aggiungerebbe un modo di sbagliare senza aggiungere risposte.

---

## Il system prompt

È il punto dove il lavoro fatto sul server diventa comportamento visibile. Ogni regola nasce da
un'evidenza misurata, non da prudenza generica.

| Regola | Perché |
|---|---|
| Rispondi **solo** con quanto tornano i tool; se non c'è, dillo | requisito della traccia, e argine all'invenzione |
| `status="not_published"` significa "la fonte non lo pubblica", **mai** "non c'è rischio" | `Aree-di-particolare-cautela` è vuoto nel 37% dei Paesi |
| Se `provenance="summary"`, dichiara che viene dalla scheda di sintesi | il fallback copre 76 casi su 82, ma non deve spacciarsi per dettaglio |
| Cita sempre URL e `updated_at` | "fonti verificabili" è nel testo della traccia |
| Se `updated_at` è più vecchia di 12 mesi, segnalalo | 5 schede su 222 lo sono |
| Su Paese ambiguo **chiedi**, non scegliere | "Corea" sono due schede diverse |
| Niente pareri legali o sanitari: riporta e rimanda alle autorità | requisito della traccia |
| Chiudi con il `notice` dell'envelope | requisito della traccia |
| Usa `see_also` per decidere il tool successivo | la fonte produce ~800 rimandi interni, è navigazione gratis |
| Per domande fuori tema usa `list_country_topics` prima di arrenderti | indice a 820 token contro ~5.000 della scheda |

Il server pubblica già le sue `INSTRUCTIONS` via MCP, ma non tutti i client le mostrano al
modello: le regole critiche vanno ripetute nel prompt dell'assistente, non date per acquisite.

---

## Conversazione

- **Memoria di sessione**: lo storico resta nel thread finché la CLI è aperta, così "e per i
  minori?" dopo una domanda sulla Thailandia funziona senza ripetere il Paese.
- **Più tool per risposta**: una domanda tipo "sto partendo per l'Egitto, cosa devo sapere?" ne
  richiede tre o quattro. Il costo misurato di una conversazione completa è intorno ai 3.000
  token di tool output, sostenibile.
- **Streaming**: la CLI stampa i token man mano e mostra quale tool sta girando, perché fra
  latenza del modello e chiamate alla fonte una risposta richiede qualche secondo.

## Interfaccia

CLI interattiva, che è quanto la traccia richiede. Per ogni risposta mostra il testo, le fonti
con la data, e una riga di stato con i tool usati — utile in demo per far vedere che l'assistente
non sta rispondendo a memoria.

Comandi minimi: `/paese <nome>` per fissare il contesto, `/tool` per l'ultimo trace, `/esci`.

Web opzionale e solo a fase 1 chiusa: una pagina sola con FastAPI e un form, che riusa lo stesso
`agent.py`. Se il tempo stringe si taglia senza toccare nient'altro.

---

## Struttura dei file

```
assistant/
  config.py      # modello, credenziali, parametri
  prompts.py     # system prompt
  agent.py       # connessione MCP + costruzione agente
  cli.py         # REPL
.env.example     # OPENAI_API_KEY, OPENAI_BASE_URL, MODEL
tests/
  test_assistant.py       # offline: prompt, costruzione, gestione errori
  test_assistant_eval.py  # marcato `llm`: le domande d'oro
```

Dipendenze verificate su questo ambiente: `langchain 1.4.0`, `langchain-openai 1.6.2`,
`langgraph 1.2.11`, `langchain-mcp-adapters 0.3.2`, `openai 3.11.0`.

---

## Come si verifica

L'eval gira **sulla traccia delle chiamate, non sulla prosa**: quali tool ha usato e con quali
argomenti è deterministico e si asserisce; la formulazione della risposta no. Sul testo si
verificano solo presenze e assenze precise.

| Domanda | Atteso |
|---|---|
| "Posso portare i miei farmaci negli Emirati?" | `get_security_info` su `local_laws`; cita il certificato medico |
| "Documenti per mio figlio di 8 anni per la Thailandia" | `get_entry_requirements` su `minors`; se la fonte rimanda altrove lo dice, non inventa |
| "Cliente derubato del passaporto a Valona" | `get_embassy_contacts`; numero `+355 (0) 68.20.27.064` **intatto**; propone il PDF contatti |
| "Ci sono zone da evitare in Austria?" | dichiara che la risposta viene dalla scheda di sintesi |
| "Posso partire per la Thailandia adesso?" | `get_recent_alerts`; cita le inondazioni e la data |
| "Parto per la Corea" | **non sceglie**: chiede quale delle due |
| "Rischio terrorismo in Andorra" | "non pubblicato dalla fonte", mai "nessun rischio" |
| "Quanto costa un volo per Bangkok?" | rifiuta: fuori dalle fonti disponibili |
| "Serve il visto per gli Stati Uniti?" | `get_entry_requirements` su `visa` |
| "Posso guidare in Marocco con la patente italiana?" | `get_local_transport` |

Trasversali su tutte: fonte e data presenti, disclaimer presente, nessun numero o URL alterato
rispetto a quanto tornato dai tool.

Le prime due e la quarta sono i casi che avevano fatto emergere i bug del server: tenerle nella
eval impedisce che tornino da un'altra porta.

---

## Ordine di lavoro

1. `config.py` e `.env.example`, con una prova secca di connessione al modello — prima di
   costruire qualsiasi cosa, si verifica che le credenziali funzionino.
2. `agent.py`: connessione MCP, caricamento tool, `create_agent`. Prova non interattiva su una
   domanda sola.
3. `prompts.py`: il system prompt, iterando sulle domande d'oro.
4. `cli.py`: REPL con streaming e trace dei tool.
5. Eval sulle dieci domande, e sistemazione del prompt dove sbaglia.
6. README: sezione assistente, con installazione ed esempi.
7. *(opzionale)* pagina web.

Il rischio maggiore è il passo 5: se il modello sbaglia sistematicamente a scegliere i tool, si
interviene sulle descrizioni nel server, non aggiungendo regole al prompt. È lì che il modello
guarda per decidere.

## Rischi

| Rischio | Mitigazione |
|---|---|
| Il modello risponde a memoria invece di usare i tool | regola esplicita nel prompt + caso di eval che lo verifica |
| Riempie un `not_published` con rassicurazioni | è il caso di eval più importante; se cede, si irrigidisce il prompt |
| Sceglie il tool sbagliato | le descrizioni elencano i contenuti; in ultima istanza c'è `list_country_topics` |
| Inventa un codice ISO | i tool accettano il nome in chiaro e sollevano errore sui codici inesistenti |
| Le credenziali non funzionano il giorno della demo | verifica al passo 1, e la CLI stampa un errore leggibile invece di un traceback |
