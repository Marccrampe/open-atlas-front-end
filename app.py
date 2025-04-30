# Affichage des dates de départ et de fin
start_date = st.selectbox("Select Start Date", available_dates)
end_date = st.selectbox("Select End Date", available_dates)

# Vérifier que la date de fin est postérieure à la date de départ
if available_dates.index(end_date) <= available_dates.index(start_date):
    st.error("End date must be later than start date.")
    st.stop()

# Récupérer les fichiers TIFF pour les deux dates sélectionnées
start_file = aoi_dict[selected_aoi][start_date]
end_file = aoi_dict[selected_aoi][end_date]

# Télécharger les fichiers TIFF depuis S3
start_tif_obj = s3_client.get_object(Bucket=s3_bucket_name, Key=start_file)
start_tif_bytes = start_tif_obj['Body'].read()

end_tif_obj = s3_client.get_object(Bucket=s3_bucket_name, Key=end_file)
end_tif_bytes = end_tif_obj['Body'].read()

# Charger les fichiers TIFF
with MemoryFile(start_tif_bytes) as start_memfile:
    with start_memfile.open() as start_src:
        start_arr = start_src.read(1).astype(np.float32)
        start_arr[start_arr <= 0] = np.nan  # Remplacer les valeurs faibles par NaN

with MemoryFile(end_tif_bytes) as end_memfile:
    with end_memfile.open() as end_src:
        end_arr = end_src.read(1).astype(np.float32)
        end_arr[end_arr <= 0] = np.nan  # Remplacer les valeurs faibles par NaN

# Calcul de la différence entre les deux dates
canopy_change = end_arr - start_arr

# Calcul des stats pour la différence
mean_change = np.nanmean(canopy_change)
min_change = np.nanmin(canopy_change)
max_change = np.nanmax(canopy_change)

# Affichage des résultats
st.markdown(f"### 🌿 Canopy Change between {start_date} and {end_date}")
col1, col2, col3 = st.columns(3)
col1.metric("🌿 Mean Change", f"{mean_change:.2f} m")
col2.metric("🔻 Min Change", f"{min_change:.2f} m")
col3.metric("🔺 Max Change", f"{max_change:.2f} m")

# Affichage de la carte avec la différence de hauteur de la canopée
center = [(start_src.bounds.top + start_src.bounds.bottom) / 2, (start_src.bounds.left + start_src.bounds.right) / 2]
m_change = folium.Map(location=center, zoom_start=13, tiles="Esri.WorldImagery")  # Utilisation du fond Esri

# Normalisation de la différence
norm_change = (canopy_change - min_change) / (max_change - min_change)
norm_change = np.nan_to_num(norm_change)  # Remplacer les NaN par 0

# Utilisation de la méthode matplotlib pour les couleurs
cmap = plt.cm.RdYlGn  # Utilisation d'un colormap avec rouge pour négatif et vert pour positif
rgba_img_change = (cmap(norm_change) * 255).astype(np.uint8)
rgb_img_change = rgba_img_change[:, :, :3]  # Enlever la couche alpha

# Ajouter la carte et la superposition de l'image
colormap_change = linear.RdYlGn.scale(min_change, max_change)
colormap_change.caption = "Canopy Height Change (m)"
colormap_change.add_to(m_change)

folium.raster_layers.ImageOverlay(
    image=rgb_img_change,
    bounds=[[start_src.bounds.bottom, start_src.bounds.left], [start_src.bounds.top, start_src.bounds.right]],
    opacity=0.6,
    name="Canopy Change"
).add_to(m_change)

folium.LayerControl().add_to(m_change)
m_change.add_child(folium.LatLngPopup())

# Affichage de la carte dans Streamlit
st.markdown("### 🌍 Canopy Change Visualization")
result_change = st_folium(m_change, width=1000, height=600)

# Get clicked lat/lon and show height change
if result_change.get("last_clicked"):
    lat = result_change["last_clicked"]["lat"]
    lon = result_change["last_clicked"]["lng"]
    with start_memfile.open() as start_src:
        row, col = start_src.index(lon, lat)
        try:
            height_change_val = canopy_change[row, col]
            st.success(f"🌲 Canopy change at ({lat:.5f}, {lon:.5f}) is **{height_change_val:.2f} m**")
        except:
            st.error("Invalid pixel location.")
