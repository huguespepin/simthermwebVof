"""Tests des classements et scénarios fournis à l'expert (expert/scenarios.py)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.db_loader import SimThermDB
from core.thermal_calc import calculer_thermique_complet
from expert.scenarios import (
    classer_materiaux, simuler_scenarios, ALPHA_CLAIR, FS_BRISE_SOLEIL,
)
from expert.gpt_expert import _construire_message_utilisateur

BD = Path(__file__).resolve().parent.parent / "data" / "SimTherm_BD_v6.xlsx"


@pytest.fixture(scope="module")
def db():
    return SimThermDB(str(BD))


def _params(db, alpha=0.85, fs=0.75):
    v = db.get_ville("Bénin", "Cotonou")
    mur = db.get_materiau_par_nom("Brique terre cuite pleine 20cm")
    toit = db.get_materiau_par_nom("Tôle galvanisée ondulée 0.5mm")
    return dict(
        t_ext_max=v.tmax, amplitude=v.amplitude, tn=v.tn, ghi_kwh_m2_j=v.ghi,
        surface_mur=94.8, surface_toit=80, volume=224,
        surface_vitree=6, U_vitrage=5.7, fs_vitrage=fs,
        surface_porte=0.0, U_porte=2.0, fs_porte=0.0,
        lambda_mur=mur.lambda_val, rho_mur=mur.rho, cp_mur=mur.cp, epaisseur_mur=0.20,
        lambda_toit=toit.lambda_val, rho_toit=toit.rho, cp_toit=toit.cp, epaisseur_toit=0.005,
        usage="Maison individuelle", apports_internes=4.0, nv=0.5, alpha_toit=alpha,
    )


class TestClassement:
    def test_trie_par_score_decroissant_et_limite_a_n(self, db):
        c = classer_materiaux(_params(db), db.get_materiaux_mur("Bénin"), "mur", n=5)
        assert 1 <= len(c) <= 5
        scores = [x["score"] for x in c]
        assert scores == sorted(scores, reverse=True)

    def test_pas_de_doublon_de_nom(self, db):
        c = classer_materiaux(_params(db), db.get_materiaux_toit("Bénin"), "toit", n=20)
        noms = [x["nom"] for x in c]
        assert len(noms) == len(set(noms))

    def test_toiture_utilise_epaisseur_de_reference(self, db):
        """Un chaume de 30 cm ne doit pas être simulé à 5 mm (épaisseur de la tôle actuelle)."""
        c = classer_materiaux(_params(db), db.get_materiaux_toit("Bénin"), "toit", n=20)
        chaume = next(x for x in c if x["nom"].startswith("Chaume dense"))
        assert chaume["epaisseur_m"] == pytest.approx(0.30)

    def test_mur_conserve_epaisseur_utilisateur(self, db):
        c = classer_materiaux(_params(db), db.get_materiaux_mur("Bénin"), "mur", n=3)
        assert all(x["epaisseur_m"] == pytest.approx(0.20) for x in c)


class TestScenarios:
    def _base_et_scenarios(self, db, **kw):
        p = _params(db, **kw)
        base = calculer_thermique_complet(**p)
        cm = classer_materiaux(p, db.get_materiaux_mur("Bénin"), "mur")
        ct = classer_materiaux(p, db.get_materiaux_toit("Bénin"), "toit")
        return base, simuler_scenarios(p, base, cm[0]["materiau"], ct[0]["materiau"])

    def test_toiture_claire_reduit_la_temperature_de_pointe(self, db):
        base, sc = self._base_et_scenarios(db)
        s = next(x for x in sc if "couleur claire" in x["libelle"])
        assert s["delta_max"] < -1.0
        assert s["t_int_max"] == pytest.approx(base.t_int_max + s["delta_max"])

    def test_scenario_toiture_claire_absent_si_deja_claire(self, db):
        _, sc = self._base_et_scenarios(db, alpha=ALPHA_CLAIR)
        assert not any("couleur claire" in x["libelle"] for x in sc)

    def test_brise_soleil_absent_si_fs_deja_bas(self, db):
        _, sc = self._base_et_scenarios(db, fs=FS_BRISE_SOLEIL)
        assert not any("brise-soleil" in x["libelle"].lower() for x in sc)

    def test_cumul_uniquement_leviers_favorables(self, db):
        _, sc = self._base_et_scenarios(db)
        cumul = sc[-1]
        assert cumul["libelle"].startswith("Cumul")
        assert "meilleur mur" not in cumul["libelle"]   # ce levier augmente T max ici
        individuels = [x for x in sc if not x["libelle"].startswith("Cumul")]
        assert cumul["delta_max"] <= min(x["delta_max"] for x in individuels) + 1e-9

    def test_un_mur_plus_isolant_peut_augmenter_la_pointe(self, db):
        """Constat du modèle quasi-statique, à ne pas masquer : quand la toiture
        domine les apports, un mur plus épais retient la chaleur."""
        _, sc = self._base_et_scenarios(db)
        s = next(x for x in sc if x["libelle"].startswith("Mur plus épais"))
        assert s["delta_max"] > 0


class TestMessageExpert:
    def test_le_message_contient_classements_et_scenarios(self, db):
        p = _params(db)
        base = calculer_thermique_complet(**p)
        cm = classer_materiaux(p, db.get_materiaux_mur("Bénin"), "mur")
        ct = classer_materiaux(p, db.get_materiaux_toit("Bénin"), "toit")
        ctx = {"classement_murs": cm, "classement_toits": ct,
               "scenarios": simuler_scenarios(p, base, cm[0]["materiau"], ct[0]["materiau"]),
               "props_materiaux": {"mur": {"lambda": 1.0, "rho": 1800, "cp": 840, "cout": 14000,
                                           "monnaie": "FCFA", "niveau_confiance": "N3"}}}
        msg = _construire_message_utilisateur(base, ctx)
        assert "Scénarios simulés par SimTherm" in msg
        assert "Meilleurs murs disponibles" in msg and "Meilleures toitures disponibles" in msg
        assert cm[0]["nom"] in msg
        assert "Propriétés des matériaux actuels" in msg
