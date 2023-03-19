from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core.client import IoTBot

    InteractionBot = discord.Interaction[IoTBot]
    ContextBot = commands.Context[IoTBot]
else:
    ContextBot = commands.Context
    InteractionBot = discord.Interaction
