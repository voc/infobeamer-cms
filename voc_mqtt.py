from json import dumps
from logging import getLogger

import paho.mqtt.client as mqtt

from conf import CONFIG

LOG = getLogger("MQTT")


def send_message(*args, **kwargs):
    c = MQTT()
    r = c.send_message(*args, **kwargs)
    c.disconnect()
    return r


class MQTT:
    def __init__(self):
        self.client = mqtt.Client()
        if CONFIG.get("MQTT_USERNAME") and CONFIG.get("MQTT_PASSWORD"):
            self.client.username_pw_set(
                CONFIG["MQTT_USERNAME"], CONFIG["MQTT_PASSWORD"]
            )
        self.client.connect(CONFIG["MQTT_SERVER"])
        LOG.info("connected to mqtt server")

    def disconnect(self):
        self.client.disconnect()

    def send_message(self, message, level="INFO", component=None):
        comp = "infobeamer-cms"
        if component is not None:
            comp = f"{comp}/{component}"
        msg = dumps(
            {
                "level": level,
                "component": comp,
                "msg": message,
            }
        )
        LOG.info(f"sending message: {msg}")
        r = self.client.publish(
            CONFIG["MQTT_TOPIC"],
            msg,
        )
        LOG.info(f"sent message: {r!r}")
        return r
