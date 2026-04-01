"""Leaflet raster URL templates — the browser loads tiles directly from OSM / Esri (no server proxy)."""

OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
