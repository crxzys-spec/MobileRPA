# MRPA Client WebSocket Protocol

This document describes the JSON messages exchanged between the MRPA server and
the device-side `client` service when running in push mode.

## Transport
- WebSocket endpoint: `ws://<mrpa-host>:8020/ws/client`
- Optional token: append `?token=...` and set `MRPA_CLIENT_TOKEN` on MRPA.
- All messages are JSON objects with a `type` field.

## Client -> MRPA

### register
```json
{
  "type": "register",
  "client_id": "client-001",
  "devices": [{"id": "DEVICE_ID", "status": "device"}],
  "sessions": [{"device_id": "DEVICE_ID", "status": "idle", "pending": 0}],
  "capabilities": {"webrtc": true, "commands": true}
}
```

### devices_update
```json
{ "type": "devices_update", "devices": [ ... ] }
```

### sessions_update
```json
{ "type": "sessions_update", "sessions": [ ... ] }
```

### session_update
```json
{ "type": "session_update", "session": { ... } }
```

### command_update
```json
{ "type": "command_update", "device_id": "DEVICE_ID", "command": { ... } }
```

### queue_clear_result
```json
{
  "type": "queue_clear_result",
  "request_id": "REQ_ID",
  "device_id": "DEVICE_ID",
  "drained": 2
}
```

### session_close_result
```json
{
  "type": "session_close_result",
  "request_id": "REQ_ID",
  "device_id": "DEVICE_ID",
  "closed": true
}
```

### webrtc_answer
```json
{
  "type": "webrtc_answer",
  "request_id": "REQ_ID",
  "sdp": "v=0...",
  "sdp_type": "answer"
}
```

## MRPA -> Client

### command
```json
{
  "type": "command",
  "device_id": "DEVICE_ID",
  "command": { "id": "CMD_ID", "type": "tap", "x": 10, "y": 20 }
}
```

### queue_clear
```json
{ "type": "queue_clear", "request_id": "REQ_ID", "device_id": "DEVICE_ID" }
```

### session_close
```json
{ "type": "session_close", "request_id": "REQ_ID", "device_id": "DEVICE_ID" }
```

### webrtc_offer
```json
{
  "type": "webrtc_offer",
  "request_id": "REQ_ID",
  "device_id": "DEVICE_ID",
  "sdp": "v=0...",
  "sdp_type": "offer"
}
```

## Notes
- `command_update` should be sent at least when status changes and when it
  finishes (done/failed).
- `register` should be sent once per connection, then periodic updates keep
  MRPA in sync.
- WebRTC media flows directly between browser and client. MRPA only relays SDP.
- Enable trace logs with `MRPA_CLIENT_WS_TRACE=true` (MRPA) and
  `CLIENT_WS_TRACE=true` (client).
- Presence is derived from `last_seen` timestamps. MRPA marks clients as
  `offline` after `MRPA_CLIENT_INACTIVE_SEC`, and evicts them after
  `MRPA_CLIENT_EVICT_SEC`.
