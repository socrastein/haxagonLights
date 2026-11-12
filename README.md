# haxagonLights

Control Haxagon hexagon lights (the ones that come with the MeRGBW app) from a web page on your own computer. No vendor
app, no ads.

This is an unofficial project, not affiliated with the lights' maker. It has been tried on one set of 12 panels.

## What it does

- Power, solid color (hue and saturation), and brightness
- A gradient from one color to another along the panels
- The 18 built-in scenes, with a speed slider
- The 6 music modes, with a sensitivity slider
- Connects to the lights automatically when the page opens

## How it works

Firefox cannot use Bluetooth from a web page, so a small Python bridge does the Bluetooth. It talks to the lights with
[bleak](https://github.com/hbldh/bleak) (BlueZ on Linux) and serves the page on `127.0.0.1:8765`, so only the computer it runs
on can control the lights. The bytes it sends were decoded from a Bluetooth capture of the official app. They are written
up in the comments of `bridge/protocol.py`, and `CLAUDE.md` lists what is known about the lights' behavior.

## Run it

You need Linux with BlueZ and Bluetooth, Python 3.10 or newer, and a browser.

```sh
python -m venv .venv
.venv/bin/pip install bleak aiohttp pytest
npm install        # only for the format and type checks
npm start          # then open http://127.0.0.1:8765
```

Other checks: `npm test` (the protocol, against frames the app really sent), `npm run format:check`, `npm run typecheck`.

On a Linux desktop, `launcher/haxagon-lights.sh` starts the bridge if needed and opens the page, and
`launcher/haxagon-lights.svg` is an icon for it. `CLAUDE.md` describes how it was added to an XFCE panel.

## Things to know

- The lights accept **one Bluetooth connection at a time**. Close or disconnect any phone app first, or the page will not
  find them.
- Only panels 1 to 11 can be colored separately. The top panel of the triangle always copies panel 2. No variation of the
  command changed that.
- LEDs wash out pale colors, so a gradient looks closer to the screen if both colors are a bit darker than you expect.
- Another set of Haxagon lights may use different panel counts or commands. The protocol notes should help if it does.

## License

0BSD: use it for anything, no conditions. See `LICENSE`.
