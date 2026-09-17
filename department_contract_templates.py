"""Department-specific standard ODS contract wording.

Keeps common commercial terms shared, while replacing the generic structural
wording used by the legacy PDF with discipline-appropriate standard clauses for
Structure, Civil and Geotechnical offers.
"""

import department_ods_patch as dept


_ORIGINAL_DEPARTMENT_TEXT = dept._department_text


STRUCTURE_DESCRIPTION = (
    "Metra Consultation Inc. offre des services d’ingénierie des structures pour "
    "l’évaluation, l’analyse, la conception, la modification et le renforcement "
    "d’éléments structuraux de bâtiments existants ou projetés. Les services "
    "peuvent comprendre, selon le mandat, l’analyse des charges, la vérification "
    "des éléments existants, la conception de poutres, colonnes, murs, fondations "
    "et assemblages, ainsi que la préparation de plans, détails, notes de calcul "
    "ou rapports signés et scellés."
)

CIVIL_DESCRIPTION = (
    "Metra Consultation Inc. offre des services de génie civil liés notamment au "
    "drainage des sites, au nivellement, à la gestion des eaux pluviales, aux "
    "réseaux d’aqueduc et d’égout, aux branchements de services, aux aménagements "
    "de site, aux stationnements, aux accès et aux infrastructures connexes. "
    "L’étendue exacte des analyses, calculs, plans et documents livrables est "
    "définie dans la description spécifique du mandat."
)

GEOTECH_DESCRIPTION = (
    "Metra Consultation Inc. offre des services d’ingénierie géotechnique visant "
    "à caractériser les conditions de sol et de roc et à fournir les paramètres "
    "et recommandations nécessaires à la conception des ouvrages projetés. Selon "
    "le mandat, les services peuvent comprendre la planification et la réalisation "
    "de forages, les essais in situ, le prélèvement d’échantillons, les essais de "
    "laboratoire spécifiés, l’interprétation des conditions stratigraphiques et "
    "des eaux souterraines ainsi que des recommandations relatives aux fondations, "
    "excavations, remblais, drainage et protection contre le gel."
)

STRUCTURE_SITE = (
    "Lorsque requis, le client doit assurer un accès sécuritaire aux zones visées "
    "par le mandat. Les finis, plafonds, murs ou autres revêtements devant être "
    "ouverts afin de permettre l’observation des éléments structuraux doivent être "
    "rendus accessibles avant la visite, sauf indication contraire dans l’offre. "
    "Les travaux d’ouverture, de démolition exploratoire et de remise en état ne "
    "sont pas inclus, sauf mention explicite."
)

CIVIL_SITE = (
    "Lorsque requis, le client doit permettre l’accès sécuritaire au site et "
    "fournir les documents disponibles nécessaires à la réalisation du mandat, "
    "notamment le certificat de localisation, les plans d’arpentage, les relevés "
    "topographiques, les plans existants et les informations relatives aux réseaux "
    "et infrastructures connus. Toute visite ou intervention sur site doit être "
    "coordonnée avec le client."
)

GEOTECH_SITE = (
    "Les travaux de terrain sont conditionnels à l’accessibilité sécuritaire du "
    "site pour les équipements de forage et à la localisation préalable des services "
    "souterrains. Le client doit signaler toute infrastructure privée, conduite, "
    "câble, réservoir ou autre ouvrage souterrain connu qui ne serait pas identifié "
    "par les services publics de localisation. Toute restriction d’accès ou condition "
    "particulière pouvant affecter la mobilisation doit être communiquée avant les travaux."
)

STRUCTURE_ASSUMPTIONS = (
    "1- Plans architecturaux, structuraux et documents existants disponibles fournis avant le début du mandat;"
    "<br/>2- Accès adéquat aux éléments structuraux visés, incluant poutres, colonnes, murs porteurs, planchers et fondations, selon les besoins du mandat;"
    "<br/>3- Les conditions dissimulées ou non accessibles pourront nécessiter une visite additionnelle ou une révision du mandat;"
    "<br/>4- Les services d’architecture, d’arpentage, de génie civil, de géotechnique et d’environnement sont exclus sauf indication contraire;"
    "<br/>5- Toute modification importante du concept architectural ou des conditions existantes après le début du mandat pourra entraîner des honoraires additionnels."
)

CIVIL_ASSUMPTIONS = (
    "1- Certificat de localisation, plans d’arpentage, relevés topographiques et autres informations disponibles fournis avant le début du mandat, selon les besoins du projet;"
    "<br/>2- Les informations disponibles concernant les réseaux existants, servitudes, branchements et infrastructures souterraines seront transmises par le client lorsqu’elles sont connues;"
    "<br/>3- Les travaux d’arpentage légal ou de relevé topographique spécialisé ne sont pas inclus sauf indication explicite dans l’offre;"
    "<br/>4- Les frais de permis, frais municipaux, frais de raccordement et droits exigés par les autorités ne sont pas inclus;"
    "<br/>5- Les études géotechniques, environnementales ou de caractérisation des sols ne sont pas incluses sauf indication contraire;"
    "<br/>6- Toute exigence additionnelle formulée par la municipalité ou une autre autorité après la préparation des documents pourra nécessiter une révision du mandat."
)

GEOTECH_ASSUMPTIONS = (
    "1- Le client fournira le plan de localisation du projet, l’implantation approximative des ouvrages projetés et les informations disponibles sur le site;"
    "<br/>2- Le site sera accessible de façon sécuritaire à l’équipement requis pour les travaux de terrain;"
    "<br/>3- Les services souterrains connus devront être localisés avant le début des forages;"
    "<br/>4- Le nombre et la profondeur des forages indiqués dans l’offre sont basés sur les informations disponibles; toute investigation additionnelle rendue nécessaire par les conditions rencontrées fera l’objet d’une autorisation du client;"
    "<br/>5- Les essais de laboratoire inclus sont uniquement ceux explicitement indiqués dans la description des services;"
    "<br/>6- La caractérisation environnementale des sols, la recherche de contaminants et les analyses environnementales sont exclues sauf indication contraire;"
    "<br/>7- Les observations du niveau d’eau effectuées pendant les forages représentent les conditions observées au moment de l’investigation et ne constituent pas un suivi piézométrique à long terme;"
    "<br/>8- La remise en état complète des surfaces, aménagements paysagers ou pavages après les travaux de forage n’est pas incluse sauf indication contraire."
)


def _looks_like_generic_description(text):
    lowered = text.lower()
    return (
        "metra consultation inc. offre ses services d'ingénierie-conseil" in lowered
        or "metra consultation inc. offre ses services de génie civil conformément" in lowered
        or "metra consultation inc. offre ses services de génie géotechnique conformément" in lowered
    )


def _looks_like_site_clause(text):
    lowered = text.lower()
    return (
        "toute requête de déplacement" in lowered
        or "toute visite ou intervention sur site doit être coordonnée" in lowered
        or "les travaux de terrain sont assujettis à l'accessibilité du site" in lowered
    )


def _is_assumption_1(text):
    lowered = text.lower().strip()
    return lowered.startswith("plans architecturaux fournis") or lowered.startswith("plans, relevés, certificat de localisation") or lowered.startswith("plans disponibles, localisation des ouvrages projetés")


def _is_structural_assumption_2_or_3(text):
    lowered = text.lower().strip()
    return lowered.startswith("accès aux éléments structuraux") or lowered.startswith("vérification, coordination et approbation par l'architecte")


def department_text(text, code, meta):
    """Return discipline-appropriate standard text while preserving project scope."""
    if not isinstance(text, str):
        return text

    # Keep the existing role/header substitutions already implemented upstream.
    text = _ORIGINAL_DEPARTMENT_TEXT(text, code, meta)
    stripped = text.strip()

    if _looks_like_generic_description(stripped):
        if code == 'STR':
            return STRUCTURE_DESCRIPTION
        if code == 'CIV':
            return CIVIL_DESCRIPTION
        if code == 'GEO':
            return GEOTECH_DESCRIPTION

    if _looks_like_site_clause(stripped):
        if code == 'STR':
            return STRUCTURE_SITE
        if code == 'CIV':
            return CIVIL_SITE
        if code == 'GEO':
            return GEOTECH_SITE

    if _is_assumption_1(stripped):
        if code == 'STR':
            return STRUCTURE_ASSUMPTIONS
        if code == 'CIV':
            return CIVIL_ASSUMPTIONS
        if code == 'GEO':
            return GEOTECH_ASSUMPTIONS

    # The legacy template prints structural assumptions 2 and 3 separately.
    # They are already incorporated into each department's new assumption block.
    if _is_structural_assumption_2_or_3(stripped):
        return ''

    return text


dept._department_text = department_text

dept.legacy.logger.warning(
    'DEPARTMENT CONTRACT TEMPLATES ACTIVE: STR/CIV/GEO descriptions, site clauses and assumptions'
)
