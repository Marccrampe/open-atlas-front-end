
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
import openai
import re
import os

st.set_page_config(layout="wide")
st.title("🌳 OpenAtlas - Canopy Height Dashboard")

# OpenAI client (new API >= 1.0.0)
client = openai.OpenAI(api_key=st.secrets["openai"]["api_key"])

# GCS setup
bucket_name = "gchm-predictions-test"
tif_prefix = "Predictions/"

credentials = service_account.Credentials.from_service_account_info(st.secrets["gcp"])
client_gcs = storage.Client(credentials=credentials)
bucket = client_gcs.bucket(bucket_name)

# List TIF files in the bucket
blobs = list(bucket.list_blobs(prefix=tif_prefix))
tif_files = [blob.name for blob in blobs if blob.name.endswith(".tif")]

if not tif_files:
    st.warning("No .tif files found in the bucket.")
    st.stop()

# Extract dates using regex
file_dates = {}
for tif in tif_files:
    base = os.path.basename(tif)
    match = re.search(r'\d{4}-\d{2}-\d{2}', base)
    if match:
        try:
            date = datetime.strptime(match.group(), "%Y-%m-%d").date()
            file_dates[tif] = date
        except Exception as e:
            print(f"Error parsing {base}: {e}")
    else:
        print(f"No valid date found in {base}")

if not file_dates:
    st.error("No valid date found in filenames.")
    st.stop()

# Select file
options = [f"{os.path.basename(k)} ({v})" for k, v in file_dates.items()]
selected_option = st.selectbox("Select a canopy height prediction file:", options)
selected_file = list(file_dates.keys())[options.index(selected_option)]
selected_date = file_dates[selected_file]

st.markdown(f"### 🛰️ File: `{selected_file}`  — Date: `{selected_date}`")

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

        colormap = linear.Viridis_09.scale(min_val, max_val)
        colormap.caption = "Canopy Height (m)"
        colormap.add_to(m)

        img_overlay = folium.raster_layers.ImageOverlay(
            image=norm_arr,
            bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
            opacity=0.6,
            colormap=lambda x: colormap(x * (max_val - min_val) + min_val),
            name="Canopy Height"
        )
        img_overlay.add_to(m)
        folium.LayerControl().add_to(m)

        # Add click marker
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

# LLM Analysis
st.markdown("### 🤖 Biodiversity Analysis by GPT")

prompt = f"""
You are an environmental analyst. Based on the following canopy height data, write a short, insightful summary on the vegetation structure and biodiversity potential.

- Date: {selected_date}
- Mean canopy height: {mean_val:.2f} meters
- Minimum: {min_val:.2f} m, Maximum: {max_val:.2f} m

Explain what this suggests about the forest maturity and biodiversity. Keep it under 100 words.
"""

try:
    with st.spinner("Analyzing with GPT..."):
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a remote sensing expert."},
                {"role": "user", "content": prompt}
            ]
        )
        summary = response.choices[0].message.content
        st.success(summary)
except Exception as e:
    st.error(f"OpenAI error: {e}")
