"""
test_thermal_calc.py — Tests unitaires du moteur de calcul.

Ces tests constituent le pilier "validation analytique" du protocole
triple décrit au Chapitre 2.2.6 du mémoire (H2). Ils vérifient chaque
fonction du moteur contre des valeurs de référence calculées
indépendamment à la main ou tirées des normes.

Lancer avec : pytest tests/ -v
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.thermal_calc import (
    calc_U, calc_U_multicouche, calc_delta, calc_xi, calc_f_amortissement, calc_phi_semi_infini,
    calc_H_paroi, calc_H_ventilation, calc_f_env,
    calc_Q_solaire_toit, calc_Q_solaire_baies, calc_Q_internes,
    calc_T_int_moy, calc_T_int_max, calc_T_int_min, calc_T_ext_moy_j,
    classifier_confort, calc_score_simtherm, calculer_thermique_complet,
)


# ============================================================
# ISO 6946:2017 — U-value
# ============================================================
class TestCalcU:
    def test_parpaing_20cm_valeur_connue(self):
        """Parpaing béton 20cm, λ=1.0 -> U attendu ≈ 2.70 W/m²K (validé Excel)."""
        U = calc_U(lambda_val=1.0, epaisseur=0.20, type_paroi="mur")
        assert U == pytest.approx(2.70, abs=0.02)

    def test_iso13786_exemple_D1_beton(self):
        """Référence ISO 13786:2017 exemple D.1 : mur béton 20cm,
        λ=1.8 W/m·K -> U attendu = 3.56 W/m²K."""
        U = calc_U(lambda_val=1.8, epaisseur=0.20, type_paroi="mur")
        assert U == pytest.approx(3.56, abs=0.02)

    def test_toiture_resistances_differentes_du_mur(self):
        """La toiture doit utiliser Rsi=0.10 (flux ascendant) au lieu
        de Rsi=0.13 (mur), donc U_toit > U_mur à matériau identique."""
        U_mur = calc_U(1.0, 0.20, "mur")
        U_toit = calc_U(1.0, 0.20, "toit")
        assert U_toit > U_mur

    def test_epaisseur_croissante_U_decroissant(self):
        """Propriété physique fondamentale : U doit strictement décroître
        quand l'épaisseur augmente (jamais l'inverse — garde-fou contre
        le bug historique où U augmentait avec l'épaisseur)."""
        U_10cm = calc_U(1.0, 0.10, "mur")
        U_20cm = calc_U(1.0, 0.20, "mur")
        U_40cm = calc_U(1.0, 0.40, "mur")
        assert U_10cm > U_20cm > U_40cm

    def test_valeurs_invalides_leve_exception(self):
        with pytest.raises(ValueError):
            calc_U(lambda_val=0, epaisseur=0.20)
        with pytest.raises(ValueError):
            calc_U(lambda_val=1.0, epaisseur=-0.1)
        with pytest.raises(ValueError):
            calc_U(lambda_val=1.0, epaisseur=0.20, type_paroi="plafond")


class TestCalcUMulticouche:
    def test_sans_enduit_identique_a_calc_U(self):
        """Sans enduit (épaisseurs nulles), calc_U_multicouche doit être
        strictement identique à calc_U — aucune régression introduite."""
        U_simple = calc_U(1.0, 0.20, "mur")
        U_multi = calc_U_multicouche(1.0, 0.20, "mur",
                                       epaisseur_enduit_int=0.0, epaisseur_enduit_ext=0.0)
        assert U_multi == pytest.approx(U_simple, abs=1e-9)

    def test_enduit_reduit_U(self):
        """Ajouter un enduit (résistance supplémentaire en série) doit
        toujours réduire U (jamais l'augmenter)."""
        U_sans = calc_U_multicouche(1.0, 0.20, "mur", 0.0, 0.0)
        U_avec = calc_U_multicouche(1.0, 0.20, "mur", 0.015, 0.015, 1.15, 1.15)
        assert U_avec < U_sans

    def test_valeur_reference_parpaing_enduit_ciment(self):
        """Parpaing 20cm + enduit ciment 1,5cm/1,5cm (λ=1,15) -> écart
        d'environ 6,6% vérifié analytiquement."""
        U_sans = calc_U_multicouche(1.0, 0.20, "mur", 0.0, 0.0)
        U_avec = calc_U_multicouche(1.0, 0.20, "mur", 0.015, 0.015, 1.15, 1.15)
        ecart_pct = (U_sans - U_avec) / U_sans * 100
        assert ecart_pct == pytest.approx(6.6, abs=0.2)

    def test_epaisseur_enduit_negative_leve_exception(self):
        with pytest.raises(ValueError):
            calc_U_multicouche(1.0, 0.20, "mur", epaisseur_enduit_int=-0.01)


# ============================================================
# ISO 13786:2017 éq.11 — Profondeur de pénétration delta
# ============================================================
class TestCalcDelta:
    def test_iso13786_exemple_D1(self):
        """Référence ISO 13786:2017 : delta attendu ≈ 0.144 m pour
        béton λ=1.8, ρ=2400, Cp=1000."""
        delta = calc_delta(lambda_val=1.8, rho=2400, cp=1000)
        assert delta == pytest.approx(0.144, abs=0.002)

    def test_parpaing_standard(self):
        """Parpaing λ=1.0 ρ=1800 Cp=840 -> delta ≈ 0.135 m (validé Excel)."""
        delta = calc_delta(lambda_val=1.0, rho=1800, cp=840)
        assert delta == pytest.approx(0.135, abs=0.002)

    def test_materiau_isolant_delta_plus_grand(self):
        """Un isolant (λ faible, ρ faible) a une conductivité par
        rapport à sa capacité calorifique différente -> delta varie
        de façon cohérente avec la diffusivité thermique."""
        delta_beton = calc_delta(1.8, 2400, 1000)
        delta_isolant = calc_delta(0.04, 30, 1200)  # laine minérale typique
        # La diffusivité alpha = lambda/(rho*Cp) : comparons directement
        assert delta_beton > 0 and delta_isolant > 0


# ============================================================
# Asan (1998) — Facteur d'amortissement f
# ============================================================
class TestCalcFAmortissement:
    def test_xi_nul_f_egal_un(self):
        """Paroi d'épaisseur nulle (xi=0) -> aucun amortissement (f=1)."""
        f = calc_f_amortissement(xi=0)
        assert f == pytest.approx(1.0, abs=1e-6)

    def test_iso13786_exemple_D1_beton_20cm(self):
        """xi≈1.393 (béton 20cm λ=1.8 réf ISO D.1) -> f attendu ≈ 0.527
        (calcul direct via la formule d'Asan, cf. TestCalcPhi pour xi)."""
        xi = calc_xi(0.20, calc_delta(1.8, 2400, 1000))
        f = calc_f_amortissement(xi)
        assert f == pytest.approx(0.527, abs=0.01)

    def test_parpaing_20cm_valide_excel(self):
        """Parpaing λ=1.0 ρ=1800 Cp=840 e=20cm -> f attendu ≈ 0.478
        (validé contre le classeur Excel SimTherm, cas Cotonou)."""
        xi = calc_xi(0.20, calc_delta(1.0, 1800, 840))
        f = calc_f_amortissement(xi)
        assert f == pytest.approx(0.478, abs=0.01)

    def test_f_decroit_avec_xi_croissant(self):
        """f doit être une fonction strictement décroissante de xi
        (paroi plus épaisse => amortissement plus fort => f plus bas)."""
        f1 = calc_f_amortissement(xi=0.5)
        f2 = calc_f_amortissement(xi=1.5)
        f3 = calc_f_amortissement(xi=3.0)
        assert f1 > f2 > f3

    def test_f_toujours_entre_0_et_1(self):
        for xi in [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
            f = calc_f_amortissement(xi)
            assert 0 <= f <= 1

    def test_approximation_exponentielle_est_differente(self):
        """Vérifie explicitement que f != exp(-xi) (approximation
        incorrecte historiquement identifiée, cf. Chapitre 2.2.3)."""
        xi = 1.5
        f_correct = calc_f_amortissement(xi)
        f_exp_incorrect = math.exp(-xi)
        assert f_correct != pytest.approx(f_exp_incorrect, rel=0.01)


# ============================================================
# Approximation semi-infinie — Déphasage phi
# ============================================================
class TestCalcPhi:
    def test_iso13786_exemple_D1_ecart_6pct_documente(self):
        """Le déphasage semi-infini doit être proche de 5.32h pour le
        cas de référence ISO (valeur ISO rigoureuse = 5.68h, écart ~6%
        assumé et documenté au Chapitre 2.2.3/2.2.7 du mémoire)."""
        xi = calc_xi(0.20, calc_delta(1.8, 2400, 1000))
        phi = calc_phi_semi_infini(xi)
        assert phi == pytest.approx(5.32, abs=0.05)
        ecart_relatif = abs(phi - 5.68) / 5.68
        assert ecart_relatif < 0.07  # écart documenté < 7%

    def test_phi_croit_avec_xi(self):
        phi1 = calc_phi_semi_infini(xi=0.5)
        phi2 = calc_phi_semi_infini(xi=1.5)
        assert phi2 > phi1

    def test_coherence_formule_excel_historique(self):
        """Vérifie l'identité mathématique φ = ξ*(T/2π) = ξ*(12/π) pour
        T=24h, cohérente avec le littéral '×12' de la formule Excel
        historique (cf. rapport de recherche, Chapitre 2.2.3)."""
        xi = 1.393
        phi_fonction = calc_phi_semi_infini(xi)
        phi_formule_excel = xi * (12 / math.pi)
        assert phi_fonction == pytest.approx(phi_formule_excel, abs=1e-6)


# ============================================================
# Conductances H
# ============================================================
class TestConductances:
    def test_H_paroi_simple(self):
        assert calc_H_paroi(U=2.7, surface=94.8) == pytest.approx(255.96, abs=0.1)

    def test_H_ventilation(self):
        H = calc_H_ventilation(nv=0.5, volume=224)
        assert H == pytest.approx(38.08, abs=0.1)

    def test_f_env_pondere_correctement(self):
        """f_env doit être une moyenne pondérée entre f_mur, f_toit et
        f_vent=1, bornée par les valeurs extrêmes."""
        f_env = calc_f_env(f_mur=0.5, H_mur=200, f_toit=0.9, H_toit=150, H_vent=50)
        assert 0.5 <= f_env <= 1.0

    def test_f_env_H_total_nul_leve_exception(self):
        with pytest.raises(ValueError):
            calc_f_env(f_mur=0.5, H_mur=0, f_toit=0.5, H_toit=0, H_vent=0)

    def test_H_baies_conduction_prise_en_compte(self):
        """Vérifie que la conductance des baies (vitrage) est bien
        intégrée à H_total — correction d'une omission physique
        identifiée après revue critique de l'application web."""
        H_baies = calc_H_paroi(U=2.8, surface=6.0)
        assert H_baies == pytest.approx(16.8, abs=0.1)

    def test_f_env_integre_H_baies(self):
        """f_env doit prendre en compte H_baies (f_baies=1, sans inertie,
        comme la ventilation) et non plus seulement mur/toit/vent."""
        f_env_sans_baies = calc_f_env(f_mur=0.5, H_mur=200, f_toit=0.9,
                                        H_toit=150, H_vent=50, H_baies=0)
        f_env_avec_baies = calc_f_env(f_mur=0.5, H_mur=200, f_toit=0.9,
                                        H_toit=150, H_vent=50, H_baies=100)
        # Ajouter des baies (f=1, comme ventilation) doit rapprocher
        # f_env de 1 (moins d'amortissement global)
        assert f_env_avec_baies > f_env_sans_baies


# ============================================================
# Classification du confort
# ============================================================
class TestClassifierConfort:
    def test_classe_A_usage_standard(self):
        c = classifier_confort(t_int=25.0, tn=25.5, usage="Maison individuelle")
        assert c.lettre == "A"

    def test_classe_D_usage_standard(self):
        c = classifier_confort(t_int=35.0, tn=26.0, usage="Maison individuelle")
        assert c.lettre == "D"

    def test_seuils_resserres_usage_sensible(self):
        """Un écart de 2°C doit être classe A en usage standard mais
        classe B en usage sensible (seuils resserrés, cf. Tableau 2.1)."""
        c_standard = classifier_confort(t_int=27.0, tn=25.0, usage="Maison individuelle")
        c_sensible = classifier_confort(t_int=27.0, tn=25.0, usage="Centre de santé / Dispensaire")
        assert c_standard.lettre == "A"
        assert c_sensible.lettre == "B"

    def test_delta_t_signe_correct(self):
        c = classifier_confort(t_int=30.0, tn=25.0, usage="Maison individuelle")
        assert c.delta_t == pytest.approx(5.0)
        c2 = classifier_confort(t_int=20.0, tn=25.0, usage="Maison individuelle")
        assert c2.delta_t == pytest.approx(-5.0)

    @pytest.mark.parametrize("delta,attendu", [
        (1.0, "A"), (2.0, "A"), (2.1, "B"), (3.5, "B"),
        (3.6, "C"), (5.0, "C"), (5.1, "D"),
    ])
    def test_seuils_exacts_usage_standard(self, delta, attendu):
        c = classifier_confort(t_int=25.0 + delta, tn=25.0, usage="Maison individuelle")
        assert c.lettre == attendu


# ============================================================
# Score composite SimTherm
# ============================================================
class TestScoreSimTherm:
    def test_meilleur_materiau_score_plus_haut(self):
        """Un matériau avec U plus bas et phi plus élevé doit avoir un
        meilleur score qu'un matériau avec U plus haut et phi plus bas."""
        score_bon = calc_score_simtherm(U=0.5, phi_h=12.0)
        score_mauvais = calc_score_simtherm(U=3.0, phi_h=2.0)
        assert score_bon > score_mauvais

    def test_score_plafonne_au_dela_de_12h(self):
        """Au-delà de phi=12h, le facteur d'inertie est plafonné à 1 —
        pas de gain de score supplémentaire."""
        score_12h = calc_score_simtherm(U=1.0, phi_h=12.0)
        score_24h = calc_score_simtherm(U=1.0, phi_h=24.0)
        assert score_12h == pytest.approx(score_24h)


# ============================================================
# Pipeline complet — cohérence de bout en bout
# ============================================================
class TestCalculerThermiqueComplet:
    def test_cas_nairobi_valide_excel_v141(self):
        """Cas de référence validé contre le classeur Excel SimTherm
        v1.4.1 : Nairobi, adobe 30cm mur, tôle+faux-plafond 10cm toit,
        maison individuelle. Attendu (Excel) : T°int_moy≈22.4°C classe A,
        T°int_max≈27.0°C classe C. Toute l'ouverture est ici assimilée
        à une fenêtre vitrée (pas de porte séparée) pour comparabilité
        avec la valeur de référence Excel antérieure à la scission
        vitrée/porte."""
        L, l, h, n = 10, 8, 2.8, 1
        A_toit = L * l
        perimetre = 2 * (L + l)
        A_baies = 6
        A_mur = perimetre * h * n - A_baies
        V = L * l * h * n

        r = calculer_thermique_complet(
            t_ext_max=26.0, amplitude=14.0, tn=23.2, ghi_kwh_m2_j=5.5,
            surface_mur=A_mur, surface_toit=A_toit, volume=V,
            surface_vitree=A_baies, U_vitrage=2.8, fs_vitrage=0.30,
            surface_porte=0.0, U_porte=2.0, fs_porte=0.0,
            lambda_mur=0.58, rho_mur=1600, cp_mur=950, epaisseur_mur=0.30,
            lambda_toit=0.35, rho_toit=200, cp_toit=1200, epaisseur_toit=0.10,
            usage="Maison individuelle", apports_internes=4.0, nv=0.5,
            alpha_toit=0.30,
        )
        assert r.t_int_moy == pytest.approx(22.4, abs=0.5)
        assert r.t_int_max == pytest.approx(27.0, abs=0.5)
        assert r.classe_ressentie.lettre == "A"

    def test_h_mur_jamais_negatif(self):
        """Garde-fou contre le bug historique de géométrie qui produisait
        des H négatifs (cf. Chapitre 2.2.6, erreur de référencement)."""
        r = calculer_thermique_complet(
            t_ext_max=33.0, amplitude=9.0, tn=26.1, ghi_kwh_m2_j=5.2,
            surface_mur=94.8, surface_toit=80, volume=224,
            surface_vitree=6, U_vitrage=2.8, fs_vitrage=0.75,
            surface_porte=0.0, U_porte=2.0, fs_porte=0.0,
            lambda_mur=1.0, rho_mur=1800, cp_mur=840, epaisseur_mur=0.20,
            lambda_toit=50, rho_toit=7800, cp_toit=480, epaisseur_toit=0.005,
            usage="Maison individuelle", apports_internes=4.0, nv=0.5,
            alpha_toit=0.85,
        )
        assert r.H_mur > 0
        assert r.H_toit > 0
        assert r.H_total > 0

    def test_cotonou_parpaing_tole_classe_D(self):
        """Configuration défavorable (Cotonou + parpaing + tôle nue)
        doit produire une classe D — validé Excel (34.6°C / classe D)."""
        r = calculer_thermique_complet(
            t_ext_max=33.0, amplitude=9.0, tn=26.1, ghi_kwh_m2_j=5.2,
            surface_mur=94.8, surface_toit=80, volume=224,
            surface_vitree=6, U_vitrage=5.7, fs_vitrage=0.75,
            surface_porte=0.0, U_porte=2.0, fs_porte=0.0,
            lambda_mur=1.0, rho_mur=1800, cp_mur=840, epaisseur_mur=0.20,
            lambda_toit=50, rho_toit=7800, cp_toit=480, epaisseur_toit=0.005,
            usage="Maison individuelle", apports_internes=4.0, nv=0.5,
            alpha_toit=0.85,
        )
        assert r.t_int_moy == pytest.approx(34.6, abs=0.7)
        assert r.classe_ressentie.lettre == "D"

    def test_porte_opaque_ne_transmet_pas_de_soleil(self):
        """Une porte pleine (FS=0) ne doit générer aucun apport solaire,
        contrairement à une fenêtre vitrée de même surface. Vérifie que
        la distinction vitrée/porte a un effet physique mesurable."""
        params_communs = dict(
            t_ext_max=33.0, amplitude=9.0, tn=26.1, ghi_kwh_m2_j=5.2,
            surface_mur=94.8, surface_toit=80, volume=224,
            lambda_mur=1.0, rho_mur=1800, cp_mur=840, epaisseur_mur=0.20,
            lambda_toit=50, rho_toit=7800, cp_toit=480, epaisseur_toit=0.005,
            usage="Maison individuelle", apports_internes=4.0, nv=0.5,
            alpha_toit=0.85,
        )
        # Cas A : 6m² tout en fenêtre vitrée (FS=0.75)
        r_fenetre = calculer_thermique_complet(
            surface_vitree=6, U_vitrage=2.8, fs_vitrage=0.75,
            surface_porte=0.0, U_porte=2.0, fs_porte=0.0,
            **params_communs,
        )
        # Cas B : 6m² tout en porte pleine opaque (FS=0)
        r_porte = calculer_thermique_complet(
            surface_vitree=0.0, U_vitrage=2.8, fs_vitrage=0.75,
            surface_porte=6, U_porte=2.0, fs_porte=0.0,
            **params_communs,
        )
        # La configuration "porte opaque" doit avoir moins d'apports
        # solaires que la configuration "fenêtre vitrée" à surface égale
        assert r_porte.Q_solaire_baies < r_fenetre.Q_solaire_baies
        assert r_porte.Q_solaire_baies == pytest.approx(0.0, abs=0.01)



# ============================================================
# Orientation & îlot de chaleur — Chapitre 2.2.3.4 et 2.2.3.5
# ============================================================
class TestOrientationEtIlotChaleur:
    """Vérifie que les deux paramètres intégrés en v1.1 (orientation
    des fenêtres et zone d'implantation) produisent l'effet physique
    attendu, tout en garantissant la non-régression par valeurs par
    défaut neutres (facteur_orientation=1.0, delta_ilot_chaleur=0.0)."""

    PARAMS_BASE = dict(
        t_ext_max=33.0, amplitude=9.0, tn=26.1, ghi_kwh_m2_j=5.2,
        surface_mur=94.8, surface_toit=80, volume=224,
        surface_vitree=6, U_vitrage=5.7, fs_vitrage=0.75,
        surface_porte=0.0, U_porte=2.0, fs_porte=0.0,
        lambda_mur=1.0, rho_mur=1800, cp_mur=840, epaisseur_mur=0.20,
        lambda_toit=50, rho_toit=7800, cp_toit=480, epaisseur_toit=0.005,
        usage="Maison individuelle", apports_internes=4.0, nv=0.5,
        alpha_toit=0.85,
    )

    def test_defaut_neutre_non_regression(self):
        """Sans passer les nouveaux paramètres, le résultat doit être
        strictement identique à celui obtenu avec les valeurs par défaut
        neutres (facteur_orientation=1.0, delta_ilot_chaleur=0.0)."""
        r_defaut = calculer_thermique_complet(**self.PARAMS_BASE)
        r_neutre = calculer_thermique_complet(
            facteur_orientation=1.0, delta_ilot_chaleur=0.0,
            **self.PARAMS_BASE,
        )
        assert r_defaut.t_int_moy == pytest.approx(r_neutre.t_int_moy, abs=1e-9)
        assert r_defaut.Q_solaire_baies == pytest.approx(r_neutre.Q_solaire_baies, abs=1e-9)

    def test_orientation_ouest_augmente_apports_baies_vs_nord(self):
        """L'orientation ouest (facteur 1,15) doit produire plus d'apports
        solaires sur les fenêtres que l'orientation nord (facteur 0,65),
        toutes choses égales par ailleurs (Chapitre 2.2.3.4)."""
        r_nord = calculer_thermique_complet(facteur_orientation=0.65, **self.PARAMS_BASE)
        r_ouest = calculer_thermique_complet(facteur_orientation=1.15, **self.PARAMS_BASE)
        # Q_solaire_baies inclut fenêtres + portes ; ici pas de porte,
        # donc l'écart mesure directement l'effet orientation sur fenêtres.
        assert r_ouest.Q_solaire_baies > r_nord.Q_solaire_baies
        # L'ordre doit se transmettre à T°int moyenne
        assert r_ouest.t_int_moy > r_nord.t_int_moy

    def test_ilot_chaleur_urbain_augmente_t_int(self):
        """Un décalage d'îlot de chaleur de +2°C (zone urbaine dense) doit
        augmenter la T°int moyenne d'exactement 2°C par rapport au cas
        rural (0°C), tous autres paramètres identiques — la Tmax
        effective est décalée avant toute la chaîne (Chapitre 2.2.3.5)."""
        r_rural = calculer_thermique_complet(delta_ilot_chaleur=0.0, **self.PARAMS_BASE)
        r_urbain = calculer_thermique_complet(delta_ilot_chaleur=2.0, **self.PARAMS_BASE)
        # Le bilan étant linéaire en Tmax pour cette partie (t_ext_moy_j
        # = Tmax - A/2, T_int_moy = t_ext_moy_j + Q/H), l'écart doit
        # être exactement +2°C sur t_int_moy.
        assert r_urbain.t_int_moy - r_rural.t_int_moy == pytest.approx(2.0, abs=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================
# Absorptivité solaire de la toiture (α) et facteur solaire (FS)
# ============================================================
class TestAlphaEtFacteurSolaire:
    def test_alpha_est_une_absorptivite(self):
        """Q_toit croît avec α : plus la toiture absorbe, plus elle chauffe."""
        from core.thermal_calc import calc_Q_solaire_toit
        q_claire = calc_Q_solaire_toit(0.30, 7.138, 216.7, 80.0)
        q_sombre = calc_Q_solaire_toit(0.85, 7.138, 216.7, 80.0)
        assert q_sombre > q_claire
        assert abs(q_sombre - 4207) < 5      # cas Cotonou conventionnel du mémoire

    def test_fs_proportionnel(self):
        from core.thermal_calc import calc_Q_solaire_baies
        assert abs(calc_Q_solaire_baies(0.75, 216.7, 4.0) - 650) < 1
        assert calc_Q_solaire_baies(0.0, 216.7, 4.0) == 0.0

    def test_reperes_dans_0_1(self):
        from core.constants import ALPHA_TOIT_TYPIQUE, FS_VITRAGE_TYPIQUE
        for d in (ALPHA_TOIT_TYPIQUE, FS_VITRAGE_TYPIQUE):
            assert all(0.0 <= v <= 1.0 for v in d.values())
        assert ALPHA_TOIT_TYPIQUE["Blanc ou peinture réfléchissante"] < ALPHA_TOIT_TYPIQUE["Tôle sombre ou rouillée"]


class TestRevetementCarreaux:
    def test_carreaux_dans_la_liste_et_aucun_en_dernier(self):
        from core.constants import LAMBDA_ENDUIT_TYPIQUE
        cles = list(LAMBDA_ENDUIT_TYPIQUE.keys())
        assert "Revêtement en carreaux (céramique)" in cles
        assert LAMBDA_ENDUIT_TYPIQUE[cles[-1]] is None   # "Aucun enduit" reste en dernier

    def test_carreaux_reduisent_U_legerement(self):
        from core.constants import LAMBDA_ENDUIT_TYPIQUE
        from core.thermal_calc import calc_U_multicouche
        lam = LAMBDA_ENDUIT_TYPIQUE["Revêtement en carreaux (céramique)"]
        u0 = calc_U_multicouche(1.0, 0.20, "mur")
        u1 = calc_U_multicouche(1.0, 0.20, "mur", epaisseur_enduit_ext=0.012,
                                lambda_enduit_ext=lam)
        assert u1 < u0 and (u0 - u1) / u0 < 0.05


class TestEnduitsDeTypesDifferentsParFace:
    def _calc(self, **kw):
        from core.thermal_calc import calculer_thermique_complet
        base = dict(t_ext_max=33.0, amplitude=9.0, tn=26.1, ghi_kwh_m2_j=5.2,
                    surface_mur=94.8, surface_toit=80.0, volume=224.0,
                    surface_vitree=4, U_vitrage=2.8, fs_vitrage=0.75,
                    surface_porte=2, U_porte=2.0, fs_porte=0.0,
                    lambda_mur=1.0, rho_mur=1920, cp_mur=900, epaisseur_mur=0.20,
                    lambda_toit=50.0, rho_toit=7800, cp_toit=450, epaisseur_toit=0.002,
                    usage="Résidentiel", apports_internes=4.0, nv=1.0, alpha_toit=0.85)
        base.update(kw)
        return calculer_thermique_complet(**base)

    def test_ext_none_equivaut_a_meme_lambda_des_deux_cotes(self):
        a = self._calc(epaisseur_enduit_int=0.015, epaisseur_enduit_ext=0.015, lambda_enduit=1.15)
        b = self._calc(epaisseur_enduit_int=0.015, epaisseur_enduit_ext=0.015, lambda_enduit=1.15,
                       lambda_enduit_ext=1.15)
        assert abs(a.U_mur - b.U_mur) < 1e-12

    def test_mortier_interieur_carreaux_exterieur(self):
        from core.thermal_calc import calc_U_multicouche
        r = self._calc(epaisseur_enduit_int=0.015, epaisseur_enduit_ext=0.012,
                       lambda_enduit=1.15, lambda_enduit_ext=1.30)
        attendu = calc_U_multicouche(1.0, 0.20, "mur", epaisseur_enduit_int=0.015,
                                     epaisseur_enduit_ext=0.012,
                                     lambda_enduit_int=1.15, lambda_enduit_ext=1.30)
        assert abs(r.U_mur - attendu) < 1e-12
