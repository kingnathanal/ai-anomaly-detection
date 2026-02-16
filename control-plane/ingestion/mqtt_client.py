"""MQTT client helper for the ingestion service."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Callable

import paho.mqtt.client as mqtt

log = logging.getLogger("ingestion.mqtt")


def create_client(on_telemetry: Callable[[dict[str, Any]], None]) -> mqtt.Client:
    """Create an MQTT client that subscribes to telemetry/# and calls
    *on_telemetry* for every valid message."""

    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    user = os.environ.get("MQTT_USER")
    pw = os.environ.get("MQTT_PASS")

    client_id = f"ingestion-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(
        client_id=client_id,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    if user and pw:
        client.username_pw_set(user, pw)

    def _on_connect(c: mqtt.Client, _ud: Any, _flags: Any,
                    reason_code: Any, _props: Any = None) -> None:
        # CallbackAPIVersion.VERSION2: reason_code is a ReasonCode object
        if reason_code == 0 or (hasattr(reason_code, 'is_failure') and not reason_code.is_failure):
            log.info("mqtt connected broker=%s:%d", host, port)
            c.subscribe("telemetry/#", qos=1)
            log.info("subscribed topic=telemetry/#")
        else:
            log.error("mqtt connect failed rc=%s", reason_code)

    def _on_disconnect(_c: mqtt.Client, _ud: Any,
                       _flags: Any = None, reason_code: Any = None,
                       _props: Any = None) -> None:
        # CallbackAPIVersion.VERSION2: 5 args (client, userdata, disconnect_flags, reason_code, properties)
        is_failure = False
        if reason_code is not None:
            if hasattr(reason_code, 'is_failure'):
                is_failure = reason_code.is_failure
            elif reason_code != 0:
                is_failure = True
        if is_failure:
            log.warning("mqtt disconnected rc=%s, will reconnect", reason_code)

    def _on_message(_c: mqtt.Client, _ud: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("bad payload topic=%s err=%s", msg.topic, exc)
            return

        # Light validation: require minimum keys
        required = {"ts", "device_id", "network_type", "target_id",
                     "interval_s", "metrics"}
        if not required.issubset(payload.keys()):
            log.warning("invalid telemetry payload, missing keys topic=%s", msg.topic)
            return

        on_telemetry(payload)

    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    client.connect(host, port, keepalive=60)
    return client
