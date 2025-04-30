import streamlit as st
import numpy as np
import boto3
from io import BytesIO
from streamlit_folium import st_folium
import folium
import matplotlib.pyplot as plt
from branca.colormap import linear
import rasterio
from rasterio.io import MemoryFile
import os
import re

st.set_page_config(layout="wide")
st.title("🌳 OpenAtlas - Canopy Height Viewer")

# Configuration S3
s3_bucket_name = "canopy-marc"
s3_prefix = "Predictions/"

aws_access_key = st.secrets["aws"]["aws_access_key"]
aws_secret_key = st.secrets["aws"]["aws_secret_key"]

# Créer un client S3 avec boto3
s3_client = boto3.client(
    's3', 
    aws_access_key_id=aws_access_key, 
    aws_secret_access_key=aws_secret_key
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
        arr[arr <= 0] = np.nan  # Remplacer les valeurs faibles (e.g. 0) par NaN
        bounds = src.bounds
        transform = src.transform
        height, width = arr.shape

        # Stats en ignorant les NaN
        mean_val = np.nanmean(arr)  # Moyenne sans NaN
        min_val = np.nanmin(arr)    # Min sans NaN
        max_val = np.nanmax(arr)    # Max sans NaN

        col1, col2, col3 = st.columns(3)
        col1.metric("🌿 Mean height", f"{mean_val:.2f} m")
        col2.metric("🔻 Min height", f"{min_val:.2f} m")
        col3.metric("🔺 Max height", f"{max_val:.2f} m")

        # Map pour la hauteur de la canopée
        center = [(bounds.top + bounds.bottom) / 2, (bounds.left + bounds.right) / 2]
        m = folium.Map(location=center, zoom_start=13, tiles="Esri.WorldImagery")  # Utilisation du fond Esri

        # Normalisation (sans NaN)
        norm_arr = (arr - min_val) / (max_val - min_val)
        norm_arr = np.nan_to_num(norm_arr)  # Remplacer les NaN par 0

        # Utilisation de la méthode matplotlib pour les couleurs
        viridis = plt.cm.viridis
        rgba_img = (viridis(norm_arr) * 255).astype(np.uint8)
        rgb_img = rgba_img[:, :, :3]  # Enlever la couche alpha

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

# 2. Section Canopy Change between Dates
st.markdown("### 2. Canopy Cover Change between Dates")
selected_date_1 = st.selectbox("Select First Date", available_dates, key="date_1")
selected_date_2 = st.selectbox("Select Second Date", available_dates, key="date_2")

# Télécharger les fichiers TIFF pour les deux dates
file_1 = aoi_dict[selected_aoi][selected_date_1]
file_2 = aoi_dict[selected_aoi][selected_date_2]

tif_obj_1 = s3_client.get_object(Bucket=s3_bucket_name, Key=file_1)
tif_bytes_1 = tif_obj_1['Body'].read()

tif_obj_2 = s3_client.get_object(Bucket=s3_bucket_name, Key=file_2)
tif_bytes_2 = tif_obj_2['Body'].read()

# Charger les données des deux dates
def load_tif_data(tif_bytes):
    with MemoryFile(tif_bytes) as memfile:
        with memfile.open() as src:
            arr = src.read(1).astype(np.float32)
            arr[arr <= 0] = np.nan  # Remplacer les valeurs faibles (e.g. 0) par NaN
            bounds = src.bounds
            return arr, bounds

arr_1, bounds_1 = load_tif_data(tif_bytes_1)
arr_2, bounds_2 = load_tif_data(tif_bytes_2)

# Calculer le changement de la canopée (sans normalisation)
canopy_change = arr_2 - arr_1

# Appliquer un facteur pour rendre le changement plus visible
canopy_change = canopy_change * 10  # Multiplier par 10 pour amplifier les différences

# Vérification des données avant affichage
st.write("Canopy Change (raw):")
st.write(canopy_change)

# Map for canopy change
st.markdown("### Map of Canopy Change")
m_change = folium.Map(
    location=[(bounds_1[1] + bounds_1[3]) / 2, (bounds_1[0] + bounds_1[2]) / 2],
    zoom_start=13,
    tiles="Esri.WorldImagery",  # Utilisation du fond Esri
    attr="Esri"  # Attribution pour Esri World Imagery
)

# Création d'un colormap rouge-vert pour le changement de canopée
colormap_change = linear.RdYlGn_09.scale(np.nanmin(canopy_change), np.nanmax(canopy_change))
colormap_change.caption = "Canopy Change (m)"
colormap_change.add_to(m_change)

# Afficher l'image du changement de la canopée
folium.raster_layers.ImageOverlay(
    image=canopy_change,
    bounds=[[bounds_1[1], bounds_1[0]], [bounds_1[3], bounds_1[2]]],
    opacity=0.6,
    name="Canopy Change"
).add_to(m_change)

st_folium(m_change, width=1000, height=600)
