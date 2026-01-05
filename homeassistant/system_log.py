"""
system_log.py
"""


class HomeAssistantSysLogEntry():
    def __init__(self, msg: str, level: str = None, logger: str = None) -> None:
        self.message = msg
        self.level = level if level else "warning"
        self.logger = logger if logger else "Device Log"

    def to_dict(self):
        return self.__dict__
