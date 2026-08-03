import unittest

from technical_content import parse_custom_technical_content


class TechnicalContentTests(unittest.TestCase):
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
