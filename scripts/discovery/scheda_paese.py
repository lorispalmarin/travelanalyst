#!/usr/bin/env python3
"""GET /schede_paese/{ISO3}.json — struttura e contenuto della scheda di un paese.

    python scripts/discovery/scheda_paese.py Albania
    python scripts/discovery/scheda_paese.py THA --section infoSicurezza --full
    python scripts/discovery/scheda_paese.py BRA --node Ambasciate-e-Consolati --links
"""

from __future__ import annotations

import argparse
import json

from _common import (
    BASE,
    SEZIONI,
    extract_links,
    fetch_json,
    html_to_text,
    pdf_urls,
    preview,
    resolve_country,
    rule,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paese", help="nome italiano, ISO3 o ISO2")
    ap.add_argument("--section", help="mostra solo questa sezione (es. infoSicurezza)")
    ap.add_argument("--node", help="mostra solo questo nodo (es. Passaporto)")
    ap.add_argument("--full", action="store_true", help="stampa il testo integrale")
    ap.add_argument("--chars", type=int, default=300, help="caratteri di anteprima (default 300)")
    ap.add_argument("--links", action="store_true", help="elenca i link estratti da ogni nodo")
    ap.add_argument("--json", action="store_true", help="stampa il JSON grezzo")
    args = ap.parse_args()

    country = resolve_country(args.paese)
    iso3 = country["Codice-3"]
    path = f"/schede_paese/{iso3}.json"
    data = fetch_json(path)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    urls = pdf_urls(iso3)
    rule(f"{country['Nome']} ({iso3}) — {BASE}{path}")
    print(f"updateDate:  {data.get('updateDate')}")
    print(f"pagina web:  {urls['pagina']}")
    print(f"PDF scheda:  {urls['scheda']}")
    print(f"PDF contatti:{urls['contatti']}")

    inattese = [k for k in data if k != "updateDate" and k not in SEZIONI]
    mancanti = [s for s in SEZIONI if s not in data]
    if inattese:
        print(f"\n!! sezioni non previste dal contratto: {', '.join(inattese)}")
    if mancanti:
        print(f"!! sezioni attese e assenti: {', '.join(mancanti)}")

    tot_nodi = tot_vuoti = 0
    for sez_id, body in data.items():
        if not isinstance(body, dict):
            continue
        if args.section and sez_id != args.section:
            continue

        nodi = body.get("nodi", {})
        da_mostrare = {k: v for k, v in nodi.items() if not args.node or k == args.node}
        if not da_mostrare:
            continue
        rule(f"[{body.get('ordinamento')}] {sez_id} — {body.get('titolo')}  ({len(nodi)} nodi)")

        for nodo_id, nodo in da_mostrare.items():
            raw = nodo.get("contenuto") or ""
            text = html_to_text(raw)
            stato = "VUOTO" if not text.strip() else f"{len(text)} char"
            tot_nodi += 1
            tot_vuoti += 0 if text.strip() else 1

            print(f"\n  • {nodo_id}")
            print(f"    titolo: {nodo.get('titolo')!r}   stato: {stato}")
            if text.strip():
                if args.full:
                    print("\n" + "\n".join("    " + l for l in text.splitlines()))
                else:
                    print(f"    {preview(text, args.chars)}")
            if args.links:
                for testo, url in extract_links(raw):
                    print(f"      link: {testo} -> {url}")

    if not args.section and not args.node:
        rule("riepilogo")
        print(f"nodi totali: {tot_nodi} | vuoti: {tot_vuoti}")
        print("attenzione: un nodo vuoto significa 'non pubblicato', non 'nessun rischio'.")


if __name__ == "__main__":
    main()
