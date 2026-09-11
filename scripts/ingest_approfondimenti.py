"""Costruisce l'indice semantico degli approfondimenti tematici.

    make ingest

Gira **offline**, mai dentro una tool call: scarica i due documenti, li spezza in chunk,
li vettorizza in chiamate batch e salva indice e metadati in `data/`. Entrambi i file sono
committati, così chi valuta il progetto può eseguire e testare la ricerca senza configurare
credenziali di embedding.

Lo scaricamento passa dal client con cache del server: rieseguire l'ingest entro il TTL non
genera traffico verso viaggiaresicuri.it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from viaggiaresicuri_mcp.approfondimenti import (  # noqa: E402
    DOCUMENTI,
    INDICE,
    QUERY_DI_PROVA,
    VETTORI,
    Chunk,
    chunk_del_documento,
    documento_path,
    documento_url,
)
from viaggiaresicuri_mcp.client import aclose, fetch  # noqa: E402
from viaggiaresicuri_mcp.embeddings import carica, embedda  # noqa: E402

FIXTURE_QUERY = ROOT / "tests" / "fixtures" / "query_prova.npz"


async def raccogli() -> tuple[list[Chunk], datetime]:
    """Tutti i chunk dei due documenti, più il momento in cui la fonte è stata scaricata."""
    chunks: list[Chunk] = []
    scaricato = datetime.now(UTC)
    for documento in DOCUMENTI:
        recuperato = await fetch(documento_path(documento))
        del_documento = chunk_del_documento(recuperato.payload, documento)
        chunks.extend(del_documento)
        scaricato = min(scaricato, recuperato.retrieved_at)
        print(f"  {documento:20} {len(del_documento):4} chunk  "
              f"(payload del {recuperato.retrieved_at:%d/%m/%Y %H:%M} UTC)")
    return chunks, scaricato


def salva(chunks: list[Chunk], matrice, token: int, scaricato: datetime, modello: str) -> None:
    import numpy as np

    INDICE.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "costruito_il": datetime.now(UTC).isoformat(timespec="seconds"),
        "scaricato_il": scaricato.isoformat(timespec="seconds"),
        "modello": modello,
        "dimensioni": int(matrice.shape[1]),
        "chunk": len(chunks),
        "token_embeddati": token,
        "documenti": {nome: titolo for nome, titolo in DOCUMENTI.items()},
        "fonti": {nome: documento_url(nome) for nome in DOCUMENTI},
    }
    INDICE.write_text(
        json.dumps({"manifest": manifest, "chunks": [c.as_dict() for c in chunks]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    np.savez_compressed(VETTORI, vettori=matrice)


def salva_fixture_query(impostazioni) -> None:
    """Vettori delle query di prova: fanno girare i test di ricerca senza chiamate di rete."""
    import numpy as np

    matrice, _ = embedda(list(QUERY_DI_PROVA), impostazioni)
    FIXTURE_QUERY.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(FIXTURE_QUERY, query=np.array(QUERY_DI_PROVA), vettori=matrice)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="costruisce i chunk e si ferma prima di embeddare")
    argomenti = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    print("Scaricamento e chunking:")
    chunks, scaricato = await raccogli()
    await aclose()
    caratteri = sum(len(c.testo) for c in chunks)

    if argomenti.dry_run:
        print(f"\n[dry-run] {len(chunks)} chunk, {caratteri:,} caratteri. Nessun embedding.")
        return 0

    impostazioni = carica()
    print(f"\nEmbedding con {impostazioni.descrizione}…")
    matrice, token = embedda([c.testo for c in chunks], impostazioni)
    salva(chunks, matrice, token, scaricato, impostazioni.model)
    salva_fixture_query(impostazioni)

    peso = VETTORI.stat().st_size + INDICE.stat().st_size
    lunghezze = sorted(len(c.testo) for c in chunks)
    print(
        f"\nIndice costruito.\n"
        f"  chunk               {len(chunks)} (da {len({c.breadcrumb for c in chunks})} nodi)\n"
        f"  caratteri           {caratteri:,} (mediana {lunghezze[len(lunghezze)//2]} per chunk)\n"
        f"  token embeddati     {token:,}\n"
        f"  dimensioni vettore  {matrice.shape[1]}\n"
        f"  indice su disco     {peso/1024/1024:.2f} MB "
        f"({VETTORI.name} {VETTORI.stat().st_size/1024/1024:.2f} MB + "
        f"{INDICE.name} {INDICE.stat().st_size/1024/1024:.2f} MB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
