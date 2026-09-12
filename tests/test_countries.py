from __future__ import annotations

import pytest

from viaggiaresicuri_mcp.countries import CountryIndex
from viaggiaresicuri_mcp.errors import CountryNotFound


class TestRisoluzione:
    """Tre regole: codice, nome esatto, nome parziale non ambiguo. Nient'altro."""

    @pytest.mark.parametrize(
        "query,iso3",
        [
            ("Thailandia", "THA"),
            ("THA", "THA"),
            ("TH", "THA"),
            ("thailandia", "THA"),          # il fold assorbe maiuscole e accenti
            ("perù", "PER"),
            ("Peru", "PER"),
            ("Costa d'Avorio", "CIV"),
            ("Paesi Bassi", "NLD"),
            ("Regno Unito", "GBR"),
            ("Federazione Russa", "RUS"),
            ("Repubblica Popolare Cinese", "CHN"),
            ("Corea del Sud", "KOR"),
            ("Corea del Nord", "PRK"),
            ("Stati Uniti", "USA"),         # parziale: la fonte dice "Stati Uniti d'America"
        ],
    )
    def test_nomi_ufficiali_e_codici(self, index: CountryIndex, query: str, iso3: str):
        match = index.resolve(query)
        assert match.match is not None, f"{query} non risolto"
        assert match.match.iso3 == iso3

    def test_ambiguita_non_viene_indovinata(self, index: CountryIndex):
        match = index.resolve("corea")
        assert match.match is None
        assert {c.iso3 for c in match.candidates} == {"KOR", "PRK"}

    def test_query_senza_corrispondenza(self, index: CountryIndex):
        with pytest.raises(CountryNotFound):
            index.resolve("zzzzzz")

    def test_query_vuota(self, index: CountryIndex):
        with pytest.raises(CountryNotFound):
            index.resolve("   ")


class TestQuelloCheNonRisolve:
    """Il tool non traduce e non indovina: fallisce dicendo come riprovare.

    Non è una limitazione da aggirare, è la divisione del lavoro. Le località e i nomi
    colloquiali li riconduce al Paese il modello, che li conosce tutti; il tool riconosce
    l'elenco della fonte, che è l'unica cosa di cui è autorevole.
    """

    @pytest.mark.parametrize("query", ["Bali", "Phuket", "Tenerife", "Sharm el Sheikh", "olanda"])
    def test_le_localita_e_i_nomi_colloquiali_non_si_risolvono(self, index: CountryIndex, query: str):
        with pytest.raises(CountryNotFound):
            index.resolve(query)

    @pytest.mark.parametrize("refuso", ["tailandia", "giapone", "portogalo", "svizzeraa"])
    def test_i_refusi_non_si_correggono(self, index: CountryIndex, refuso: str):
        with pytest.raises(CountryNotFound):
            index.resolve(refuso)

    def test_russia_non_diventa_bielorussia(self, index: CountryIndex):
        """Il caso che ha motivato il confronto per parola invece che per sottostringa.

        "russia" è un pezzo di "bielorussia", e con il contenimento generico era l'unica
        corrispondenza: il tool rispondeva Bielorussia, con sicurezza e in silenzio.
        """
        with pytest.raises(CountryNotFound):
            index.resolve("Russia")
        assert index.resolve("Federazione Russa").match.iso3 == "RUS"


class TestCoperturaCompleta:
    """Verifiche su tutti i 222 paesi, non su un campione."""

    def test_ogni_paese_si_risolve_col_proprio_nome(self, index: CountryIndex):
        falliti = []
        for ref in index.all():
            try:
                match = index.resolve(ref.name)
            except CountryNotFound:
                falliti.append((ref.name, "non trovato"))
                continue
            if match.match is None:
                falliti.append((ref.name, f"ambiguo: {[c.iso3 for c in match.candidates]}"))
            elif match.match.iso3 != ref.iso3:
                falliti.append((ref.name, f"risolto in {match.match.iso3}"))
        assert not falliti, f"{len(falliti)} paesi non si risolvono col proprio nome: {falliti[:5]}"

    def test_ogni_paese_si_risolve_col_proprio_iso3(self, index: CountryIndex):
        for ref in index.all():
            match = index.resolve(ref.iso3)
            assert match.match is not None and match.match.iso3 == ref.iso3

    def test_ogni_paese_si_risolve_col_proprio_iso2(self, index: CountryIndex):
        falliti = [
            ref.name
            for ref in index.all()
            if (m := index.resolve(ref.iso2)).match is None or m.match.iso3 != ref.iso3
        ]
        assert not falliti, f"ISO2 non risolti: {falliti}"
