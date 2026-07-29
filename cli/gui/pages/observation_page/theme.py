from __future__ import annotations

# "Signal Room" -- this page's own scoped surface, independent of
# app.py's page.theme_mode (that's global; Contract/Infra/Scenario stay
# plain Material) -- every color here is applied directly to this page's
# own ft.Container/Text controls. Light instrument-panel: a cool
# off-white ground, white panels, teal/amber/coral accents pulled dark
# enough to hold contrast -- same oscilloscope-readout identity as before,
# just lit instead of dark.
VOID = "#EEF3F4"
PANEL = "#FFFFFF"
HAIRLINE = "#D7E0E4"
SIGNAL = "#0F9B8E"
ALERT = "#B8720F"
CRITICAL = "#C1443A"
INK = "#141A1F"
INK_MUTED = "#5B6B76"

# Chakra Petch: a technical, HUD-adjacent display face for headers/labels
# -- registered globally in app.py's page.fonts but only ever referenced
# by this page's Text controls, so the other three pages are unaffected.
DISPLAY_FONT = "Chakra Petch"
# IBM Plex Mono replaces the generic "monospace" alias for every piece of
# live data on this page (addresses, ports, timestamps, secrets).
DATA_FONT = "IBM Plex Mono"

STATUS_COLORS = {
    "signal": SIGNAL,
    "alert": ALERT,
    "critical": CRITICAL,
}
