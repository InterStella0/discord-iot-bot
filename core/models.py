from __future__ import annotations
import asyncio
import contextlib
import dataclasses
import datetime
import enum
import json
from typing import Optional, Dict, Any, List, Literal

import discord.utils
import starlight
import websockets
from discord.ext import commands
from tuya_iot import TuyaOpenAPI, TuyaAssetManager, TuyaOpenMQ, AuthType

from core.errors import TuyaError
from settings import Settings


class IoTBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__('?uwu ', intents=settings.intents, help_command=starlight.MenuHelpCommand(with_app_command=True))
        self.settings: Settings = settings
        self.tuya_client: TuyaClient = TuyaClient(self)
        self.action = CloseRoom(self)

    async def on_stella_state(self, data: StellaStatePayload):
        if data.state == "connected":
            self.action.cancel()
        elif data.state == "disconnected":
            self.action.do()

    async def _startup(self) -> None:
        discord.utils.setup_logging()
        async with self, self.tuya_client:
            await self.start(self.settings.bot_token)

    async def retrieve_devices(self):
        return await self.tuya_client.retrieve_devices_ids(self.settings.tuya_socket_id)

    def startup(self) -> None:
        asyncio.run(self._startup())


class CloseRoom:
    MAXIMUM_TIME_WAIT = 60

    def __init__(self, bot: IoTBot):
        self.task: Optional[asyncio.Task] = None
        self.bot: IoTBot = bot

    async def wait_until_action(self):
        await asyncio.sleep(self.MAXIMUM_TIME_WAIT)
        try:
            await self.ask()
        except asyncio.TimeoutError:
            print("TIMEOUT")

    async def ask(self):
        value = await self.prompt('')
        if value:
            if devices := await self.bot.retrieve_devices():
                device, *_ = devices
                await self.bot.tuya_client.set_device_value(device['id'], 0, 0)
                return

            print("NO DEVICES RESPONSE:", devices)
        else:
            print("CANCELLED")

    def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()
            self.task = None

    def do(self):
        if self.task is not None:
            self.task.cancel()

        self.task = asyncio.create_task(self.wait_until_action())




class Webserver:
    BASE = "ws://localhost:7001"

    def __init__(self, bot: IoTBot):
        self.bot: IoTBot = bot

    async def listen(self, websocket):
        async for message in websocket:
            try:
                payload = json.loads(message)
            except Exception as e:
                print("IGNORING ERROR:", e, message)
                continue

            if payload.get('event') == Event.STELLA_STATE:
                data = payload['data']
                state = StellaStatePayload(data['state'], data['when'])
                self.bot.dispatch(Event.STELLA_STATE, state)
            else:
                print("IGNORING MESSAGE FROM WEBSERVER:", message)

    async def start(self):
        async for websocket in websockets.connect(self.BASE):
            try:
                await self.listen(websocket)
            except websockets.ConnectionClosed:
                continue


@dataclasses.dataclass
class SocketPayload:
    data_id: str
    id: str
    key: str
    status: List[Dict[str, Any]]
    t: int
    pv: str
    protocol: int
    sign: str


@dataclasses.dataclass
class StellaStatePayload:
    state: Literal['connect', 'disconnect']
    when: datetime.datetime


class Event(enum.Enum):
    SOCKET = 'socket'
    STELLA_STATE = 'stella_state'


class TuyaClient:
    BASE = "https://openapi.tuyaeu.com"

    def __init__(self, bot: IoTBot) -> None:
        self.bot: IoTBot = bot
        self.client_api: TuyaOpenAPI = TuyaOpenAPI(
            self.BASE, bot.settings.tuya_access_id, bot.settings.tuya_secret, auth_type=AuthType.CUSTOM
        )
        self.asset_client: TuyaAssetManager = TuyaAssetManager(self.client_api)
        self.iot_hub: TuyaOpenMQ = TuyaOpenMQ(self.client_api)

    async def __aenter__(self) -> TuyaClient:
        await self.connect(self.bot.settings.tuya_username, self.bot.settings.tuya_password)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.cleanup()

    async def connect(self, username: str, password: str):
        value = await asyncio.to_thread(self.client_api.connect, username, password)
        if not value['success']:
            raise TuyaError(value['msg'], value['code'])

        self.iot_hub.start()
        self.iot_hub.add_message_listener(self.on_message)
        return value

    def on_message(self, data: Dict[str, Any]):
        if not (received := data.get('data')):
            return

        payload = SocketPayload(
            data_id=received['dataId'], id=received['devId'], key=received['productKey'],
            protocol=data['protocol'], pv=data['pv'], sign=data['sign'], t=data['t'],
            status=received['status']
        )
        self.bot.dispatch(Event.SOCKET, payload)

    async def post(self, endpoint: str, body: Optional[dict] = None):
        return await asyncio.to_thread(self.client_api.post, endpoint, body)

    async def get(self, endpoint: str, params: Optional[dict] = None):
        return await asyncio.to_thread(self.client_api.get, endpoint, params)

    async def retrieve_devices_ids(self, socket_id: str):
        return await asyncio.to_thread(self.asset_client.get_device_list, socket_id)

    async def retrieve_devices_info(self, *device_ids: str):
        result = await self.get("/v1.0/iot-03/devices", {"device_ids": ",".join(device_ids)})
        value = result.get("result")
        if value is None:
            return result
        return value

    async def retrieve_devices_status(self, *device_ids: str):
        return await self.get("/v1.0/iot-03/devices/status", {"device_ids": ",".join(device_ids)})

    async def retrieve_status(self, device_id: str):
        endpoint = f"/v1.0/iot-03/devices/{device_id}/status"
        return await self.get(endpoint)

    async def set_device_value(self, device_id: str, value: bool, countdown: int):
        endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
        cmds = {"commands": [{"code": "switch_1", "value": value}, {'code': 'countdown_1', 'value': countdown}]}
        return await self.post(endpoint, cmds)

    async def toggle_device(self, device_id: str, countdown: int):
        status = await self.retrieve_status(device_id)
        result = status.get('result')
        if result is None:
            return status

        value = False
        for val in result:
            if val['code'] == 'switch_1':
                value = not val['value']
                break

        return await self.set_device_value(device_id, value, countdown)

    async def cleanup(self):
        with contextlib.suppress(AttributeError):
            self.iot_hub.stop()
