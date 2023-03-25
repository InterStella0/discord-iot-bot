from typing import Set

import discord


class Settings:
    bot_token: str = ""
    tuya_access_id: str = ""
    tuya_secret: str = ""
    tuya_username: str = ""
    tuya_password: str = ""
    tuya_socket_id: str = ""
    websocket_username: str = ""
    websocket_password: str = ""
    pg_username = ""
    pg_password = ""
    pg_database_name = ""
    owner_ids: Set[int] = {}
    current_monitor_webhook = ""
    intents: discord.Intents = discord.Intents(0b1100011111111011111111)
