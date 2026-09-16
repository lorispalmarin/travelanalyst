"""Le domande di prova sulle guide generali, e il costo del sommario.

`fixtures/domande_guide.json` tiene 35 domande scritte a mano leggendo le sezioni: per ognuna, le
sezioni che contengono la risposta e un estratto letterale del paragrafo. Le domande con
`risposta_in` vuoto sono fuori dalla copertura delle guide.

Qui l'etichetta si verifica da sola: se la fonte cambia o l'etichetta è sbagliata, questo test
fallisce. Quanto spesso il modello scelga la sezione giusta leggendo il sommario è invece una
misura che richiede il modello, e non è ancora stata fatta.

    .venv/bin/python -m pytest tests/test_general_info_eval.py -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from viaggiaresicuri_mcp.general_info import build_sections, guide_index

DOMANDE = json.loads(
    (Path(__file__).parent / "fixtures" / "domande_guide.json").read_text(encoding="utf-8")
)
COPERTE = [d for d in DOMANDE if d["risposta_in"]]


def _spazi(testo: str) -> str:
    return " ".join(testo.split())


@pytest.fixture(scope="module")
def sezioni(guide_payloads):
    return build_sections(guide_payloads)


def test_ogni_etichetta_punta_al_paragrafo_che_contiene_la_risposta(sezioni):
    testi = {s.id: _spazi(s.text) for s in sezioni}
    errori = [
        f"domanda {d['id']}: {sezione}"
        for d in COPERTE
        for sezione, estratto in d["risposta_in"].items()
        if _spazi(estratto) not in testi.get(sezione, "")
    ]
    assert not errori, f"etichette che non trovano il proprio estratto: {errori}"
    assert len(COPERTE) >= 30


def test_il_sommario_costa_meno_di_una_sezione(sezioni):
    """È la ragione del disegno: scegliere dall'elenco costa meno che farsi cercare dentro."""
    voci = guide_index(sezioni)
    sommario = "\n".join(f"{v.id} {v.breadcrumb} {v.chars}" for v in voci)
    piu_corta = min(len(s.text) for s in sezioni)
    print(f"\n  sommario: {len(sommario)} caratteri per {len(voci)} sezioni")
    for voce in voci:
        print(f"    {voce.chars:>5} car.  {voce.id}")
    assert len(sommario) < piu_corta
