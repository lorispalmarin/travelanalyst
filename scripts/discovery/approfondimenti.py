#!/usr/bin/env python3
"""GET /approfondimenti/{nome}.json — guide generali, non legate a un singolo paese.

    python scripts/discovery/approfondimenti.py                 # panoramica di tutti i file
    python scripts/discovery/approfondimenti.py saluteinviaggio
    python scripts/discovery/approfondimenti.py avvertenze --full
"""

from __future__ import annotations

import argparse
import json

from _common import BASE, fetch_json_safe, html_to_text, preview, rule

NOMI = [
    "avvertenze",
    "documentidiviaggio",
    "preparaunviaggio",
    "saluteinviaggio",
    "sicurezzaaerea",
]


def sezioni_di(payload: dict) -> tuple[str, list[dict]]:
    chiave = next(iter(payload))
    return chiave, payload[chiave]


def panoramica() -> None:
    rule("panoramica /approfondimenti/*.json")
    print(f"{'FILE':22} {'CHIAVE':22} {'MACRO':>6} {'SEZIONI':>8} {'CHAR':>9}")
    ids_per_file = {}
    for nome in NOMI:
        payload, err = fetch_json_safe(f"/approfondimenti/{nome}.json")
        if err:
            print(f"{nome:22} {'-':22} {err}")
            continue
        chiave, macro = sezioni_di(payload)
        sezioni = [s for m in macro for s in m.get("sezioni", [])]
        chars = sum(len(html_to_text(s.get("contenuto"))) for s in sezioni)
        ids_per_file[nome] = {s.get("id") for s in sezioni}
        print(f"{nome:22} {chiave:22} {len(macro):>6} {len(sezioni):>8} {chars:>9}")

    rule("sovrapposizioni fra file (sezioni con lo stesso id)")
    nomi = list(ids_per_file)
    trovate = False
    for i, a in enumerate(nomi):
        for b in nomi[i + 1 :]:
            comuni = ids_per_file[a] & ids_per_file[b]
            if comuni:
                trovate = True
                print(f"  {a} ∩ {b}: {len(comuni)} -> {sorted(comuni)}")
    if not trovate:
        print("  nessuna")

    print("\nnota: la documentazione ufficiale (/contenuti/JSON.pdf) elenca 'sicurezzaaerea'")
    print("come sezione sulla sicurezza aerea, ma l'endpoint restituisce 'Preparare un viaggio'.")
    print("Il nome dell'endpoint non è una garanzia sul contenuto: validare il payload.")


def dettaglio(nome: str, full: bool, chars: int) -> None:
    payload, err = fetch_json_safe(f"/approfondimenti/{nome}.json")
    if err:
        raise SystemExit(f"errore: {nome}.json non disponibile ({err})")

    chiave, macro = sezioni_di(payload)
    rule(f"{nome}.json — {BASE}/approfondimenti/{nome}.json")
    print(f"chiave di primo livello: {chiave!r}   macro-sezioni: {len(macro)}")

    for m in macro:
        sezioni = m.get("sezioni", [])
        rule(f"[{m.get('ordinamento')}] {m.get('id')} — {m.get('nome')}  ({len(sezioni)} sezioni)")
        proprio = html_to_text(m.get("contenuto"))
        if proprio:
            print(f"  contenuto proprio: {preview(proprio, chars)}")
        for s in sezioni:
            testo = html_to_text(s.get("contenuto"))
            print(f"\n  • {s.get('id')} — {s.get('nome')}  ({len(testo)} char)")
            if full:
                print("\n".join("    " + l for l in testo.splitlines()))
            else:
                print(f"    {preview(testo, chars)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("nome", nargs="?", choices=NOMI, help="file da ispezionare")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--chars", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.json:
        if not args.nome:
            ap.error("--json richiede un nome file")
        payload, err = fetch_json_safe(f"/approfondimenti/{args.nome}.json")
        if err:
            raise SystemExit(f"errore: {err}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.nome:
        dettaglio(args.nome, args.full, args.chars)
    else:
        panoramica()


if __name__ == "__main__":
    main()
