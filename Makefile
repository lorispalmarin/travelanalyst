.PHONY: help ingest test test-all

VENV ?= .venv/bin

help:
	@echo "make ingest    costruisce l'indice semantico degli approfondimenti (richiede credenziali)"
	@echo "make test      suite offline"
	@echo "make test-all  offline + fonte reale + eval del modello"

# Offline e fuori dal server: non deve mai girare dentro una tool call.
ingest:
	$(VENV)/python scripts/ingest_approfondimenti.py

test:
	$(VENV)/python -m pytest -q -m "not network and not llm"

test-all:
	$(VENV)/python -m pytest -q
