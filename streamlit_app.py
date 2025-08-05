import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time, timedelta
import pytz

# --- Page Configuration ---
st.set_page_config(page_title="Flight Observer", layout="wide")
st.title("IAH Flight Observation Tool")

# --- Constants and Timezone ---
CENTRAL_TZ = pytz.timezone("America/Chicago")
SHEET_URL = "https://docs.google.com/spreadsheets/d/109xeylSzvDEMTRjqYTllbzj3nElbfVCTSzZxfn4caBQ/edit?usp=sharing"

# --- Authorization & Data Loading (Cached) ---
@st.cache_resource(ttl=600)
def authorize_gspread():
    """Authorize Google Sheets API using Streamlit Secrets."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["google_service_account"], scopes=scope
    )
    return gspread.authorize(creds)

@st.cache_data(ttl=300)
def get_sheet_data(_gc, sheet_name):
    """
    Fetch and process data for a given sheet name.
    The '_gc' parameter is included to ensure this function reruns when the connection object changes.
    """
    # Initialize data to an empty list to prevent NameError if get_all_records fails
    data = [] 
    try:
        master_sheet = _gc.open_by_url(SHEET_URL)
        sheet = master_sheet.worksheet(sheet_name)
        data = sheet.get_all_records() # This will reassign data if successful
        
        if not data:
            st.warning(f"Sheet '{sheet_name}' is empty.")
            return pd.DataFrame()
        
        df = pd.DataFrame(data)

        # --- Data Cleaning and Type Conversion ---
        def parse_and_localize_time(time_str):
            """Safely parse time strings and combine with today's date, making it timezone-aware."""
            if not time_str or pd.isna(time_str):
                return pd.NaT
            try:
                # Combine today's date (in the correct timezone) with the time from the sheet
                time_obj = pd.to_datetime(str(time_str), errors='coerce').time()
                if pd.notna(time_obj):
                    today_date = datetime.now(CENTRAL_TZ).date()
                    naive_datetime = datetime.combine(today_date, time_obj)
                    # Localize the naive datetime to our target timezone
                    return CENTRAL_TZ.localize(naive_datetime)
                return pd.NaT
            except (ValueError, TypeError):
                return pd.NaT

        # Apply time parsing to relevant columns
        for col in ['Est. Boarding Start', 'Est. Boarding End', 'SCHED DEP']:
            if col in df.columns:
                df[col] = df[col].apply(parse_and_localize_time)

        # Ensure other columns have the correct type
        for col in ['Flight Num', 'Observers', 'Fleet Type Grouped']:
             if col in df.columns:
                 df[col] = df[col].astype(str)

        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Sheet named '{sheet_name}' not found. Please ensure a sheet for today's day of the week exists (e.g., 'Tuesday').")
        return None
    except Exception as e:
        st.error(f"An error occurred while processing sheet '{sheet_name}': {e}")
        return None

# --- Main App Logic ---
try:
    gc = authorize_gspread()
    master_sheet = gc.open_by_url(SHEET_URL)
    all_sheets = master_sheet.worksheets()
    sheet_map = {sheet.title: sheet for sheet in all_sheets}
    
    # Define the days of the week for the tabs
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # --- Session State Initialization ---
    if "mode" not in st.session_state:
        st.session_state.mode = "today"
    if "suggested_schedule" not in st.session_state:
        st.session_state.suggested_schedule = None

    # --- UI: Mode Selection Buttons ---
    col1, col2, col3, col4 = st.columns(4)
    if col1.button("Today's Flights", use_container_width=True):
        st.session_state.mode = "today"
    if col2.button("Suggest My Schedule", use_container_width=True):
        st.session_state.mode = "suggest"
    if col3.button("Manual Sign-up", use_container_width=True):
        st.session_state.mode = "signup"
    if col4.button("View Tracker", use_container_width=True):
        st.session_state.mode = "tracker"

    # --- Dynamic Sheet Name Logic ---
    today_date = datetime.now(CENTRAL_TZ)
    current_day_sheet_name = today_date.strftime("%A")
    display_date = today_date.strftime("%A, %B %d")

    # ==============================================================================
    # --- MODE 1: TODAY'S FLIGHTS (Read-Only View) ---
    # ==============================================================================
    if st.session_state.mode == "today":
        st.subheader(f"Upcoming Flights for {display_date}")
        
        # Create tabs for each day of the week
        tabs = st.tabs(day_names)

        # Loop through tabs and display data for the corresponding day
        for i, day in enumerate(day_names):
            with tabs[i]:
                df = get_sheet_data(gc, day)
                if df is not None and not df.empty:
                    now_datetime = datetime.now(CENTRAL_TZ)
                    valid_times_df = df.dropna(subset=['Est. Boarding Start'])
                    
                    # Filter for upcoming flights only on the current day's tab
                    if day == current_day_sheet_name:
                         upcoming_df = valid_times_df[valid_times_df["Est. Boarding Start"] >= now_datetime].copy()
                    else:
                         upcoming_df = valid_times_df.copy()
                         
                    if not upcoming_df.empty:
                        cols_to_display = {
                            "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                            "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End",
                            "PAX TOTAL": "Pax", "Important flight?": "Important", "Observers": "Observers"
                        }
                        final_display_df = upcoming_df[list(cols_to_display.keys())].rename(columns=cols_to_display)
                        
                        final_display_df['Board Start'] = pd.to_datetime(final_display_df['Board Start']).dt.strftime('%-I:%M %p')
                        final_display_df['Board End'] = pd.to_datetime(final_display_df['Board End']).dt.strftime('%-I:%M %p')

                        st.dataframe(final_display_df, hide_index=True, use_container_width=True)
                    else:
                        st.info("No more upcoming flights for this day.")
                else:
                    st.info(f"No flight data available for {day}.")

    # ==============================================================================
    # --- MODE 2: SUGGEST MY SCHEDULE ---
    # ==============================================================================
    elif st.session_state.mode == "suggest":
        st.subheader("Get an Optimized Schedule Suggestion")
        df = get_sheet_data(gc, current_day_sheet_name)
        
        if df is not None and not df.empty:
            name = st.text_input("Enter your name:", key="suggest_name")
            c1, c2 = st.columns(2)
            start_time_input = c1.time_input("Enter your start time:", value=time(9, 0))
            end_time_input = c2.time_input("Enter your end time:", value=time(17, 0))

            if st.button("Suggest My Schedule", use_container_width=True):
                if not name.strip():
                    st.warning("Please enter your name.")
                else:
                    flights_df = df.copy()
                    flights_df = flights_df[(flights_df['Has Equipment'] == 'Yes') & (flights_df['Observers'] == '')]
                    
                    start_datetime = CENTRAL_TZ.localize(datetime.combine(today_date.date(), start_time_input))
                    end_datetime = CENTRAL_TZ.localize(datetime.combine(today_date.date(), end_time_input))

                    available_flights = flights_df[
                        (flights_df['Est. Boarding Start'].notna()) &
                        (flights_df['Est. Boarding End'].notna()) &
                        (flights_df['Est. Boarding Start'] >= start_datetime) &
                        (flights_df['Est. Boarding End'] <= end_datetime)
                    ].copy()

                    available_flights['importance_score'] = available_flights['Important flight?'].apply(lambda x: 0 if x == 'Yes' else 1)
                    available_flights = available_flights.sort_values(by=['importance_score', 'Est. Boarding Start'])

                    schedule = []
                    last_flight_end = datetime.min.replace(tzinfo=CENTRAL_TZ)
                    for _, flight in available_flights.iterrows():
                        flight_start = flight['Est. Boarding Start']
                        if flight_start >= last_flight_end:
                            schedule.append(flight)
                            last_flight_end = flight['Est. Boarding End'] + timedelta(minutes=10)

                    st.session_state.suggested_schedule = pd.DataFrame(schedule) if schedule else pd.DataFrame()

            if st.session_state.suggested_schedule is not None:
                if not st.session_state.suggested_schedule.empty:
                    st.markdown("---")
                    st.success("Here is your suggested schedule:")
                    
                    display_cols = {
                        "DEP GATE": "Gate", "Flight Num": "Flight", "ARR": "Dest",
                        "Est. Boarding Start": "Board Start", "Est. Boarding End": "Board End"
                    }
                    final_display_df = st.session_state.suggested_schedule[list(display_cols.keys())].rename(columns=display_cols)

                    final_display_df['Board Start'] = pd.to_datetime(final_display_df['Board Start']).dt.strftime('%-I:%M %p')
                    final_display_df['Board End'] = pd.to_datetime(final_display_df['Board End']).dt.strftime('%-I:%M %p')

                    st.dataframe(final_display_df, hide_index=True, use_container_width=True)

                    if st.button("Confirm & Sign Up For This Schedule", use_container_width=True):
                        with st.spinner("Updating Google Sheet..."):
                            sheet_to_update = sheet_map[current_day_sheet_name]
                            flights_to_update = st.session_state.suggested_schedule['Flight Num'].tolist()
                            all_flight_nums = sheet_to_update.col_values(df.columns.get_loc("Flight Num") + 1)
                            observer_col_index = df.columns.get_loc("Observers") + 1
                            
                            cells_to_update = []
                            for flight_num in flights_to_update:
                                try:
                                    row_index = all_flight_nums.index(str(flight_num)) + 1
                                    cells_to_update.append(gspread.Cell(row_index, observer_col_index, name.strip()))
                                except ValueError:
                                    st.warning(f"Could not find flight {flight_num} to update.")
                            
                            if cells_to_update:
                                sheet_to_update.update_cells(cells_to_update)
                                st.success(f"{name.strip()}, you have been signed up for {len(cells_to_update)} flights!")
                            
                            st.session_state.suggested_schedule = None
                            st.cache_data.clear()
                            st.rerun()
                else:
                    st.info("No available flights match your criteria.")

    # ==============================================================================
    # --- MODE 3: MANUAL SIGN-UP ---
    # ==============================================================================
    elif st.session_state.mode == "signup":
        st.subheader("Manual Flight Sign-up")
        # Create tabs for each day of the week
        tabs = st.tabs(day_names)
        
        name = st.text_input("Enter your name:", key="manual_name")

        for i, day in enumerate(day_names):
            with tabs[i]:
                if name.strip():
                    df = get_sheet_data(gc, day)
                    if df is not None and not df.empty:
                        sheet_to_update = sheet_map[day]
                        flight_num_col_idx = df.columns.get_loc("Flight Num") + 1
                        observer_col_idx = df.columns.get_loc("Observers") + 1
                        live_flight_nums = sheet_to_update.col_values(flight_num_col_idx)

                        for j, row in df.iterrows():
                            sched_dep_str = row['SCHED DEP'].strftime('%-I:%M %p') if pd.notna(row['SCHED DEP']) else "N/A"
                            flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {sched_dep_str} → {row['ARR']} | Observers: {row['Observers']}"
                            flight_num_to_update = str(row['Flight Num'])

                            if st.button(flight_label, key=f"manual_{day}_{flight_num_to_update}_{j}"):
                                try:
                                    sheet_row = live_flight_nums.index(flight_num_to_update) + 1
                                    current_observers_str = sheet_to_update.cell(sheet_row, observer_col_idx).value or ""
                                    observers_list = [obs.strip() for obs in current_observers_str.split(',') if obs.strip()]

                                    if name.strip() not in observers_list:
                                        observers_list.append(name.strip())
                                        new_observers = ", ".join(observers_list)
                                        sheet_to_update.update_cell(sheet_row, observer_col_idx, new_observers)
                                        st.success(f"Signed up for flight {row['CARR (IATA)']} {row['FLIGHT OUT']} on {day}!")
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.warning(f"You are already signed up for this flight on {day}.")
                                except ValueError:
                                    st.error(f"Could not find flight {flight_num_to_update} in the sheet for {day}. It may have been changed. Please refresh.")
                                except Exception as e:
                                    st.error(f"An error occurred: {e}")
                    else:
                        st.info(f"No flight data available for {day}.")
                else:
                    st.warning("Please enter your name to sign up for flights.")

    # ==============================================================================
    # --- MODE 4: TRACKER ---
    # ==============================================================================
    elif st.session_state.mode == "tracker":
        st.subheader("Observer Sign-Up Tracker")
        GOAL_PER_CATEGORY = 10
        summary_data = []
        
        relevant_sheet_names = [s.title for s in all_sheets] 
        
        for sheet_name in relevant_sheet_names:
            df_sheet = get_sheet_data(gc, sheet_name)
            if df_sheet is not None and not df_sheet.empty and "Observers" in df_sheet.columns and "Fleet Type Grouped" in df_sheet.columns:
                df_sheet.dropna(subset=["Observers", "Fleet Type Grouped"], inplace=True)
                for _, row in df_sheet.iterrows():
                    observers_str = str(row["Observers"])
                    num_signups = len([obs for obs in observers_str.split(",") if obs.strip()])
                    category = str(row["Fleet Type Grouped"]).strip().lower()
                    if category in {"widebody", "narrowbody", "express"}:
                        summary_data.append({"Day": sheet_name, "Category": category, "Signups": num_signups})
        
        if summary_data:
            df_summary = pd.DataFrame(summary_data)
            chart_data = df_summary.pivot_table(index="Day", columns="Category", values="Signups", aggfunc="sum", fill_value=0)
            
            st.markdown("### Signups by Day and Category")
            st.dataframe(chart_data, use_container_width=True)

            total_by_category = chart_data.sum()
            st.markdown("### Total Progress Toward Goals")
            for category in ["widebody", "narrowbody", "express"]:
                count = total_by_category.get(category, 0)
                progress = min(count / GOAL_PER_CATEGORY, 1.0) if GOAL_PER_CATEGORY > 0 else 0
                st.progress(progress, text=f"{category.capitalize()}: {int(count)} / {GOAL_PER_CATEGORY}")
        else:
            st.info("No tracking data available yet.")

except Exception as e:
    st.error(f"A critical error occurred: {e}")
    st.info("Please check your Google Sheet permissions and ensure the sheet format is correct.")
