"""Quanto trova la ricerca full-text nelle due guide generali, su domande etichettate a mano.

`fixtures/domande_guide.json` associa a ogni domanda le sezioni che contengono la risposta e, per
ciascuna, un estratto letterale del paragrafo: l'estratto rende l'etichetta verificabile, e se la
fonte cambia fallisce il primo test invece di spostarsi la metrica. Le domande con `risposta_in`
vuoto sono fuori dalla copertura delle guide e servono a vedere che cosa torna quando la risposta
non c'è.

    .venv/bin/python -m pytest tests/test_general_info_eval.py -s
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from viaggiaresicuri_mcp.general_info import MAX_RISULTATI, build_index

DOMANDE = json.loads(
    (Path(__file__).parent / "fixtures" / "domande_guide.json").read_text(encoding="utf-8")
)
COPERTE = [d for d in DOMANDE if d["risposta_in"]]
FUORI = [d for d in DOMANDE if not d["risposta_in"]]


def _spazi(testo: str) -> str:
    return " ".join(testo.split())


@pytest.fixture(scope="module")
def indice(guide_payloads):
    return build_index(guide_payloads)


def test_ogni_etichetta_punta_al_paragrafo_che_contiene_la_risposta(indice):
    testi = {s.id: _spazi(s.text) for s in indice.sezioni}
    errori = [
        f"domanda {d['id']}: {sezione}"
        for d in COPERTE
        for sezione, estratto in d["risposta_in"].items()
        if _spazi(estratto) not in testi.get(sezione, "")
    ]
    assert not errori, f"etichette che non trovano il proprio estratto: {errori}"


def test_recupero(indice):
    ranghi: list[int | None] = []
    punteggi_primi: list[float] = []
    print()
    for d in COPERTE:
        trovate = indice.search(d["domanda"], MAX_RISULTATI)
        ids = [h.id for h in trovate]
        posizioni = [ids.index(s) + 1 for s in d["risposta_in"] if s in ids]
        rango = min(posizioni) if posizioni else None
        ranghi.append(rango)
        if trovate:
            punteggi_primi.append(trovate[0].score)
        if rango != 1:
            print(f"  [{rango or '-'}] {d['id']:>2}. {d['domanda']}")
            print(f"        attese:  {', '.join(d['risposta_in'])}")
            print(f"        trovate: {', '.join(ids[:3]) or '(nessuna)'}")

    n = len(ranghi)
    for k in (1, 3, 5):
        entro = sum(1 for r in ranghi if r is not None and r <= k)
        print(f"  hit@{k}: {entro}/{n} ({entro / n:.0%})")
    print(f"  MRR@{MAX_RISULTATI}: {sum(1 / r for r in ranghi if r) / n:.3f}")
    print(f"  punteggio del primo risultato, mediana: {statistics.median(punteggi_primi):.2f}")
    assert n >= 30


def test_le_domande_fuori_copertura_ricevono_comunque_risultati(indice):
    """Il filtro lo fa l'agente, non la ricerca: qui si vede quanto è netto il confine."""
    print("\n  domande fuori copertura:")
    con_risultati = 0
    for d in FUORI:
        trovate = indice.search(d["domanda"], MAX_RISULTATI)
        con_risultati += bool(trovate)
        primo = f"{trovate[0].score:.2f}  {trovate[0].id}" if trovate else "(nessun risultato)"
        print(f"    {d['id']:>2}. {d['domanda']}\n        {primo}")
    assert con_risultati, "nessuna domanda fuori copertura produce risultati: il confine è cambiato"
