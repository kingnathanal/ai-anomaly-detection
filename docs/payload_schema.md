# Payload Schema Reference

Detailed field descriptions for all MQTT payloads.

## Telemetry Payload

| Field                    | Type    | Required | Description                          |
|--------------------------|---------|----------|--------------------------------------|
| `ts`                     | string  | yes      | ISO 8601 UTC timestamp               |
| `device_id`              | string  | yes      | Node identifier (e.g., `pi03-lan`)   |
| `network_type`           | string  | yes      | `lan` or `wifi`                      |
| `target_id`              | string  | yes      | Active probe target (e.g., `primary`)|
| `interval_s`             | int     | yes      | Current sampling interval in seconds |
| `metrics.icmp.ok`        | bool    | yes      | Whether ping succeeded               |
| `metrics.icmp.rtt_min_ms`| float   | yes      | Minimum RTT in ms                    |
| `metrics.icmp.rtt_avg_ms`| float   | yes      | Average RTT in ms                    |
| `metrics.icmp.rtt_max_ms`| float   | yes      | Maximum RTT in ms                    |
| `metrics.icmp.loss_pct`  | float   | yes      | Packet loss percentage               |
| `metrics.dns.ok`         | bool    | yes      | Whether DNS resolution succeeded     |
| `metrics.dns.query`      | string  | yes      | Domain queried                       |
| `metrics.dns.latency_ms` | float   | yes      | DNS resolution time in ms            |
| `metrics.http.ok`        | bool    | yes      | Whether HTTP GET returned 2xx/3xx    |
| `metrics.http.url`       | string  | yes      | URL probed                           |
| `metrics.http.status`    | int     | yes      | HTTP status code (0 if failed)       |
| `metrics.http.latency_ms`| float   | yes      | HTTP response time in ms             |

## Mitigation Command Payload

| Field         | Type   | Required | Description                              |
|---------------|--------|----------|------------------------------------------|
| `ts`          | string | yes      | ISO 8601 UTC timestamp                   |
| `command_id`  | string | yes      | Unique command identifier (UUID)         |
| `action`      | string | yes      | `failover_endpoint` or `set_interval`    |
| `params`      | object | yes      | Action-specific parameters               |

## Mitigation Status Payload

| Field         | Type   | Required | Description                              |
|---------------|--------|----------|------------------------------------------|
| `ts`          | string | yes      | ISO 8601 UTC timestamp                   |
| `command_id`  | string | yes      | Matches the command being acknowledged   |
| `device_id`   | string | yes      | Node that executed the command            |
| `status`      | string | yes      | `applied` or `failed`                    |
| `details`     | string | yes      | Human-readable description of outcome    |
