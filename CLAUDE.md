# haxagonLights

A local web page plus a Bluetooth bridge that control Haxagon lights (the MeRGBW app's lights) without the vendor app.
Follows the global coding standards; this file adds only what is specific to this repo.

## Layout

- `bridge/protocol.py`: pure functions from intent to byte frames. No Bluetooth. Every number was decoded from a Bluetooth
  capture of the MeRGBW app, not from documentation.
- `bridge/lights.py`: finds, connects to and writes to the lights (bleak/BlueZ). Sends frames, decides nothing.
- `bridge/server.py`: aiohttp server on 127.0.0.1:8765. Serves `web/` and a JSON API; one row in `ACTIONS` per control.
- `web/`: plain HTML/CSS/JS, no build step, typed with JSDoc and `checkJs`. Firefox has no Web Bluetooth, which is why the
  Bluetooth lives in the bridge.

Dependencies point one way: `web` calls `server`, `server` calls `lights` and `protocol`, `lights` calls `protocol`.

## Commands

- `npm start`: run the bridge, then open http://127.0.0.1:8765
- `npm test`: pytest for the protocol (every expected frame is a frame the app really sent)
- `npm run format:check` / `npm run format`: Prettier for the web files (Python has no formatter, by choice)
- `npm run typecheck`: `checkJs` over `web/`
- `npm run measure -- web/app.js`: the standards' measure tool (JS only; the measure tool does not read Python)
- First use: `python -m venv .venv && .venv/bin/pip install bleak aiohttp pytest`, then `npm install`

## Facts about the lights

- The lights accept **one Bluetooth connection at a time** and stop advertising while connected. A phone app, a leftover
  `bluetoothctl` session or a crashed bridge can all hold them. Check with `bluetoothctl devices Connected`.
- Commands go to characteristic `0xfff3`; replies arrive on `0xfff4` after writing `01 00` to its descriptor.
- Frame: `55 CMD ff LEN payload CHECKSUM`; checksum is the complement of the byte sum. The per-light "DIY" command (`04`) is
  the exception: its last byte was a constant `0x63` in every capture.
- 12 panels in a ring (a triangle). The cable enters at panel 1, then counterclockwise, ending at the top tip. A DIY frame has
  20 RGB entries but only entries 1-11 light panels 1-11; entry 2 also lights panel 12 (the tip). Entries 12-20 do nothing.

## Open questions

- Whether commands need the handshake and clock sync the app sends after connecting (the bridge sends both).
- The real minimum brightness (the app's lowest captured value was 0x00be, 19%).
- The default music sensitivity on the wire (the capture never showed the app's 75%).
- What the leading `01` and trailing `0x63` bytes of the DIY frame mean.

## Capturing more of the app's protocol

Enable "Enable Bluetooth HCI snoop log" in Android Developer options, use the app, then `adb bugreport` and read
`FS/data/misc/bluetooth/logs/btsnoop_hci.log` (btsnoop format, H4 packets, ATT on L2CAP channel 4). Delete the bug report
afterwards: it holds a lot of the phone's data.
