"""Aderenza del contratto alla fonte reale, su tutti i paesi.

Non è un test di logica: è la sentinella che avvisa quando Viaggiare Sicuri cambia forma.
Escludibile con `pytest -m "not network"` quando si lavora offline.

    .venv/bin/pytest -m network -v
"""

from __future__ import annotations

import asyncio

import pytest

from viaggiaresicuri_mcp.countries import get_index, reset_index
from viaggiaresicuri_mcp.client import aclose
from viaggiaresicuri_mcp.models import CountrySheet
from viaggiaresicuri_mcp.sheet import FALLBACKS, fetch_sheet, topic_map

pytestmark = pytest.mark.network

CONCORRENZA = 8


@pytest.fixture(scope="module")
def schede() -> dict[str, CountrySheet]:
    """Scarica e valida ogni scheda paese pubblicata. Fallisce se anche una sola non aderisce."""

    async def scarica_tutte() -> tuple[dict[str, CountrySheet], list[str]]:
        reset_index()
        index = await get_index()
        semaforo = asyncio.Semaphore(CONCORRENZA)
        risultati: dict[str, CountrySheet] = {}
        errori: list[str] = []

        async def una(ref):
            async with semaforo:
                try:
                    risultati[ref.iso3] = await fetch_sheet(ref.iso3, ref)
                except Exception as exc:
                    errori.append(f"{ref.iso3} ({ref.name}): {type(exc).__name__}: {exc}")

        await asyncio.gather(*(una(ref) for ref in index.all()))
        await aclose()
        return risultati, errori

    valide, errori = asyncio.run(scarica_tutte())
    assert not errori, f"{len(errori)} schede non aderiscono al contratto: {errori[:5]}"
    assert len(valide) >= 200, f"solo {len(valide)} schede scaricate, la fonte è cambiata?"
    return valide


def test_tutte_le_schede_validano(schede):
    assert len(schede) >= 200


def test_nessuna_sezione_o_nodo_fuori_contratto(schede):
    """Una chiave nuova non rompe il server, ma vogliamo saperlo subito."""
    inattesi = []
    for iso3, sheet in schede.items():
        if sheet.unknown_sections:
            inattesi.append(f"{iso3}: sezioni {sheet.unknown_sections}")
        for nome in ("highlights", "general", "entry", "security", "health", "mobility"):
            ignoti = getattr(sheet, nome).nodes.unknown
            if ignoti:
                inattesi.append(f"{iso3}: {nome} -> {ignoti}")
    assert not inattesi, f"la fonte ha aggiunto contenuti: {inattesi[:10]}"


def test_le_chiavi_di_fallback_esistono(schede):
    qualsiasi = next(iter(schede.values()))
    chiavi = set(topic_map(qualsiasi))
    mancanti = [k for coppia in FALLBACKS.items() for k in coppia if k not in chiavi]
    assert not mancanti, f"FALLBACKS punta a chiavi inesistenti: {mancanti}"


def test_i_nodi_di_dettaglio_vuoti_restano_una_minoranza(schede):
    """Se la quota esplode, la fonte ha cambiato politica editoriale e va rivisto il design."""
    totali = vuoti = 0
    for sheet in schede.values():
        for nome in ("general", "entry", "security", "health", "mobility"):
            for topic in getattr(sheet, nome).nodes.topics():
                totali += 1
                vuoti += topic.status == "not_published"
    quota = vuoti / totali
    assert quota < 0.20, f"nodi non pubblicati al {quota:.0%}: era il 7,6% al momento del design"


def test_il_fallback_copre_quasi_tutte_le_aree_di_cautela_mancanti(schede):
    """Nei paesi dove il dettaglio manca, il riassunto deve dare una risposta quasi sempre.

    Il residuo scoperto è il vicolo cieco della fonte: primo piano fatto solo di rimando alla
    sezione Sicurezza, che a sua volta è vuota (Polonia, Nuova Zelanda, Dominica, Madagascar,
    Gambia, Timor Est). Lì la risposta corretta è "non pubblicato", non una rassicurazione.
    """
    mancanti = [
        iso3
        for iso3, sheet in schede.items()
        if sheet.security.nodes.caution_areas.status == "not_published"
    ]
    scoperti = [
        iso3 for iso3 in mancanti if topic_map(schede[iso3])["security.caution_areas"].status != "available"
    ]
    assert mancanti, "nessun paese con dettaglio vuoto: la fonte è cambiata, rivedere il fallback"
    copertura = 1 - len(scoperti) / len(mancanti)
    assert copertura > 0.85, (
        f"il fallback copre solo il {copertura:.0%} dei {len(mancanti)} paesi senza dettaglio; "
        f"scoperti: {scoperti[:10]}"
    )


def test_nessun_nodo_non_pubblicato_conserva_link(schede):
    """Un nodo che la fonte non ha compilato non può avere link: se li ha, li abbiamo svuotati noi."""
    incoerenti = [
        f"{iso3}.{nome}.{topic.id}"
        for iso3, sheet in schede.items()
        for nome in ("highlights", "general", "entry", "security", "health", "mobility")
        for topic in getattr(sheet, nome).nodes.topics()
        if topic.status == "not_published" and topic.links
    ]
    assert not incoerenti, f"nodi svuotati per errore dalla normalizzazione: {incoerenti[:10]}"


def test_i_paesi_scoperti_non_ricevono_un_riassunto_finto(schede):
    """Dove nemmeno il primo piano ha contenuto, non si deve dichiarare provenienza `summary`."""
    bugiardi = [
        iso3
        for iso3, sheet in schede.items()
        if (topic := topic_map(sheet)["security.caution_areas"]).status == "not_published"
        and topic.provenance == "summary"
    ]
    assert not bugiardi, f"risposte vuote spacciate per riassunto: {bugiardi[:10]}"
