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

VIETATE = ("nessun rischio", "nessun pericolo", "tutto tranquillo", "non c'è alcun rischio")


@dataclass
class Caso:
    nome: str
    domanda: str
    tool_attesi: set[str] = field(default_factory=set)
    tool_vietati: set[str] = field(default_factory=set)
    deve_contenere: tuple[str, ...] = ()
    non_deve_contenere: tuple[str, ...] = ()
    richiede_fonte: bool = True


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
        tool_attesi={"get_recent_alerts"},
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
        nome="guidare in Marocco",
        domanda="Posso guidare in Marocco con la patente italiana?",
        tool_attesi={"get_local_transport"},
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
