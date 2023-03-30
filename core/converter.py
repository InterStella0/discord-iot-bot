import discord
from discord.ext import commands

from core.types import ContextBot
from tuya.models import Device


class DeviceConverter(commands.Converter[Device]):
    async def convert(self, ctx: ContextBot, argument: str) -> Device:
        tuya = ctx.bot.tuya_client
        device = tuya.get_device(argument)
        if device is None:
            device = discord.utils.get(tuya.devices, name=argument)

        if not device:
            raise commands.CommandError(f"No device name or id found with '{argument}'")

        return device
