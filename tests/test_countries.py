from __future__ import annotations

import pytest

from viaggiaresicuri_mcp.countries import ALIASES, CountryIndex, fold
from viaggiaresicuri_mcp.errors import CountryNotFound


class TestRisoluzione:
    @pytest.mark.parametrize(
        "query,iso3",
        [
            ("Thailandia", "THA"),
            ("THA", "THA"),
            ("TH", "THA"),
            ("thailand", "THA"),
            ("tailandia", "THA"),
            ("Cina", "CHN"),
            ("china", "CHN"),
            ("russia", "RUS"),
            ("inghilterra", "GBR"),
            ("olanda", "NLD"),
            ("Stati Uniti", "USA"),
            ("Dubai", "ARE"),
            ("Peru", "PER"),
            ("perù", "PER"),
            ("Costa d'Avorio", "CIV"),
            ("corea del sud", "KOR"),
            ("corea del nord", "PRK"),
        ],
    )
    def test_casi_reali(self, index: CountryIndex, query: str, iso3: str):
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


class TestMatchDeboli:
    """Un solo candidato debole non è un'ambiguità: proporlo è peggio del silenzio."""

    @pytest.mark.parametrize("query", ["maiorca-xyz", "sardegna", "qwertyuiop"])
    def test_un_match_debole_non_diventa_un_candidato(self, index: CountryIndex, query: str):
        with pytest.raises(CountryNotFound):
            index.resolve(query)

    def test_ibiza_non_propone_la_libia(self, index: CountryIndex):
        match = index.resolve("Ibiza")
        assert match.match is not None
        assert match.match.iso3 == "ESP", "Ibiza deve risolvere in Spagna, non somigliare a Libia"

    @pytest.mark.parametrize(
        "localita,iso3",
        [("Sharm el Sheikh", "EGY"), ("Phuket", "THA"), ("Tenerife", "ESP"), ("Bali", "IDN")],
    )
    def test_localita_note_al_customer_care(self, index: CountryIndex, localita: str, iso3: str):
        assert index.resolve(localita).match.iso3 == iso3

    @pytest.mark.parametrize("refuso,iso3", [("tailandia", "THA"), ("giapone", "JPN"),
                                             ("portogalo", "PRT"), ("svizzeraa", "CHE")])
    def test_i_refusi_veri_continuano_a_risolvere(self, index: CountryIndex, refuso: str, iso3: str):
        match = index.resolve(refuso)
        assert match.match is not None and match.match.iso3 == iso3


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

    def test_nessun_alias_punta_a_un_paese_inesistente(self, index: CountryIndex):
        noti = {ref.iso3 for ref in index.all()}
        rotti = {alias: iso3 for alias, iso3 in ALIASES.items() if iso3 not in noti}
        assert not rotti, f"alias verso paesi inesistenti: {rotti}"

    def test_nessun_alias_maschera_il_nome_ufficiale_di_un_altro_paese(self, index: CountryIndex):
        conflitti = {
            alias: iso3
            for alias, iso3 in ALIASES.items()
            if (altro := next((r for r in index.all() if fold(r.name) == alias), None))
            and altro.iso3 != iso3
        }
        assert not conflitti, f"alias in conflitto con nomi ufficiali: {conflitti}"

    def test_gli_alias_risolvono_tutti(self, index: CountryIndex):
        for alias, iso3 in ALIASES.items():
            match = index.resolve(alias)
            assert match.match is not None, f"alias {alias!r} non risolve"
            assert match.match.iso3 == iso3, f"alias {alias!r} -> {match.match.iso3}, atteso {iso3}"
