import traceback
from typing import List

import discord.utils
import starlight
from discord import app_commands
from discord.ext import commands
from starlight.star_commands.views.pagination import SimplePaginationView

import settings
from core.client import IoTBot
from core.views import DeviceControl
from tuya.models import DeviceListResult, WebSocketProtocol, Socket

bot = IoTBot(settings.Settings)

@bot.hybrid_command(help="Lists all devices within your asset.")
async def sockets(ctx: commands.Context):
    devices = bot.tuya_client.sockets
    paginator = SimplePaginationView(discord.utils.as_chunks(devices, 5), cache_page=True)
    async for item in starlight.inline_pagination(paginator, ctx):
        sockets_data: List[Socket] = item.data
        start = paginator.current_page * 5 + 1

        def show_state(data: Socket) -> str:
            return "\U0001f7e9" if data.value else "\U0001f7e5"
        embed = discord.Embed(
            title="Devices",
            description="\n".join([f'{i}. {show_state(v)} {v.name} [`{v.id}`]' for i, v in enumerate(sockets_data, start=start)])
        )
        item.format(embed=embed)


@bot.hybrid_command(help="Controlling a device within your asset.")
@app_commands.describe(name="Device id or name to control.")
async def control_device(ctx: commands.Context, *, name: str):
    device = bot.tuya_client.get_socket(name)
    if device is None:
        device = discord.utils.get(bot.tuya_client.sockets, name=name)

    if not device:
        raise commands.CommandError(f"No device name or id found with {name}")

    await DeviceControl().send(ctx, device)


@control_device.autocomplete('name')
async def auto_complete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    list_sockets = bot.tuya_client.sockets
    if current != '':
        list_sockets = starlight.search(list_sockets, name=starlight.Fuzzy(current))

    choices = [app_commands.Choice(name=s.name, value=s.id) for s in list_sockets]
    return choices

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    error = getattr(error, "original", error)
    if isinstance(error, commands.CommandNotFound):
        return

    await ctx.send(str(error))
    raise error


@bot.event
async def on_socket(data: WebSocketProtocol):
    print("INCOMING SOCKET", data)


@bot.command()
async def sync(ctx: commands.Context):
    bot.tree.copy_global_to(guild=ctx.guild)
    cmds = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"Synced {len(cmds)} commands")


@bot.check
async def bot_check(ctx: commands.Context):
    return await bot.is_owner(ctx.author)


bot.startup()
