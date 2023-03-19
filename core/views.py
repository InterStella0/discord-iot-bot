from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

import discord

from core.errors import FatalViewError, NotAuthorError, ViewError
from tuya.models import Socket

if TYPE_CHECKING:
    from core.models import IoTBot, DeviceListResult
    from core.types import InteractionBot, ContextBot


@dataclasses.dataclass
class ViewDataDevice:
    message: discord.Message
    author: discord.User
    device: Socket


class ViewPrompt(discord.ui.View):
    def __init__(self, messageable: discord.abc.Messageable, user: discord.Object):
        super().__init__()
        self.messageable = messageable
        self.user = user
        self.value = None
        self.response_true = None
        self.response_false = None
        self.message = None

    @classmethod
    def from_context(cls, ctx: ContextBot) -> ViewPrompt:
        return cls(ctx, ctx.author)

    async def ask(self, question: str, response_true: str, response_false: str) -> bool:
        self.message = await self.messageable.send(question, view=self)
        self.response_true = response_true
        self.response_false = response_false

        await self.wait()
        if self.value is None:
            raise asyncio.TimeoutError("Timeout")

        return self.value

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def on_confirm(self, interaction: InteractionBot, button: discord.ui.Button):
        await self._response(interaction, True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def on_cancel(self, interaction: InteractionBot, button: discord.ui.Button):
        await self._response(interaction, False)

    async def on_timeout(self) -> None:
        if self.message is None:
            return

        await self.message.delete(delay=0)

    async def _response(self, interaction: InteractionBot, value: bool):
        self.value = value
        response = self.response_true if value else self.response_false
        await interaction.response.send_message(response, ephemeral=True, delete_after=5)
        await self.message.delete(delay=0)
        self.stop()

    async def interaction_check(self, interaction: InteractionBot, /) -> bool:
        if interaction.user.id == self.user.id:
            return True

        raise NotAuthorError(f"Only {self.user} can use this interaction.")

    async def on_error(self, interaction: InteractionBot, error: Exception, item: discord.ui.Item[ViewPrompt], /) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(str(error))
        else:
            await interaction.response.send_message(str(error), ephemeral=True)


class DeviceControl(discord.ui.View):
    def __init__(self, *, bot: Optional[IoTBot] = None, atomic: bool = False):
        super().__init__(timeout=None)
        self.view_data: Dict[InteractionBot, ViewDataDevice] = {}
        self._socket_data: Dict[str, ViewDataDevice] = {}
        self.bot: Optional[IoTBot] = bot
        self.atomic: bool = atomic
        self.logger: logging.Logger = logging.getLogger('view.device')
        if atomic:
            if bot is None:
                raise ValueError("Bot must be given on atomic set to True.")

            asyncio.create_task(self.ainit())

    async def dispatch_update(self, device_id: str) -> None:
        data = self._socket_data.get(device_id)
        if data is None:
            return

        try:
            await data.message.edit(embed=self.format_device(data.device), view=self)
        except discord.NotFound:
            self.logger.info(f"Missing message {data.message.id} found. Removing...")
            self._socket_data.pop(device_id, None)
            await self.bot.pool.execute("DELETE FROM device_info_view WHERE message_id=$1", data.message.id)

    async def ainit(self) -> None:
        # for dynamic message update
        for data in await self.bot.pool.fetch('SELECT * FROM device_info_view'):
            message = self.bot.get_partial_messageable(data['channel_id']).get_partial_message(data['message_id'])
            device = self.bot.tuya_client.get_socket(data['device_id'])
            view_data = ViewDataDevice(message=message, author=self.bot.get_user(data['author_id']), device=device)
            self._socket_data[device.id] = view_data
            await self.dispatch_update(device.id)

        self.logger.debug(f"Cache filled: {self._socket_data}")

    def format_device(self, device: Socket) -> discord.Embed:
        from tuya.client import TuyaClient  # Lazy
        self.on_open.disabled = device.value
        self.on_close.disabled = not device.value
        color = discord.Color.green() if device.value else discord.Color.red()
        state = "\U0001f7e9" if device.value else "\U0001f7e5"
        return (discord.Embed(title=f"{state} {device.name}", color=color)
                .set_thumbnail(url=f"{TuyaClient.BASE_IMAGE}/{device.icon}")
                .add_field(name="ID", value=device.id, inline=False)
                .add_field(name="Category", value=device.category_name)
                .add_field(name="Status", value="Online" if device.online else "Offline")
                .add_field(name="Model", value=device.model)
                .add_field(name="Current", value=device.current)
                .add_field(name="Power", value=device.power)
                .add_field(name="Timer", value=device.countdown or "Not set")
        )

    async def send(self, ctx: ContextBot, device: DeviceListResult) -> None:
        embed = self.format_device(device)
        message = await ctx.send(embed=embed, view=self)
        await self.store_data(ctx, device.id, message)

    async def store_data(self, ctx: ContextBot, device_id: str, message: discord.Message) -> None:
        bot = ctx.bot
        view_data = bot.get_view_data(device_id)
        if view_data is not None:
            await view_data.message.delete(delay=0)
            await bot.pool.execute("DELETE FROM device_info_view WHERE device_id=$1", device_id)

        query = "INSERT INTO device_info_view VALUES($1, $2, $3, $4)"
        await bot.pool.execute(query, device_id, ctx.author.id, message.id, message.channel.id)
        if view_data is not None:
            view_data.message = message
            view_data.author = ctx.author
        else:
            device = bot.tuya_client.get_socket(device_id)
            data = ViewDataDevice(message=message, author=ctx.author, device=device)
            bot.device_control_view._socket_data[device.id] = data

    async def fetch_data(self, interaction: InteractionBot) -> ViewDataDevice:
        if interaction in self.view_data:
            return self.view_data[interaction]

        query = "SELECT * FROM device_info_view WHERE message_id=$1"
        message = interaction.message
        bot = interaction.client
        row = await bot.pool.fetchrow(query, getattr(message, "id", None))
        if not row:
            raise FatalViewError("Message id is not associated with any view.")

        device = self.get_device(interaction, row['device_id'])
        data = ViewDataDevice(message=message, author=bot.get_user(row['author_id']), device=device)
        interaction.client.device_control_view._socket_data[device.id] = data
        self.view_data[interaction] = data
        return data

    @discord.ui.button(label="Open", style=discord.ButtonStyle.green, custom_id="iot-device-open")
    async def on_open(self, interaction: InteractionBot, button: discord.ui.Button):
        await self._response(interaction, True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="iot-device-close")
    async def on_close(self, interaction: InteractionBot, button: discord.ui.Button):
        await self._response(interaction, False)

    def get_device(self, interaction: InteractionBot, device_id: str) -> Socket:
        device = interaction.client.tuya_client.get_socket(device_id)
        if device:
            return device
        else:
            raise FatalViewError("This is no longer a valid view.")

    async def _response(self, interaction: InteractionBot, value: bool):
        await interaction.response.defer()
        data = await self.fetch_data(interaction)
        device = data.device
        response = "Opening {}" if value else "Closing {}"
        message = await interaction.followup.send(response.format(device.name), ephemeral=True)
        await message.delete(delay=5)
        tuya = interaction.client.tuya_client
        success = await tuya.set_device_value(device.id, value, 0)
        if success:
            device.value = value
            if not value:  # logically implied due to websocket slow dispatch.
                device.current = 0
                device.power = 0
            await interaction.client.device_control_view.dispatch_update(device.id)
        else:
            await interaction.followup.send(f"Something went wrong with {response.format(device.name).lower()}")

    async def interaction_check(self, interaction: InteractionBot, /) -> bool:
        data = await self.fetch_data(interaction)
        if interaction.user == data.author:
            return True

        raise NotAuthorError(f"Only {data.author} can use this interaction.")

    async def on_error(self, interaction: InteractionBot, error: Exception, item: discord.ui.Item[Any], /) -> None:
        response = interaction.response.send_message if not interaction.response.is_done() else interaction.followup.send
        if isinstance(error, FatalViewError):
            self.stop()
            await interaction.message.edit(view=None)
            await response(str(error), ephemeral=True)
        elif isinstance(error, ViewError):
            await response(str(error), ephemeral=True)
        else:
            await response(str(error), ephemeral=True)
            raise error
