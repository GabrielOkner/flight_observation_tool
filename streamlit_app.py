import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time, timedelta, date # Import date
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
            # For 'Scheduler' sheet, empty data is an alert, not a warning for all sheets
            if sheet_name != 'Scheduler':
                st.warning(f"Sheet '{sheet_name}' is empty.")
            return pd.DataFrame()
        
        df = pd.DataFrame(data)

        # --- FIX: Strip whitespace from all column names ---
        df.columns = df.columns.str.strip()

        # --- Data Cleaning and Type Conversion ---
        def parse_and_localize_time(time_str, is_observer_time=False):
            """Safely parse time strings and combine with today's date, making it timezone-aware."""
            if not time_str or pd.isna(time_str):
                return pd.NaT
            try:
                time_obj = pd.to_datetime(str(time_str), errors='coerce').time()
                if pd.notna(time_obj):
                    # For observer times, use a fixed date (e.g., today's date) to combine with time
                    # For flight times, the date component isn't strictly used for comparison, only time
                    today_date_for_combine = datetime.now(CENTRAL_TZ).date()
                    naive_datetime = datetime.combine(today_date_for_combine, time_obj)
                    return CENTRAL_TZ.localize(naive_datetime)
                return pd.NaT
            except (ValueError, TypeError):
                return pd.NaT

        # Apply time parsing to relevant columns
        if sheet_name != 'Scheduler': # Flight data sheets
            for col in ['Est. Boarding Start', 'Est. Boarding End', 'SCHED DEP']:
                if col in df.columns:
                    df[col] = df[col].apply(parse_and_localize_time)
            
            # Calculate busyStart and busyEnd for flights
            if 'Est. Boarding Start' in df.columns and 'Est. Boarding End' in df.columns:
                df['busyStart'] = df['Est. Boarding Start'] - timedelta(minutes=10)
                df['busyEnd'] = df['Est. Boarding End'] + timedelta(minutes=10)

        else: # 'Scheduler' sheet
            for col in ['Start Time', 'End Time']:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: parse_and_localize_time(x, is_observer_time=True))


        # Ensure other columns have the correct type
        # Added 'MANDATORY OBSERVER' for flight data
        cols_to_str = ['FLIGHT OUT', 'Observers', 'Fleet Type Grouped']
        if sheet_name != 'Scheduler' and 'MANDATORY OBSERVER' in df.columns:
            cols_to_str.append('MANDATORY OBSERVER')

        for col in cols_to_str:
             if col in df.columns:
                 df[col] = df[col].astype(str)

        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Sheet named '{sheet_name}' not found. Please ensure a sheet for today's day of the week exists (e.g., 'Tuesday').")
        return None
    except Exception as e:
        st.error(f"An error occurred while processing sheet '{sheet_name}': {e}")
        return None

# --- Helper function for gate parsing (Python adaptation) ---
def parse_gate(gate):
    """Parses a gate string into its concourse and number components."""
    if not isinstance(gate, str) or len(gate) == 0:
        return {'concourse': None, 'number': float('inf')}
    
    concourse = gate.strip().upper()[0] if gate.strip() else None
    number_match = ''.join(filter(str.isdigit, gate))
    number = int(number_match) if number_match else float('inf')
    return {'concourse': concourse, 'number': number}

# --- Main App Logic ---
try:
    gc = authorize_gspread()
    master_sheet = gc.open_by_url(SHEET_URL)
    all_sheets = master_sheet.worksheets()
    sheet_map = {sheet.title: sheet for sheet in all_sheets}
    
    # Define the days of the week for the dropdown (only Monday, Tuesday, Wednesday)
    available_days_for_selection = ["Monday", "Tuesday", "Wednesday"]
    
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
        # Determine the display names for the selectbox, with "Today" for the current day
        display_options = []
        default_index = 0 # Default to Monday's index if current day not in available_days_for_selection
        for i, day in enumerate(available_days_for_selection):
            if day == current_day_sheet_name:
                display_options.append("Today")
                default_index = i # Set default index to "Today"
            else:
                display_options.append(day)

        # Create the selectbox for day selection
        selected_display_name = st.selectbox(
            "Select a Day:",
            options=display_options,
            index=default_index, # Set the default selected option
            key="day_selector_today_mode"
        )

        # Map the selected display name back to the actual sheet name
        actual_sheet_name = current_day_sheet_name if selected_display_name == "Today" else selected_display_name
        
        st.subheader(f"Flights for {selected_display_name}") 
        df = get_sheet_data(gc, actual_sheet_name)
        if df is not None and not df.empty:
            valid_times_df = df.dropna(subset=['Est. Boarding Start'])
            
            if actual_sheet_name == current_day_sheet_name:
                now_datetime = datetime.now(CENTRAL_TZ)
                display_df = valid_times_df[valid_times_df["Est. Boarding Start"] >= now_datetime].copy()
            else:
                display_df = valid_times_df.copy()
                 
            if not display_df.empty:
                cols_to_display = {
                    "DEP GATE": "Gate", 
                    "FLIGHT OUT": "Flight", 
                    "ARR": "Dest",
                    "SCHED DEP": "ETD (Sched Dep)", 
                    "Est. Boarding Start": "Board Start", 
                    "Est. Boarding End": "Board End",
                    "PAX TOTAL": "Pax", 
                    "Important flight?": "Important", 
                    "Observers": "Observers"
                }
                
                actual_cols_to_display = {k: v for k, v in cols_to_display.items() if k in display_df.columns}
                
                final_display_df = display_df[list(actual_cols_to_display.keys())].rename(columns=actual_cols_to_display)
                
                if 'Board Start' in final_display_df.columns:
                    final_display_df['Board Start'] = pd.to_datetime(final_display_df['Board Start']).dt.strftime('%-I:%M %p')
                if 'Board End' in final_display_df.columns:
                    final_display_df['Board End'] = pd.to_datetime(final_display_df['Board End']).dt.strftime('%-I:%M %p')
                if 'ETD (Sched Dep)' in final_display_df.columns: 
                    final_display_df['ETD (Sched Dep)'] = pd.to_datetime(final_display_df['ETD (Sched Dep)']).dt.strftime('%-I:%M %p')

                st.dataframe(final_display_df, hide_index=True, use_container_width=True)
            else:
                st.info(f"No flights to display for {actual_sheet_name} based on criteria.")
        else:
            st.info(f"No flight data available for {actual_sheet_name}.")

    # ==============================================================================
    # --- MODE 2: SUGGEST MY SCHEDULE ---
    # ==============================================================================
    elif st.session_state.mode == "suggest":
        st.subheader("Get an Optimized Schedule Suggestion")
        df = get_sheet_data(gc, current_day_sheet_name) # Get today's flight data

        if df is not None and not df.empty:
            # Generate time options for the sliders (7 AM to 11 PM, 30-min intervals)
            # Store time objects directly, and let st.slider handle default formatting
            time_options_time_only = []
            for hour in range(7, 24): # 7 AM to 11 PM
                time_options_time_only.append(time(hour, 0))
                if hour < 23: # Add 30-minute intervals, but not past 11:00 PM
                    time_options_time_only.append(time(hour, 30))

            # Find indices for default 9:00 AM and 5:00 PM
            default_start_time = time(9, 0)
            default_end_time = time(17, 0)

            start_index = 0
            if default_start_time in time_options_time_only:
                start_index = time_options_time_only.index(default_start_time)

            end_index = len(time_options_time_only) - 1
            if default_end_time in time_options_time_only:
                end_index = time_options_time_only.index(default_end_time)

            c1, c2 = st.columns(2)
            user_start_time = c1.slider(
                "Enter your start time:",
                min_value=time_options_time_only[0],
                max_value=time_options_time_only[-1],
                value=time_options_time_only[start_index],
                # Removed format_func as it's not supported in older Streamlit versions
                # The slider will use the default string representation of datetime.time objects
                key="suggest_start_time_slider"
            )
            user_end_time = c2.slider(
                "Enter your end time:",
                min_value=time_options_time_only[0],
                max_value=time_options_time_only[-1],
                value=time_options_time_only[end_index],
                # Removed format_func as it's not supported in older Streamlit versions
                # The slider will use the default string representation of datetime.time objects
                key="suggest_end_time_slider"
            )
            
            # Using a unique key for the button to resolve the error
            if st.button("Suggest My Schedule", use_container_width=True, key="suggest_schedule_button"):
                with st.spinner("Generating suggested schedule..."):
                    # Prepare all flights for the day (ignore existing observers for suggestion)
                    all_flights_for_scheduling = df[
                        (df['Has Equipment'] == 'Yes') &
                        (df['Est. Boarding Start'].notna()) &
                        (df['Est. Boarding End'].notna())
                    ].copy()

                    # Convert 'Important flight?' to boolean
                    if 'Important flight?' in all_flights_for_scheduling.columns:
                        all_flights_for_scheduling['isImportant'] = all_flights_for_scheduling['Important flight?'].apply(lambda x: str(x).strip().lower() == 'yes')
                    else:
                        all_flights_for_scheduling['isImportant'] = False
                        st.warning("Warning: 'Important flight?' column not found in flight data. All flights treated as not important for scheduling.")

                    # Calculate busyStart and busyEnd for flights
                    all_flights_for_scheduling['busyStart'] = all_flights_for_scheduling['Est. Boarding Start'] - timedelta(minutes=10)
                    all_flights_for_scheduling['busyEnd'] = all_flights_for_scheduling['Est. Boarding End'] + timedelta(minutes=10)

                    # Create a single "virtual" observer for the user's schedule request
                    user_observer_state = {
                        'name': "User", # Placeholder name
                        'startTime': CENTRAL_TZ.localize(datetime.combine(today_date.date(), user_start_time)),
                        'endTime': CENTRAL_TZ.localize(datetime.combine(today_date.date(), user_end_time)),
                        'schedule': [],
                        'lastFlight': None
                    }

                    # The available flights pool starts with all relevant flights
                    available_flights_pool = all_flights_for_scheduling.copy()

                    # --- Scheduling Logic (adapted from Phase 2 of original script) ---
                    # This is a greedy single-observer assignment.
                    assignments_made_in_round = True
                    while assignments_made_in_round and not available_flights_pool.empty:
                        assignments_made_in_round = False

                        potential_next_flights = pd.DataFrame()
                        
                        current_observer_end_time = user_observer_state['endTime']
                        current_observer_start_time = user_observer_state['startTime']
                        last_flight_busy_end = user_observer_state['lastFlight']['busyEnd'] if user_observer_state['lastFlight'] else current_observer_start_time

                        potential_next_flights = available_flights_pool[
                            (available_flights_pool['Est. Boarding Start'] >= last_flight_busy_end) &
                            (available_flights_pool['Est. Boarding End'] <= current_observer_end_time)
                        ].copy()

                        if not potential_next_flights.empty:
                            potential_next_flights['downtime'] = potential_next_flights.apply(
                                lambda row: (row['busyStart'] - last_flight_busy_end).total_seconds() / 60
                                if user_observer_state['lastFlight'] else 0, axis=1
                            )
                            potential_next_flights['importance_score'] = potential_next_flights['isImportant'].apply(lambda x: 0 if x else 1)
                            
                            # Ensure 'DEP GATE' is used for gate parsing
                            last_gate_parsed = parse_gate(user_observer_state['lastFlight']['DEP GATE']) if user_observer_state['lastFlight'] else None
                            potential_next_flights['gate_score'] = potential_next_flights['DEP GATE'].apply(
                                lambda gate: (
                                    abs(parse_gate(gate)['number'] - last_gate_parsed['number']) / 10
                                    if last_gate_parsed and parse_gate(gate)['concourse'] == last_gate_parsed['concourse']
                                    else 15
                                )
                            )

                            potential_next_flights = potential_next_flights.sort_values(
                                by=['importance_score', 'downtime', 'gate_score']
                            )

                            best_choice = potential_next_flights.iloc[0]
                            
                            user_observer_state['schedule'].append(best_choice.to_dict())
                            user_observer_state['lastFlight'] = best_choice.to_dict()
                            available_flights_pool = available_flights_pool[available_flights_pool['FLIGHT OUT'] != best_choice['FLIGHT OUT']]
                            assignments_made_in_round = True
                    
                    # Display the generated schedule
                    if user_observer_state['schedule']:
                        # Sort the individual's schedule by time before outputting
                        user_observer_state['schedule'].sort(key=lambda f: f['Est. Boarding Start'])
                        
                        final_output_data = []
                        headers = ["Gate", "Flight #", "Destination", "Boarding Start", "Boarding End", "Time Between"]
                        
                        previous_flight_end = None
                        for flight in user_observer_state['schedule']:
                            time_between = "---"
                            if previous_flight_end:
                                diff_ms = (flight['Est. Boarding Start'] - previous_flight_end).total_seconds() * 1000
                                diff_mins = int(diff_ms / (60 * 1000))
                                hours = diff_mins // 60
                                mins = diff_mins % 60
                                time_between = f"{hours:01d}:{mins:02d}"

                            final_output_data.append([
                                flight['DEP GATE'],
                                flight['FLIGHT OUT'],
                                flight['ARR'],
                                flight['Est. Boarding Start'].strftime('%-I:%M %p'),
                                flight['Est. Boarding End'].strftime('%-I:%M %p'),
                                time_between
                            ])
                            previous_flight_end = flight['Est. Boarding End']
                        
                        st.session_state.suggested_schedule = pd.DataFrame(final_output_data, columns=headers)
                        st.success(f"Here is your suggested schedule:") 
                    else:
                        st.session_state.suggested_schedule = pd.DataFrame()
                        st.info("No available flights match your criteria for a suggested schedule.")

            if st.session_state.suggested_schedule is not None and not st.session_state.suggested_schedule.empty:
                st.dataframe(st.session_state.suggested_schedule, hide_index=True, use_container_width=True)
            elif st.session_state.suggested_schedule is not None and st.session_state.suggested_schedule.empty:
                st.info("No available flights match your criteria for a suggested schedule.")

    # ==============================================================================
    # --- MODE 3: MANUAL SIGN-UP ---
    # ==============================================================================
    elif st.session_state.mode == "signup":
        st.subheader("Manual Flight Sign-up")
        
        # Determine the list of tab names, with "Today" replacing the current day
        display_options = []
        default_index = 0 # Default to Monday's index if current day not in available_days_for_selection
        for i, day in enumerate(available_days_for_selection):
            if day == current_day_sheet_name:
                display_options.append("Today")
                default_index = i # Set default index to "Today"
            else:
                display_options.append(day)

        # Create the selectbox for day selection in manual sign-up mode
        selected_display_name = st.selectbox(
            "Select a Day:",
            options=display_options,
            index=default_index, # Set the default selected option
            key="day_selector_signup_mode"
        )
        
        # Map the selected display name back to the actual sheet name
        actual_sheet_name = current_day_sheet_name if selected_display_name == "Today" else selected_display_name

        st.subheader(f"Sign-up for {selected_display_name} Flights") 
        name = st.text_input("Enter your name:", key="manual_name")

        if name.strip():
            df = get_sheet_data(gc, actual_sheet_name)
            if df is not None and not df.empty:
                sheet_to_update = sheet_map[actual_sheet_name]
                flight_num_col_idx = df.columns.get_loc("FLIGHT OUT") + 1
                observer_col_idx = df.columns.get_loc("Observers") + 1
                live_flight_nums = sheet_to_update.col_values(flight_num_col_idx)

                for j, row in df.iterrows():
                    sched_dep_str = row['SCHED DEP'].strftime('%-I:%M %p') if pd.notna(row['SCHED DEP']) else "N/A"
                    flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {sched_dep_str} → {row['ARR']} | Observers: {row['Observers']}"
                    flight_num_to_update = str(row['FLIGHT OUT'])

                    if st.button(flight_label, key=f"manual_{actual_sheet_name}_{flight_num_to_update}_{j}"):
                        try:
                            sheet_row = live_flight_nums.index(flight_num_to_update) + 1
                            current_observers_str = sheet_to_update.cell(sheet_row, observer_col_idx).value or ""
                            observers_list = [obs.strip() for obs in current_observers_str.split(',') if obs.strip()]

                            if name.strip() not in observers_list:
                                observers_list.append(name.strip())
                                new_observers = ", ".join(observers_list)
                                sheet_to_update.update_cell(sheet_row, observer_col_idx, new_observers)
                                st.success(f"Signed up for flight {row['CARR (IATA)']} {row['FLIGHT OUT']} on {actual_sheet_name}!")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.warning(f"You are already signed up for this flight on {actual_sheet_name}.")
                        except ValueError:
                            st.error(f"Could not find flight {flight_num_to_update} in the sheet for {actual_sheet_name}. It may have been changed. Please refresh.")
                        except Exception as e:
                            st.error(f"An error occurred: {e}")
            else:
                st.info(f"No flight data available for {actual_sheet_name}.")
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
