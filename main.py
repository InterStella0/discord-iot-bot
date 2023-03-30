from typing import List, Annotated

import discord.utils
import starlight
from discord import app_commands
from discord.ext import commands
from starlight.star_commands.views.pagination import SimplePaginationView

import settings
from core.client import IoTBot
from core.converter import DeviceConverter
from core.views import DeviceControl
from tuya.models import Socket, WebSocketProtocol, ReportDeviceStatusData, DeviceListResult, ContactSensor, Device

from core.types import InteractionBot, ContextBot

bot = IoTBot(settings.Settings)

@bot.hybrid_command(help="Lists all devices within your asset.")
async def devices(ctx: ContextBot):
    device_infos = await bot.tuya_client.fetch_devices_states()
    paginator = SimplePaginationView(discord.utils.as_chunks(device_infos, 5), cache_page=True)
    async for item in starlight.inline_pagination(paginator, ctx):
        device_data: List[DeviceListResult] = item.data
        start = paginator.current_page * 5 + 1

        def show_state(data: DeviceListResult) -> str:
            return "\U0001f7e9" if data.online else "\U0001f7e5"
        embed = discord.Embed(
            title="Devices",
            description="\n".join([f'`{i}. `{show_state(v)} {v.name} [`{v.category_name}`]'
                                   for i, v in enumerate(device_data, start=start)])
        )
        item.format(embed=embed)


@bot.hybrid_command(help="Show information about a device.")
@app_commands.describe(name="Device id or name to show.")
async def device(ctx: ContextBot, *, name: Annotated[Device, DeviceConverter]):
    device_info = name
    embed = discord.Embed(
        title=f"{device_info.name}",
        timestamp=discord.utils.utcnow(),
        color=discord.Color.green() if device_info.online else discord.Color.red()
    )
    embed.set_thumbnail(url=device_info.icon)
    embed.add_field(name="Category", value=device_info.category_name)
    embed.add_field(name="Product", value=device_info.product_name)
    embed.add_field(name="Model", value=device_info.model)
    embed.add_field(name="Status", value="Online" if device_info.online else "Offline")
    embed.add_field(name="Asset ID", value=device_info.asset_id)

    if isinstance(device_info, Socket):
        device_info: Socket
        embed.add_field(name="Current", value=device_info.current)
        embed.add_field(name="Voltage", value=device_info.voltage)
        embed.add_field(name="Power", value=device_info.power)
    elif isinstance(device_info, ContactSensor):
        device_info: ContactSensor
        embed.add_field(name="Battery", value=device_info.battery_state)
        embed.add_field(name="Door", value="Open" if device_info.doorcontact_state else "Close")

    await ctx.send(embed=embed)


@device.autocomplete('name')
async def auto_complete(interaction: InteractionBot, current: str) -> List[app_commands.Choice[str]]:
    list_sockets = bot.tuya_client.devices
    if current != '':
        list_sockets = starlight.search(list_sockets, name=starlight.Fuzzy(current))

    choices = [app_commands.Choice(name=s.name, value=s.id) for s in list_sockets]
    return choices


@bot.hybrid_command(help="Controlling a socket within your asset.")
@app_commands.describe(name="Socket id or name to control.")
async def control_socket(ctx: ContextBot, *, name: str):
    device = bot.tuya_client.get_device(name)
    if device is None:
        device = discord.utils.get(bot.tuya_client.sockets, name=name)

    if not device:
        raise commands.CommandError(f"No device name or id found with {name}")

    await DeviceControl().send(ctx, device)


@control_socket.autocomplete('name')
async def auto_complete(interaction: InteractionBot, current: str) -> List[app_commands.Choice[str]]:
    list_sockets = bot.tuya_client.sockets
    if current != '':
        list_sockets = starlight.search(list_sockets, name=starlight.Fuzzy(current))

    choices = [app_commands.Choice(name=s.name, value=s.id) for s in list_sockets]
    return choices


@bot.event
async def on_device_update(protocol: WebSocketProtocol):
    if isinstance(data := protocol.data, ReportDeviceStatusData):
        data: ReportDeviceStatusData
        if any([x in status.code for x in ('current', 'power', 'voltage') for status in data.status]):
            device: Socket = bot.tuya_client.get_device(data.dev_id)
            embed = discord.Embed(
                title=f"{device.name} Power Update",
                description=f"**ID**: {device.id}\n"
                            f"**Power:** `{device.power}`\n"
                            f"**Voltage:** `{device.voltage}`\n"
                            f"**Current:** `{device.current}`",
                timestamp=discord.utils.utcnow()
            )
            await bot.device_update.send(embed=embed)
        elif any(['doorcontact_state' == status.code for status in data.status]):
            device: ContactSensor = bot.tuya_client.get_device(data.dev_id)
            embed = discord.Embed(
                title=f"{device.name} Update",
                description=f"**ID**: {device.id}\n"
                            f"**Battery:** `{device.battery_state}`\n"
                            f"**State:** `{'Open' if device.doorcontact_state else 'Close'}`\n",
                timestamp=discord.utils.utcnow()
            )
            await bot.device_update.send(embed=embed)


@bot.event
async def on_command_error(ctx: ContextBot, error: commands.CommandError):
    error = getattr(error, "original", error)
    if isinstance(error, commands.CommandNotFound):
        return

    await ctx.send(str(error))
    raise error


@bot.command()
async def sync(ctx: ContextBot):
    bot.tree.copy_global_to(guild=ctx.guild)
    cmds = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"Synced {len(cmds)} commands")


@bot.check
async def bot_check(ctx: ContextBot):
    return await bot.is_owner(ctx.author)


bot.startup()
