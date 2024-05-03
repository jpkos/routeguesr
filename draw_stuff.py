#%%
import geopandas as gpd
import pandas as pd
import shapely
import folium
import numpy as np
#%%

def draw_route(coords, color='random', weight=7):
    """
    Draw folium polyline from a given list of coordinate pairs
    """
    line = list(coords)
    if color == 'random':
         color = str(hex(np.random.randint(0,16777215)))
         color = f'#{color[2:]}'
    return folium.PolyLine(locations=line, weight=weight, color=color)