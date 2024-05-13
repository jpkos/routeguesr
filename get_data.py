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
#%% Get route types from emissions.txt
df_emissions = pd.read_csv('data/hsl/emissions.txt')
#%%
df_lines = pd.merge(
    left=df_lines,
    right=df_emissions,
    on='route_short_name',
    how='left'
)
#%%
df_lines['Type'] = df_lines['Type'].fillna('')
#%%
df_lines['Type'] = df_lines['Type'].apply(lambda x: 'bus' if 'bus' in x else x.lower())
#%%
df_lines = df_lines.rename(columns={'Type':'transport_type'})
#%%
print(df_lines.shape)

#%% Add helper columns for identyifying lines
df_lines['route_short_name'] = df_lines['route_short_name'].fillna('')
df_lines['operating_type'] = df_lines['route_short_name'].apply(lambda x: 'night' if x.endswith('N') else 'normal')
#%% Manual edits
# df_lines.loc[df_lines['route_short_name'] == '15', 'transport_type'] = 'tram'
df_lines.loc[df_lines['route_short_name'].isin(['H', 'D']), 'transport_type'] = 'train'
df_lines.loc[df_lines['route_short_name'].isin(['17', '19', '19E']), 'transport_type'] = 'ferry'
df_lines.loc[df_lines['route_short_name'].isin(['1T', '8T', '8X', '9B']), 'transport_type'] = 'tram'
df_lines.loc[df_lines['route_short_name'].isin(['24S', '99M',
       '213X', '245A', '348BK', '600N', '711K', '712', '211E', '211U',
       '211X', '249Y', '911X', '913AK', '913BK', '191A', '191', '192V',
       '192', '193K', '193VK', '193', '194VK', '194VT', '194V', '195',
       '275', '280', '346', '375V', '375', '455A', '455', '456A', '456N',
       '456', '457A', '457', '459', '465B', '465', '848', '999', '965T',
       '969X']), 'transport_type'] = 'bus'
#%% Save for app
df_lines.to_pickle('data/processed/lines.pkl')
# %%
