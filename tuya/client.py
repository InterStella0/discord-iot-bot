from __future__ import annotations

import asyncio
import contextlib
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from tuya_iot import TuyaOpenAPI, TuyaAssetManager, TuyaOpenMQ, AuthType

from tuya.errors import TuyaError, TuyaMissingPermissions
from tuya.models import DeviceListResult, CursorPage, DeviceStatus, WebSocketProtocol, ReportDeviceStatusData, \
    Protocol20, Socket, GoPresence
from core.models import Event

if TYPE_CHECKING:
    from core.client import IoTBot


class TuyaClient:
    BASE = "https://openapi.tuyaeu.com"
    BASE_IMAGE = "https://images.tuyaeu.com"

    def __init__(self, bot: IoTBot) -> None:
        self.bot: IoTBot = bot
        self.client_api: TuyaOpenAPI = TuyaOpenAPI(
            self.BASE, bot.settings.tuya_access_id, bot.settings.tuya_secret, auth_type=AuthType.CUSTOM
        )
        self.asset_client: TuyaAssetManager = TuyaAssetManager(self.client_api)
        self.iot_hub: TuyaOpenMQ = TuyaOpenMQ(self.client_api)
        self._sockets_infos: Dict[str, Socket] = {}

    @property
    def sockets(self):
        return [*self._sockets_infos.values()]

    def get_socket(self, id: str) -> Optional[Socket]:
        return self._sockets_infos.get(id)

    async def __aenter__(self) -> TuyaClient:
        await self.connect(self.bot.settings.tuya_username, self.bot.settings.tuya_password)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.cleanup()

    async def connect(self, username: str, password: str):
        value = await asyncio.to_thread(self.client_api.connect, username, password)
        if not value['success']:
            raise TuyaError(value['code'], value['msg'])

        self.iot_hub.start()
        self.iot_hub.add_message_listener(self.on_message)
        await self.cache_fill()
        print("CACHE FILLED", self._sockets_infos)
        return value

    async def fetch_device_ids(self) -> List[str]:
        return await self.fetch_devices_ids(self.bot.settings.tuya_socket_id)

    async def fetch_devices(self) -> List[DeviceListResult]:
        devices = await self.fetch_device_ids()
        return await self.fetch_devices_info(*devices)

    async def fetch_sockets(self) -> List[Socket]:
        devices = await self.fetch_devices()
        sockets = {x.id: x for x in map(Socket, devices)}
        for item in await self.fetch_devices_status(*sockets):
            sockets[item.id].update_from_status(item.status)

        return [*sockets.values()]

    async def cache_fill(self):
        self._sockets_infos = {x.id: x for x in await self.fetch_sockets()}

    def _process_socket(self, payload: WebSocketProtocol) -> None:
        if payload.protocol == 4:
            data: ReportDeviceStatusData = payload.data
            socket = self._sockets_infos.get(data.dev_id)
            if socket is None:
                return

            socket.update_from_status(data.status)
            self.bot.update_device(data.dev_id)
        elif payload.protocol == 20:
            data: Protocol20 = payload.data
            if isinstance(data.biz_data, GoPresence):
                socket = self._sockets_infos.get(data.dev_id)
                if socket is None:
                    return

                socket.online = data.biz_code == 'online'
                self.bot.update_device(data.dev_id)

    def on_message(self, data: Dict[str, Any]):
        factory = {4: ReportDeviceStatusData, 20: Protocol20}
        if (protocol := data['protocol']) in factory:  # REPORT DEVICE
            payload = WebSocketProtocol.from_payload(data, factory[protocol])
            self._process_socket(payload)
            self.bot.dispatch(Event.SOCKET.value, payload)
        else:
            print("IGNORING INCOMING MESSAGE", data)

    async def post(self, endpoint: str, body: Optional[dict] = None):
        result = await asyncio.to_thread(self.client_api.post, endpoint, body)
        sanitize = self.handle_result(result)
        return sanitize

    def handle_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not result['success']:
            code = result['code']
            msg = result['msg']
            if result['code'] == 1106:
                raise TuyaMissingPermissions(code, msg)
            raise TuyaError(code, msg)

        return result

    async def get(self, endpoint: str, params: Optional[dict] = None):
        result = await asyncio.to_thread(self.client_api.get, endpoint, params)
        sanitize = self.handle_result(result)
        return sanitize

    async def fetch_devices_ids(self, socket_id: str):
        return await asyncio.to_thread(self.asset_client.get_device_list, socket_id)

    async def fetch_devices_info(self, *device_ids: str) -> List[DeviceListResult]:
        params = {"device_ids": ",".join(device_ids)}
        results = []
        while True:
            state = await self.get("/v1.0/iot-03/devices", params)
            cursor = CursorPage.from_state(state['result'])
            results.extend(cursor.list)
            if not cursor.has_more:
                break

            params['last_row_key'] = cursor.last_row_key

        return results

    async def fetch_devices_status(self, *device_ids: str) -> List[DeviceStatus]:
        result = await self.get("/v1.0/iot-03/devices/status", {"device_ids": ",".join(device_ids)})
        return [DeviceStatus.from_state(s) for s in result['result']]

    async def fetch_status(self, device_id: str) -> DeviceStatus:
        endpoint = f"/v1.0/iot-03/devices/{device_id}/status"
        result = await self.get(endpoint)
        return DeviceStatus.from_state({'id': device_id, 'status': result['result']})

    async def set_device_value(self, device_id: str, value: bool, countdown: int) -> bool:
        endpoint = f'/v1.0/iot-03/devices/{device_id}/commands'
        cmds = {"commands": [{"code": "switch_1", "value": value}, {'code': 'countdown_1', 'value': countdown}]}
        value = await self.post(endpoint, cmds)
        return value['result']

    async def cleanup(self):
        with contextlib.suppress(AttributeError):
            self.iot_hub.stop()
