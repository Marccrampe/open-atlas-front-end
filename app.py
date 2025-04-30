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

# Sélection de la date pour la visualisation de la hauteur de la canopée
available_dates = sorted(aoi_dict[selected_aoi].keys())
selected_date = st.selectbox("Select date for Canopy Height", available_dates)

# Récupérer le fichier TIF pour la date sélectionnée
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

# --- Ajout du deuxième frame pour le changement de la canopée entre deux dates ---

# Sélection des dates de départ et de fin pour le changement de la canopée
start_date_change = st.selectbox("Select Start Date for Canopy Change", available_dates)
end_date_change = st.selectbox("Select End Date for Canopy Change", available_dates)

# Vérifier que la date de fin est postérieure à la date de départ
if available_dates.index(end_date_change) <= available_dates.index(start_date_change):
    st.error("End date must be later than start date.")
    st.stop()

# Calculer une seule fois
if "change_computed" not in st.session_state:
    st.session_state.change_computed = False

# Créer un bouton pour calculer la différence de hauteur de la canopée
if st.button("Compute Canopy Change") and not st.session_state.change_computed:
    st.session_state.change_computed = True  # Marquer que le calcul a été effectué

    # Récupérer les fichiers TIFF pour les deux dates sélectionnées
    start_file_change = aoi_dict[selected_aoi][start_date_change]
    end_file_change = aoi_dict[selected_aoi][end_date_change]

    # Télécharger les fichiers TIFF depuis S3
    start_tif_obj_change = s3_client.get_object(Bucket=s3_bucket_name, Key=start_file_change)
    start_tif_bytes_change = start_tif_obj_change['Body'].read()

    end_tif_obj_change = s3_client.get_object(Bucket=s3_bucket_name, Key=end_file_change)
    end_tif_bytes_change = end_tif_obj_change['Body'].read()

    # Charger les fichiers TIFF
    with MemoryFile(start_tif_bytes_change) as start_memfile_change:
        with start_memfile_change.open() as start_src_change:
            start_arr_change = start_src_change.read(1).astype(np.float32)
            start_arr_change[start_arr_change <= 0] = np.nan  # Remplacer les valeurs faibles par NaN

    with MemoryFile(end_tif_bytes_change) as end_memfile_change:
        with end_memfile_change.open() as end_src_change:
            end_arr_change = end_src_change.read(1).astype(np.float32)
            end_arr_change[end_arr_change <= 0] = np.nan  # Remplacer les valeurs faibles par NaN

    # Calcul de la différence entre les deux dates
    canopy_change = end_arr_change - start_arr_change

    # Calcul des stats pour la différence
    mean_change = np.nanmean(canopy_change)
    min_change = np.nanmin(canopy_change)
    max_change = np.nanmax(canopy_change)

    # Affichage des résultats
    st.markdown(f"### 🌿 Canopy Change between {start_date_change} and {end_date_change}")
    col1, col2, col3 = st.columns(3)
    col1.metric("🌿 Mean Change", f"{mean_change:.2f} m")
    col2.metric("🔻 Min Change", f"{min_change:.2f} m")
    col3.metric("🔺 Max Change", f"{max_change:.2f} m")

    # --- Vérification des min_change et max_change ---
    if np.isnan(min_change) or np.isnan(max_change):
        st.error("Error: Invalid values for canopy change (NaN detected).")
    else:
        # Affichage de la carte avec la différence de hauteur de la canopée
        center_change = [(start_src_change.bounds.top + start_src_change.bounds.bottom) / 2, (start_src_change.bounds.left + start_src_change.bounds.right) / 2]
        m_change = folium.Map(location=center_change, zoom_start=13, tiles="Esri.WorldImagery")  # Fond ESRI

        # Normalisation de la différence
        norm_change = (canopy_change - min_change) / (max_change - min_change)
        norm_change = np.nan_to_num(norm_change)  # Remplacer les NaN par 0

        # Utilisation de la méthode matplotlib pour les couleurs
        cmap = plt.cm.RdBu  # Utilisation d'un colormap valide
        rgba_img_change = (cmap(norm_change) * 255).astype(np.uint8)
        rgb_img_change = rgba_img_change[:, :, :3]  # Enlever la couche alpha

        # Ajouter la carte et la superposition de l'image
        colormap_change = linear.RdYlGn_09.scale(min_change, max_change)
        colormap_change.caption = "Canopy Height Change (m)"
        colormap_change.add_to(m_change)

        folium.raster_layers.ImageOverlay(
            image=rgb_img_change,
            bounds=[[start_src_change.bounds.bottom, start_src_change.bounds.left], [start_src_change.bounds.top, start_src_change.bounds.right]],
            opacity=0.6,
            name="Canopy Change"
        ).add_to(m_change)

        folium.LayerControl().add_to(m_change)
        m_change.add_child(folium.LatLngPopup())

        # Affichage de la carte dans Streamlit
        st.markdown("### 🌍 Canopy Change Visualization")
        st_folium(m_change, width=1000, height=600)
