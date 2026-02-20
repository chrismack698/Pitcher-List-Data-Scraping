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
date = st.date_input("Select Date", value="today", min_value=None, max_value=None, format="YYYY/MM/DD")

if date is not None:
    st.write("Date selected...")

base_url = 'https://baseballsavant.mlb.com/gf?game_pk='

try:
    request_yesterday = r.get(f'https://statsapi.mlb.com/api/v1/schedule?date={date + timedelta(days=-1)}&sportId=1&hydrate=broadcasts,probablePitcher(note)')
    request_today = r.get(f'https://statsapi.mlb.com/api/v1/schedule?date={date}&sportId=1&hydrate=broadcasts,probablePitcher(note)')
except Exception as e:
    st.error(f"Failed to fetch schedule data: {e}")
    st.stop()

game_ids = []
games = statsapi.schedule(start_date=date + timedelta(days=-1), end_date=date + timedelta(days=-1))

for i in games:
    game_ids.append(i['game_id'])


def parse_game_data(data):
    rows = []
    for d in data.get('dates', []):
        for game in d['games']:
            gamePk = game['gamePk']
            broadcasts = game.get('broadcasts', [])
            on_tv = any(broadcast['type'] == 'TV' for broadcast in broadcasts)
            rows.append({'gamePk': gamePk, 'ON_TV': on_tv})
    df = pd.DataFrame(rows)
    return df


today_data = request_yesterday.json()
on_tv = parse_game_data(today_data)

# ── Yesterday's game log ──────────────────────────────────────────────────────

if not game_ids:
    st.warning(f"No games found for {date + timedelta(days=-1)}. The yesterday's pitcher file cannot be generated.")
else:
    dfs = []

    for i in game_ids:
        try:
            game_id_str = str(i)
            response = r.get(base_url + game_id_str)
            response_json = response.json()

            # Gracefully handle missing keys in the Savant response
            scoreboard = response_json.get('scoreboard', {})
            stats = scoreboard.get('stats', {})
            pitch_velocity = stats.get('pitchVelocity', {})
            game_status_code = response_json.get('game_status_code', '')

            if game_status_code != 'C':
                if pitch_velocity and pitch_velocity.get('topPitches'):
                    statcast_status = "Statcast Games"
                else:
                    statcast_status = "No Statcast"
            else:
                statcast_status = 'Cancelled'

            boxscore = statsapi.boxscore_data(i)
            if not boxscore:
                st.warning(f"No boxscore data for game {i}. Skipping.")
                continue

            games_box_away = pd.DataFrame(boxscore['awayPitchers'])
            games_box_home = pd.DataFrame(boxscore['homePitchers'])

            if games_box_away.empty and games_box_home.empty:
                st.warning(f"No pitcher data for game {i}. Skipping.")
                continue

            away_team_abbr = boxscore['teamInfo']['away']['abbreviation']
            home_team_abbr = boxscore['teamInfo']['home']['abbreviation']
            game_info = home_team_abbr + ' vs. ' + away_team_abbr

            for df, abbr in [(games_box_away, away_team_abbr), (games_box_home, home_team_abbr)]:
                df['teamname'] = abbr
                df['game_info'] = game_info
                df['game_id'] = i
                df['statcast_status'] = statcast_status

            dfs.append(games_box_home)
            dfs.append(games_box_away)

        except Exception as e:
            st.warning(f"Error processing game {i}: {e}. Skipping.")
            continue

    if not dfs:
        st.warning("No pitcher data could be retrieved for yesterday's games.")
    else:
        try:
            final = pd.concat(dfs, ignore_index=True)
            final = final.merge(on_tv, left_on='game_id', right_on='gamePk', how='inner')
            filtered_df = final[~final['namefield'].str.contains('Pitchers')]

            pitcher_names = []
            for i in filtered_df['personId']:
                try:
                    player = statsapi.player_stat_data(i)
                    full_name = player['first_name'] + ' ' + player['last_name']
                except Exception:
                    full_name = 'Unknown'
                pitcher_names.append(full_name)

            filtered_df = filtered_df.copy()
            filtered_df['full_name'] = pitcher_names

            filtered_df_update = filtered_df.iloc[:, [1, 2, 4, 5, 6]].astype(str).apply(lambda x: x + ' ' + x.name.upper())
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

            header_order = [
                ("Statcast Games", True),
                ("Statcast Games", False),
                ("No Statcast", True),
                ("No Statcast", False)
            ]
            header_order_map = {item: index for index, item in enumerate(header_order)}

            grouped = final_df.groupby(['statcast_status', 'on_tv'])
            grouped_items = list(grouped)
            sorted_groups = sorted(grouped_items, key=lambda x: header_order_map.get((x[0][0], x[0][1]), -1))

            html_content = ""
            for (statcast_status, on_tv_val), group in sorted_groups:
                header_key = (statcast_status == "Statcast Games", on_tv_val)
                html_content += headers[header_key] + "<br><br>"

                game_infos = group['game_info'].unique()
                for game_info in game_infos:
                    html_content += f"{game_info}<br>&nbsp;<br>"
                html_content += "&nbsp;<br>"

                for index, row in group.iterrows():
                    formatted_string = (
                        f"<strong>{row['full_name']} ({row['current_team']}) - "
                        f"{row['ip']}, {row['er']}, {row['h']}, {row['bb']}, {row['k']}.</strong>"
                    )
                    html_content += formatted_string + "<br>&nbsp;<br>"
                html_content += "&nbsp;<br><br>"

            st.write("File created successfully!")
            st.download_button(
                f"Download Text File for Pitcher Performances from {date + timedelta(days=-1)}",
                html_content,
                file_name=f"output_{date + timedelta(days=-1)}.txt"
            )

        except Exception as e:
            st.error(f"Error building yesterday's pitcher file: {e}")


# ── Today's TV starters ───────────────────────────────────────────────────────

try:
    on_tv_today = request_today.json()
    on_tv_today_df = parse_game_data(on_tv_today)

    game_info_today = statsapi.schedule(date)

    if not game_info_today:
        st.warning(f"No games scheduled for {date}. The today's TV pitcher list cannot be generated.")
    else:
        games_df = pd.DataFrame(game_info_today)
        games_df = games_df[['game_id', 'home_probable_pitcher', 'away_probable_pitcher']]
        games_df.rename(columns={'game_id': 'gamePk'}, inplace=True)

        merged_df = pd.merge(on_tv_today_df, games_df, on='gamePk', how='left')
        pitchers_filtered = merged_df[merged_df['ON_TV'] == True]

        if pitchers_filtered.empty:
            st.warning("No TV games found for today.")
        else:
            pitchers = (
                pitchers_filtered['home_probable_pitcher'].tolist()
                + pitchers_filtered['away_probable_pitcher'].tolist()
            )

            header = """SPs to watch on TV today #SpringSPnotes

Get morning updates to EVERY SP via my daily Plus Pitch Podcast AND SP Roundup article on the Pitcher List site.
"""
            tv_content = header + "\n" + "\n".join(f"{p} - " for p in pitchers if p)

            st.download_button(
                label="Download Pitchers on TV for Today",
                data=tv_content.encode('utf-8'),
                file_name=f"pitcher_list_on_tv_{date}.txt"
            )

except Exception as e:
    st.error(f"Error building today's TV pitcher list: {e}")
