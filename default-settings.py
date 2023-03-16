import discord


class Settings:
    bot_token: str = ""
    tuya_access_id: str = ""
    tuya_secret: str = ""
    tuya_username: str = ""
    tuya_password: str = ""
    tuya_socket_id: str = ""
    intents: discord.Intents = discord.Intents(0b1100011111111011111101)
