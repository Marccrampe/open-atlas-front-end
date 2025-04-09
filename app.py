
import streamlit as st
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from google.cloud import storage
from google.oauth2 import service_account
from streamlit_folium import st_folium
import folium
from branca.colormap import linear
from datetime import datetime
import re
import os
from matplotlib import cm

st.set_page_config(layout="wide")
st.title("🌳 OpenAtlas - Canopy Height Viewer")

# GCS setup
bucket_name = "gchm-predictions-test"
tif_prefix = "Predictions/"

credentials = service_account.Credentials.from_service_account_info(st.secrets["gcp"])
client_gcs = storage.Client(credentials=credentials)
bucket = client_gcs.bucket(bucket_name)

# List all prediction TIFs
blobs = list(bucket.list_blobs(prefix=tif_prefix))
tif_files = [blob.name for blob in blobs if blob.name.endswith("_predictions.tif")]

# Extract AOI and dates
aoi_dict = {}  # {AOI: {date: filepath}}
for tif in tif_files:
    base = os.path.basename(tif)
    match = re.match(r"(.*)_([0-9]{4}-[0-9]{2}-[0-9]{2})_predictions\.tif", base)
    if match:
        aoi = match.group(1)
        date_str = match.group(2)
        if aoi not in aoi_dict:
            aoi_dict[aoi] = {}
        aoi_dict[aoi][date_str] = tif

if not aoi_dict:
    st.error("No valid prediction TIFs found.")
    st.stop()

# AOI selection
selected_aoi = st.selectbox("Select Area of Interest (AOI)", sorted(aoi_dict.keys()))

# Date selection
available_dates = sorted(aoi_dict[selected_aoi].keys())
selected_date = st.selectbox("Select date", available_dates)

# Get file path
selected_file = aoi_dict[selected_aoi][selected_date]
st.markdown(f"### 🛰️ File: `{selected_file}`")

# Load TIF
blob = bucket.blob(selected_file)
tif_bytes = blob.download_as_bytes()

with MemoryFile(tif_bytes) as memfile:
    with memfile.open() as src:
        arr = src.read(1).astype(np.float32)
        arr[arr <= 0] = np.nan
        bounds = src.bounds
        transform = src.transform
        height, width = arr.shape

        # Stats
        mean_val = np.nanmean(arr)
        min_val = np.nanmin(arr)
        max_val = np.nanmax(arr)

        col1, col2, col3 = st.columns(3)
        col1.metric("🌿 Mean height", f"{mean_val:.2f} m")
        col2.metric("🔻 Min height", f"{min_val:.2f} m")
        col3.metric("🔺 Max height", f"{max_val:.2f} m")

        # Map
        center = [(bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2]
        m = folium.Map(location=center, zoom_start=13, tiles="Esri.WorldImagery")

        norm_arr = (arr - min_val) / (max_val - min_val)
        norm_arr = np.nan_to_num(norm_arr)

        viridis = cm.get_cmap("viridis")
        rgba_img = (viridis(norm_arr) * 255).astype(np.uint8)
        rgb_img = rgba_img[:, :, :3]

        colormap = linear.viridis.scale(min_val, max_val)
        colormap.caption = "Canopy Height (m)"
        colormap.add_to(m)

        folium.raster_layers.ImageOverlay(
            image=rgb_img,
            bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
            opacity=0.6,
            name="Canopy Height"
        ).add_to(m)

        folium.LayerControl().add_to(m)
        m.add_child(folium.LatLngPopup())

        result = st_folium(m, width=1000, height=600)

        # Get clicked lat/lon and show height
        if result.get("last_clicked"):
            lat = result["last_clicked"]["lat"]
            lon = result["last_clicked"]["lng"]
            with memfile.open() as src:
                row, col = src.index(lon, lat)
                try:
                    height_val = arr[row, col]
                    st.success(f"🌲 Canopy height at ({lat:.5f}, {lon:.5f}) is **{height_val:.2f} m**")
                except:
                    st.error("Invalid pixel location.")
