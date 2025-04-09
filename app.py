
import streamlit as st
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from google.cloud import storage
from google.oauth2 import service_account
from streamlit_folium import folium_static
import folium
from datetime import datetime
import io
import os

st.set_page_config(layout="wide")
st.title("🌳 OpenAtlas - Canopy Height Dashboard")

# GCS setup
bucket_name = "gchm-predictions-test"
tif_prefix = "Predictions/"

credentials = service_account.Credentials.from_service_account_info(st.secrets["gcp"])
client = storage.Client(credentials=credentials)
bucket = client.bucket(bucket_name)

# List TIF files in the bucket
blobs = list(bucket.list_blobs(prefix=tif_prefix))
tif_files = [blob.name for blob in blobs if blob.name.endswith(".tif")]

if not tif_files:
    st.warning("No .tif files found in the bucket.")
    st.stop()

# Extract date from format: zone_YYYY-MM-DD_predictions.tif
file_dates = {}
for tif in tif_files:
    base = os.path.basename(tif)
    try:
        date_str = base.split("_")[1]  # e.g., 2019-03-01
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        file_dates[tif] = date
    except:
        continue

if not file_dates:
    st.error("No valid date found in TIF filenames.")
    st.stop()

# Let user select a file manually
options = [f"{os.path.basename(k)} ({v})" for k, v in file_dates.items()]
selected_option = st.selectbox("Select a canopy height prediction file:", options)

# Extract back the filename
selected_file = list(file_dates.keys())[options.index(selected_option)]
selected_date = file_dates[selected_file]

st.markdown(f"### 🛰️ File: `{selected_file}`  — Date: `{selected_date}`")

# Load selected TIF
blob = bucket.blob(selected_file)
tif_bytes = blob.download_as_bytes()

with MemoryFile(tif_bytes) as memfile:
    with memfile.open() as src:
        arr = src.read(1).astype(np.float32)
        arr[arr <= 0] = np.nan
        bounds = src.bounds
        transform = src.transform

        # Stats
        mean_val = np.nanmean(arr)
        min_val = np.nanmin(arr)
        max_val = np.nanmax(arr)
        surface_gt3 = np.sum(arr > 3) * abs(transform[0] * transform[4]) / 10000  # hectares

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🌿 Mean height", f"{mean_val:.2f} m")
        col2.metric("🔻 Min height", f"{min_val:.2f} m")
        col3.metric("🔺 Max height", f"{max_val:.2f} m")
        col4.metric("🟩 Area > 3m", f"{surface_gt3:.2f} ha")

        # Map display
        center = [(bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2]
        m = folium.Map(location=center, zoom_start=13, tiles="Esri.WorldImagery")

        # Normalize image for overlay
        norm_arr = arr.copy()
        norm_arr = (norm_arr - np.nanmin(norm_arr)) / (np.nanmax(norm_arr) - np.nanmin(norm_arr))
        norm_arr = np.nan_to_num(norm_arr)

        folium.raster_layers.ImageOverlay(
            image=norm_arr,
            bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
            opacity=0.6,
            colormap=lambda x: (1, 0.4, 0, x),  # orange gradient
            name="Canopy Height"
        ).add_to(m)

        folium.LayerControl().add_to(m)
        folium_static(m, width=1000, height=600)

# Auto-generated report
st.markdown("### 🤖 Automated Biodiversity Report")

st.info(f"""
**Canopy Summary for {selected_date}:**

- The average canopy height in the selected area is **{mean_val:.2f} meters**, with values ranging from **{min_val:.2f} m** to **{max_val:.2f} m**.
- A total area of **{surface_gt3:.2f} hectares** is covered by trees taller than 3 meters.
- This structure indicates a likely presence of mature vegetation, potentially supporting a rich biodiversity.
- Such canopy characteristics may also align with sustainability and EUDR compliance indicators.
""")
