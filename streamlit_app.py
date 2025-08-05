import streamlit as st
import pandas as pd
import gspread
from datetime import datetime, timedelta
import pytz
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- Page Configuration ---
st.set_page_config(page_title="Flight Observer", layout="wide")
st.title("IAH Flight Observation Tool")

# --- Authorization & Data Loading (Cached) ---
@st.cache_resource(ttl=600)
def authorize_gspread():
    """Authorize Google Sheets API."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["google_service_account"], scopes=scope
    )
    return gspread.authorize(credentials)

@st.cache_data(ttl=600)
def get_sheet_data(sheet_name):
    """Fetch and process data for a given sheet name."""
    try:
        sheet = master_sheet.worksheet(sheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        # --- Data Cleaning and Type Conversion ---
        # Ensure time columns are parsed correctly
        for col in ['Est. Boarding Start', 'Est. Boarding End']:
            df[col] = pd.to_datetime(df[col], format='%I:%M %p', errors='coerce').dt.time
        
        # Ensure flight numbers are strings for consistent matching
        df['Flight Num'] = df['Flight Num'].astype(str)
        df['Observers'] = df['Observers'].astype(str)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Sheet named '{sheet_name}' not found. Please make sure today's flight data has been uploaded.")
        return None

gc = authorize_gspread()
SHEET_URL = "https://docs.google.com/spreadsheets/d/109xeylSzvDEMTRjqYTllbzj3nElbfVCTSzZxfn4caBQ/edit?usp=sharing"
master_sheet = gc.open_by_url(SHEET_URL)
all_sheets = master_sheet.worksheets()
sheet_map = {sheet.title: sheet for sheet in all_sheets}

# --- Session State Initialization ---
if "mode" not in st.session_state:
    st.session_state.mode = "today"
if "suggested_schedule" not in st.session_state:
    st.session_state.suggested_schedule = None

# --- UI: Mode Selection Buttons ---
col1, col2, col3, col4 = st.columns(4)
if col1.button("Today's Flights"):
    st.session_state.mode = "today"
if col2.button("Suggest My Schedule"):
    st.session_state.mode = "suggest"
if col3.button("Manual Sign-up"):
    st.session_state.mode = "signup"
if col4.button("View Tracker"):
    st.session_state.mode = "tracker"

# --- Dynamic Sheet Name Logic ---
central_tz = pytz.timezone("America/Chicago")
today_date = datetime.now(central_tz)
current_sheet_name = today_date.strftime("%A %-m/%-d")


# ==============================================================================
# --- MODE 1: TODAY'S FLIGHTS (Read-Only View) ---
# ==============================================================================
if st.session_state.mode == "today":
    st.subheader(f"Upcoming Flights for {current_sheet_name}")
    df = get_sheet_data(current_sheet_name)

    if df is not None:
        now_time = datetime.now(central_tz).time()
        upcoming_df = df[df["Est. Boarding Start"] >= now_time].copy()

        if not upcoming_df.empty:
            cols_to_display = {
                "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End",
                "PAX TOTAL": "Pax", "Important flight?": "Important", "Observers": "Observers"
            }
            display_df = upcoming_df[list(cols_to_display.keys())].rename(columns=cols_to_display)
            st.dataframe(display_df, hide_index=True, use_container_width=True)
        else:
            st.info("No more upcoming flights for today.")

# ==============================================================================
# --- MODE 2: SUGGEST MY SCHEDULE (New Feature) ---
# ==============================================================================
elif st.session_state.mode == "suggest":
    st.subheader("Get an Optimized Schedule Suggestion")
    df = get_sheet_data(current_sheet_name)

    if df is not None:
        name = st.text_input("Enter your name:", key="suggest_name")
        c1, c2 = st.columns(2)
        start_time_input = c1.time_input("Enter your start time:", timedelta(hours=9))
        end_time_input = c2.time_input("Enter your end time:", timedelta(hours=17))

        if st.button("Suggest My Schedule"):
            if not name:
                st.warning("Please enter your name.")
            else:
                # --- Python Scheduler Logic ---
                # 1. Prepare flight data
                flights_df = df.copy()
                flights_df = flights_df[flights_df['Has Equipment'] == 'Yes']
                
                # Filter by observer's shift and flights not already taken
                available_flights = flights_df[
                    (flights_df['Est. Boarding Start'] >= start_time_input) &
                    (flights_df['Est. Boarding End'] <= end_time_input) &
                    (flights_df['Observers'] == '')
                ].copy()

                # 2. Scheduling Algorithm
                schedule = []
                last_flight_end_time = None

                while not available_flights.empty:
                    potential_next = available_flights.copy()
                    
                    if last_flight_end_time:
                        # Add 10 min buffer to last flight's end time
                        buffer_end_time = (datetime.combine(datetime.today(), last_flight_end_time) + timedelta(minutes=10)).time()
                        potential_next = potential_next[potential_next['Est. Boarding Start'] >= buffer_end_time]

                    if potential_next.empty:
                        break

                    # 3. Score potential flights
                    # This is a simplified scoring. Can be enhanced with gate logic.
                    potential_next['time_score'] = potential_next['Est. Boarding Start'].apply(
                        lambda x: (datetime.combine(datetime.today(), x) - datetime.combine(datetime.today(), last_flight_end_time if last_flight_end_time else start_time_input)).total_seconds()
                    )
                    potential_next['importance_score'] = potential_next['Important flight?'].apply(lambda x: 0 if x == 'Yes' else 1)
                    
                    # Sort by importance, then by time
                    potential_next = potential_next.sort_values(by=['importance_score', 'time_score'])
                    
                    best_choice = potential_next.iloc[0]
                    schedule.append(best_choice)
                    
                    last_flight_end_time = best_choice['Est. Boarding End']
                    # Remove chosen flight from the available pool
                    available_flights = available_flights[available_flights['Flight Num'] != best_choice['Flight Num']]

                st.session_state.suggested_schedule = pd.DataFrame(schedule) if schedule else None

        if st.session_state.suggested_schedule is not None:
            st.markdown("---")
            st.success("Here is your suggested schedule:")
            
            display_cols = {
                "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End"
            }
            st.dataframe(st.session_state.suggested_schedule[list(display_cols.keys())].rename(columns=display_cols), hide_index=True)

            if st.button("Confirm & Sign Up For This Schedule"):
                sheet_to_update = sheet_map[current_sheet_name]
                flights_to_update = st.session_state.suggested_schedule['Flight Num'].tolist()
                
                # Find the row numbers for each flight in the Google Sheet
                all_flight_nums = sheet_to_update.col_values(df.columns.get_loc("Flight Num") + 1)
                
                with st.spinner("Updating Google Sheet..."):
                    for flight_num in flights_to_update:
                        try:
                            # +1 for header, +1 for 1-based index
                            row_index = all_flight_nums.index(flight_num) + 1
                            # +1 for 1-based index
                            observer_col_index = df.columns.get_loc("Observers") + 1
                            
                            # Update the cell
                            sheet_to_update.update_cell(row_index, observer_col_index, name)
                        except ValueError:
                            st.warning(f"Could not find flight {flight_num} to update.")
                
                st.success(f"{name}, you have been signed up for {len(flights_to_update)} flights!")
                st.session_state.suggested_schedule = None # Clear suggestion
                st.cache_data.clear() # Clear cache to refetch data
                st.rerun()

# ==============================================================================
# --- MODE 3: MANUAL SIGN-UP (Your existing logic) ---
# ==============================================================================
elif st.session_state.mode == "signup":
    st.subheader("Manual Flight Sign-up")
    # This section contains your existing manual sign-up logic.
    # It has been kept as is for users who prefer to sign up for flights one by one.
    df = get_sheet_data(current_sheet_name)
    if df is not None:
        name = st.text_input("Enter your name:", key="manual_name")
        if name:
            for i, row in df.iterrows():
                flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {row['SCHED DEP']} → {row['ARR']}"
                if st.button(flight_label, key=f"manual_{i}"):
                    # Logic to update the sheet for a single flight
                    observer_col_index = df.columns.get_loc("Observers") + 1
                    current_observers = row['Observers']
                    new_observers = f"{current_observers}, {name}" if current_observers else name
                    sheet_map[current_sheet_name].update_cell(i + 2, observer_col_index, new_observers)
                    st.success(f"Signed up for {flight_label}!")
                    st.cache_data.clear()
                    st.rerun()

# ==============================================================================
# --- MODE 4: TRACKER (Your existing logic) ---
# ==============================================================================
elif st.session_state.mode == "tracker":
    st.subheader("Observer Sign-Up Tracker")
    # This section contains your existing tracker logic.
    # It has been kept as is.
    GOAL_PER_CATEGORY = 10
    summary_data = []
    for sheet_name, sheet in sheet_map.items():
        try:
            records = sheet.get_all_records()
            df_sheet = pd.DataFrame(records)
            if "Observers" in df_sheet.columns and "Fleet Type Grouped" in df_sheet.columns:
                for _, row in df_sheet.iterrows():
                    num_signups = len(row["Observers"].split(",")) if row["Observers"] else 0
                    category = str(row["Fleet Type Grouped"]).strip().lower()
                    if category in {"widebody", "narrowbody", "express"}:
                        summary_data.append({"Day": sheet_name, "Category": category, "Signups": num_signups})
        except Exception as e:
            st.warning(f"Could not process sheet {sheet_name}: {e}")
    
    if summary_data:
        df_summary = pd.DataFrame(summary_data)
        chart_data = df_summary.pivot_table(index="Day", columns="Category", values="Signups", aggfunc="sum", fill_value=0)
        st.markdown("### Signups by Day and Category")
        st.dataframe(chart_data)

        total_by_category = chart_data.sum()
        st.markdown("### Total Progress Toward Goals")
        for category in ["widebody", "narrowbody", "express"]:
            count = total_by_category.get(category, 0)
            progress = min(count / GOAL_PER_CATEGORY, 1.0)
            st.progress(progress, text=f"{category.capitalize()}: {int(count)}/{GOAL_PER_CATEGORY}")

