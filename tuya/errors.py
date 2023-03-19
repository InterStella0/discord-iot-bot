class TuyaError(Exception):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.message: str = msg
        self.code: int = code

class TuyaMissingPermissions(TuyaError):
    pass
