# Immagine unica per i due modi di eseguire il progetto:
#   docker run -p 8000:8000 --env-file .env travelanalyst          -> assistente via browser
#   docker run -i --rm --env-file .env travelanalyst python server.py -> server MCP su stdio
#
# Il secondo caso è il motivo per cui l'entrypoint non è uno script di avvio: un client MCP
# esterno deve poter parlare al processo su stdin/stdout senza niente in mezzo.

FROM python:3.12-slim

# Nessun compilatore: tutte le dipendenze hanno wheel per linux/amd64 e linux/arm64.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Le dipendenze in un layer a sé: cambiano molto meno spesso del codice, e così un'edit al
# codice non ricompra l'installazione. `pip install .` vuole anche i pacchetti, quindi qui si
# installa soltanto da pyproject con una copia minima dell'albero.
COPY pyproject.toml ./
RUN mkdir -p viaggiaresicuri_mcp assistant \
    && touch viaggiaresicuri_mcp/__init__.py assistant/__init__.py \
    && pip install --no-cache-dir .

COPY viaggiaresicuri_mcp/ viaggiaresicuri_mcp/
COPY assistant/ assistant/
COPY server.py ./
RUN pip install --no-cache-dir --no-deps .

# La cache dei payload è l'unica cosa che il processo scrive. Sta in un percorso dedicato così
# che `-v` possa conservarla fra i run: senza volume l'immagine riparte con la cache vuota e
# rigenera traffico verso la fonte a ogni avvio, che è esattamente ciò che la cache evita.
ENV VS_CACHE_PATH=/var/lib/travelanalyst/cache.sqlite3 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000

# Utente non privilegiato, proprietario solo di ciò che deve scrivere.
RUN useradd --create-home --uid 10001 viaggiatore \
    && mkdir -p /var/lib/travelanalyst \
    && chown viaggiatore:viaggiatore /var/lib/travelanalyst
USER viaggiatore

EXPOSE 8000

# Interroga la pagina, non solo la porta: l'assistente apre il sottoprocesso MCP all'avvio, e
# un 200 dice che quel sottoprocesso è vivo e i tool sono stati caricati.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/', timeout=4)"

CMD ["travelanalyst-web"]
