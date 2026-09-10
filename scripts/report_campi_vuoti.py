#!/usr/bin/env python3
"""Scarica tutte le schede paese e produce un resoconto su campi vuoti e anomalie.

    python scripts/report_campi_vuoti.py
    python scripts/report_campi_vuoti.py --limit 30 --workers 8
    python scripts/report_campi_vuoti.py --csv report.csv
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import csv
import statistics
import sys
import time

from _common import SEZIONI, fetch_json_safe, html_to_text, load_countries, rule


def scarica(country: dict) -> dict:
    iso3 = country["Codice-3"]
    payload, err = fetch_json_safe(f"/schede_paese/{iso3}.json")
    return {"country": country, "iso3": iso3, "payload": payload, "error": err}


def analizza(esito: dict) -> dict | None:
    payload = esito["payload"]
    if payload is None:
        return None
    nodi = {}
    chars = 0
    for sez_id, body in payload.items():
        if not isinstance(body, dict):
            continue
        for nodo_id, nodo in (body.get("nodi") or {}).items():
            testo = html_to_text(nodo.get("contenuto"))
            nodi[f"{sez_id}.{nodo_id}"] = len(testo.strip())
            chars += len(testo)
    return {
        "iso3": esito["iso3"],
        "nome": esito["country"]["Nome"],
        "updateDate": (payload.get("updateDate") or "")[:10],
        "sezioni": [k for k in payload if isinstance(payload[k], dict)],
        "nodi": nodi,
        "chars": chars,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=6, help="richieste in parallelo (default 6)")
    ap.add_argument("--limit", type=int, help="analizza solo i primi N paesi")
    ap.add_argument("--csv", help="esporta il dettaglio per nodo in un CSV")
    args = ap.parse_args()

    countries = load_countries()
    if args.limit:
        countries = countries[: args.limit]

    print(f"scarico {len(countries)} schede con {args.workers} worker...", file=sys.stderr)
    inizio = time.time()
    schede, errori = [], []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, esito in enumerate(pool.map(scarica, countries), 1):
            if esito["error"]:
                errori.append((esito["iso3"], esito["country"]["Nome"], esito["error"]))
            else:
                scheda = analizza(esito)
                if scheda:
                    schede.append(scheda)
            if i % 25 == 0:
                print(f"  {i}/{len(countries)}", file=sys.stderr)
    durata = time.time() - inizio

    if not schede:
        raise SystemExit("nessuna scheda scaricata, impossibile produrre il resoconto")

    n = len(schede)
    rule("RESOCONTO SCHEDE PAESE")
    print(f"paesi in lista:   {len(countries)}")
    print(f"schede scaricate: {n}")
    print(f"errori:           {len(errori)}")
    print(f"tempo:            {durata:.1f}s")

    rule("SEZIONI DI PRIMO LIVELLO")
    presenza = collections.Counter(s for sch in schede for s in sch["sezioni"])
    for sez in SEZIONI:
        c = presenza.get(sez, 0)
        flag = "" if c == n else "   <-- NON universale"
        print(f"  {sez:32} {c}/{n}{flag}")
    inattese = set(presenza) - set(SEZIONI)
    print(f"  sezioni non previste dal contratto: {sorted(inattese) if inattese else 'nessuna'}")

    rule("NODI — TASSO DI CAMPI VUOTI")
    presenti = collections.Counter()
    vuoti = collections.Counter()
    for sch in schede:
        for nodo, lunghezza in sch["nodi"].items():
            presenti[nodo] += 1
            if lunghezza == 0:
                vuoti[nodo] += 1

    print(f"  {'NODO':58} {'VUOTI':>14}")
    for nodo, tot in sorted(presenti.items(), key=lambda kv: (-vuoti[kv[0]] / kv[1], kv[0])):
        v = vuoti[nodo]
        print(f"  {nodo:58} {v:4}/{tot:<5} {v / tot:>5.0%}")

    sempre_vuoti = [k for k, t in presenti.items() if vuoti[k] == t]
    mai_vuoti = [k for k in presenti if vuoti[k] == 0]
    print(f"\n  nodi sempre vuoti ({len(sempre_vuoti)}): {sempre_vuoti or 'nessuno'}")
    print(f"  nodi mai vuoti:   {len(mai_vuoti)}/{len(presenti)}")
    non_universali = [k for k, t in presenti.items() if t != n]
    print(f"  nodi non presenti in tutti i paesi: {non_universali or 'nessuno'}")

    rule("PAESI CON PIÙ NODI VUOTI")
    classifica = sorted(schede, key=lambda s: -sum(1 for v in s["nodi"].values() if v == 0))
    for sch in classifica[:10]:
        v = sum(1 for x in sch["nodi"].values() if x == 0)
        print(f"  {sch['nome'][:34]:34} {sch['iso3']}  {v}/{len(sch['nodi'])} vuoti"
              f"   aggiornata {sch['updateDate']}")

    rule("FRESCHEZZA (updateDate)")
    date = sorted(s["updateDate"] for s in schede if s["updateDate"])
    if date:
        print(f"  più vecchia: {date[0]}")
        print(f"  mediana:     {date[len(date) // 2]}")
        print(f"  più recente: {date[-1]}")
        soglia = f"{int(date[-1][:4]) - 1}{date[-1][4:]}"
        print(f"  più vecchie di 12 mesi rispetto alla più recente: "
              f"{sum(1 for d in date if d < soglia)}/{len(date)}")

    rule("DIMENSIONI (testo ripulito dall'HTML)")
    misure = sorted(s["chars"] for s in schede)
    print(f"  min:     {misure[0]:>7} char (~{misure[0] // 4} token)")
    print(f"  mediana: {int(statistics.median(misure)):>7} char (~{int(statistics.median(misure)) // 4} token)")
    print(f"  max:     {misure[-1]:>7} char (~{misure[-1] // 4} token)"
          f"  [{max(schede, key=lambda s: s['chars'])['nome']}]")

    if errori:
        rule("ERRORI")
        for iso3, nome, err in errori:
            print(f"  {iso3} {nome}: {err}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["iso3", "nome", "updateDate", "nodo", "char"])
            for sch in schede:
                for nodo, lunghezza in sorted(sch["nodi"].items()):
                    writer.writerow([sch["iso3"], sch["nome"], sch["updateDate"], nodo, lunghezza])
        print(f"\nCSV scritto in {args.csv}")

    rule("PROMEMORIA")
    print("Un nodo vuoto significa 'non pubblicato dalla fonte', non 'nessun rischio'.")
    print("I nodi con alto tasso di vuoti sono quelli su cui serve il fallback su infoPrimopiano.")


if __name__ == "__main__":
    main()
