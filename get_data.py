#%%
import numpy as np
import pandas as pd
import geopandas as gpd
import os
import shapely
import requests
#%%
# import zipfile
# #%% Get zipped GTFS data
# response = requests.get('https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip')
# #%%
# zip_path = 'data/hsl/hsl.zip'
# with open(zip_path, 'wb') as f:
#         f.write(response.content)

# with zipfile.ZipFile(zip_path, 'r') as zip_ref:
#         zip_ref.extractall('data/hsl/')
#%% Get route shape data
df_shapes = pd.read_csv('data/hsl/shapes.txt')
# %% Create new df with routes as linestrings
df_lines = df_shapes.groupby('shape_id').apply(lambda x: shapely.LineString(x[['shape_pt_lat', 'shape_pt_lon']])).reset_index()
df_lines = df_lines.rename(columns={0:'geometry'})
#%% Separate line id from shape_id

df_lines['line'] = df_lines['shape_id'].str.split('_').str[0]
#%% To geopandas
df_lines = gpd.GeoDataFrame(df_lines, geometry='geometry', crs='epsg:4326')
#%% Join route codes by trips and shape ids
df_trips = pd.read_csv('data/hsl/trips.txt')
df_routes = pd.read_csv('data/hsl/routes.txt')
#%%
df_trips = df_trips.drop_duplicates(subset='shape_id')
df_lines = pd.merge(
    left=df_lines,
    right=df_trips[['shape_id', 'route_id']],
    on='shape_id',
    how='left'
)
#%%
df_lines = pd.merge(
    left=df_lines,
    right=df_routes,
    on='route_id',
    how='left'
)
#%% Save for app
df_lines.to_pickle('data/processed/lines.pkl')