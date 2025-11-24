from json import dumps
from logging import getLogger

import paho.mqtt.client as mqtt
from flask import url_for
from requests import post

from conf import CONFIG
from util import cached_asset_name

LOG = getLogger("Notifier")


class Notifier:
    def __init__(self):
        self.config = CONFIG["NOTIFIER"]
        LOG.debug(f"init {self.config=}")

        self.mqtt = None
        if self.config.get("MQTT_HOST"):
            self.mqtt = mqtt.Client()
            if self.config.get("MQTT_USERNAME") and self.config.get("MQTT_PASSWORD"):
                self.mqtt.username_pw_set(
                    self.config["MQTT_USERNAME"], self.config["MQTT_PASSWORD"]
                )

    def message(self, message, level="INFO", component=None, asset=None):
        LOG.debug(f"{message=} {level=} {component=}")
        if self.mqtt:
            try:
                self._mqtt_message(message, level, component)
            except Exception:
                LOG.exception("could not send mqtt message")

        for ntfy_url in self.config.get("NTFY", set()):
            try:
                self._ntfy_message(ntfy_url, message, asset)
            except Exception:
                LOG.exception(f"ntfy url {ntfy_url} failed sending")

        for webhook_url in self.config.get("GCHAT", set()):
            try:
                self._googlechat_webhook(webhook_url, message)
            except Exception:
                LOG.exception(f"googlechat webhook url {webhook_url} failed sending")

        for webhook_url in self.config.get("MATTERMOST", set()):
            try:
                self._mattermost_webhook(webhook_url, message, asset)
            except Exception:
                LOG.exception(f"mattermost webhook url {webhook_url} failed sending")

    def _mqtt_message(self, message, level, component_suffix):
        assert self.mqtt is not None

        LOG.info("sending mqtt message")

        component = "infobeamer-cms"
        if component_suffix is not None:
            component = f"{component}/{component_suffix}"

        payload = {
            "level": level,
            "component": component,
            "msg": message,
        }

        LOG.info(f"mqtt payload is {payload!r}")

        self.mqtt.connect(self.config["MQTT_HOST"])
        self.mqtt.publish(self.config["MQTT_TOPIC"], dumps(payload))
        self.mqtt.disconnect()

        LOG.info("sent mqtt message")

    @staticmethod
    def _ntfy_message(ntfy_url, message, asset):
        LOG.info(f"sending alert to {ntfy_url} with message {message!r}")

        headers = {}
        if asset is not None:
            headers["Click"] = url_for(
                "content_moderate", asset_id=asset.id, _external=True
            )
            headers["Attach"] = url_for(
                "static", filename=cached_asset_name(asset), _external=True
            )

        r = post(
            ntfy_url,
            data=str(message).encode("utf-8"),
            headers=headers,
        )
        r.raise_for_status()

        LOG.info(f"ntfy url {ntfy_url} returned {r.status_code}")

    @staticmethod
    def _googlechat_webhook(webhook_url, message):
        LOG.info(f"sending message to {webhook_url} with message {message!r}")

        r = post(
            webhook_url,
            json={
                "text": message,
            },
        )
        r.raise_for_status()

        LOG.info(f"sent message to {webhook_url}")

    @staticmethod
    def _mattermost_webhook(webhook_url, message, asset):
        LOG.info(f"sending message to {webhook_url} with message {message!r}")

        data = {
            "icon_url": url_for("static", filename="event-logo.png", _external=True),
        }
        if asset is not None:
            data["attachments"] = [
                {
                    "image_url": asset.thumb,
                    "text": message,
                    "fallback": message,
                },
            ]
        else:
            data["text"] = message

        r = post(
            webhook_url,
            json=data,
        )
        r.raise_for_status()

        LOG.info(f"sent message to {webhook_url}")
