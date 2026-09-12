.PHONY: help ingest test test-all docker docker-run

VENV ?= .venv/bin
IMMAGINE ?= travelanalyst:dev

help:
	@echo "make test        suite offline (217 test, nessuna rete)"
	@echo "make test-all    offline + fonte reale + eval del modello"
	@echo "make ingest      ricostruisce l'indice semantico (richiede credenziali di embedding)"
	@echo "make docker      costruisce l'immagine $(IMMAGINE)"
	@echo "make docker-run  avvia l'assistente web nel container su http://127.0.0.1:8000"

# Offline e fuori dal server: non deve mai girare dentro una tool call.
ingest:
	$(VENV)/python scripts/ingest_approfondimenti.py

test:
	$(VENV)/python -m pytest -q -m "not network and not llm"

test-all:
	$(VENV)/python -m pytest -q

docker:
	docker build -t $(IMMAGINE) .

# Il volume conserva la cache dei payload fra un run e l'altro: senza, ogni avvio
# riscaricherebbe dalla fonte quello che aveva già.
docker-run:
	docker run --rm -p 8000:8000 --env-file .env \
		-v travelanalyst-cache:/var/lib/travelanalyst $(IMMAGINE)
