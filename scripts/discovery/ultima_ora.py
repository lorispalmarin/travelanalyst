#!/usr/bin/env python3
"""GET /ultima_ora/{ISO3}.json e /ultima_ora/totale.json — allerte e avvisi.

    python scripts/discovery/ultima_ora.py Thailandia
    python scripts/discovery/ultima_ora.py --totale
    python scripts/discovery/ultima_ora.py PER --full
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json

from _common import BASE, fetch_json, html_to_text, preview, resolve_country, rule


def when(ts: str | None) -> str:
    try:
        return dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "?"


def show_items(items: list[dict], full: bool, chars: int) -> None:
    for item in sorted(items, key=lambda i: i.get("tsModifica") or "", reverse=True):
        text = html_to_text(item.get("testo"))
        print(f"\n  • [{item.get('id')}] {when(item.get('tsModifica'))}")
        print(f"    nazione: {item.get('nazione') or '(nessuna)'!r}"
              f"   tipologia: {item.get('tipologia') or '(vuota)'!r}"
              f"   follow: {item.get('follow') or '-'!r}")
        print(f"    {item.get('titolo', '').strip()}")
        if full:
            print("\n" + "\n".join("    " + l for l in text.splitlines()))
        else:
            print(f"    {preview(text, chars)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paese", nargs="?", help="nome italiano, ISO3 o ISO2")
    ap.add_argument("--totale", action="store_true", help="usa il feed globale totale.json")
    ap.add_argument("--full", action="store_true", help="stampa il testo integrale")
    ap.add_argument("--chars", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.totale and not args.paese:
        ap.error("indica un paese oppure usa --totale")

    if args.totale:
        path = "/ultima_ora/totale.json"
        titolo = "feed globale"
    else:
        country = resolve_country(args.paese)
        path = f"/ultima_ora/{country['Codice-3']}.json"
        titolo = f"{country['Nome']} ({country['Codice-3']})"

    data = fetch_json(path)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    rule(f"{titolo} — {BASE}{path}")
    print(f"liste presenti: {', '.join(f'{k} ({len(v)})' for k, v in data.items())}")

    for lista, items in data.items():
        if not items:
            continue
        rule(f"{lista} — {len(items)} elementi")
        if lista == "aggiornamentiSchedaPaese":
            print("  (notifiche di scheda aggiornata: il titolo elenca le sezioni modificate)")
        show_items(items, args.full, args.chars)

    if args.totale:
        rule("distribuzione per nazione")
        for lista, items in data.items():
            if not items:
                continue
            conta = collections.Counter(i.get("nazione") or "(nessuna)" for i in items)
            print(f"  {lista}: {dict(conta.most_common())}")
        print("\nnota: totale.json è un feed recente troncato, non un archivio:")
        print("per le allerte di un paese fa fede /ultima_ora/{ISO3}.json.")


if __name__ == "__main__":
    main()
