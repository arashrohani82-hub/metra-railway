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
    assert "setMyCommands" in SOURCE


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
    assert "size=8.5, leading=10.2" in SOURCE
    assert "for line in raw[:4]" in SOURCE
    assert "if len(compact_line) > 140" in SOURCE
