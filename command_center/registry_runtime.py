import os
import runner

# runner imports the base command_center app and applies the existing runtime patches.
command_center = runner.command_center

NEW_BOTS = [
    {
        "key": "home_shopping",
        "name": "Home Shopping Manager",
        "emoji": "🛒",
        "username_env": "HOME_SHOPPING_BOT_USERNAME",
        "service_url_env": "HOME_SHOPPING_SERVICE_URL",
        "username": "Home_Shopping_Manager_bot",
        "repo": "separate service",
    },
    {
        "key": "arvin_daily",
        "name": "Arvin Daily Tracker",
        "emoji": "👦",
        "username_env": "ARVIN_DAILY_BOT_USERNAME",
        "service_url_env": "ARVIN_DAILY_SERVICE_URL",
        "username": "Arvin_Daily_Tracker_bot",
        "repo": "separate service",
    },
]

existing_keys = {bot.get("key") for bot in command_center.BOTS}
for bot in NEW_BOTS:
    if bot["key"] not in existing_keys:
        command_center.BOTS.append(bot)

_original_bot_username = command_center.bot_username


def bot_username_with_fallback(bot):
    configured = _original_bot_username(bot)
    return configured or bot.get("username", "").strip().lstrip("@")


command_center.bot_username = bot_username_with_fallback

_original_main_menu = command_center.main_menu


def main_menu_with_new_bots():
    menu = _original_main_menu()
    system_row = menu.pop() if menu else []
    menu.append([
        command_center.bot_open_button("home_shopping", "🛒 Home Shopping"),
        command_center.bot_open_button("arvin_daily", "👦 Arvin Daily"),
    ])
    if system_row:
        menu.append(system_row)
    return menu


command_center.main_menu = main_menu_with_new_bots

# Flask application exported for Gunicorn.
app = runner.app
