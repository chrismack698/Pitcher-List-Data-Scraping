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
selected_date = st.date_input("Select Date", value="today", min_value=None, max_value=None, format="YYYY/MM/DD")

if selected_date is not None:
    st.write("Date selected...")

try:
    request_yesterday = r.get(f'https://statsapi.mlb.com/api/v1/schedule?date={selected_date + timedelta(days=-1)}&sportId=1&hydrate=broadcasts,probablePitcher(note)')
    request_today = r.get(f'https://statsapi.mlb.com/api/v1/schedule?date={selected_date}&sportId=1&hydrate=broadcasts,probablePitcher(note)')
except Exception as e:
    st.error(f"Failed to fetch schedule data: {e}")
    st.stop()

game_ids = []
games = statsapi.schedule(start_date=selected_date + timedelta(days=-1), end_date=selected_date + timedelta(days=-1))

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


yesterday_data = request_yesterday.json()
on_tv = parse_game_data(yesterday_data)

# ── Yesterday's game log ──────────────────────────────────────────────────────

if not game_ids:
    st.warning(f"No games found for {selected_date + timedelta(days=-1)}. The yesterday's pitcher file cannot be generated.")
else:
    dfs = []

    for i in game_ids:
        try:
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

            stat_cols = ['ip', 'h', 'bb', 'k', 'er']
            filtered_df_update = filtered_df[stat_cols].astype(str).apply(lambda x: x + ' ' + x.name.upper())
            filtered_df_update['full_name'] = filtered_df['full_name'].values
            filtered_df_update['current_team'] = filtered_df['teamname'].values
            filtered_df_update['on_tv'] = filtered_df['ON_TV'].values
            filtered_df_update['game_info'] = filtered_df['game_info'].values
            final_df = filtered_df_update[['full_name', 'current_team', 'ip', 'h', 'bb', 'k', 'er', 'on_tv', 'game_info']]

            headers = {
                True:  '<span style="font-size: 20pt; color: #3366ff;"><strong>On TV</strong></span>',
                False: '<span style="font-size: 20pt; color: #339966;"><strong>Not on TV</strong></span>',
            }

            # TV games first, then non-TV
            grouped = final_df.groupby('on_tv')
            sorted_groups = sorted(grouped, key=lambda x: x[0], reverse=True)

            html_content = ""
            for on_tv_val, group in sorted_groups:
                html_content += headers[on_tv_val] + "<br><br>"

                for game_info_val in group['game_info'].unique():
                    html_content += f"{game_info_val}<br>&nbsp;<br>"
                html_content += "&nbsp;<br>"

                for _, row in group.iterrows():
                    formatted_string = (
                        f"<strong>{row['full_name']} ({row['current_team']}) - "
                        f"{row['ip']}, {row['er']}, {row['h']}, {row['bb']}, {row['k']}.</strong>"
                    )
                    html_content += formatted_string + "<br>&nbsp;<br>"
                html_content += "&nbsp;<br><br>"

            st.write("File created successfully!")
            st.download_button(
                f"Download Text File for Pitcher Performances from {selected_date + timedelta(days=-1)}",
                html_content,
                file_name=f"output_{selected_date + timedelta(days=-1)}.txt"
            )

        except Exception as e:
            st.error(f"Error building yesterday's pitcher file: {e}")


# ── Today's TV starters ───────────────────────────────────────────────────────

try:
    on_tv_today = request_today.json()
    on_tv_today_df = parse_game_data(on_tv_today)

    game_info_today = statsapi.schedule(selected_date)

    if not game_info_today:
        st.warning(f"No games scheduled for {selected_date}. The today's TV pitcher list cannot be generated.")
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
                file_name=f"pitcher_list_on_tv_{selected_date}.txt"
            )

except Exception as e:
    st.error(f"Error building today's TV pitcher list: {e}")
