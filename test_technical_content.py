import unittest

from technical_content import parse_custom_technical_content


class TechnicalContentTests(unittest.TestCase):
    def test_numbered_markdown_titles_and_descriptions_stay_four_items(self):
        text = """1. **Révision documentaire et évaluation de l’état structural**\\
   Révision du rapport d’inspection structurale de 2024, des plans et documents disponibles, inspection visuelle des éléments concernés et interprétation des résultats de carottages et essais de laboratoire fournis par le client.
2. **Analyse des déficiences et recommandations structurales**\\
   Évaluation des fissures, détériorations et désordres observés dans la dalle du toit-terrasse et les poutres du stationnement, analyse de leurs causes probables et formulation des recommandations de réparation, renforcement ou autres correctifs requis.
3. **Évaluation et conception des interventions structurales**\\
   Évaluation de la faisabilité de corriger les pentes de la dalle, analyse des impacts structuraux et des charges additionnelles, ainsi que conception et dimensionnement des interventions, réparations, renforcements ou modifications nécessaires.
4. **Plans, détails et investigations complémentaires**\\
   Préparation des calculs, plans, détails et notes structurales requis pour les travaux, incluant l’émission de plans signés et scellés par un ingénieur, ainsi que l’identification, au besoin, des investigations complémentaires nécessaires à la validation de la conception."""
        mandate, services = parse_custom_technical_content(text, "Mandat existant")
        self.assertEqual(mandate, "Mandat existant")
        self.assertEqual(len(services), 4)
        for index, phrase in enumerate(("carottages", "stationnement", "charges additionnelles", "validation de la conception")):
            self.assertIn(phrase, services[index])
        self.assertNotIn("**", " ".join(services))
        self.assertNotIn("\\", " ".join(services))

    def test_plain_multiline_services_replace_old_scope(self):
        text = "Révision du rapport de 2024.\nInspection des poutres.\nConception des réparations.\nPlans signés et scellés."
        mandate, services = parse_custom_technical_content(text, "Ancien mandat")
        self.assertEqual(mandate, "Ancien mandat")
        self.assertEqual(len(services), 4)
        self.assertIn("Plans signés et scellés", services[-1])

    def test_manual_scope_is_not_silently_truncated(self):
        text = "\n".join(f"{i}. Intervention {i}" for i in range(1, 8))
        _, services = parse_custom_technical_content(text, max_services=5)
        self.assertEqual(len(services), 7)

    def test_explicit_multiline_mandate_keeps_services_unchanged(self):
        mandate, services = parse_custom_technical_content("Mandat : Évaluer la dalle\net les poutres existantes.", "Ancien")
        self.assertEqual(mandate, "Évaluer la dalle et les poutres existantes.")
        self.assertEqual(services, [])

    def test_pasted_service_lines_replace_table_content(self):
        text = """Visite du site et relevé visuel des conditions existantes;
Analyse des plans existants et du projet de rénovation proposé;
Identification des murs porteurs et évaluation des éléments structuraux touchés par les travaux;
Conception préliminaire des renforcements structuraux requis, le cas échéant;
Préparation d’un rapport d’évaluation structurale signé et scellé par un ingénieur."""
        mandate, services = parse_custom_technical_content(text, "Mandat existant")
        self.assertEqual(mandate, "Mandat existant")
        self.assertEqual(len(services), 5)
        self.assertTrue(services[0].startswith("Visite du site"))
        self.assertTrue(services[-1].endswith(";"))

    def test_mandate_and_services_can_be_edited_together(self):
        text = """Mandat : Évaluer les interventions structurales requises avant rénovation.

Services :
• Analyse des plans existants;
• Inspection des éléments accessibles;
• Préparation d’un rapport signé et scellé."""
        mandate, services = parse_custom_technical_content(text, "Ancien mandat")
        self.assertEqual(mandate, "Évaluer les interventions structurales requises avant rénovation.")
        self.assertEqual(len(services), 3)

    def test_single_paragraph_changes_only_mandate(self):
        mandate, services = parse_custom_technical_content(
            "Inspection structurale préalable aux travaux de rénovation.",
            "Ancien mandat",
        )
        self.assertEqual(mandate, "Inspection structurale préalable aux travaux de rénovation.")
        self.assertEqual(services, [])


if __name__ == "__main__":
    unittest.main()
