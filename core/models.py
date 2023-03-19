from __future__ import annotations
import asyncio
import dataclasses
import datetime
import enum
import json
import logging
import traceback
from typing import Optional, Dict, Any, Literal, TYPE_CHECKING

import aiohttp
import discord.utils
import websockets
from discord.ext import commands

from core.views import ViewPrompt

if TYPE_CHECKING:
    from core.client import IoTBot


class ControlRoom:
    MAXIMUM_TIME_WAIT = 60
    CHANNEL_ID = 1085196307016192080
    GUILD_ID = 1010844235857149952
    USER_ID = 718854043899920395

    def __init__(self, bot: IoTBot):
        self.task: Optional[asyncio.Task] = None
        self.bot: IoTBot = bot
        self.view: Optional[ViewPrompt] = None

    async def wait_until_action(self):
        await asyncio.sleep(self.MAXIMUM_TIME_WAIT)
        try:
            await self.ask()
        except asyncio.TimeoutError:
            print("TIMEOUT")

    async def prompt(self, question: str, response_true: str, response_false: str,
                     *, ctx: Optional[commands.Context] = None) -> bool:
        if ctx:
            view = ViewPrompt.from_context(ctx)
        else:
            messageable = self.bot.get_partial_messageable(self.CHANNEL_ID, guild_id=self.GUILD_ID)
            view = ViewPrompt(messageable, discord.Object(self.USER_ID))
        self.view = view
        return await view.ask(question, response_true, response_false)

    async def ask(self):
        ask = f"<@{self.USER_ID}> Do you wanna close the room? Choose your action:"
        false = "Staying open."
        true = "Closing the room..."
        value = await self.prompt(ask, true, false)
        if value:
            await self.close()

    async def open(self):
        await self.device_action(True)

    async def close(self):
        await self.device_action(False)

    async def device_action(self, value: bool, *, countdown: int = 0):
        if devices := self.bot.tuya_client.sockets:
            device, *_ = devices
            if device.value == value and device.countdown == countdown:
                return

            success = await self.bot.tuya_client.set_device_value(device.id, value, countdown)
            if success:
                device.value = value
                device.countdown = countdown
                self.bot.update_device(device.id)

            return

    def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()
            self.task = None

        if self.view is not None:
            self.view.stop()
            self.view = None

    def do(self):
        if self.task is not None:
            self.task.cancel()

        self.task = asyncio.create_task(self.wait_until_action())


class Webserver:
    BASE: str = "api.interstella.online"
    URL_BASE: str = f"https://{BASE}"
    SOCKET_BASE: str = f"ws://{BASE}/nearby/ws"

    def __init__(self, bot: IoTBot):
        self.bot: IoTBot = bot
        self.task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("websockets.server")

    def _dispatch(self, data: Dict[str, Any]) -> None:
        when = datetime.datetime.strptime(data['when'], '%Y-%m-%dT%H:%M:%S.%f')
        state = StellaStatePayload(data['state'], when)
        self.logger.info(f"DISPATCH {Event.STELLA_STATE.value}: {state}")
        self.bot.dispatch(Event.STELLA_STATE.value, state)

    def dispatch(self, data: str) -> None:
        try:
            self._dispatch(json.loads(data))
        except Exception:
            self.logger.error("Error dispatching state event.")
            traceback.print_exc()

    async def listen(self, websocket):
        async for message in websocket:
            try:
                payload = json.loads(message)
            except Exception as e:
                self.logger.error(f"IGNORING ERROR:{e}, {message}")
                continue

            if payload.get('event') == Event.STELLA_STATE.value:
                self.logger.debug(f"RECEIVING: {payload}")
                self.dispatch(payload['data'])
            else:
                self.logger.debug(f"IGNORING MESSAGE FROM WEBSERVER:, {message}")

    async def credential(self):
        settings = self.bot.settings
        data = {"username": settings.websocket_username, "password": settings.websocket_password}
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{self.URL_BASE}/auth/account/token", data=data) as r:
                if r.status == 401:
                    raise Exception("Forbidden. Invalid credential.")

                obj = await r.json()
                return obj['access_token']

    def stop(self):
        if self.task is not None:
            self.task.cancel()

    def run(self):
        self.task = asyncio.create_task(self.start())

    async def _start(self):
        try:
            await self.start()
        except Exception:
            self.logger.error("FAILURE TO CONNECT TO SERVER.")
            traceback.print_exc()

    async def start(self):
        token = await self.credential()
        uri = f"{self.SOCKET_BASE}?token={token}"
        self.logger.debug(f"Attempting to establish webserver socket: {uri}")
        async for websocket in websockets.connect(uri):
            self.logger.info(f"Websocket established: {self.SOCKET_BASE}")
            try:
                await self.listen(websocket)
            except websockets.ConnectionClosed:
                continue


@dataclasses.dataclass
class StellaStatePayload:
    state: Literal['connected', 'disconnected']
    when: datetime.datetime


class Event(enum.Enum):
    SOCKET = 'socket'
    STELLA_STATE = 'state'
