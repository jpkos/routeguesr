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

import draw_stuff as ds

#%%
html = '''
<div id="maptitle" style="position: fixed; top: 20px; left: 100px; z-index: 9999; font-size: 12px; color: black; background-color: white; padding: 5px;">
    <h4>Mikä reitti tässä kulkee?</h4>
    <p> Kokeile, kuinka hyvin tunnet HSL:n joukkoliikenteen reitit </p>
    <p> Reittivaihtoehdot löytyvät pudotusvalikosta </p>
</div>
<script>
    var title = L.control({position: 'topleft'});
    title.onAdd = function (map) {
        var div = L.DomUtil.get("maptitle");
        return div;
    };
    title.addTo({{this}});
</script>
'''
title_html = Element(html)
app = Flask(__name__)
app.secret_key = 'erittain_salainen'
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

ZOOM_LVL = 11
LINE_COLOR = '#13B7FB'

df_lines = pd.read_pickle('data/processed/lines.pkl').drop_duplicates(subset='line')
possible_lines = list(df_lines['line'].values)
@app.route('/')
def index():
    # start_coords = (60.19912857374085, 24.940578211739854)  
    # folium_map = folium.Map(location=start_coords,
    #                         zoom_start=11)
    # folium_map.get_root().html.add_child(title_html)
    session['total_guesses'] = 0
    session['correct_guesses'] = 0
    random_line = df_lines.sample(1)
    session['correct_line'] = random_line['line'].iloc[0]
    coords = random_line['geometry'].iloc[0].coords
    start_coords = coords[0]
    folium_map = folium.Map(location=start_coords, zoom_start=ZOOM_LVL)
    folium_map.get_root().html.add_child(title_html)
    polyline = ds.draw_route(coords, color=LINE_COLOR)
    folium_map.add_child(polyline)
    map_html = folium_map._repr_html_()

    html_template  = render_template('index.html', map_html=map_html, possible_lines=possible_lines)
    return html_template

@app.route('/new_line')
def new_line():
    random_line = df_lines.sample(1).iloc[0]
    session['correct_line'] = random_line['line']  # Store correct line in session

    # Draw the line on the map
    coords = random_line['geometry'].coords
    start_coords = coords[len(coords)//2]
    folium_map = folium.Map(location=start_coords, zoom_start=ZOOM_LVL)
    folium_map.get_root().html.add_child(title_html)
    polyline = ds.draw_route(coords, color=LINE_COLOR)
    folium_map.add_child(polyline)

    map_html = folium_map._repr_html_()

    # Render just the necessary parts to update
    return render_template('partial_map.html', map_html=map_html, possible_lines=possible_lines)

@app.route('/check_guess', methods=['POST'])
def check_guess():
    user_guess = request.form['guess']
    correct_line = session.get('correct_line', 'Ei linjaa valittuna')  # Retrieve correct line from session
    session['total_guesses'] += 1
    if user_guess == correct_line:
        result = f"Oikein! :) Oikea linja oli {correct_line}."
        session['correct_guesses'] += 1
    else:
        result = f"Väärin :( Oikea linja oli {correct_line}."

    return jsonify(result=result,
                   total_guesses=session['total_guesses'],
                   correct_guesses=session['correct_guesses'])

if __name__ == '__main__':
    app.run(debug=True)
# %%
    # for i, df in df_lines.sample(5).groupby('line'):
    #     coords = df['geometry'].iloc[0].coords
    #     polyline = ds.draw_route(coords)
    #     marker_coords = coords[0]
    #     folium_map.add_child(polyline)
    #     folium.Marker(
    #             location=marker_coords,
    #             tooltip=df['line'].iloc[0]
    #         ).add_to(folium_map)