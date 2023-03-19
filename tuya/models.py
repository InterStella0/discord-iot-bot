from __future__ import annotations
import dataclasses
from typing import List, Dict, Any, Optional, Generic, TypeVar


class ProtocolData:
    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> ProtocolData:
        raise NotImplementedError


class Protocol20Data:
    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> ProtocolData:
        raise NotImplementedError


@dataclasses.dataclass
class Protocol20(ProtocolData):
    dev_id: str
    product_key: str
    biz_code: str
    biz_data: Any

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> Protocol20:
        factory_dict = {'online': GoPresence, 'offline': GoPresence}
        factory = factory_dict.get(data['bizCode'], Protocol20Identity)
        return cls(
            dev_id=data['devId'], product_key=data['productKey'], biz_code=data['bizCode'],
            biz_data=factory.from_payload(data['bizData'])
        )


@dataclasses.dataclass
class GoPresence(Protocol20Data):  # consist of online&offline due to same payload
    time: int

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> Protocol20Data:
        return cls(**data)


@dataclasses.dataclass
class Protocol20Identity(Protocol20Data):
    etc: Dict[str, Any]

    @classmethod
    def from_payload(cls, data: Dict[str, Any]) -> Protocol20Identity:
        return cls(etc=data)


@dataclasses.dataclass
class WebSocketProtocol:
    protocol: int
    pv: str
    t: int
    data: ProtocolData
    sign: str

    @classmethod
    def from_payload(cls, payload: Dict[str, Any], protocol_factory: ProtocolData) -> WebSocketProtocol:
        data = payload.pop('data')
        return cls(data=protocol_factory.from_payload(data), **payload)


@dataclasses.dataclass
class StatusItem:
    code: str
    value: Any
    t: str
    etc: Dict[str, str]  # stupid API randomly have mapping[str, str]. Added etc to account for stupid.


@dataclasses.dataclass
class ReportDeviceStatusData(ProtocolData):
    data_id: str
    dev_id: str
    product_key: str
    status: List[Dict[str, Any]]

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> ReportDeviceStatusData:
        status = payload.pop('status')
        return cls(
            status=[StatusItem(
                t=kwargs.pop('t'),
                code=kwargs.pop('code'),
                value=kwargs.pop('value'),
                etc=kwargs
            ) for kwargs in status],
            data_id=payload['dataId'], dev_id=payload['devId'], product_key=payload['productKey']
        )


@dataclasses.dataclass
class DeviceStatus:
    id: str
    status: List[DeviceStatusValue]

    @classmethod
    def from_state(cls, state: Dict[str, Any]):
        return cls(id=state['id'], status=[DeviceStatusValue(**kwargs) for kwargs in state['status']])


@dataclasses.dataclass
class DeviceStatusResult:
    pass


@dataclasses.dataclass
class DeviceStatusValue:
    code: str
    value: Any


@dataclasses.dataclass
class CursorPage:
    has_more: bool
    list: List[DeviceListResult]
    total: int
    last_row_key: Optional[str] = None

    @classmethod
    def from_state(cls, state: Dict[str, Any]):
        device_list = state.pop('list')
        return cls(
            list=[DeviceListResult(**kwargs) for kwargs in device_list],
            **state
        )


class Socket:
    def __init__(self, device_state: DeviceListResult) -> None:
        self.name = device_state.name
        self.gateway_id = device_state.gateway_id
        self.asset_id = device_state.asset_id
        self.id = device_state.id
        self.icon = device_state.icon
        self.category = device_state.category
        self.category_name = device_state.category_name
        self.model = device_state.model
        self.online = device_state.online
        self.product_name = device_state.product_name
        self.product_id = device_state.product_id
        self.ip = device_state.ip
        self.value: bool = False
        self.voltage: int = 0
        self.current: int = 0
        self.power: int = 0
        self.countdown: int = 0

    def __repr__(self):
        return ('<Socket(id={0.id}, category={0.category}, model={0.model}, product_id={0.product_id}, '
                'value={0.value}, voltage={0.voltage}, current={0.current}, power={0.power}, countdown={0.countdown})>'
                ).format(self)

    def update_from_status(self, status: DeviceStatus):
        attrs = {'switch_1': 'value', 'countdown_1': 'countdown', 'cur_current': 'current', 'cur_voltage': 'voltage',
                 'cur_power': 'power'}
        for status_value in status:
            if status_value.code in attrs:
                setattr(self, attrs[status_value.code], status_value.value)


@dataclasses.dataclass
class DeviceListResult:
    active_time: int
    asset_id: str
    category: str
    category_name: str
    create_time: int
    gateway_id: str
    icon: str
    id: str
    ip: str
    lat: str
    local_key: str
    lon: str
    model: str
    name: str
    online: bool
    product_id: str
    product_name: str
    sub: bool
    time_zone: str
    update_time: int
    uuid: str