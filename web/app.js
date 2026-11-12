// @ts-check
// Behavior of the control page (index.html): wires each control to the local bridge's JSON API.
// The bridge (bridge/server.py) turns these requests into Bluetooth frames; no byte formats here.

// Fast enough to feel live, slow enough not to flood Bluetooth.
const SLIDER_SEND_INTERVAL_MILLISECONDS = 100;

/** @typedef {{ row: number, column: number }} PanelPosition */
/** @typedef {{ panelColors: string[], brightness: number }} Preset - As bridge/presets.py stores it. */

// Where each panel hangs in the triangle, panel 1 first, following the cable counterclockwise.
// Row 0 is the tip and row 4 the bottom; a row has one more slot than the one above it, and the
// column counts slots from that row's left end.
const PANEL_POSITIONS = [
  { row: 1, column: 0 }, // Panel 1, where the cable enters.
  { row: 2, column: 0 },
  { row: 3, column: 0 },
  { row: 4, column: 0 }, // Bottom left corner.
  { row: 4, column: 1 },
  { row: 4, column: 2 },
  { row: 4, column: 3 },
  { row: 4, column: 4 }, // Bottom right corner.
  { row: 3, column: 3 },
  { row: 2, column: 2 },
  { row: 1, column: 1 },
  { row: 0, column: 0 }, // Panel 12, the tip.
];
const BOTTOM_ROW_PANELS = 5;
// Panel size as a share of the map (see #panel-map in style.css): each row starts three quarters
// of a panel below the one above, because pointed-top hexagons nest into each other.
const PANEL_WIDTH_PERCENT = 100 / BOTTOM_ROW_PANELS;
const ROW_STEP_PERCENT = 18.75;
const PANEL_OFF_COLOR = "#000000";

// Each panel's color as "#rrggbb", panel 1 first. The page cannot read the lights' colors, so
// every panel starts off, and the first pick sends the rest as off too.
const panelColors = PANEL_POSITIONS.map(() => PANEL_OFF_COLOR);

/**
 * Fetch a bridge endpoint and return its JSON body.
 * @param {string} path - e.g. "/api/status".
 * @param {"GET" | "POST" | "PUT"} [method] - Defaults to GET.
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
 * Fill the panel map with a gradient between the two picked colors, then send it.
 *
 * The bridge works out the colors so the blending lives in one tested place (protocol.py).
 * @returns {Promise<void>}
 */
async function applyGradient() {
  try {
    const { colors } = await callBridge("/api/gradient-colors", "POST", {
      startColor: slider("gradient-start").value,
      endColor: slider("gradient-end").value,
    });
    setPanelColors(colors);
    sendPanelColors();
  } catch (error) {
    showFailure(error);
  }
}

/**
 * Draw one button per panel, placed as the panels hang on the wall.
 * @returns {void}
 */
function createPanelMap() {
  const map = element("panel-map");
  PANEL_POSITIONS.forEach((position, index) => {
    map.appendChild(createPanelButton(index, position));
  });
  showPanelColors();
}

/**
 * Make the hexagon button for one panel; pressing it selects or deselects the panel.
 * @param {number} index - The panel's place in panelColors (panel number minus one).
 * @param {PanelPosition} position
 * @returns {HTMLButtonElement}
 */
function createPanelButton(index, position) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "panel";
  button.setAttribute("aria-label", `Panel ${index + 1}`);
  button.setAttribute("aria-pressed", "false");
  placePanel(button, position);
  const swatch = document.createElement("span");
  swatch.className = "panel-swatch";
  swatch.textContent = String(index + 1);
  button.appendChild(swatch);
  button.addEventListener("click", () => togglePanel(button, index));
  return button;
}

/**
 * Put a panel's shape where the panel hangs, within a map sized like #panel-map.
 * @param {HTMLElement} panel
 * @param {PanelPosition} position
 * @returns {void}
 */
function placePanel(panel, { row, column }) {
  panel.style.left = `${panelLeftPercent(row, column)}%`;
  panel.style.top = `${row * ROW_STEP_PERCENT}%`;
}

/**
 * Where a panel's left edge sits, as a percent of the map's width. Rows are centered over the
 * bottom row, so each row up starts half a panel further right.
 * @param {number} row
 * @param {number} column
 * @returns {number}
 */
function panelLeftPercent(row, column) {
  const emptySlotsBesideRow = BOTTOM_ROW_PANELS - (row + 1);
  const rowStartInPanels = emptySlotsBesideRow / 2;
  return (rowStartInPanels + column) * PANEL_WIDTH_PERCENT;
}

/**
 * Select or deselect a panel. Selecting one also loads its color into the picker, so it can be
 * adjusted from where it is.
 * @param {HTMLButtonElement} button
 * @param {number} index
 * @returns {void}
 */
function togglePanel(button, index) {
  const isSelected = !isPressed(button);
  button.setAttribute("aria-pressed", String(isSelected));
  if (isSelected) slider("panel-color").value = panelColors[index];
}

/**
 * Select every panel (true) or none (false).
 * @param {boolean} isSelected
 * @returns {void}
 */
function selectAllPanels(isSelected) {
  for (const button of panelButtons()) button.setAttribute("aria-pressed", String(isSelected));
}

/**
 * The panel buttons, panel 1 first.
 * @returns {HTMLButtonElement[]}
 */
function panelButtons() {
  return [...element("panel-map").querySelectorAll("button")];
}

/**
 * Give every selected panel the picker's color, on the page only (sendPanelColors sends it).
 * @returns {void}
 */
function paintSelectedPanels() {
  const color = slider("panel-color").value;
  const selectedIndexes = selectedPanelIndexes();
  if (selectedIndexes.length === 0) showStatus("Select a panel first, then pick its color", true);
  for (const index of selectedIndexes) panelColors[index] = color;
  showPanelColors();
}

/**
 * The selected panels' places in panelColors, in panel order.
 * @returns {number[]}
 */
function selectedPanelIndexes() {
  const indexes = [];
  for (const [index, button] of panelButtons().entries()) {
    if (isPressed(button)) indexes.push(index);
  }
  return indexes;
}

/**
 * Whether a toggle button is pressed (for a panel: selected).
 * @param {HTMLButtonElement} button
 * @returns {boolean}
 */
function isPressed(button) {
  return button.getAttribute("aria-pressed") === "true";
}

/**
 * Replace every panel's color and show the new ones. The array is changed in place because the
 * rest of the page holds on to it.
 * @param {string[]} colors - "#rrggbb", panel 1 first, one per panel.
 * @returns {void}
 */
function setPanelColors(colors) {
  panelColors.splice(0, panelColors.length, ...colors);
  showPanelColors();
}

/**
 * Fill each panel's hexagon with its color.
 * @returns {void}
 */
function showPanelColors() {
  for (const [index, button] of panelButtons().entries()) {
    const swatch = /** @type {HTMLElement} */ (button.firstElementChild);
    swatch.style.background = panelColors[index];
  }
}

/**
 * Send every panel's color to the lights.
 * @returns {void}
 */
function sendPanelColors() {
  sendAction("panels", { colors: panelColors });
}

/**
 * Fetch the saved presets and show them.
 * @returns {Promise<void>}
 */
async function loadPresets() {
  const { slots } = await callBridge("/api/presets");
  showPresets(slots);
}

/**
 * Draw one slot per preset, replacing what was there.
 * @param {(Preset | null)[]} slots - Slot 1 first; null marks an empty slot.
 * @returns {void}
 */
function showPresets(slots) {
  const slotItems = slots.map((preset, index) => createPresetSlot(index + 1, preset));
  element("preset-slots").replaceChildren(...slotItems);
}

/**
 * Make one slot: the preset's apply button above its Save button.
 * @param {number} slotNumber - 1 to 6, as shown.
 * @param {Preset | null} preset
 * @returns {HTMLLIElement}
 */
function createPresetSlot(slotNumber, preset) {
  const item = document.createElement("li");
  item.append(
    createPresetApplyButton(slotNumber, preset),
    createPresetSaveButton(slotNumber, preset),
  );
  return item;
}

/**
 * Make the button that shows a preset and applies it; it is disabled while the slot is empty.
 * @param {number} slotNumber
 * @param {Preset | null} preset
 * @returns {HTMLButtonElement}
 */
function createPresetApplyButton(slotNumber, preset) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "preset-apply";
  button.append(createPresetPreview(preset), `Preset ${slotNumber}`);
  button.disabled = preset === null;
  if (preset) button.addEventListener("click", () => applyPreset(preset));
  return button;
}

/**
 * Make the button that saves the current look to a slot.
 * @param {number} slotNumber
 * @param {Preset | null} preset - What the slot holds now, so replacing it can be confirmed.
 * @returns {HTMLButtonElement}
 */
function createPresetSaveButton(slotNumber, preset) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Save";
  button.setAttribute("aria-label", `Save to preset ${slotNumber}`);
  button.addEventListener("click", () => savePreset(slotNumber, preset));
  return button;
}

/**
 * Draw a small copy of the panel map in a preset's colors; an empty slot shows only the outline.
 * @param {Preset | null} preset
 * @returns {HTMLSpanElement}
 */
function createPresetPreview(preset) {
  const preview = document.createElement("span");
  preview.className = "preset-preview";
  preview.setAttribute("aria-hidden", "true");
  PANEL_POSITIONS.forEach((position, index) => {
    const panel = document.createElement("span");
    panel.className = "preset-panel";
    placePanel(panel, position);
    if (preset) panel.style.background = preset.panelColors[index];
    preview.appendChild(panel);
  });
  return preview;
}

/**
 * Show a preset's colors and brightness on the page, then send both to the lights.
 *
 * Brightness goes second because it applies on top of whatever the panels show.
 * @param {Preset} preset
 * @returns {Promise<void>}
 */
async function applyPreset(preset) {
  setPanelColors(preset.panelColors);
  slider("brightness-slider").value = String(preset.brightness);
  await sendAction("panels", { colors: panelColors });
  await sendAction("brightness", { percent: preset.brightness });
}

/**
 * Save the panel colors and brightness to a slot, asking first if that replaces a preset.
 * @param {number} slotNumber
 * @param {Preset | null} existingPreset - What the slot holds now.
 * @returns {Promise<void>}
 */
async function savePreset(slotNumber, existingPreset) {
  if (existingPreset && !confirm(`Replace preset ${slotNumber}?`)) return;
  try {
    const { slots } = await callBridge(`/api/presets/${slotNumber}`, "PUT", {
      panelColors,
      brightness: Number(slider("brightness-slider").value),
    });
    showPresets(slots);
    showStatus(`Saved preset ${slotNumber}`);
  } catch (error) {
    showFailure(error);
  }
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
  element("gradient-button").addEventListener("click", applyGradient);
  connectPanelControls();
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
 * Make the panel color picker and the select buttons do their jobs.
 * @returns {void}
 */
function connectPanelControls() {
  const sendPanelColorsWhilePicking = throttled(sendPanelColors);
  slider("panel-color").addEventListener("input", () => {
    paintSelectedPanels();
    sendPanelColorsWhilePicking();
  });
  element("select-all-panels-button").addEventListener("click", () => selectAllPanels(true));
  element("select-no-panels-button").addEventListener("click", () => selectAllPanels(false));
}

/**
 * Wire every control, load the scene and music names, and connect to the lights if needed.
 * @returns {Promise<void>}
 */
async function start() {
  connectControls();
  createPanelMap();
  const options = await callBridge("/api/options");
  fillButtons("scene-buttons", options.scenes, "scene");
  fillButtons("music-buttons", options.musicModes, "music-mode");
  await loadPresets();
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
