// @ts-check
// Behavior of the control page (index.html): wires each control to the local bridge's JSON API.
// The bridge (bridge/server.py) turns these requests into Bluetooth frames; no byte formats here.

// Fast enough to feel live, slow enough not to flood Bluetooth.
const SLIDER_SEND_INTERVAL_MILLISECONDS = 100;

/**
 * Fetch a bridge endpoint and return its JSON body.
 * @param {string} path - e.g. "/api/status".
 * @param {"GET" | "POST"} [method] - Defaults to GET.
 * @param {Record<string, unknown>} [body] - Sent as JSON; the bridge insists on the JSON content type.
 * @returns {Promise<any>} The parsed response.
 * @throws {Error} With the bridge's own error message when the response is not OK.
 */
async function callBridge(path, method = "GET", body = undefined) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const parsed = await response.json();
  if (!response.ok) throw new Error(parsed.error ?? `request failed (${response.status})`);
  return parsed;
}

/**
 * Look up an element that index.html is known to contain.
 * @param {string} id
 * @returns {HTMLElement}
 * @throws {Error} When index.html has no such element, which is a bug in one of the two files.
 */
function element(id) {
  const found = document.getElementById(id);
  if (!found) throw new Error(`index.html is missing #${id}`);
  return found;
}

/**
 * Look up a range slider that index.html is known to contain.
 * @param {string} id
 * @returns {HTMLInputElement}
 */
function slider(id) {
  return /** @type {HTMLInputElement} */ (element(id));
}

/**
 * Show a message in the status line.
 * @param {string} message
 * @param {boolean} [isError] - Colors the message as an error.
 * @returns {void}
 */
function showStatus(message, isError = false) {
  element("status").textContent = message;
  element("status").classList.toggle("is-error", isError);
}

/**
 * Show a failed request in the status line.
 * @param {unknown} error - Whatever was thrown; only Error messages are shown as written.
 * @returns {void}
 */
function showFailure(error) {
  showStatus(error instanceof Error ? error.message : String(error), true);
}

/**
 * Send one action to the lights, showing any failure in the status line.
 * @param {string} action - Bridge action name, e.g. "color".
 * @param {Record<string, unknown>} fields - Parameters for the action.
 * @returns {Promise<void>}
 */
async function sendAction(action, fields) {
  try {
    await callBridge(`/api/${action}`, "POST", fields);
  } catch (error) {
    showFailure(error);
  }
}

/**
 * Wrap a function so a burst of calls runs it once per interval.
 *
 * The wrapped function must read its inputs when it runs (a slider's value, not a value passed in),
 * so the one run that follows a burst always sees where the slider ended up.
 * @param {() => void} send
 * @returns {() => void}
 */
function throttled(send) {
  let isRunScheduled = false;
  return () => {
    if (isRunScheduled) return;
    isRunScheduled = true;
    setTimeout(() => {
      isRunScheduled = false;
      send();
    }, SLIDER_SEND_INTERVAL_MILLISECONDS);
  };
}

/**
 * Enable or disable every control to match the connection.
 * @param {boolean} isConnected
 * @returns {void}
 */
function showConnection(isConnected) {
  /** @type {HTMLFieldSetElement} */ (element("controls")).disabled = !isConnected;
  element("connect-button").textContent = isConnected ? "Disconnect" : "Connect";
  showStatus(isConnected ? "Connected" : "Not connected");
}

/**
 * Connect if disconnected and disconnect if connected, as the bridge currently sees it.
 * @returns {Promise<void>}
 */
async function toggleConnection() {
  try {
    const { isConnected } = await callBridge("/api/status");
    if (isConnected) await disconnectFromLights();
    else await connectToLights();
  } catch (error) {
    showFailure(error);
  }
}

/**
 * Ask the bridge to find and connect to the lights, then enable the controls.
 *
 * The scan takes up to 10 seconds. It fails when something else, such as a phone app, already
 * holds the lights, because they accept one connection at a time.
 * @returns {Promise<void>}
 * @throws {Error} With the bridge's message when the lights cannot be found.
 */
async function connectToLights() {
  showStatus("Looking for the lights...");
  const status = await callBridge("/api/connect", "POST");
  showConnection(status.isConnected);
}

/**
 * Ask the bridge to release the lights, then disable the controls.
 * @returns {Promise<void>}
 */
async function disconnectFromLights() {
  const status = await callBridge("/api/disconnect", "POST");
  showConnection(status.isConnected);
}

/**
 * Update the swatch to show the color the sliders describe: the pure hue, mixed toward white as
 * saturation falls (the lights show white at zero saturation).
 * @returns {void}
 */
function updateColorPreview() {
  const saturationSlider = slider("saturation-slider");
  const whiteAmount = 1 - Number(saturationSlider.value) / Number(saturationSlider.max);
  const whiteOverlay = `rgb(255 255 255 / ${whiteAmount})`;
  const pureHue = `hsl(${slider("hue-slider").value} 100% 50%)`;
  element("color-preview").style.background =
    `linear-gradient(${whiteOverlay}, ${whiteOverlay}), ${pureHue}`;
}

/**
 * Send the hue and saturation sliders' current values as one color.
 * @returns {void}
 */
function sendColor() {
  updateColorPreview();
  sendAction("color", {
    hue: Number(slider("hue-slider").value),
    saturation: Number(slider("saturation-slider").value),
  });
}

/**
 * Update the preview bar to show the fade between the two picked colors.
 * @returns {void}
 */
function updateGradientPreview() {
  const startColor = slider("gradient-start").value;
  const endColor = slider("gradient-end").value;
  element("gradient-preview").style.background =
    `linear-gradient(to right, ${startColor}, ${endColor})`;
}

/**
 * Send the two picked colors as a gradient along the panels.
 * @returns {void}
 */
function sendGradient() {
  sendAction("gradient", {
    startColor: slider("gradient-start").value,
    endColor: slider("gradient-end").value,
  });
}

/**
 * Show white: zero saturation, with the saturation slider moved to match.
 * @returns {void}
 */
function sendWhite() {
  slider("saturation-slider").value = "0";
  sendColor();
}

/**
 * Send a slider's value as a percent whenever it moves.
 * @param {string} sliderId
 * @param {string} action - The bridge action that takes a "percent" field.
 * @returns {void}
 */
function connectSlider(sliderId, action) {
  const sendValue = throttled(() =>
    sendAction(action, { percent: Number(slider(sliderId).value) }),
  );
  slider(sliderId).addEventListener("input", sendValue);
}

/**
 * Make one button per name; pressing one sends the action and marks it as the active choice.
 * @param {string} containerId - Element that receives the buttons.
 * @param {string[]} names - Labels, also sent as the "name" field.
 * @param {string} action
 * @returns {void}
 */
function fillButtons(containerId, names, action) {
  const container = element(containerId);
  for (const name of names) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = name;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      for (const other of container.children) other.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-pressed", "true");
      sendAction(action, { name });
    });
    container.appendChild(button);
  }
}

/**
 * Make every fixed control in index.html do its job (the scene and music buttons are made later,
 * once the bridge has said what they are).
 * @returns {void}
 */
function connectControls() {
  element("connect-button").addEventListener("click", toggleConnection);
  element("power-on-button").addEventListener("click", () => sendAction("power", { isOn: true }));
  element("power-off-button").addEventListener("click", () => sendAction("power", { isOn: false }));
  element("white-button").addEventListener("click", sendWhite);
  element("gradient-button").addEventListener("click", sendGradient);
  slider("gradient-start").addEventListener("input", updateGradientPreview);
  slider("gradient-end").addEventListener("input", updateGradientPreview);
  const sendColorWhileDragging = throttled(sendColor);
  slider("hue-slider").addEventListener("input", sendColorWhileDragging);
  slider("saturation-slider").addEventListener("input", sendColorWhileDragging);
  connectSlider("brightness-slider", "brightness");
  connectSlider("scene-speed-slider", "scene-speed");
  connectSlider("music-sensitivity-slider", "music-sensitivity");
}

/**
 * Wire every control, load the scene and music names, and connect to the lights if needed.
 * @returns {Promise<void>}
 */
async function start() {
  connectControls();
  const options = await callBridge("/api/options");
  fillButtons("scene-buttons", options.scenes, "scene");
  fillButtons("music-buttons", options.musicModes, "music-mode");
  updateColorPreview();
  updateGradientPreview();
  const { isConnected } = await callBridge("/api/status");
  showConnection(isConnected);
  // Opening the page means wanting the lights, so connect without a click. A failure is shown in the
  // status line and the Connect button retries; it is not a bridge failure, so it must not reach
  // the "cannot reach the bridge" handler below.
  if (!isConnected) await connectToLights().catch(showFailure);
}

start().catch((error) => showStatus(`Cannot reach the bridge: ${error.message}`, true));
