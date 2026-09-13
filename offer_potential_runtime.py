import logging

import offer_followup_runtime as followup

legacy = followup.legacy
STORE = followup.STORE
logger = logging.getLogger(__name__)


LEVELS = {
    "high": ("🔥", "High Potential"),
    "medium": ("🟡", "Medium Potential"),
    "low": ("⚪", "Low Potential"),
}


def _text(offer):
    return " ".join(
        str(offer.get(key) or "")
        for key in ("description", "contact", "source", "status")
    ).lower()


def potential_score(offer, state=None):
    """Simple explainable first-version lead score. Manual override wins."""
    state = dict(state or {})
    manual = str(state.get("potential_override") or "").lower()
    if manual in LEVELS:
        fixed = {"high": 90, "medium": 60, "low": 30}[manual]
        return {
            "score": fixed,
            "level": manual,
            "reasons": ["Classement manuel"],
            "manual": True,
        }

    score = 35
    reasons = []
    amount = float(offer.get("price") or 0)
    blob = _text(offer)

    if amount >= 5000:
        score += 22
        reasons.append("mandat à forte valeur")
    elif amount >= 2500:
        score += 15
        reasons.append("mandat de bonne valeur")
    elif amount >= 1200:
        score += 8

    priority_terms = (
        "loi 122", "loi 16", "mur porteur", "load bearing", "fondation",
        "foundation", "structure", "structural", "permis", "permit",
        "façade", "stationnement", "parking", "conception", "design",
    )
    if any(term in blob for term in priority_terms):
        score += 15
        reasons.append("service prioritaire")

    intent_terms = (
        "urgent", "rapidement", "asap", "décision", "decision", "prêt",
        "ready", "commencer", "start", "attente", "waiting", "devis modifié",
        "modified quote", "entrepreneur", "contractor",
    )
    if any(term in blob for term in intent_terms):
        score += 15
        reasons.append("signal d’intention / urgence")

    if offer.get("email"):
        score += 5
    if offer.get("contact"):
        score += 3

    followups = int(state.get("followup_count") or 0)
    if followups >= 3:
        score -= 10
        reasons.append("plusieurs relances sans conversion")
    elif followups == 0:
        score += 5
        reasons.append("pas encore relancée")

    status = str(offer.get("status") or "").lower()
    if status == "hold":
        score -= 12
        reasons.append("dossier en attente")

    score = max(0, min(100, int(score)))
    level = "high" if score >= 75 else "medium" if score >= 50 else "low"
    if not reasons:
        reasons.append("profil standard")
    return {"score": score, "level": level, "reasons": reasons[:3], "manual": False}


def next_action(offer, state, level):
    age = followup.followup_stage(offer.get("date"), followup.local_now().date())["days"]
    count = int(state.get("followup_count") or 0)
    if level == "high":
        if count == 0:
            return "Appel ou courriel personnalisé aujourd’hui" if age >= 2 else "Suivi personnalisé à J+3"
        if count == 1:
            return "Deuxième contact direct sous 3–4 jours"
        if count == 2:
            return "Appel court pour décision / blocage"
        return "Suivi final actif puis décision de classement"
    if level == "medium":
        return f"Suivi standard J+{followup.recommended_followup_day(age)}"
    return "Suivi léger; éviter de surinvestir du temps"


def _state(reference):
    return (STORE.load().get("offers") or {}).get(reference, {})


def _save_override(reference, level):
    payload = STORE.load()
    payload.setdefault("offers", {})
    state = dict(payload["offers"].get(reference) or {})
    if level == "auto":
        state.pop("potential_override", None)
    else:
        state["potential_override"] = level
    payload["offers"][reference] = state
    STORE.save(payload)


def show_offer_with_potential(chat_id, uid):
    offer = followup._selected(uid)
    if not offer:
        legacy.tg(chat_id, "❌ Offre introuvable. Ouvrez de nouveau Suivi offres.")
        return
    state = _state(offer["reference"])
    result = potential_score(offer, state)
    icon, label = LEVELS[result["level"]]
    reasons = ", ".join(result["reasons"])
    mode = "manuel" if result["manual"] else "auto"
    extra = (
        f"\n\n🎯 Potentiel : {icon} {label} — {result['score']}/100"
        f"\nRaison : {reasons}"
        f"\nProchaine action : {next_action(offer, state, result['level'])}"
        f"\nClassement : {mode}"
    )
    buttons = [
        [{"text": "🎯 Définir le potentiel", "callback_data": "pot_menu"}],
        [{"text": "✉️ Préparer un courriel de suivi", "callback_data": "of_email_menu"}],
        [{"text": "✅ Relance effectuée", "callback_data": "of_mark"}],
        [
            {"text": "⏸ Hold", "callback_data": "of_status:Hold"},
            {"text": "🔄 In process", "callback_data": "of_status:In process"},
        ],
        [
            {"text": "❌ Refused", "callback_data": "of_status:Refused"},
            {"text": "🔒 Closed", "callback_data": "of_status:Closed"},
        ],
        [{"text": "📁 Acceptée → projet", "callback_data": "of_convert"}],
        [{"text": "⬅️ Offres de ce mois", "callback_data": "of_back"}],
    ]
    legacy.tg(chat_id, followup._offer_text(offer, state) + extra, buttons)


def show_open_offers_priority(chat_id, uid, month_key):
    session = followup._session(uid)
    offers = (session.get("offer_followup_months") or {}).get(month_key)
    if offers is None:
        followup.show_offer_months(chat_id, uid)
        return

    ranked = []
    for offer in offers:
        state = _state(offer["reference"])
        result = potential_score(offer, state)
        ranked.append((result["score"], result["level"], offer))
    ranked.sort(key=lambda item: item[0], reverse=True)

    choices, rows = {}, []
    for index, (score, level, offer) in enumerate(ranked[:40], start=1):
        choices[str(index)] = offer
        stage = followup.followup_stage(offer["date"], followup.local_now().date())
        icon = LEVELS[level][0]
        label = f"{icon} {score} · {stage['days']}j · {offer['reference']} · {offer['contact'] or 'Client'}"
        rows.append([{"text": label[:62], "callback_data": f"of_pick:{index}"}])

    session["offer_followup_choices"] = choices
    session["offer_followup_month"] = month_key
    session.pop("offer_followup_selected", None)
    followup._save_session(uid, session)
    rows.append([{"text": "⬅️ Choisir un autre mois", "callback_data": "of_months"}])
    legacy.tg(
        chat_id,
        f"🎯 Offres du mois {month_key} — classées par potentiel\n\n"
        "🔥 priorité haute · 🟡 moyenne · ⚪ basse\n"
        f"{len(offers)} offre(s).",
        rows,
    )


# Replace detail/list renderers used by the existing follow-up callbacks.
followup.show_offer = show_offer_with_potential
followup.show_open_offers = show_open_offers_priority

_previous_handle_update = legacy.handle_update


def handle_update_potential(data):
    callback = data.get("callback_query") or {}
    cdata = str(callback.get("data") or "")
    if not cdata.startswith("pot_"):
        return _previous_handle_update(data)

    actor_id = callback.get("from", {}).get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    if actor_id not in legacy.ALLOWED_USERS:
        legacy.tg(chat_id, "⛔ Ce bot est privé.")
        return
    followup._ack(callback)
    uid = str(actor_id)
    offer = followup._selected(uid)
    if not offer:
        legacy.tg(chat_id, "❌ Offre introuvable.")
        return

    if cdata == "pot_menu":
        current = potential_score(offer, _state(offer["reference"]))
        icon, label = LEVELS[current["level"]]
        legacy.tg(
            chat_id,
            f"🎯 Potentiel de {offer['reference']}\n\nActuel : {icon} {label} — {current['score']}/100\n\nChoisissez :",
            [
                [{"text": "🔥 High Potential", "callback_data": "pot_set:high"}],
                [{"text": "🟡 Medium Potential", "callback_data": "pot_set:medium"}],
                [{"text": "⚪ Low Potential", "callback_data": "pot_set:low"}],
                [{"text": "🤖 Revenir au score automatique", "callback_data": "pot_set:auto"}],
                [{"text": "⬅️ Retour", "callback_data": "pot_back"}],
            ],
        )
        return

    if cdata.startswith("pot_set:"):
        level = cdata.split(":", 1)[1]
        if level not in {"high", "medium", "low", "auto"}:
            return
        _save_override(offer["reference"], level)
        legacy.tg(chat_id, "✅ Potentiel mis à jour.")
        show_offer_with_potential(chat_id, uid)
        return

    if cdata == "pot_back":
        show_offer_with_potential(chat_id, uid)
        return


legacy.handle_update = handle_update_potential
logger.info("OFFER POTENTIAL SCORING ACTIVE")
