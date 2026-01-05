"""
device.py

# TODO: Create a base class for event, number, sensor since they all have a common
        set of functions.
"""

# Standard imports
import binascii
import json
import machine
import os
from sys import platform
try:
    from typing import Any, Callable, Dict, List, Optional
except ImportError:
    pass

# Third party imports
from homeassistant import DISCOVERY_PREFIX
from homeassistant.system_log import HomeAssistantSysLogEntry
from homeassistant.number import HomeAssistantNumber
from homeassistant.sensor import HomeAssistantSensor


class HomeAssistantDevice():
    def __init__(self, device_name: str,
                 model: str,
                 network_send_fxn: Callable[[str, str], bool],
                 debug: bool = False) -> None:
        self.device_name = device_name
        self.model = model
        self.network_send_fxn = network_send_fxn
        self.debug = debug
        self.mf = platform
        self.device_id = f"{self.model}-{binascii.hexlify(machine.unique_id()).decode('utf-8')}"
        self.log_topic = f"{DISCOVERY_PREFIX}/logs/{self.device_id}"
        self.number_topic = f"{DISCOVERY_PREFIX}/number/{self.device_id}"
        self.sensor_topic = f"{DISCOVERY_PREFIX}/sensor/{self.device_id}"
        self.discovery_device = {
            "ids": f"{binascii.hexlify(machine.unique_id()).decode('utf-8')}",
            "mf": f"{self.mf}",
            "mdl": f"{os.uname().machine}",
            "name": f"{self.device_name}",
            "sw": f"{os.uname().version}"
        }
        self.numbers: List[HomeAssistantNumber] = []
        self.sensors: List[HomeAssistantSensor] = []
        self.sensors_msg = {}

    def add_number(self, number: HomeAssistantNumber):
        if self.debug:
            print(f"Adding number: {number.name}")

        # Prepend device name to sensor name to further differentiate it
        number.set_device_name(
            f"{self.device_name}_{number.sanitized_name}")

        # Update sensor discovery info with device details
        number_unique_id = f"{self.device_id}_{number.device_name}"
        number.set_discovery_topic(f"{DISCOVERY_PREFIX}/number/{number_unique_id}/config")
        number.set_discovery_info("~", self.number_topic)
        number.set_discovery_info("obj_id", number.device_name)
        number.set_discovery_info("uniq_id", number_unique_id)
        number.set_discovery_info("dev", self.discovery_device)
        number.set_discovery_info(
            "val_tpl",
            f"{{{{ value_json.{number.sanitized_name} | round({number.precision}) }}}}"
        )

        # Add to collection of device numbers
        self.numbers.append(number)

    def add_sensor(self, sensor: HomeAssistantSensor):
        if self.debug:
            print(f"Adding sensor: {sensor.name}")

        # Prepend device name to sensor name to further differentiate it
        sensor.set_device_name(
            f"{self.device_name}_{sensor.sanitized_name}")

        # Update sensor discovery info with device details
        sensor_unique_id = f"{self.device_id}_{sensor.device_name}"
        sensor.set_discovery_topic(f"{DISCOVERY_PREFIX}/sensor/{sensor_unique_id}/config")
        sensor.set_discovery_info("~", self.sensor_topic)
        sensor.set_discovery_info("obj_id", sensor.device_name)
        sensor.set_discovery_info("uniq_id", sensor_unique_id)
        sensor.set_discovery_info("dev", self.discovery_device)

        if "device_class" not in sensor.discovery_info and "unit_of_meas" not in sensor.discovery_info:
            round_str = ""
        else:
            round_str = f"| round({sensor.precision})"
            sensor.set_discovery_info("stat_cla", "measurement")

        sensor.set_discovery_info(
            "val_tpl",
            f"{{{{ value_json.{sensor.sanitized_name} {round_str} }}}}"
        )

        # Add to collection of device sensors
        self.sensors.append(sensor)
        self.sensors_msg[sensor.sanitized_name] = None

    def publish_logs(self, logs: list, **kwargs) -> None:
        """Publish logs to Home Assistant via the logs topic.

        Args:
            logs (list): List of log strings OR List of HomeAssistantSysLogEntry objects.

        Raises:
            RuntimeError: If invalid log type.
        """
        qos = kwargs.get("qos", 1)

        # Ensure log messages are of type HomeAssistantSysLogEntry
        syslogs = []
        if logs:
            if isinstance(logs[0], str):
                for log in logs:
                    syslogs.append(HomeAssistantSysLogEntry(log))
            elif isinstance(logs[0], bytes):
                for log in logs:
                    syslogs.append(HomeAssistantSysLogEntry(log.decode()))
            elif not isinstance(logs[0], HomeAssistantSysLogEntry):
                raise RuntimeError("Logs must be of type HomeAssistantSysLogEntry")
            else:
                syslogs = logs
        else:
            syslogs = logs

        for log in syslogs:
            msg = json.dumps(log.to_dict())
            self.network_send_fxn(msg=msg, topic=self.log_topic, retain=True, qos=qos, **kwargs)

    def publish_numbers(self, **kwargs) -> None:
        """Publish all number data"""
        if not self.numbers:
            return

        topic = f"{self.number_topic}/state"
        qos = kwargs.get("qos", 1)

        msg = {}
        for number in self.numbers:
            number_data = number.read()
            msg[number.sanitized_name] = number_data

        if self.debug:
            print(f"Publishing to {topic}:")
            print(f"{json.dumps(msg)}")

        self.network_send_fxn(msg=json.dumps(msg), topic=topic, retain=True, qos=qos, **kwargs)

    def publish_sensors(self, **kwargs) -> None:
        """Publish all cached sensor data"""
        if not self.sensors:
            return

        topic = f"{self.sensor_topic}/state"
        qos = kwargs.get("qos", 1)

        total_samples = max(len(sensor.cache) for sensor in self.sensors)
        for _ in range(total_samples):
            for sensor in self.sensors:
                if data := sensor.pop_cache():
                    self.sensors_msg[sensor.sanitized_name] = data

            if self.debug:
                print(f"Publishing to {topic}:")
                print(f"{json.dumps(self.sensors_msg)}")

            self.network_send_fxn(msg=json.dumps(self.sensors_msg), topic=topic, retain=True, qos=qos, **kwargs)

    def read(self, sensor: HomeAssistantSensor, cache: bool = True) -> Any:
        """Read an individual sensor
           Data will be saved for publishing if cache == True"""
        if sensor not in self.sensors:
            raise RuntimeError(f"Sensor {sensor.name} not registered with device {self.device_name}")

        return sensor.read(cache=cache)

    def read_sensors(self, cache: bool = True) -> Dict:
        """Read data from all added sensors.
           Data will be saved for publishing if cache == True"""
        data = {}
        for sensor in self.sensors:
            sensor_data = sensor.read(cache=cache)
            data[sensor.name] = sensor_data

        return data

    def send_discovery(self, **kwargs):
        """Send discovery data to Home Assistant"""
        qos = kwargs.get("qos", 1)

        for sensor in self.sensors:
            if self.debug:
                print(f"Discovery topic: {sensor.discovery_topic}")
                print(f"Discovery msg:\n{json.dumps(sensor.discovery_info)}")

            self.network_send_fxn(msg=json.dumps(sensor.discovery_info),
                                  topic=sensor.discovery_topic,
                                  retain=True,
                                  qos=qos,
                                  **kwargs)

        for number in self.numbers:
            if self.debug:
                print(f"Discovery topic: {number.discovery_topic}")
                print(f"Discovery msg:\n{json.dumps(number.discovery_info)}")

            self.network_send_fxn(msg=json.dumps(number.discovery_info),
                                  topic=number.discovery_topic,
                                  retain=True,
                                  qos=qos,
                                  **kwargs)
