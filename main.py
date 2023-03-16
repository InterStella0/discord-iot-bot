import settings
from core.models import IoTBot

bot = IoTBot(settings.Settings)
bot.startup()