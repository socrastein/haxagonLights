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
- Frame: `55 CMD ff LEN payload CHECKSUM`; checksum is the complement of the byte sum. The per-light "DIY" command (`04`)
  is the exception: it ends in a constant (`0x63` in every capture) that the lights do not check (`0x00` also worked).
- 12 panels in an open ring (a triangle). The cable enters at panel 1, then counterclockwise, ending at the top tip.
- The panels are one chain of addressable LEDs: entry N of a per-light frame's 20 lights the Nth panel from the cable, and
  entries past the last panel do nothing. A panel plugged into two neighbors gets the same data twice, so the ring must stay
  open: the tip once copied panel 2 because it was also plugged into panel 1.
- The lights **ignore** a per-light frame unless it has all 20 entries and the leading byte is `01` (`00` and `02` were
  acknowledged but ignored, as were 11- and 12-entry tables). They acknowledge everything, so an ack proves nothing.
- Brightness (`05`) still works on top of a per-light frame.
- LEDs wash out light colors: a pale pink on screen looks nearly white on the panels, so pick the gradient's colors darker.

## Open questions

- Whether commands need the handshake and clock sync the app sends after connecting (the bridge sends both).
- The real minimum brightness (the app's lowest captured value was 0x00be, 19%).
- The default music sensitivity on the wire (the capture never showed the app's 75%).
- Why a power-on frame sometimes gets no `56 01` reply.

## Capturing more of the app's protocol

Enable "Enable Bluetooth HCI snoop log" in Android Developer options, use the app, then `adb bugreport` and read
`FS/data/misc/bluetooth/logs/btsnoop_hci.log` (btsnoop format, H4 packets, ATT on L2CAP channel 4). Delete the bug report
afterwards: it holds a lot of the phone's data.

## Taskbar launcher

`launcher/haxagon-lights.sh` starts the bridge if nothing answers on port 8765 (detached, logging to
`~/.cache/haxagon-lights.log`), then opens the page in a new Firefox window. `launcher/haxagon-lights.svg` is its icon: a
flat-topped hexagon in the website's dark-theme hero gradient.

On mattPC the XFCE panel (`xfce4-panel`, settings in xfconf channel `xfce4-panel`) has it as plugin 34 in panel 1, between
the Webcam Zoom and Mouse Settings launchers. The panel's launcher reads `~/.config/xfce4/panel/launcher-34/haxagon-lights.desktop`
(it points at this script and icon by absolute path). To recreate it: write that file, then
`xfconf-query -c xfce4-panel -n -p /plugins/plugin-34 -t string -s launcher`, set `/plugins/plugin-34/items` to
`haxagon-lights.desktop` (an array), insert 34 into `/panels/panel-1/plugin-ids`, and run `xfce4-panel -r`. The panel config
before this change is kept beside the live one as `xfce4-panel.xml.before-haxagon`.

The bridge keeps running after the page closes, and holds the lights only while connected. Stop it with
`kill $(pgrep -f 'bridge/server.py')`, run from a shell whose own command line does not contain that text.
