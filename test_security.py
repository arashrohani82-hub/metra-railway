from pathlib import Path


SOURCE = Path("app.py").read_text(encoding="utf-8")


def test_telegram_access_is_restricted():
    assert "ALLOWED_TELEGRAM_USER_IDS" in SOURCE
    assert "actor_id not in ALLOWED_USERS" in SOURCE


def test_webhook_uses_telegram_secret_header():
    assert "X-Telegram-Bot-Api-Secret-Token" in SOURCE
    assert "hmac.compare_digest" in SOURCE


def test_sensitive_routes_require_setup_secret():
    assert "def has_setup_access():" in SOURCE
    assert SOURCE.count("if not has_setup_access():") >= 4


def test_runtime_data_uses_persistent_directory():
    assert "os.path.join(DATA_DIR, 'offre_user_data.json')" in SOURCE
    assert "os.path.join(DATA_DIR, 'ods_counter.json')" in SOURCE


def test_telegram_menu_and_commands_are_registered():
    assert "def main_menu():" in SOURCE
    assert "{'text': '🧾 Facturation'}" in SOURCE
    assert "setMyCommands" in SOURCE


def test_legacy_runtime_does_not_claim_the_telegram_webhook():
    fixed_runtime = Path("fixed_ods_app.py").read_text(encoding="utf-8")
    assert "\nsync_telegram_webhook()\n" not in fixed_runtime


def test_active_runtime_retries_telegram_rate_limits():
    runtime = Path("ods_runtime.py").read_text(encoding="utf-8")
    assert 'os.environ.get(\n    "ODS_PUBLIC_URL"' in runtime
    assert "for attempt in range(3):" in runtime
    assert 'response.status_code != 429' in runtime


def test_ods_prompt_generates_one_concise_engineering_scope():
    assert "Prepare ONE proposal only" in SOURCE
    assert "maximum 70 words" in SOURCE
    assert '"service_lines"' in SOURCE
    assert "Never invent a test, deliverable, quantity" in SOURCE


def test_files_wait_for_all_confirmations():
    for field in (
        "project_num",
        "price_confirmed",
        "delai",
        "special_note_confirmed",
    ):
        assert field in SOURCE
    assert "Générer Excel + PDF" in SOURCE


def test_taxes_are_always_extra_without_a_question():
    assert "Les taxes sont-elles incluses ou en sus?" not in SOURCE
    assert "data.get('taxes') or 'En sus'" in SOURCE


def test_pdf_layout_is_bounded_and_compact():
    assert "topMargin=3.8*cm, bottomMargin=2.15*cm" in SOURCE
    assert "size=9.5, leading=11.7" in SOURCE
    assert "sn2=s('n2',size=8.5,leading=10.2)" in SOURCE
    assert "for line in raw[:4]" in SOURCE
    assert "if len(compact_line) > 140" in SOURCE
    assert SOURCE.index("6. Présence sur site et logistique") < SOURCE.index("story.append(PageBreak())")
    assert SOURCE.index("story.append(PageBreak())") < SOURCE.index("HONORAIRES – FORFAIT DU PROJET")


def test_client_civility_and_missing_contact_placeholders():
    assert "client_civility" in SOURCE
    assert "Never guess weakly" in SOURCE
    assert "def normalize_client_name(value):" in SOURCE
    assert "def normalize_civility(value):" in SOURCE
    assert "return 'M./Mme'" in SOURCE
    assert "'phone': phone or 'À compléter'" in SOURCE
    assert "'address': addr or 'À confirmer'" in SOURCE
    assert "'email': email or 'À compléter'" in SOURCE
    assert "story.append(Paragraph(client_identity(data), sn))" in SOURCE
    assert "ws['B7'] = client_identity(data)" in SOURCE
    assert "return [] if name" in SOURCE


def test_email_send_requires_explicit_confirmation_and_graph_credentials():
    assert "MS_TENANT_ID" in SOURCE
    assert "MS_CLIENT_ID" in SOURCE
    assert "MS_CLIENT_SECRET" in SOURCE
    assert "EMAIL_SENDER" in SOURCE
    assert "def graph_access_token():" in SOURCE
    assert "'scope': 'https://graph.microsoft.com/.default'" in SOURCE
    assert "def send_ods_email(data):" in SOURCE
    assert "/sendMail" in SOURCE
    assert "response.status_code != 202" in SOURCE
    assert "'saveToSentItems': True" in SOURCE
    assert "'callback_data': 'email_send'" in SOURCE
    assert "elif cdata == 'email_send':" in SOURCE
    assert "email_sent_at" in SOURCE
    assert "Ce courriel a déjà été envoyé" in SOURCE
    assert "show_email_confirmation(chat_id, uid)" in SOURCE
    assert "Pièce jointe : PDF de l'offre de service" in SOURCE
