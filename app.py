import streamlit as st
import numpy as np
import boto3
from io import BytesIO
from streamlit_folium import st_folium
import folium
from branca.colormap import linear
import rasterio
from rasterio.io import MemoryFile
from matplotlib import cm
import os
import re

st.set_page_config(layout="wide")
st.title("🌳 OpenAtlas - Canopy Height Viewer")

# Configuration S3
s3_bucket_name = "your-s3-bucket-name"
s3_prefix = "Predictions/"

# Créez un client S3 avec des clés d'authentification AWS
s3_client = boto3.client(
    's3', 
    aws_access_key_id=st.secrets["aws_access_key"],  # Ajoutez vos secrets dans .streamlit/secrets.toml
    aws_secret_access_key=st.secrets["aws_secret_key"]
)

# Liste des fichiers .tif dans le bucket S3
def list_tif_files_from_s3(bucket_name, prefix):
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    tif_files = [obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith("_predictions.tif")]
    return tif_files

# Extraire AOI et dates des fichiers TIF
def extract_aoi_and_dates(tif_files):
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
    return aoi_dict

# Liste des fichiers TIF dans S3
tif_files = list_tif_files_from_s3(s3_bucket_name, s3_prefix)

# Extraire AOI et dates
aoi_dict = extract_aoi_and_dates(tif_files)

if not aoi_dict:
    st.error("No valid prediction TIFs found.")
    st.stop()

# Sélection de l'AOI
selected_aoi = st.selectbox("Select Area of Interest (AOI)", sorted(aoi_dict.keys()))

# Sélection de la date
available_dates = sorted(aoi_dict[selected_aoi].keys())
selected_date = st.selectbox("Select date", available_dates)

# Récupérer le chemin du fichier sélectionné
selected_file = aoi_dict[selected_aoi][selected_date]
st.markdown(f"### 🛰️ File: `{selected_file}`")

# Télécharger le fichier TIFF depuis S3
tif_obj = s3_client.get_object(Bucket=s3_bucket_name, Key=selected_file)
tif_bytes = tif_obj['Body'].read()

# Charger le TIFF
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
