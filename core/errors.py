class TuyaError(Exception):
    def __init__(self, msg, code) -> None:
        self.message = msg
        self.code = code
