"""Approfondimenti tematici: gli unici contenuti della fonte che non hanno una chiave.

Le schede paese sono indicizzate per Paese e argomento, e per quelle il retrieval semantico
sarebbe un passo indietro: c'è già una chiave, e cercare "per somiglianza" fra 222 Paesi rischia
di rispondere sull'Albania con il testo del Marocco. Questi due documenti no: sono prosa
divulgativa dentro un albero di sezioni, senza un asse su cui interrogarli. Lì il retrieval
semantico è la scelta giusta, ed è l'unico posto dove è usato.

Questo modulo tiene insieme le due metà del ciclo di vita, che condividono il formato:
  - ingest (offline, `scripts/ingest_approfondimenti.py`): cammina l'albero, ripulisce, spezza;
  - query (dentro il server MCP): carica l'indice una volta e cerca.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import BASE_URL
from .errors import UnexpectedPayload
from .models import Meta
from .normalize import extract_links

# Titolo leggibile di ogni documento: è la testa del breadcrumb, e nella fonte non esiste —
# la radice del JSON porta solo l'id tecnico.
DOCUMENTI: dict[str, str] = {
    "saluteinviaggio": "Salute in viaggio",
    "documentidiviaggio": "Documenti di viaggio",
}

# Oltre questa soglia un nodo viene spezzato sui confini di paragrafo. La mediana dei nodi è
# ~2.760 caratteri e la coda arriva a 12.200: senza taglio un solo risultato riempirebbe il
# contesto, e l'embedding di un testo lungo diluisce l'argomento specifico che si cerca.
MAX_CARATTERI = 2000

# Sotto questa soglia un pezzo non è un risultato ma un frammento — tipicamente un titolo
# ("Che cos'è la dengue?") rimasto isolato dal taglio. Un frammento del genere è il peggiore dei
# risultati possibili: somiglia moltissimo alla domanda e non contiene la risposta.
MIN_CARATTERI = 300

INDICE = Path(__file__).resolve().parent.parent / "data" / "approfondimenti.json"
VETTORI = Path(__file__).resolve().parent.parent / "data" / "approfondimenti.npz"


def documento_path(nome: str) -> str:
    return f"/approfondimenti/{nome}.json"


def documento_url(nome: str) -> str:
    return f"{BASE_URL}{documento_path(nome)}"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    documento: str      # "saluteinviaggio" | "documentidiviaggio"
    breadcrumb: str     # "Salute in viaggio > Malattie del viaggiatore > Dengue"
    url: str
    testo: str          # breadcrumb in testa + prosa ripulita + URL citati in coda

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


# --------------------------------------------------------------------------- albero


def radice(payload: Any, documento: str) -> list[dict]:
    """I nodi di primo livello. La radice del JSON ha una sola chiave: il nome del documento."""
    if not isinstance(payload, dict) or documento not in payload:
        raise UnexpectedPayload(f"{documento}.json non ha la chiave '{documento}' in radice")
    nodi = payload[documento]
    if not isinstance(nodi, list) or not nodi:
        raise UnexpectedPayload(f"{documento}.json non contiene una lista di sezioni")
    return nodi


def cammina(nodi: Sequence[dict] | None, catena: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Percorre l'albero e produce `(catena dei nomi, HTML)` per ogni nodo che ha contenuto.

    Un nodo senza contenuto non genera un chunk ma **non interrompe la discesa**: nella fonte i
    contenitori sono esattamente così — tutte e 5 le sezioni di primo livello di "Salute in
    viaggio" hanno `contenuto` vuoto e tengono dentro i 48 nodi che il testo ce l'hanno.

    La profondità non è fissata: oggi l'albero arriva a due livelli, il contratto della fonte ne
    ammette tre, e la ricorsione non si accorge della differenza.
    """
    for nodo in nodi or []:
        if not isinstance(nodo, dict):
            continue
        nome = (nodo.get("nome") or "").strip()
        qui = catena + (nome,) if nome else catena
        contenuto = nodo.get("contenuto") or ""
        if contenuto.strip():
            yield qui, contenuto
        yield from cammina(nodo.get("sezioni"), qui)


def breadcrumb_di(documento: str, catena: tuple[str, ...]) -> str:
    """Titolo del documento + catena degli antenati, senza ripetizioni.

    In `documentidiviaggio` l'unico nodo di primo livello si chiama come il documento: senza
    questo controllo il breadcrumb sarebbe "Documenti di viaggio > Documenti di viaggio > …".
    """
    titolo = DOCUMENTI.get(documento, documento)
    parti = [titolo]
    for nome in catena:
        if nome and nome.casefold() != parti[-1].casefold():
            parti.append(nome)
    return " > ".join(parti)


# --------------------------------------------------------------------------- HTML


# La distinzione fra a capo di riga e di paragrafo non è estetica: è quella su cui `_spezza`
# taglia i nodi lunghi. Collassando tutto a un solo "a capo" resterebbe un blocco inseparabile.
_LI_APERTO = re.compile(r"(?i)<li\b[^>]*>")
_CELLA = re.compile(r"(?i)</t[dh]\s*>\s*")
_RIGA = re.compile(r"(?i)</tr\s*>|<br\s*/?>")
_PARAGRAFO = re.compile(r"(?i)</(p|div|h[1-6]|ul|ol|table)\s*>")
_TAG = re.compile(r"<[^>]+>")
_SPAZI = re.compile(r"[ \t ]+")
_VUOTE = re.compile(r"\n\s*\n(\s*\n)+")


def html_a_testo(html: str) -> str:
    """HTML → testo leggibile: paragrafi a capo, `<li>` in elenco puntato, tabelle a celle.

    Non riusa `normalize.html_to_text`, che è tarato sulle schede paese: lì i contenuti sono
    frasi brevi e i rimandi vanno estratti, qui è prosa con elenchi e due tabelle da tenere
    leggibili. Tenere separati i due normalizzatori evita di far pagare a ciascuno i vincoli
    dell'altro.
    """
    testo = _LI_APERTO.sub("\n- ", html or "")
    testo = _CELLA.sub(" | ", testo)
    testo = _RIGA.sub("\n", testo)
    testo = _PARAGRAFO.sub("\n\n", testo)
    testo = _TAG.sub("", testo)
    testo = unescape(testo)
    righe = [_SPAZI.sub(" ", riga).strip().rstrip("|").strip() for riga in testo.split("\n")]
    return _VUOTE.sub("\n\n", "\n".join(righe)).strip()


def _coda_di_link(link: Sequence[tuple[str, str]]) -> str:
    if not link:
        return ""
    return "\n\nLink citati: " + " · ".join(dict.fromkeys(url for _, url in link))


# --------------------------------------------------------------------------- chunking


def _slug(testo: str) -> str:
    piatto = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", piatto.lower())).strip("-")[:60]


def _blocchi(testo: str, limite: int) -> list[str]:
    """Le unità su cui si taglia: i paragrafi, e per quelli ancora troppo lunghi le righe interne.

    Il secondo livello serve perché una parte della fonte separa i capoversi con `<br>` singoli
    invece che con `<p>`: senza, quei nodi resterebbero blocchi indivisibili da 3.000 caratteri.
    """
    blocchi: list[str] = []
    for paragrafo in re.split(r"\n{2,}", testo):
        paragrafo = paragrafo.strip()
        if not paragrafo:
            continue
        if len(paragrafo) <= limite or "\n" not in paragrafo:
            blocchi.append(paragrafo)
        else:
            blocchi.extend(r.strip() for r in paragrafo.split("\n") if r.strip())
    return blocchi


def _spezza(testo: str, disponibili: int) -> list[str]:
    """Riempie ogni pezzo fino al limite, senza mai tagliare dentro un blocco.

    Nessuna finestra scorrevole e nessun overlap: i paragrafi di questi documenti sono unità di
    senso compiute, e duplicare testo fra pezzi contigui produrrebbe solo risultati che si
    ripetono fra loro nella stessa risposta. Un blocco singolo più lungo del limite resta intero:
    spezzarlo a metà frase costerebbe più di quanto valga.
    """
    pezzi: list[str] = []
    corrente = ""
    for blocco in _blocchi(testo, disponibili):
        if corrente and len(corrente) + len(blocco) + 2 > disponibili:
            pezzi.append(corrente)
            corrente = blocco
        else:
            corrente = f"{corrente}\n\n{blocco}" if corrente else blocco
    if corrente:
        pezzi.append(corrente)
    return _unisci_frammenti(pezzi) or [""]


def _unisci_frammenti(pezzi: list[str]) -> list[str]:
    """Fonde i pezzi troppo corti con il vicino: in coda quello che precede, in testa quello che segue."""
    if len(pezzi) < 2:
        return pezzi
    fusi: list[str] = []
    for pezzo in pezzi:
        if fusi and len(pezzo) < MIN_CARATTERI:
            fusi[-1] = f"{fusi[-1]}\n\n{pezzo}"
        else:
            fusi.append(pezzo)
    if len(fusi) > 1 and len(fusi[0]) < MIN_CARATTERI:
        fusi[1] = f"{fusi[0]}\n\n{fusi[1]}"
        fusi.pop(0)
    return fusi


def chunk_del_nodo(documento: str, catena: tuple[str, ...], html: str) -> list[Chunk]:
    """I chunk di un singolo nodo: uno solo, o più pezzi se il testo supera la soglia."""
    briciole = breadcrumb_di(documento, catena)
    intestazione = f"[{briciole}]\n"
    link = extract_links(html)
    corpo = html_a_testo(html)
    if not corpo.strip():
        return []

    pezzi = _spezza(corpo, MAX_CARATTERI - len(intestazione))
    url = documento_url(documento)
    base = _slug(briciole)
    chunks: list[Chunk] = []
    for i, pezzo in enumerate(pezzi):
        # ogni link finisce nel pezzo che contiene la sua etichetta; quelli che non si
        # ritrovano (etichetta spezzata o vuota) restano sul primo, per non perderli
        suoi = [(t, u) for t, u in link if t and t in pezzo]
        if i == 0:
            orfani = [(t, u) for t, u in link if not t or not any(t in p for p in pezzi)]
            suoi = suoi + orfani
        chunks.append(
            Chunk(
                chunk_id=f"{documento}/{base}#{i}",
                documento=documento,
                breadcrumb=briciole,
                url=url,
                testo=intestazione + pezzo + _coda_di_link(suoi),
            )
        )
    return chunks


def chunk_del_documento(payload: Any, documento: str) -> list[Chunk]:
    """Tutti i chunk di un documento, nell'ordine dell'albero."""
    chunks: list[Chunk] = []
    for catena, html in cammina(radice(payload, documento)):
        chunks.extend(chunk_del_nodo(documento, catena, html))
    return chunks


# --------------------------------------------------------------------------- indice e ricerca

# Le domande con cui si verifica la ricerca offline. I loro vettori vengono salvati dall'ingest
# come fixture: è l'unico modo di provare la qualità del retrieval *vero* senza credenziali.
QUERY_DI_PROVA: tuple[str, ...] = (
    "dengue",
    "smarrimento del passaporto",
    "vaccinazioni in gravidanza",
    "assicurazione sanitaria per l'estero",
)


class Risultato(BaseModel):
    """Un passaggio trovato, con la sua citazione: da quale documento e da quale sezione viene."""

    chunk_id: str
    documento: str
    breadcrumb: str
    url: str
    testo: str
    score: float


class Indice:
    """Chunk, vettori e manifest tenuti insieme. Si carica una volta e si interroga tante."""

    def __init__(self, chunks: list[dict], matrice: Any, manifest: dict) -> None:
        if len(chunks) != len(matrice):
            raise UnexpectedPayload(
                f"indice incoerente: {len(chunks)} chunk e {len(matrice)} vettori"
            )
        self.chunks = chunks
        self.matrice = matrice
        self.manifest = manifest

    def __len__(self) -> int:
        return len(self.chunks)

    def cerca(self, vettore: Any, top_k: int = 5) -> list[Risultato]:
        """I top_k chunk più vicini. I vettori sono normalizzati: il coseno è un prodotto scalare."""
        import numpy as np

        punteggi = self.matrice @ np.asarray(vettore, dtype="float32")
        quanti = max(1, min(int(top_k), len(self.chunks)))
        migliori = np.argsort(-punteggi)[:quanti]
        return [
            Risultato(
                chunk_id=self.chunks[i]["chunk_id"],
                documento=self.chunks[i]["documento"],
                breadcrumb=self.chunks[i]["breadcrumb"],
                url=self.chunks[i]["url"],
                testo=self.chunks[i]["testo"],
                score=round(float(punteggi[i]), 4),
            )
            for i in migliori
        ]


_indice: Indice | None = None


def carica_indice(indice: Path = INDICE, vettori: Path = VETTORI) -> Indice:
    """Legge l'indice da disco. Memoizzato: il server lo fa una volta sola, all'avvio."""
    global _indice
    if _indice is None:
        import numpy as np

        if not indice.exists() or not vettori.exists():
            raise UnexpectedPayload(
                f"indice degli approfondimenti assente ({indice.name}): eseguire `make ingest`"
            )
        dati = json.loads(indice.read_text(encoding="utf-8"))
        with np.load(vettori) as archivio:
            matrice = archivio["vettori"]
        _indice = Indice(dati["chunks"], matrice, dati["manifest"])
    return _indice


def scarica_indice() -> None:
    """Dimentica l'indice caricato. Serve ai test, non al runtime."""
    global _indice
    _indice = None


def meta_dell_indice(indice: Indice) -> Meta:
    """La freschezza di un indice è quella della fonte da cui è stato costruito.

    `cache_status` resta "fresh": non stiamo ripiegando su una copia perché la fonte è giù, stiamo
    servendo uno snapshot costruito apposta. Quanto è vecchio lo dice `age_seconds`, ed è quello
    il numero che conta — questi documenti cambiano di rado, ma non mai.
    """
    from datetime import UTC, datetime

    scaricato = datetime.fromisoformat(indice.manifest["scaricato_il"])
    return Meta(
        last_updated=scaricato,
        retrieved_at=scaricato,
        cache_status="fresh",
        age_seconds=max(0, int((datetime.now(UTC) - scaricato).total_seconds())),
    )
