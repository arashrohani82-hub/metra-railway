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
