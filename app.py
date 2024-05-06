#%%
import numpy as np
import pandas as pd
import requests
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session
import folium
from folium.plugins import FloatImage
from folium import Element
import yaml
from bs4 import BeautifulSoup
from flask_session import Session
import secrets
# from google.cloud import datastore

import draw_stuff as ds
from ui_config import *

app = Flask(__name__)
with open('secrets.txt', 'r') as f:
    app.secret_key = f.readline()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

# datastore_client = datastore.Client()

# Session(app)
#%% Load data

df_lines = pd.read_pickle('data/processed/lines.pkl').drop_duplicates(subset='route_short_name', keep='last').dropna(subset='route_short_name')
possible_lines = sorted(list(df_lines['route_short_name'].values))

#TODO
# class MapTemplate:
#     def __init__(self, df_lines):
#         self.df_lines = df_lines
#         self.possible_lines = sorted(list(df_lines['line'].values))
#         self.random_line()

#     def random_line(self):
#         self.random_line = df_lines.sample(1)
#         self.coords = self.random_line['geometry'].iloc[0].coords

#     def create_folium_map(self):
#         start_coords = self.coords[len(self.coords)//2]
#         folium_map = folium.Map(location=start_coords, zoom_start=ZOOM_LVL)
#         folium_map.get_root().html.add_child(title_html)
#         polyline = ds.draw_route(self.coords, color=LINE_COLOR)
#         folium_map.add_child(polyline)
#         return folium_map

#     def render_html_template(self, folium_map, html_output):
#         map_html = folium_map._repr_html_()
#         return render_template(html_output, map_html=map_html, possible_lines=self.possible_lines)

    
#     def create_new_line(self):
#         self.random_line()
#         fmap = self.create_folium_map()

# TODO: move contents to class
def new_template(df_lines, html_output):
    # Get random line
    random_line = df_lines.sample(1)
    session['correct_line'] = random_line['route_short_name'].iloc[0]
    coords = random_line['geometry'].iloc[0].coords
    start_coords = coords[len(coords)//2]
    # Draw map
    folium_map = folium.Map(location=start_coords, zoom_start=ZOOM_LVL)
    folium_map.get_root().html.add_child(title_html)
    polyline = ds.draw_route(coords, color=LINE_COLOR)
    folium_map.add_child(polyline)
    # Render html
    map_html = folium_map._repr_html_()
    html_template  = render_template(html_output, map_html=map_html, possible_lines=possible_lines)
    return html_template

@app.route('/')
def index():
    """
    Initialize app 
    """
    session['total_guesses'] = 0
    session['correct_guesses'] = 0
    html_template = new_template(df_lines, 'index.html')

    return html_template

@app.route('/new_line')
def new_line():
    """
    Draw new random line on map
    """
    html_template = new_template(df_lines, 'partial_map.html')
    return html_template

@app.route('/check_guess', methods=['POST'])
def check_guess():
    """
    Check user's guess and keep track of guesses
    """
    user_guess = request.form['guess']
    # Retrieve correct line from session
    correct_line = session.get('correct_line', 'Ei linjaa valittuna') 
    if 'total_guesses' not in session.keys():
        session['total_guesses'] = 0
    if 'correct_guesses' not in session.keys():
        session['correct_guesses'] = 0
    session['total_guesses'] = session.get('total_guesses', 0) + 1
    if user_guess == correct_line:
        result = f"Oikein! :) Oikea linja oli {correct_line}."
        session['correct_guesses'] = session.get('correct_guesses', 0) + 1
    else:
        result = f"Väärin :( Oikea linja oli {correct_line}."
    # TODO: Display guessed line as gray on the map after guess
    session['correct_pct'] = (session.get('correct_guesses', 0)/session.get('total_guesses', 0))*100 if session.get('total_guesses', 0)>0 else 0
    
    return jsonify(result=result,
                   total_guesses=session.get('total_guesses', 0),
                   correct_guesses=session.get('correct_guesses', 0),
                   correct_pct=f'{session.get('correct_pct', 0):.2f}')

if __name__ == '__main__':
    app.run(debug=False)