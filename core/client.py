import asyncio
from typing import Optional
from weakref import WeakValueDictionary

import aiohttp
import asyncpg
import discord
import starlight
from discord.ext import commands

from core.models import ControlRoom, Webserver, StellaStatePayload
from core.views import DeviceControl, ViewDataDevice
from settings import Settings
from tuya.client import TuyaClient


class IoTBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__('?uwu ', intents=settings.intents, help_command=starlight.MenuHelpCommand(with_app_command=True))
        self.owner_ids = settings.owner_ids
        self.settings: Settings = settings
        self.tuya_client: TuyaClient = TuyaClient(self)
        self.room: ControlRoom = ControlRoom(self)
        self.pool: Optional[asyncpg.Pool] = None
        self.server = Webserver(self)
        self.recent_task: WeakValueDictionary[str, asyncio.Task] = WeakValueDictionary()
        self.device_control_view: Optional[DeviceControl] = None
        self.device_update: Optional[discord.Webhook] = None

    def get_view_data(self, device_id: str) -> Optional[ViewDataDevice]:
        return self.device_control_view._socket_data.get(device_id)

    def update_device(self, device_id: str) -> None:
        if task := self.recent_task.get(device_id):
            task.cancel()

        async def dispatching(id: str) -> None:
            await asyncio.sleep(1)
            await self.device_control_view.dispatch_update(id)

        self.recent_task[device_id] = self.loop.create_task(dispatching(device_id))

    async def connect_to_db(self) -> asyncpg.Pool:
        settings = self.settings
        pool = await asyncpg.create_pool(
            user=settings.pg_username, password=settings.pg_password, database=settings.pg_database_name
        )
        return pool

    async def on_state(self, data: StellaStatePayload) -> None:
        if data.state == "connected":
            self.room.cancel()
            await self.room.open()
        elif data.state == "disconnected":
            self.room.do()

    async def _startup(self) -> None:
        discord.utils.setup_logging()
        async with self, self.tuya_client, await self.connect_to_db() as self.pool, aiohttp.ClientSession() as self.session:
            self.device_update = discord.Webhook.from_url(self.settings.current_monitor_webhook, session=self.session)
            self.device_control_view = view = DeviceControl(bot=self, atomic=True)
            self.add_view(view)
            self.server.run()
            await self.start(self.settings.bot_token)

        self.server.stop()

    def startup(self) -> None:
        asyncio.run(self._startup())
