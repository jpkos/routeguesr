#%%
import numpy as np
import pandas as pd
import requests
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, url_for
import folium
from folium.plugins import FloatImage
from folium import Element
import yaml
from bs4 import BeautifulSoup
from flask_session import Session
# from flask_socketio import  SocketIO, join_room, emit
import secrets
import uuid
from google.cloud import secretmanager
from google.oauth2 import service_account
# from google.cloud import datastore
import draw_stuff as ds
from ui_config import *
#%%
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = '../route-guesser-2024-122f66f95311.json'

# credentials = service_account.Credentials.from_service_account_file(
#     filename=os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
#     scopes=['https://www.googleapis.com/auth/cloud-platform'])
# client = secretmanager.SecretManagerServiceClient(credentials=credentials)
client = secretmanager.SecretManagerServiceClient()
# name = f"projects/741704884780/secrets/session_secret/versions/1"
name = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT')}/secrets/session_secret/versions/1"
session_response = client.access_secret_version(request={"name": name})
secret_key = session_response.payload.data.decode("UTF-8")

app = Flask(__name__)
app.secret_key = secret_key
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

# socketio = SocketIO(app)
# datastore_client = datastore.Client()

# Session(app)
#%% Load data

df_lines = pd.read_pickle('data/processed/lines.pkl').drop_duplicates(subset='route_short_name', keep='last').dropna(subset='route_short_name')
df_lines = df_lines.sort_values(by=['transport_type', 'route_short_name'], ascending=False)
possible_lines = list(df_lines['route_short_name'].values)#sorted(list(df_lines['route_short_name'].values))

line_types = df_lines[['route_short_name', 'transport_type']].to_dict('records')
# possible_line_types = list(df_lines['transport_type'].values)
# transport_lines_dict = df_lines[]
#%%
# game_sessions = {}
# def create_game_session():
#     session_id = str(uuid.uuid4())
#     game_sessions[session_id] = {
#         'players': [],
#         'state': 'waiting',  # 'waiting', 'ready', 'in_progress'
#         'map': None,
#         'correct_line': None,
#         'total_guesses': 0,
#         'correct_guesses': 0
#     }
#     return session_id
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

# def generate_session_id():
#     # Generate a random UUID (UUID4)
#     return str(uuid.uuid4())

# TODO: move contents to class
def new_template(df_lines, html_output):
    """
    Creates a new map template with a randomly chosen line
    """
    # Get random line
    # print(session['transport_type'])
    # print(session['operating_type'])
    random_line = df_lines[df_lines['transport_type'].isin(session['transport_type']) & df_lines['operating_type'].isin(session['operating_type'])].reset_index(drop=True).sample(1)
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
    html_template  = render_template(html_output, map_html=map_html, line_types=line_types)
    return html_template

@app.route('/')
def index():
    """
    Initialize app when site is first loaded.
    """
    session['total_guesses'] = 0
    session['correct_guesses'] = 0
    session['transport_type'] = list(df_lines['transport_type'].unique())
    session['operating_type'] = list(df_lines['operating_type'].unique())
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
                   correct_pct=f'{session.get("correct_pct", 0):.2f}')

@app.route('/update_single_settings', methods=['POST'])
def update_single_settings():
    """
    Update single player settings
    """
    try:
        data = request.json
        print(data)
        allowed_transport_types = [key for key, val in data['transportTypes'].items() if val]
        session['transport_type'] = allowed_transport_types
        # Operating types defined currently only for buses
        allowed_operating_types = [key for key, val in data['operatingTypes'].items() if val]
        if not allowed_operating_types: # if no selection, pick all
            allowed_operating_types = list(df_lines['operating_type'].unique())
        session['operating_type'] = allowed_operating_types
        # Add logic to handle data as needed
        return jsonify({"message": "Asetukset tallennettu onnistuneesti"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# @app.route('/update_single_settings', methods=['POST'])
# def update_single_settings():
#     data = request.json
#     print(data)  # This will show data separated by column
#     # Example processing:
#     session['Type'] = data['columnA']
#     # session['categoriesB'] = data['columnB']
#     return jsonify({"message": "Options updated successfully"})

# @app.route('/new_multiplayer_game', methods=['POST'])
# def new_multiplayer_game():
#     session_id = create_game_session()
#     game_sessions[session_id] = {
#         'num_questions': request.form['num_questions'],
#         'time_per_question': request.form['time_per_question']
#     }
#     session['sessionId'] = session_id 
#     return jsonify(url=url_for('game_room', session_id=session_id, _external=True))

# @app.route('/game/<session_id>')
# def game_room(session_id):
#     session_info = game_sessions.get(session_id)
#     if session_info:
#         return render_template('game_room.html', session_id=session_id, session_info=session_info)
#     return 'Session not found', 404

# @socketio.on('player_ready')
# def handle_player_ready(session_id):
#     pass

# @app.route('/player_ready/<session_id>', methods=['POST'])
# def handle_player_ready(session_id):
#     session = game_sessions.get(session_id)
#     if session:
#         session['players_ready'] += 1
#         if session['players_ready'] == 2:  # Assuming 2 players for simplicity
#             return jsonify({'start_game': True})
#         return jsonify({'waiting': True})
#     return 'Session not found', 404

# @app.route('/join_game/<session_id>')
# def join_game(session_id):
#     game = game_sessions.get(session_id, None)
#     if game and len(game['players']) < 2:
#         game['players'].append({'id': len(game['players']) + 1, 'status': 'joined'})
#         if len(game['players']) == 2:
#             game['state'] = 'ready'
#         return jsonify({
#             'message': 'Joined game',
#             'game_status': game['state']
#         })
#     return 'Game not found or full', 404

# @app.route('/start_game/<session_id>')
# def start_game(session_id):
#     game = game_sessions.get(session_id, None)
#     if game and game['state'] == 'ready':
#         game['state'] = 'in_progress'
#         return new_template(session_id)
#     return 'Waiting for all players to be ready', 400

# @app.route('/check_guess/<session_id>', methods=['POST'])
# def check_multi_guess(session_id):
#     guess = request.form['guess']
#     game = game_sessions.get(session_id, None)
#     if game and game['state'] == 'in_progress':
#         correct_line = game['correct_line']
#         game['total_guesses'] += 1
#         if guess == correct_line:
#             game['correct_guesses'] += 1
#             result = "Correct"
#         else:
#             result = "Incorrect"
#         return jsonify(result=result, total_guesses=game['total_guesses'], correct_guesses=game['correct_guesses'])
#     return 'Invalid game state or session not found', 400

if __name__ == '__main__':
     socketio.run(app, debug=True)
# %%
