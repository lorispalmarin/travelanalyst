"""Eval dell'assistente sulle domande che contano.

Si asserisce **sulla traccia delle chiamate**, che è deterministica, e sul testo solo per
presenze e assenze precise: la formulazione della risposta non è un contratto, quali tool sono
stati usati e quali numeri compaiono sì.

Tre casi (farmaci negli Emirati, documenti per i minori, passaporto rubato a Valona) sono quelli
che avevano fatto emergere i bug del server: restano qui perché non rientrino da un'altra porta.

    .venv/bin/pytest -m llm -s
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from assistant.agent import apri_assistente

pytestmark = pytest.mark.llm


@pytest.fixture(autouse=True)
def cache_accesa(monkeypatch):
    """La eval usa la cache, al contrario del resto della suite.

    `conftest.py` spegne la cache per i test offline, e quella variabile viene ereditata dal
    sottoprocesso MCP: senza questo, ogni rilancio della eval rigenererebbe una cinquantina di
    richieste verso viaggiaresicuri.it. È esattamente il traffico che la cache esiste per evitare.
    """
    monkeypatch.setenv("VS_CACHE_ENABLED", "true")

VIETATE = ("nessun rischio", "nessun pericolo", "tutto tranquillo", "non c'è alcun rischio")


@dataclass
class Caso:
    nome: str
    domanda: str
    tool_attesi: set[str] = field(default_factory=set)
    tool_vietati: set[str] = field(default_factory=set)
    deve_contenere: tuple[str, ...] = ()
    non_deve_contenere: tuple[str, ...] = ()
    apre_con: tuple[str, ...] = ()          # almeno uno nei primi FINESTRA_APERTURA caratteri
    prima_di: tuple[tuple[str, ...], tuple[str, ...]] | None = None
    richiede_fonte: bool = True


# "In testa alla risposta" va misurato, non lasciato alla buona volontà: un'allerta di sicurezza
# che compare in fondo, dopo mezza pagina di requisiti sul passaporto, non è stata riportata.
FINESTRA_APERTURA = 400


CASI = [
    Caso(
        nome="farmaci negli Emirati",
        domanda="Un cliente parte per gli Emirati Arabi e prende psicofarmaci su prescrizione. Cosa deve sapere?",
        tool_attesi={"get_security_info"},
        deve_contenere=("certificat",),
    ),
    Caso(
        nome="documenti per un minore",
        domanda="Che documenti servono per portare mio figlio di 8 anni in Thailandia?",
        tool_attesi={"get_entry_requirements"},
    ),
    Caso(
        nome="passaporto rubato a Valona",
        domanda="Un cliente è stato derubato del passaporto a Valona, in Albania. Chi contatto e come?",
        tool_attesi={"get_embassy_contacts"},
        deve_contenere=("68.20.27.064",),
    ),
    Caso(
        nome="zone da evitare in Austria",
        domanda="Ci sono zone da evitare in Austria?",
        tool_attesi={"get_security_info"},
        non_deve_contenere=VIETATE,
    ),
    Caso(
        nome="rischi naturali dove la fonte tace",
        domanda="Quali rischi ambientali e calamità naturali sono segnalati per la Svezia?",
        tool_attesi={"get_security_info"},
        non_deve_contenere=VIETATE,
    ),
    Caso(
        nome="si può partire adesso",
        domanda="Si può partire per la Thailandia adesso? Ci sono allerte in corso?",
        tool_attesi={"get_allerte"},
    ),
    Caso(
        # Il caso che motiva la regola: rispondere solo sui documenti sarebbe corretto e inutile.
        # La fonte sconsiglia tutti i viaggi verso l'Ucraina, e chi chiama deve saperlo per primo.
        nome="allerta prima del contenuto richiesto",
        domanda="Che documenti servono per andare in Ucraina?",
        tool_attesi={"get_allerte", "get_entry_requirements"},
        apre_con=("sconsigl", "allerta", "avviso", "sicurezza"),
        prima_di=(("sconsigl", "allerta", "avviso"), ("passaporto", "visto")),
        non_deve_contenere=VIETATE,
    ),
    Caso(
        nome="paese senza avvisi, senza rassicurazioni",
        domanda="Ci sono allerte per l'Albania?",
        tool_attesi={"get_allerte"},
        non_deve_contenere=VIETATE + ("il paese è sicuro", "si può partire tranquill"),
    ),
    Caso(
        nome="paese ambiguo",
        domanda="Un cliente parte per la Corea, che documenti servono?",
        deve_contenere=("Corea del Sud", "Corea del Nord"),
        richiede_fonte=False,
    ),
    Caso(
        nome="fuori dalle fonti",
        domanda="Quanto costa un volo Milano-Bangkok a marzo?",
        tool_vietati={"get_entry_requirements", "get_security_info", "get_health_info"},
        richiede_fonte=False,
    ),
    Caso(
        nome="visto per gli Stati Uniti",
        domanda="Serve il visto per andare negli Stati Uniti per turismo?",
        tool_attesi={"get_entry_requirements"},
    ),
    Caso(
        # L'altro lato della regola 7: una domanda puntuale che un avviso non sposterebbe non
        # deve pagare una chiamata in più. È il caso che misura che il controllo sia una scelta.
        nome="guidare in Marocco",
        domanda="Posso guidare in Marocco con la patente italiana?",
        tool_attesi={"get_local_transport"},
        tool_vietati={"get_allerte"},
    ),
]


def _valuta(caso: Caso, testo: str, tool_usati: list[str]) -> list[str]:
    problemi: list[str] = []
    usati = set(tool_usati)
    minuscolo = testo.lower()

    mancanti = caso.tool_attesi - usati
    if mancanti:
        problemi.append(f"tool attesi non usati: {sorted(mancanti)} (usati: {tool_usati})")

    vietati = caso.tool_vietati & usati
    if vietati:
        problemi.append(f"tool che non doveva usare: {sorted(vietati)}")

    for atteso in caso.deve_contenere:
        if atteso.lower() not in minuscolo:
            problemi.append(f"manca {atteso!r} nella risposta")

    for vietato in caso.non_deve_contenere:
        if vietato.lower() in minuscolo:
            problemi.append(f"contiene la formula vietata {vietato!r}")

    if caso.apre_con:
        testa = minuscolo[:FINESTRA_APERTURA]
        if not any(t.lower() in testa for t in caso.apre_con):
            problemi.append(
                f"non apre con l'allerta: nessuno fra {caso.apre_con} nei primi "
                f"{FINESTRA_APERTURA} caratteri"
            )

    if caso.prima_di:
        primi, secondi = caso.prima_di
        posizioni = [minuscolo.find(t.lower()) for t in primi if t.lower() in minuscolo]
        dopo = [minuscolo.find(t.lower()) for t in secondi if t.lower() in minuscolo]
        if not posizioni:
            problemi.append(f"non menziona l'allerta: nessuno fra {primi}")
        elif dopo and min(posizioni) > min(dopo):
            problemi.append("l'allerta compare dopo il contenuto richiesto, non prima")

    if caso.richiede_fonte:
        if "viaggiaresicuri.it" not in minuscolo:
            problemi.append("non cita la fonte")
        if "verific" not in minuscolo:
            problemi.append("non riporta l'avvertenza di verifica")

    if not testo.strip():
        problemi.append("risposta vuota")

    return problemi


async def test_domande_dorate():
    esiti: list[tuple[Caso, list[str], list[str]]] = []

    async with apri_assistente() as assistente:
        for caso in CASI:
            assistente.nuova_conversazione()
            risposta = await assistente.chiedi(caso.domanda)
            esiti.append((caso, _valuta(caso, risposta.testo, risposta.tool_usati), risposta.tool_usati))

    print("\n")
    for caso, problemi, tool_usati in esiti:
        segno = "OK  " if not problemi else "FAIL"
        print(f"  [{segno}] {caso.nome:38} tool: {', '.join(tool_usati) or '(nessuno)'}")
        for problema in problemi:
            print(f"         - {problema}")

    falliti = [caso.nome for caso, problemi, _ in esiti if problemi]
    assert not falliti, f"{len(falliti)}/{len(CASI)} casi falliti: {falliti}"


async def test_le_allerte_si_chiedono_una_volta_sola_per_paese():
    """La regola dice "una volta per Paese": va verificata, o è solo una frase nel prompt.

    Due turni sullo stesso Paese nella stessa conversazione. Il primo controlla le allerte, il
    secondo deve riusare quel risultato invece di rifare la chiamata.
    """
    async with apri_assistente() as assistente:
        assistente.nuova_conversazione()
        primo = await assistente.chiedi("Che documenti servono per andare in Ucraina?")
        secondo = await assistente.chiedi("E la situazione sanitaria com'è?")

    print(f"\n  turno 1: {primo.tool_usati}\n  turno 2: {secondo.tool_usati}")
    assert "get_allerte" in primo.tool_usati, "il primo turno deve controllare le allerte"
    assert "get_allerte" not in secondo.tool_usati, (
        "il secondo turno ha richiamato get_allerte: il risultato andava riusato"
    )
    assert "get_health_info" in secondo.tool_usati
