"""Errori del server.

La distinzione che conta è fra "non ho capito la domanda" e "la fonte non risponde":
i primi sono recuperabili dall'agente, i secondi no. In nessun caso un'eccezione grezza
della libreria HTTP deve arrivare fino al modello.
"""

from __future__ import annotations


class SourceError(Exception):
    """Base per tutti gli errori riconducibili alla fonte."""

    code = "source_error"


class SourceUnavailable(SourceError):
    """Timeout, errore di rete o 5xx: la fonte c'è ma non risponde."""

    code = "source_unavailable"


class SourceNotFound(SourceError):
    """404: la risorsa richiesta non esiste sulla fonte."""

    code = "not_found"


class UnexpectedPayload(SourceError):
    """La risposta non ha la forma attesa: meglio fallire che restituire mezza scheda."""

    code = "unexpected_payload"


class UnknownTopic(Exception):
    """Filtro su argomenti inesistenti.

    Fallire è meglio del silenzio: un filtro che non matcha nulla restituirebbe una risposta
    vuota, che l'agente leggerebbe come "la fonte non pubblica niente su questo tema".
    """

    code = "unknown_topic"

    def __init__(self, section: str, unknown: list[str], valid: list[str]) -> None:
        super().__init__(
            f"argomenti non validi per {section}: {', '.join(unknown)}. "
            f"Valori ammessi: {', '.join(valid)}"
        )
        self.section = section
        self.unknown = unknown
        self.valid = valid


class CountryNotFound(Exception):
    """Il testo fornito non corrisponde a nessun paese."""

    code = "country_not_found"

    def __init__(self, query: str) -> None:
        super().__init__(f"nessun paese corrisponde a {query!r}")
        self.query = query
