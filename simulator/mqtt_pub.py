"""MQTT publisher matching the Teltonika bridge JSON contract."""

from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger("simulator.mqtt")


class TelemetryPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        imei: str,
        qos: int = 1,
    ) -> None:
        self.imei = imei
        self.qos = qos
        self.telemetry_topic = f"teltonika/{imei}/telemetry"
        self.dtc_topic = f"teltonika/{imei}/dtc"

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"predict-fmc150-sim-{imei[-6:]}",
        )
        self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._host = host
        self._port = port
        self._connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = reason_code == 0
        if self._connected:
            logger.info("MQTT connected to %s:%s", self._host, self._port)
        else:
            logger.error("MQTT connect failed: %s", reason_code)

    def connect(self) -> None:
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()
        # Brief wait for CONNACK
        for _ in range(50):
            if self._connected:
                return
            import time
            time.sleep(0.1)
        if not self._connected:
            raise RuntimeError(
                f"Could not connect to MQTT at {self._host}:{self._port} "
                "(is Mosquitto up? check username/password)"
            )

    def close(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def publish_telemetry(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"))
        info = self._client.publish(self.telemetry_topic, body, qos=self.qos)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("Telemetry publish rc=%s", info.rc)

    def publish_dtc(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"))
        info = self._client.publish(self.dtc_topic, body, qos=self.qos)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("DTC publish rc=%s", info.rc)
        else:
            logger.info("Published DTC %s → %s", payload.get("dtc_code"), self.dtc_topic)
