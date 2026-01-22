# scrcpy Control Messages (Notes)

This project uses scrcpy's control socket to inject touch input. scrcpy does
not ship a formal protocol spec; the canonical references are the upstream
tests linked in `docs/develop.md`:
- app/tests/test_control_msg_serialize.c
- server/src/test/java/com/genymobile/scrcpy/ControlMessageReaderTest.java

The protocol is internal and version-specific. These notes reflect scrcpy
3.3.4 behavior as used in this repo.

## Control socket

The control socket is opened after the video socket (and audio if enabled).
We use `adb forward tcp:<port> localabstract:scrcpy_<scid>` and connect via
TCP on localhost.

## INJECT_TOUCH_EVENT

We currently only send the "inject touch event" message.

Message layout (big-endian):

```
u8   type          (2 = INJECT_TOUCH_EVENT)
u8   action        (MotionEvent action)
u64  pointer_id
i32  x
i32  y
u16  screen_width
u16  screen_height
u16  pressure
u32  action_button
u32  buttons
```

In code we serialize as:

```
struct.pack(">BBQiiHHHII", type, action, pointer_id, x, y,
            screen_width, screen_height, pressure, action_button, buttons)
```

Notes:
- action follows Android MotionEvent action codes:
  - 0 = ACTION_DOWN
  - 1 = ACTION_UP
  - 2 = ACTION_MOVE
  - 3 = ACTION_CANCEL
- pointer_id is 0 for single-touch.
- screen_width/screen_height are the source video dimensions the client uses
  to map coordinates to device space. We pass the current stream size from
  the UI for stable mapping.
- pressure uses 0xFFFF for DOWN/MOVE and 0 for UP.
- action_button uses 0 for touch input.
- buttons uses 0 for touch input (mouse buttons are not set).

## INJECT_KEYCODE

Message layout (big-endian):

```
u8   type          (0 = INJECT_KEYCODE)
u8   action        (KeyEvent action)
i32  keycode
i32  repeat
i32  meta_state
```

In code we serialize as:

```
struct.pack(">BBiii", type, action, keycode, repeat, meta_state)
```

Notes:
- action uses Android KeyEvent action codes:
  - 0 = ACTION_DOWN
  - 1 = ACTION_UP
- repeat and meta_state are 0 for a simple press.

## Implementation

See `infra/scrcpy/control.py` for the current serializer and session handling.
