"""Local web server: serves the control page and turns its requests into frames for the lights.

The page (../web) sends plain JSON like {"hue": 120}; this file picks the protocol.py function for
each action and hands the frame to lights.py. It listens on localhost only, so just this PC can
control the lights.

Run with: .venv/bin/python bridge/server.py
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiohttp import web

import lights
import presets
import protocol

HOST = "127.0.0.1"
PORT = 8765
WEB_DIRECTORY = Path(__file__).resolve().parent.parent / "web"
LIGHTS_KEY = web.AppKey("lights", lights.LightsConnection)
CONNECT_LOCK_KEY = web.AppKey("connect lock", asyncio.Lock)
PRESETS_PATH = presets.default_presets_path()

# Action name -> (frame builder, the JSON fields it takes, in the builder's argument order).
# Adding a control means adding one row here and one function to protocol.py.
ACTIONS: dict[str, tuple[Callable[..., bytes], list[str]]] = {
    "power": (protocol.power_frame, ["isOn"]),
    "color": (protocol.color_frame, ["hue", "saturation"]),
    "brightness": (protocol.brightness_frame, ["percent"]),
    "panels": (protocol.panel_colors_frame, ["colors"]),
    "scene": (protocol.scene_frame, ["name"]),
    "scene-speed": (protocol.scene_speed_frame, ["percent"]),
    "music-mode": (protocol.music_mode_frame, ["name"]),
    "music-sensitivity": (protocol.music_sensitivity_frame, ["percent"]),
}


def json_error(message: str, status: int) -> web.Response:
    """Build the error body every failure uses: {"error": "..."}."""
    return web.json_response({"error": message}, status=status)


@web.middleware
async def local_requests_only(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    """Reject requests that did not come from this server's own page.

    Any website open in the browser can send requests to localhost, so without this a random page
    could flash the lights. Checking Host stops DNS-rebinding tricks and checking Origin stops
    other sites' scripts.
    """
    allowed_hosts = {f"{HOST}:{PORT}", f"localhost:{PORT}"}
    origin = request.headers.get("Origin")
    is_own_origin = origin is None or origin in {f"http://{host}" for host in allowed_hosts}
    if request.host not in allowed_hosts or not is_own_origin:
        return json_error("forbidden", 403)
    return await handler(request)


async def show_page(_request: web.Request) -> web.FileResponse:
    """Serve the control page."""
    return web.FileResponse(WEB_DIRECTORY / "index.html")


async def show_options(_request: web.Request) -> web.Response:
    """List the scene and music mode names, so the page never hard-codes them."""
    return web.json_response(
        {"scenes": list(protocol.SCENE_IDS), "musicModes": list(protocol.MUSIC_MODE_IDS)}
    )


async def show_status(request: web.Request) -> web.Response:
    """Report whether the lights are currently connected."""
    is_connected = lights.is_lights_connected(request.app.get(LIGHTS_KEY))
    return web.json_response({"isConnected": is_connected})


async def show_gradient_colors(request: web.Request) -> web.Response:
    """Work out a gradient's panel colors without sending them; the page shows, then sends them."""
    try:
        body = await read_json_body(request)
        colors = protocol.gradient_colors(body["startColor"], body["endColor"])
    except (ValueError, TypeError, KeyError) as error:
        return json_error(f"bad request: {error}", 400)
    return web.json_response({"colors": colors})


async def show_presets(_request: web.Request) -> web.Response:
    """List the preset slots, slot 1 first; null marks an empty one."""
    return web.json_response({"slots": presets.load_presets(PRESETS_PATH)})


async def store_preset(request: web.Request) -> web.Response:
    """Save the body's look to the slot in the path; answer with every slot, like show_presets."""
    try:
        slot_number = int(request.match_info["slot"])
        slots = presets.save_preset(PRESETS_PATH, slot_number, await read_json_body(request))
    except ValueError as error:  # Also covers a slot that is not a number and malformed JSON.
        return json_error(f"bad request: {error}", 400)
    return web.json_response({"slots": slots})


async def connect(request: web.Request) -> web.Response:
    """Find and connect to the lights: a second or two, or the full scan time when they are absent.

    Requests take turns, because BlueZ refuses a second scan while one runs (two tabs opening at
    once used to crash one with a 500). The one that waited then finds the lights connected.
    """
    async with request.app[CONNECT_LOCK_KEY]:
        if lights.is_lights_connected(request.app.get(LIGHTS_KEY)):
            return web.json_response({"isConnected": True})
        try:
            request.app[LIGHTS_KEY] = await lights.connect_to_lights()
        except lights.LightsNotFoundError as error:
            return json_error(str(error), 404)
        return web.json_response({"isConnected": True})


async def disconnect(request: web.Request) -> web.Response:
    """Release the lights so the phone app can use them."""
    connection = request.app.pop(LIGHTS_KEY, None)
    if connection is not None:
        await lights.disconnect_from_lights(connection)
    return web.json_response({"isConnected": False})


async def run_action(request: web.Request) -> web.Response:
    """Build the frame for one action from the JSON body and send it to the lights."""
    action_name = request.match_info["action"]
    if action_name not in ACTIONS:
        return json_error(f"unknown action '{action_name}'", 404)
    connection = request.app.get(LIGHTS_KEY)
    if not lights.is_lights_connected(connection):
        return json_error("lights are not connected", 409)
    try:
        frame = build_action_frame(action_name, await read_json_body(request))
    except (ValueError, TypeError, KeyError) as error:
        return json_error(f"bad request: {error}", 400)
    await lights.send_frame(connection, frame)
    return web.json_response({"sent": frame.hex(" ")})


async def read_json_body(request: web.Request) -> dict[str, object]:
    """Parse the body as a JSON object; requiring the JSON content type forces a CORS preflight."""
    if request.content_type != "application/json":
        raise ValueError("content type must be application/json")
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    return body


def build_action_frame(action_name: str, body: dict[str, object]) -> bytes:
    """Pick the protocol function for the action and call it with the fields from the body."""
    build_frame, field_names = ACTIONS[action_name]
    return build_frame(*[body[field_name] for field_name in field_names])


async def release_lights_on_shutdown(app: web.Application) -> None:
    """Disconnect on exit so the lights are not left held by a dead process."""
    connection = app.get(LIGHTS_KEY)
    if lights.is_lights_connected(connection):
        await lights.disconnect_from_lights(connection)


def create_app() -> web.Application:
    """Assemble the routes: the page, its static files, and the JSON API under /api."""
    app = web.Application(middlewares=[local_requests_only])
    app[CONNECT_LOCK_KEY] = asyncio.Lock()
    app.add_routes(
        [
            web.get("/", show_page),
            web.static("/static", WEB_DIRECTORY),
            web.get("/api/options", show_options),
            web.get("/api/status", show_status),
            web.post("/api/gradient-colors", show_gradient_colors),
            web.get("/api/presets", show_presets),
            web.put("/api/presets/{slot}", store_preset),
            web.post("/api/connect", connect),
            web.post("/api/disconnect", disconnect),
            web.post("/api/{action}", run_action),
        ]
    )
    app.on_cleanup.append(release_lights_on_shutdown)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    web.run_app(create_app(), host=HOST, port=PORT)
