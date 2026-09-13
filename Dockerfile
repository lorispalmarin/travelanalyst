# Build separate: --build-arg COMPONENT=server oppure COMPONENT=assistant.

FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY viaggiaresicuri_mcp/ viaggiaresicuri_mcp/
COPY assistant/ assistant/
COPY server.py ./
ARG COMPONENT=assistant
RUN pip install --no-cache-dir ".[${COMPONENT}]"

ENV VS_CACHE_PATH=/var/lib/travelanalyst/cache.sqlite3 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000

# Utente non privilegiato, proprietario solo di ciò che deve scrivere
RUN useradd --create-home --uid 10001 viaggiatore \
    && mkdir -p /var/lib/travelanalyst \
    && chown viaggiatore:viaggiatore /var/lib/travelanalyst
USER viaggiatore

EXPOSE 8000 8001

CMD ["travelanalyst-web"]
