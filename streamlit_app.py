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
        for col in ['Est. Boarding Start', 'Est. Boarding End', 'SCHED DEP']:
             # Combine a fixed date with the time to create a full datetime object for calculations
            df[col] = df[col].apply(lambda x: datetime.combine(datetime.today(), pd.to_datetime(x, format='%H:%M', errors='coerce').time()) if pd.notna(x) else pd.NaT)

        df['Flight Num'] = df['Flight Num'].astype(str)
        df['Observers'] = df['Observers'].astype(str)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Sheet named '{sheet_name}' not found. Please make sure today's flight data has been uploaded.")
        return None
    except Exception as e:
        st.error(f"An error occurred while processing sheet '{sheet_name}': {e}")
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
        now_time = datetime.now(central_tz)
        # Compare entire datetime objects
        upcoming_df = df[df["Est. Boarding Start"] >= now_time].copy()

        if not upcoming_df.empty:
            cols_to_display = {
                "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End",
                "PAX TOTAL": "Pax", "Important flight?": "Important", "Observers": "Observers"
            }
            display_df = upcoming_df.copy()
            # Format time columns for display
            display_df['Board Start'] = display_df['Est. Boarding Start'].dt.strftime('%I:%M %p')
            display_df['Board End'] = display_df['Est. Boarding End'].dt.strftime('%I:%M %p')

            display_df = display_df[list(cols_to_display.keys())].rename(columns=cols_to_display)
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
        start_time_input = c1.time_input("Enter your start time:", value=datetime.strptime("09:00", "%H:%M").time())
        end_time_input = c2.time_input("Enter your end time:", value=datetime.strptime("17:00", "%H:%M").time())

        if st.button("Suggest My Schedule"):
            if not name:
                st.warning("Please enter your name.")
            else:
                # --- Python Scheduler Logic ---
                flights_df = df.copy()
                flights_df = flights_df[flights_df['Has Equipment'] == 'Yes']
                
                start_datetime = datetime.combine(datetime.today(), start_time_input)
                end_datetime = datetime.combine(datetime.today(), end_time_input)

                available_flights = flights_df[
                    (flights_df['Est. Boarding Start'] >= start_datetime) &
                    (flights_df['Est. Boarding End'] <= end_datetime) &
                    (flights_df['Observers'] == '')
                ].copy()

                # Score and sort all available flights first
                available_flights['importance_score'] = available_flights['Important flight?'].apply(lambda x: 0 if x == 'Yes' else 1)
                available_flights = available_flights.sort_values(by=['importance_score', 'Est. Boarding Start'])
                
                schedule = []
                
                for index, flight in available_flights.iterrows():
                    is_conflict = False
                    for scheduled_flight in schedule:
                        # Check for time conflict with 10-minute buffer
                        buffer_start = scheduled_flight['Est. Boarding Start'] - timedelta(minutes=10)
                        buffer_end = scheduled_flight['Est. Boarding End'] + timedelta(minutes=10)
                        if not (flight['Est. Boarding End'] < buffer_start or flight['Est. Boarding Start'] > buffer_end):
                            is_conflict = True
                            break
                    if not is_conflict:
                        schedule.append(flight)

                st.session_state.suggested_schedule = pd.DataFrame(schedule) if schedule else None

        if st.session_state.suggested_schedule is not None and not st.session_state.suggested_schedule.empty:
            st.markdown("---")
            st.success("Here is your suggested schedule:")
            
            display_df = st.session_state.suggested_schedule.copy()
            display_cols = {
                "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End"
            }
            # Format time columns for display
            display_df['Board Start'] = display_df['Est. Boarding Start'].dt.strftime('%I:%M %p')
            display_df['Board End'] = display_df['Est. Boarding End'].dt.strftime('%I:%M %p')

            st.dataframe(display_df[list(display_cols.keys())].rename(columns=display_cols), hide_index=True)


            if st.button("Confirm & Sign Up For This Schedule"):
                sheet_to_update = sheet_map[current_sheet_name]
                flights_to_update = st.session_state.suggested_schedule['Flight Num'].tolist()
                
                all_flight_nums = sheet_to_update.col_values(df.columns.get_loc("Flight Num") + 1)
                
                with st.spinner("Updating Google Sheet..."):
                    for flight_num in flights_to_update:
                        try:
                            row_index = all_flight_nums.index(flight_num) + 1
                            observer_col_index = df.columns.get_loc("Observers") + 1
                            sheet_to_update.update_cell(row_index, observer_col_index, name)
                        except ValueError:
                            st.warning(f"Could not find flight {flight_num} to update.")
                
                st.success(f"{name}, you have been signed up for {len(flights_to_update)} flights!")
                st.session_state.suggested_schedule = None
                st.cache_data.clear()
                st.rerun()
        elif st.session_state.suggested_schedule is not None:
             st.info("No available flights match your criteria.")


# ==============================================================================
# --- MODE 3: MANUAL SIGN-UP (Your existing logic) ---
# ==============================================================================
elif st.session_state.mode == "signup":
    st.subheader("Manual Flight Sign-up")
    df = get_sheet_data(current_sheet_name)
    if df is not None:
        name = st.text_input("Enter your name:", key="manual_name")
        if name:
            for i, row in df.iterrows():
                # Format time for display
                sched_dep_str = row['SCHED DEP'].strftime('%I:%M %p') if pd.notna(row['SCHED DEP']) else "N/A"
                flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {sched_dep_str} → {row['ARR']}"
                if st.button(flight_label, key=f"manual_{i}"):
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
    st.subhea
