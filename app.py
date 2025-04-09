
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
    st.warning("Aucun fichier .tif trouvé dans le bucket.")
    st.stop()

# Nouveau format: zone_YYYY-MM-DD_predictions.tif
file_dates = {}
for tif in tif_files:
    base = os.path.basename(tif)
    try:
        date_str = base.split("_")[1]  # Extrait '2019-03-01'
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        file_dates[tif] = date
    except Exception as e:
        print(f"Erreur lecture date pour {base} : {e}")
        continue

if not file_dates:
    st.error("Aucune date valide n’a été détectée dans les fichiers .tif.")
    st.stop()

# Tri par date
sorted_files = sorted(file_dates.items(), key=lambda x: x[1])
dates = [item[1] for item in sorted_files]
files_sorted = [item[0] for item in sorted_files]

# Time slider
selected_idx = st.slider("📅 Sélectionnez une date", 0, len(dates) - 1, len(dates) - 1,
                         format="DD/MM/YYYY")
selected_file = files_sorted[selected_idx]
selected_date = dates[selected_idx]
st.markdown(f"### 🛰️ Fichier sélectionné : `{selected_file}` ({selected_date})")

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
        surface_gt3 = np.sum(arr > 3) * abs(transform[0] * transform[4]) / 10000  # en hectares

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🌿 Moyenne (m)", f"{mean_val:.2f}")
        col2.metric("🔻 Min (m)", f"{min_val:.2f}")
        col3.metric("🔺 Max (m)", f"{max_val:.2f}")
        col4.metric("🟩 Surface > 3m", f"{surface_gt3:.2f} ha")

        # Carte
        center = [(bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2]
        m = folium.Map(location=center, zoom_start=12)
        folium.raster_layers.ImageOverlay(
            image=arr,
            bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
            opacity=0.6,
            colormap=lambda x: (1, 0, 0, x) if x else (0, 0, 0, 0)
        ).add_to(m)
        folium.LayerControl().add_to(m)
        folium_static(m, width=1000, height=600)

# Chatbox (placeholder)
st.markdown("### 🤖 Résumé par IA (simulation)")
prompt = st.text_area("Pose une question sur la zone visualisée (biodiversité, EUDR...)")
if st.button("Analyser"):
    st.success("🔍 Résumé automatique : Cette zone présente une canopée développée avec une couverture > 3m significative. Cela peut indiquer une maturité écologique favorable à la biodiversité.")
