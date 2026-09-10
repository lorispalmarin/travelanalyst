#!/usr/bin/env python3
"""GET /schede_paese/lista_nazioni.json — elenco completo delle nazioni disponibili.

    python scripts/lista_nazioni.py
    python scripts/lista_nazioni.py --search thai
    python scripts/lista_nazioni.py --json
"""

from __future__ import annotations

import argparse
import json

from _common import BASE, load_countries, rule, slug


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--search", help="filtra per porzione di nome o codice")
    ap.add_argument("--json", action="store_true", help="stampa il JSON grezzo")
    args = ap.parse_args()

    countries = load_countries()

    if args.json:
        print(json.dumps(countries, indent=2, ensure_ascii=False))
        return

    rule(f"{BASE}/schede_paese/lista_nazioni.json")
    print(f"campi per record: {', '.join(countries[0].keys())}")
    print(f"nazioni totali:   {len(countries)}")

    rows = countries
    if args.search:
        q = slug(args.search)
        rows = [c for c in countries if q in slug(c["Nome"]) or q in slug(c["Codice-3"])]
        print(f"filtrate su '{args.search}': {len(rows)}")

    rule()
    print(f"{'NOME':42} {'ISO3':6} {'ISO2':6} {'LAT':>9} {'LNG':>9}")
    for c in rows:
        centro = (c.get("centroPaese") or [{}])[0]
        lat, lng = centro.get("lat", ""), centro.get("lng", "")
        print(f"{c['Nome'][:42]:42} {c['Codice-3']:6} {c['Codice-2']:6} {lat:>9} {lng:>9}")

    rule("controlli")
    iso3 = [c["Codice-3"] for c in countries]
    print(f"ISO3 duplicati:        {len(iso3) - len(set(iso3))}")
    print(f"record senza ISO2:     {sum(1 for c in countries if not c.get('Codice-2'))}")
    print(f"record senza centro:   {sum(1 for c in countries if not c.get('centroPaese'))}")
    print("\nnota: gli endpoint della scheda paese e delle allerte usano il codice ISO3.")


if __name__ == "__main__":
    main()
