
import streamlit as st
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from google.cloud import storage
from google.oauth2 import service_account
from streamlit_folium import st_folium
import folium
from datetime import datetime
import openai
import re
import os

st.set_page_config(layout="wide")
st.title("🌳 OpenAtlas - Canopy Height Dashboard")

# OpenAI API
openai.api_key = st.secrets["openai"]["api_key"]

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

# Extract dates from any position in the filename using regex
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

# Selectbox to choose file
options = [f"{os.path.basename(k)} ({v})" for k, v in file_dates.items()]
selected_option = st.selectbox("Select a canopy height prediction file:", options)

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

        # Map
        center = [(bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2]
        m = folium.Map(location=center, zoom_start=13, tiles="Esri.WorldImagery")

        norm_arr = arr.copy()
        norm_arr = (norm_arr - np.nanmin(norm_arr)) / (np.nanmax(norm_arr) - np.nanmin(norm_arr))
        norm_arr = np.nan_to_num(norm_arr)

        folium.raster_layers.ImageOverlay(
            image=norm_arr,
            bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
            opacity=0.6,
            colormap=lambda x: (1, 0.4, 0, x),
            name="Canopy Height"
        ).add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, width=1000, height=600)

# LLM Analysis
st.markdown("### 🤖 Biodiversity Analysis by GPT")

prompt = f"""
You are an environmental analyst. Based on the following canopy height data, write a short, insightful summary on the vegetation structure and biodiversity potential.

- Date: {selected_date}
- Mean canopy height: {mean_val:.2f} meters
- Minimum: {min_val:.2f} m, Maximum: {max_val:.2f} m
- Total area above 3 meters: {surface_gt3:.2f} hectares

Explain what this suggests about the forest maturity and biodiversity. Keep it under 100 words.
"""

try:
    with st.spinner("Analyzing with GPT..."):
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a remote sensing expert."},
                {"role": "user", "content": prompt}
            ]
        )
        st.success(response.choices[0].message.content)
except Exception as e:
    st.error(f"OpenAI error: {e}")
