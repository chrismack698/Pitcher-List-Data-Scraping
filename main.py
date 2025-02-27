import streamlit as st
import pybaseball as py
import pandas as pd
import statsapi
import json
from pybaseball import pitching_stats_range
from pybaseball.retrosheet import season_game_logs
import requests as r
from datetime import date, timedelta

st.title("Spring Training Pitcher File Generator")
date = st.date_input("Select Date", value="today", min_value=None, max_value=None,format="YYYY/MM/DD" )

if date is not None:
    st.write("Date selected...")

base_url = 'https://baseballsavant.mlb.com/gf?game_pk='
request_yesterday = r.get(f'https://statsapi.mlb.com/api/v1/schedule?date={date + timedelta(days=-1)}&sportId=1&hydrate=broadcasts,probablePitcher(note)')
request_today = r.get(f'https://statsapi.mlb.com/api/v1/schedule?date={date}&sportId=1&hydrate=broadcasts,probablePitcher(note)')
game_ids = []
games = statsapi.schedule(start_date=date + timedelta(days=-1),end_date=date + timedelta(days=-1))

for i in games:
    game_ids.append(i['game_id'])

def parse_game_data(data):
    # Initialize a list to hold the rows for the DataFrame
    rows = []

    # Loop over all games in the dates
    for date in data['dates']:
        for game in date['games']:
            gamePk = game['gamePk']
            
            # Check if the 'broadcasts' key exists before checking the type
            broadcasts = game.get('broadcasts', [])
            
            # Check if any of the broadcasts has type 'TV'
            on_tv = any(broadcast['type'] == 'TV' for broadcast in broadcasts)
            
            # Append the result to the rows list
            rows.append({'gamePk': gamePk, 'ON_TV': on_tv})
    
    # Convert the rows list into a pandas DataFrame
    df = pd.DataFrame(rows)
    
    return df


today_data = request_yesterday.json()

on_tv = parse_game_data(today_data)


# Initialize an empty list to store DataFrames
dfs = []

for i in game_ids:
    # Convert game_id to string
    game_id_str = str(i)
    
    # Make the request with the string game_id
    response = r.get(base_url + game_id_str)
    
    # Process the JSON response
    pitch_velocity = response.json()['scoreboard']['stats']['pitchVelocity']
    
    # Determine if there is Statcast data
    if response.json()['game_status_code'] != 'C':
        if pitch_velocity['topPitches']:
            statcast_status = "Statcast Games"
        else:
            statcast_status = "No Statcast"
    else:
       statcast_status = 'Cancelled'
    
    # Create DataFrames for away and home pitchers
    games_box_away = pd.DataFrame(statsapi.boxscore_data(i)['awayPitchers'])
    games_box_home = pd.DataFrame(statsapi.boxscore_data(i)['homePitchers'])
    
    # Add the team abbreviation as a new column
    away_team_abbr = statsapi.boxscore_data(i)['teamInfo']['away']['abbreviation']
    home_team_abbr = statsapi.boxscore_data(i)['teamInfo']['home']['abbreviation']
    game_info = home_team_abbr + ' vs. ' + away_team_abbr
    games_box_away['teamname'] = away_team_abbr
    games_box_home['teamname'] = home_team_abbr
    games_box_away['game_info'] = game_info
    games_box_home['game_info'] = game_info
    games_box_away['game_id'] = i
    games_box_home['game_id'] = i
     
    # Add the Statcast status as a new column
    games_box_away['statcast_status'] = statcast_status
    games_box_home['statcast_status'] = statcast_status
    
    # Append the DataFrames to the list
    dfs.append(games_box_home)
    dfs.append(games_box_away)

# Concatenate all DataFrames
final = pd.concat(dfs, ignore_index=True)
final = final.merge(on_tv, left_on='game_id', right_on='gamePk', how='inner')
filtered_df = final[~final['namefield'].str.contains('Pitchers')]

pitcher_names = []
# current_teams = []

# Assuming 'filtered_df' contains player IDs in 'personId'
for i in filtered_df['personId']:
    try:
        full_name = statsapi.player_stat_data(i)['first_name'] + ' ' + statsapi.player_stat_data(i)['last_name']
    except:
        full_name = 'Unknown'
    # try:
    #     current_team = get_team_abbreviation(statsapi.player_stat_data(i)['current_team'])
    # except:
    #     'Unknown'
    # current_teams.append(current_team)
    pitcher_names.append(full_name)

filtered_df['full_name'] = pitcher_names

filtered_df_update = filtered_df.iloc[:, [1, 2, 4, 5, 6]].astype(str).apply(lambda x : x+' '+x.name.upper())
filtered_df_update['full_name'] = filtered_df['full_name']
filtered_df_update['current_team'] = filtered_df['teamname']
filtered_df_update['statcast_status'] = filtered_df['statcast_status']
filtered_df_update['on_tv'] = filtered_df['ON_TV']
filtered_df_update['game_info'] = filtered_df['game_info']
final_df = filtered_df_update.iloc[:, [5, 6, 0, 2, 1, 3, 4, 7, 8, 9]]

headers = {
    (True, True): '<span style="font-size: 20pt; color: #3366ff;"><strong>Statcast Games - TV</strong></span>',
    (True, False): '<span style="font-size: 20pt; color: #339966;"><strong>Statcast Games - No TV</strong></span>',
    (False, True): '<span style="font-size: 20pt; color: #cf5606;"><strong>No Statcast - TV</strong></span>',
    (False, False): '<span style="font-size: 20pt; color: #940a0a;"><strong>No Statcast - No TV</strong></span>'
}

# Define the order of the headers
header_order = [
    ("Statcast Games", True),
    ("Statcast Games", False),
    ("No Statcast", True),
    ("No Statcast", False)
]

# Create a mapping to convert each (statcast_status, on_tv) to an index
header_order_map = {item: index for index, item in enumerate(header_order)}

# Group the DataFrame by 'statcast_status' and 'on_tv' columns
grouped = final_df.groupby(['statcast_status', 'on_tv'])

# Extract the keys and group DataFrames
grouped_items = list(grouped)

# Sort the groups based on the defined header order by the group key (statcast_status, on_tv)
sorted_groups = sorted(grouped_items, key=lambda x: header_order_map.get((x[0][0], x[0][1]), -1))

# Initialize HTML content
html_content = ""

# Iterate over the sorted groups
for (statcast_status, on_tv), group in sorted_groups:
    # Determine the header key
    header_key = (statcast_status == "Statcast Games", on_tv)
    
    # Add the header
    html_content += headers[header_key] + "<br><br>"
    
    # Add the game info
    game_infos = group['game_info'].unique()
    for game_info in game_infos:
        html_content += f"{game_info}<br>&nbsp;<br>"
    
    # Add a single blank line for spacing after the game info section
    html_content += "&nbsp;<br>"
    
    # Add player stat lines
    for index, row in group.iterrows():
        full_name = row['full_name']
        current_team = row['current_team']
        ip = row['ip']
        er = row['er']
        h = row['h']
        bb = row['bb']
        k = row['k']
        
        # Format the output string
        formatted_string = f"<strong>{full_name} ({current_team}) - {ip}, {er}, {h}, {bb}, {k}.</strong>"
        
        # Append the formatted string to the HTML content
        html_content += formatted_string + "<br>&nbsp;<br>"
    
    # Add a blank line for spacing between groups
    html_content += "&nbsp;<br><br>"


st.write("File created successfully!")

st.download_button(f"Download Text File for Pitcher Performances from {date + timedelta(days=-1)}", html_content, file_name=f"output_{date + timedelta(days=-1)}")


on_tv_today = request_today.json()

# Get the dataframe with the game information
on_tv_today_df = parse_game_data(on_tv_today)

game_info = statsapi.schedule(date)

games_df = pd.DataFrame(game_info)

# We are interested in game_id, home_probable_pitcher, and away_probable_pitcher
games_df = games_df[['game_id', 'home_probable_pitcher', 'away_probable_pitcher']]

# Rename the column in games_df for merging
games_df.rename(columns={'game_id': 'gamePk'}, inplace=True)

# Merge the two dataframes on gamePk
merged_df = pd.merge(on_tv_today_df, games_df, on='gamePk', how='left')

pitchers_filtered = merged_df[merged_df['ON_TV'] == True]

# Extract the pitcher names (both home and away) and combine them into a list
pitchers = pitchers_filtered['home_probable_pitcher'].tolist() + pitchers_filtered['away_probable_pitcher'].tolist()

# Open the file in write mode
# Define the header content
header = """SPs to watch on TV today #SpringSPnotes

Get morning updates to EVERY SP via my daily Plus Pitch Podcast AND SP Roundup article on the Pitcher List site.
"""

# Write the header and pitchers to the file
with open('pitcher_list_on_tv.txt', 'w', encoding='utf-8') as file:
    # Write the header
    file.write(header + "\n")
    
    # Write the list of pitchers
    for pitcher in pitchers:
        file.write(f"{pitcher} - \n")


with open('pitcher_list_on_tv.txt', 'rb') as file:
    btn = st.download_button(
        label="Download Pitchers on TV for Today",
        data=file,
        file_name=f"pitcher_list_on_tv_{date}.txt"
    )
