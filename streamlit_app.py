import streamlit as st
import pandas as pd
import gspread
from datetime import datetime, timedelta, time
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
        def parse_and_combine_time(time_str):
            """Safely parse time strings and combine with today's date."""
            if not time_str or pd.isna(time_str):
                return pd.NaT
            try:
                # Handle both '9:25' and '9:25 AM' formats
                time_obj = pd.to_datetime(str(time_str), errors='coerce').time()
                if pd.notna(time_obj):
                    return datetime.combine(datetime.today().date(), time_obj)
                return pd.NaT
            except (ValueError, TypeError):
                return pd.NaT

        for col in ['Est. Boarding Start', 'Est. Boarding End', 'SCHED DEP']:
            df[col] = df[col].apply(parse_and_combine_time)

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
        # FIX: Use a full timezone-aware datetime object for comparison
        now_datetime = datetime.now(central_tz).replace(tzinfo=None) # Make naive to compare with df
        
        # Filter out rows with invalid boarding start times before comparison
        valid_times_df = df.dropna(subset=['Est. Boarding Start'])
        upcoming_df = valid_times_df[valid_times_df["Est. Boarding Start"] >= now_datetime].copy()

        if not upcoming_df.empty:
            cols_to_display = {
                "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End",
                "PAX TOTAL": "Pax", "Important flight?": "Important", "Observers": "Observers"
            }
            display_df = upcoming_df.copy()
            # Format time columns for display
            display_df['Board Start'] = display_df['Est. Boarding Start'].dt.strftime('%-I:%M %p')
            display_df['Board End'] = display_df['Est. Boarding End'].dt.strftime('%-I:%M %p')

            # Select and rename columns for the final display
            final_display_df = display_df[list(cols_to_display.keys())].rename(columns=cols_to_display)
            st.dataframe(final_display_df, hide_index=True, use_container_width=True)
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
        # FIX: Use datetime.time objects for time_input values
        start_time_input = c1.time_input("Enter your start time:", value=time(9, 0))
        end_time_input = c2.time_input("Enter your end time:", value=time(17, 0))

        if st.button("Suggest My Schedule"):
            if not name:
                st.warning("Please enter your name.")
            else:
                # --- Python Scheduler Logic ---
                flights_df = df.copy()
                flights_df = flights_df[flights_df['Has Equipment'] == 'Yes']
                
                start_datetime = datetime.combine(today_date.date(), start_time_input)
                end_datetime = datetime.combine(today_date.date(), end_time_input)

                available_flights = flights_df[
                    (flights_df['Est. Boarding Start'].notna()) &
                    (flights_df['Est. Boarding End'].notna()) &
                    (flights_df['Est. Boarding Start'] >= start_datetime) &
                    (flights_df['Est. Boarding End'] <= end_datetime) &
                    (flights_df['Observers'] == '')
                ].copy()

                available_flights['importance_score'] = available_flights['Important flight?'].apply(lambda x: 0 if x == 'Yes' else 1)
                available_flights = available_flights.sort_values(by=['importance_score', 'Est. Boarding Start'])
                
                schedule = []
                for index, flight in available_flights.iterrows():
                    is_conflict = False
                    for scheduled_flight in schedule:
                        buffer_start = scheduled_flight['Est. Boarding Start'] - timedelta(minutes=10)
                        buffer_end = scheduled_flight['Est. Boarding End'] + timedelta(minutes=10)
                        if not (flight['Est. Boarding End'] < buffer_start or flight['Est. Boarding Start'] > buffer_end):
                            is_conflict = True
                            break
                    if not is_conflict:
                        schedule.append(flight)

                st.session_state.suggested_schedule = pd.DataFrame(schedule) if schedule else pd.DataFrame()

        if st.session_state.suggested_schedule is not None:
            if not st.session_state.suggested_schedule.empty:
                st.markdown("---")
                st.success("Here is your suggested schedule:")
                
                display_df = st.session_state.suggested_schedule.copy()
                display_cols = {
                    "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                    "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End"
                }
                display_df['Board Start'] = display_df['Est. Boarding Start'].dt.strftime('%-I:%M %p')
                display_df['Board End'] = display_df['Est. Boarding End'].dt.strftime('%-I:%M %p')

                final_display_df = display_df[list(display_cols.keys())].rename(columns=display_cols)
                st.dataframe(final_display_df, hide_index=True)

                if st.button("Confirm & Sign Up For This Schedule"):
                    sheet_to_update = sheet_map[current_sheet_name]
                    flights_to_update = st.session_state.suggested_schedule['Flight Num'].tolist()
                    
                    all_flight_nums = sheet_to_update.col_values(df.columns.get_loc("Flight Num") + 1)
                    
                    with st.spinner("Updating Google Sheet..."):
                        for flight_num in flights_to_update:
                            try:
                                # Find the correct row index in the live sheet
                                row_index = all_flight_nums.index(flight_num) + 1
                                observer_col_index = df.columns.get_loc("Observers") + 1
                                sheet_to_update.update_cell(row_index, observer_col_index, name)
                            except ValueError:
                                st.warning(f"Could not find flight {flight_num} to update.")
                    
                    st.success(f"{name}, you have been signed up for {len(flights_to_update)} flights!")
                    st.session_state.suggested_schedule = None
                    st.cache_data.clear()
                    st.rerun()
            else:
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
                sched_dep_str = row['SCHED DEP'].strftime('%-I:%M %p') if pd.notna(row['SCHED DEP']) else "N/A"
                flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {sched_dep_str} → {row['ARR']}"
                
                if st.button(flight_label, key=f"manual_{i}"):
                    observer_col_index = df.columns.get_loc("Observers") + 1
                    # FIX: Robustly handle adding names to the observer list
                    current_observers_str = str(row['Observers'])
                    observers_list = [obs.strip() for obs in current_observers_str.split(',') if obs.strip() and obs.strip().lower() != 'nan']

                    if name not in observers_list:
                        observers_list.append(name)
                        new_observers = ", ".join(observers_list)
                        sheet_map[current_sheet_name].update_cell(i + 2, observer_col_index, new_observers)
                        st.success(f"Signed up for {flight_label}!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.warning(f"You are already signed up for {flight_label}.")

# ==============================================================================
# --- MODE 4: TRACKER (Your existing logic) ---
# ==============================================================================
elif st.session_state.mode == "tracker":
    st.subheader("Observer Sign-Up Tracker")
    GOAL_PER_CATEGORY = 10
    summary_data = []
    for sheet_name in sheet_map.keys():
        df_sheet = get_sheet_data(sheet_name)
        if df_sheet is not None and "Observers" in df_sheet.columns and "Fleet Type Grouped" in df_sheet.columns:
            for _, row in df_sheet.iterrows():
                # FIX: Robustly count observers
                observers_str = str(row["Observers"])
                num_signups = len([obs for obs in observers_str.split(",") if obs.strip() and obs.strip().lower() != 'nan'])
                category = str(row["Fleet Type Grouped"]).strip().lower()
                if category in {"widebody", "narrowbody", "express"}:
                    summary_data.append({"Day": sheet_name, "Category": category, "Signups": num_signups})
    
    if summary_data:
        df_summary = pd.DataFrame(summary_data)
        chart_data = df_summary.pivot_table(index="Day", columns="Category", values="Signups", aggfunc="sum", fill_value=0)
        st.markdown("### Signups by Day and Category")
        st.dataframe(chart_data)

        total_by_category = chart_data.sum()
        st.markdown("### Total Progress Toward Goals")
        for category in ["widebody", "narrowbody", "express"}:
            count = total_by_category.get(category, 0)
            progress = min(count / GOAL_PER_CATEGORY, 1.0)
            st.progress(progress, text=f"{category.capitalize()}: {int(count)}/{GOAL_PER_CATEGORY}")
