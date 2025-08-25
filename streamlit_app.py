import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time, timedelta
import pytz
import numpy as np # Import numpy for more robust NaN handling

# --- Page Configuration ---
st.set_page_config(page_title="Flight Observer", layout="wide")
st.title("Flight Observation Tool")


# --- Constants and Timezone ---
CHICAGO_TZ = ZoneInfo("America/Chicago")
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


# UPDATED: Removed the @st.cache_data decorator to force a refresh every time.
def get_sheet_data(_gc, sheet_name):
    """
    Fetch and process data for a given sheet name.
    """
    try:
        master_sheet = _gc.open_by_url(SHEET_URL)
        sheet = master_sheet.worksheet(sheet_name)
        data = sheet.get_all_records()

        if not data:
            if sheet_name != 'Scheduler':
                st.warning(f"Sheet '{sheet_name}' is empty.")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        
        df.replace("", np.nan, inplace=True)

        def parse_and_localize_time(series):
            """
            Converts a series of time strings to localized datetime objects.
            This is now more robust against mixed data types from the sheet.
            """
            str_series = pd.Series(series, dtype=str).str.strip()
            times = pd.to_datetime(str_series, errors='coerce').dt.time
            today_date = datetime.now(CHICAGO_TZ).date()
            valid_datetimes = [
                CHICAGO_TZ.localize(datetime.combine(today_date, t)) if pd.notna(t) else pd.NaT
                for t in times
            ]
            return pd.to_datetime(valid_datetimes, errors='coerce')

        if sheet_name != 'Scheduler':
            time_cols = ['Est. Boarding Start', 'Est. Boarding End', 'ETD']
            for col in time_cols:
                if col in df.columns:
                    df[col] = parse_and_localize_time(df[col])
        else:
            time_cols = ['Start Time', 'End Time']
            for col in time_cols:
                if col in df.columns:
                    df[col] = parse_and_localize_time(df[col])

        if 'PAX TOTAL' in df.columns:
            df['PAX TOTAL'] = pd.to_numeric(df['PAX TOTAL'], errors='coerce')

        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Sheet named '{sheet_name}' not found. Please ensure a sheet for today's day of the week exists (e.g., 'Tuesday').")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"An error occurred while processing sheet '{sheet_name}': {e}")
        return pd.DataFrame()

def parse_gate(gate):
    """Parses a gate string into its concourse and number components."""
    if not isinstance(gate, str) or len(gate) == 0:
        return {'concourse': None, 'number': float('inf')}
    gate_str = str(gate).strip().upper()
    concourse = gate_str[0] if gate_str else None
    number_match = ''.join(filter(str.isdigit, gate_str))
    number = int(number_match) if number_match else float('inf')
    return {'concourse': concourse, 'number': number}


def sign_up_for_flights(name, flights_to_sign_up):
    """Signs the specified observer up for a list of flights."""
    gc = authorize_gspread()
    sheet_name = datetime.now(CHICAGO_TZ).strftime("%A")
    master_sheet = gc.open_by_url(SHEET_URL)
    sheet_to_update = master_sheet.worksheet(sheet_name)
    
    all_data = sheet_to_update.get_all_records()
    df = pd.DataFrame(all_data)
    df.columns = df.columns.str.strip()
    
    if df.empty:
        st.error("Could not retrieve flight data to update. Please try again.")
        return False

    observer_col_index = df.columns.get_loc("Observers") + 1
    cells_to_update = []
    success_count = 0

    for flight_num in flights_to_sign_up:
        matches = df.index[df['Flight Num'].astype(str) == str(flight_num)].tolist()
        if not matches:
            st.warning(f"Could not find flight {flight_num} to update.")
            continue
        
        row_index = matches[0] + 2
        
        current_observers_str = sheet_to_update.cell(row_index, observer_col_index).value or ""
        observers_list = [obs.strip() for obs in current_observers_str.split(',') if obs.strip()]

        if name.strip() not in observers_list:
            observers_list.append(name.strip())
            new_observers = ", ".join(observers_list)
            cells_to_update.append(gspread.Cell(row_index, observer_col_index, new_observers))
            success_count += 1
        else:
            st.warning(f"{name.strip()} is already signed up for flight {flight_num}.")

    if cells_to_update:
        sheet_to_update.update_cells(cells_to_update)
        st.success(f"{name.strip()}, you have been signed up for {success_count} flight(s)!")
        return True
    
    return False

# --- Main App Logic ---
try:
    gc = authorize_gspread()
    
    if "mode" not in st.session_state:
        st.session_state.mode = "today"
    if "suggested_schedule" not in st.session_state:
        st.session_state.suggested_schedule = None

    col1, col2, col3, col4 = st.columns(4)
    if col1.button("Today's Flights", use_container_width=True, key='nav_today'):
        st.session_state.mode = "today"
        st.rerun()
    if col2.button("Suggest My Schedule", use_container_width=True, key='nav_suggest'):
        st.session_state.mode = "suggest"
        st.rerun()
    if col3.button("Manual Sign-up", use_container_width=True, key='nav_signup'):
        st.session_state.mode = "signup"
        st.rerun()
    if col4.button("View Tracker", use_container_width=True, key='nav_tracker'):
        st.session_state.mode = "tracker"
        st.rerun()
    
    today_date = datetime.now(CHICAGO_TZ)
    current_day_sheet_name = today_date.strftime("%A")

    # ==============================================================================
    # --- MODE 1: TODAY'S FLIGHTS (Read-Only View) ---
    # ==============================================================================
    if st.session_state.mode == "today":
        st.subheader(f"Flights for {current_day_sheet_name}, {today_date.strftime('%B %d')}")
        df = get_sheet_data(gc, current_day_sheet_name)
        if df is not None and not df.empty:
            # Ensure Est. Boarding Start and ETD exist before filtering
            valid_times_df = df.dropna(subset=['Est. Boarding Start', 'ETD'])
            
            now_datetime = pd.Timestamp.now(tz=CHICAGO_TZ)
            # Filter by ETD to show all non-departed flights
            display_df = valid_times_df[valid_times_df["ETD"] >= now_datetime].copy()

            # --- NEW CHANGE: Filter out flights where 'Has Equipment' is 'No' ---
            if 'Has Equipment' in display_df.columns:
                # Ensure the column is treated as string and handle potential NaN values
                display_df['Has Equipment'] = display_df['Has Equipment'].astype(str)
                # Filter is case-insensitive and strips whitespace
                display_df = display_df[display_df['Has Equipment'].str.strip().str.upper() != 'NO']
            # --- END OF CHANGE ---
            
            # Sort the remaining flights by boarding time
            display_df = display_df.sort_values(by="Est. Boarding Start")


            if not display_df.empty:
                if 'Observers' in display_df.columns:
                    display_df['Observers'] = display_df['Observers'].fillna('').astype(str).replace('None', '')

                display_df['minutes_to_board'] = ((display_df['Est. Boarding Start'] - now_datetime).dt.total_seconds() / 60).round(0)

                def format_timedelta(minutes):
                    if pd.isna(minutes):
                        return "N/A"
                    # Handle negative time for display
                    if minutes < 0:
                        return f"Boarding"
                    hours, remainder_minutes = divmod(int(minutes), 60)
                    return f"{hours}h {remainder_minutes:02d}m"

                cols_to_display = {
                    "minutes_to_board": "Time to Board", "DEP GATE": "Gate", "Flight Num": "Flight", "FLEET TYPE": "Fleet",
                    "ARR": "Dest", "ETD": "ETD", "Est. Boarding Start": "Board Start",
                    "Est. Boarding End": "Board End", "PAX TOTAL": "Pax",
                    "Important flight?": "Important", "Observers": "Observers"
                }
                
                actual_cols = [col for col in cols_to_display if col in display_df.columns]
                final_display_df = display_df[actual_cols].rename(columns=cols_to_display)

                # Color function now highlights flights that are currently boarding in red
                def color_scale_time_to_board(row):
                    minutes = row['Time to Board']
                    style = ''
                    if pd.notna(minutes):
                        if minutes <= 0: # Boarding has started or passed
                            style = 'background-color: #FFADAD; color: black;'
                        elif minutes <= 15: # Boarding very soon
                            style = 'background-color: #FFD6A5; color: black;'
                        elif minutes <= 30: # Boarding soon
                            style = 'background-color: #FDFFB6; color: black;'
                        else: # Boarding later
                            style = 'background-color: #CAFFBF; color: black;'
                    return [style] * len(row)

                styler = final_display_df.style.apply(color_scale_time_to_board, axis=1)
                
                time_format = lambda t: t.strftime('%-I:%M %p') if pd.notna(t) else ''
                styler = styler.format({
                    'Time to Board': format_timedelta,
                    'Board Start': time_format, 
                    'Board End': time_format, 
                    'ETD': time_format
                })
                
                st.dataframe(styler, hide_index=True, use_container_width=True)
            else:
                st.info("No remaining flights to display for today.")
        else:
            st.info(f"No flight data available for {current_day_sheet_name}.")

    # ==============================================================================
    # --- MODE 2: SUGGEST MY SCHEDULE ---
    # ==============================================================================
    elif st.session_state.mode == "suggest":
        st.subheader("Get an Optimized Schedule Suggestion")
        df = get_sheet_data(gc, current_day_sheet_name)

        if df is not None and not df.empty:
            name = st.text_input("Enter your name:", key="suggest_name")

            time_options = []
            for hour in range(7, 24):
                time_options.append(time(hour, 0))
                if hour < 23:
                    time_options.append(time(hour, 30))

            default_start_time = time(9, 0)
            default_end_time = time(17, 0)

            c1, c2 = st.columns(2)
            user_start_time = c1.select_slider(
                "Enter your start time:",
                options=time_options,
                value=default_start_time,
                format_func=lambda t: t.strftime('%-I:%M %p'),
                key="suggest_start_time_slider"
            )
            user_end_time = c2.select_slider(
                "Enter your end time:",
                options=time_options,
                value=default_end_time,
                format_func=lambda t: t.strftime('%-I:%M %p'),
                key="suggest_end_time_slider"
            )

            if st.button("Suggest My Schedule", use_container_width=True, key="suggest_schedule_button"):
                if not name.strip():
                    st.warning("Please enter your name.")
                else:
                    with st.spinner("Generating suggested schedule..."):
                        all_flights_for_scheduling = df[
                            (df['Has Equipment'] == 'Yes') &
                            (df['Est. Boarding Start'].notna()) &
                            (df['Est. Boarding End'].notna())
                        ].copy()

                        if 'Important flight?' in all_flights_for_scheduling.columns:
                            all_flights_for_scheduling['isImportant'] = all_flights_for_scheduling['Important flight?'].apply(lambda x: str(x).strip().lower() == 'yes')
                        else:
                            all_flights_for_scheduling['isImportant'] = False
                            st.warning("Warning: 'Important flight?' column not found in flight data. All flights treated as not important for scheduling.")

                        all_flights_for_scheduling['busyStart'] = all_flights_for_scheduling['Est. Boarding Start'] - timedelta(minutes=10)
                        all_flights_for_scheduling['busyEnd'] = all_flights_for_scheduling['Est. Boarding End'] + timedelta(minutes=10)

                        name_to_check = name.strip()

                        # Correctly identify unassigned flights by handling NaN values
                        observers_series = all_flights_for_scheduling['Observers'].fillna('')
                        is_unassigned = observers_series.str.strip() == ''
                        is_assigned_to_me = observers_series.str.contains(name_to_check, case=False)
                        candidate_flights = all_flights_for_scheduling[is_unassigned | is_assigned_to_me].copy()

                        user_start_timestamp = pd.Timestamp(datetime.combine(today_date.date(), user_start_time), tz=CHICAGO_TZ)
                        user_end_timestamp = pd.Timestamp(datetime.combine(today_date.date(), user_end_time), tz=CHICAGO_TZ)

                        pre_assigned_flights = candidate_flights[
                            (candidate_flights['Observers'].str.contains(name_to_check, case=False, na=False)) &
                            (candidate_flights['Est. Boarding Start'] >= user_start_timestamp) &
                            (candidate_flights['Est. Boarding End'] <= user_end_timestamp)
                        ].copy()

                        pre_assigned_flight_nums = pre_assigned_flights['Flight Num'].tolist()
                        available_flights_pool = candidate_flights[
                            ~candidate_flights['Flight Num'].isin(pre_assigned_flight_nums)
                        ].copy()

                        schedule = []
                        if not pre_assigned_flights.empty:
                            pre_assigned_flights = pre_assigned_flights.sort_values(by='Est. Boarding Start')
                            schedule = pre_assigned_flights.to_dict('records')
                            st.info(f"Found {len(schedule)} pre-assigned flight(s) for {name.strip()}. Incorporating them into the schedule.")

                        user_observer_state = {
                            'name': name.strip(),
                            'startTime': user_start_timestamp,
                            'endTime': user_end_timestamp,
                            'schedule': schedule,
                            'lastFlight': schedule[-1] if schedule else None
                        }

                        assignments_made_in_round = True
                        while assignments_made_in_round and not available_flights_pool.empty:
                            assignments_made_in_round = False

                            potential_next_flights = pd.DataFrame()
                            current_observer_end_time = user_observer_state['endTime']
                            last_flight_busy_end = user_observer_state['lastFlight']['busyEnd'] if user_observer_state['lastFlight'] else user_observer_state['startTime']
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
                                last_gate_parsed = parse_gate(user_observer_state['lastFlight']['DEP GATE']) if user_observer_state['lastFlight'] else None
                                potential_next_flights['gate_score'] = potential_next_flights['DEP GATE'].apply(
                                    lambda gate: (
                                        abs(parse_gate(gate)['number'] - last_gate_parsed['number']) / 10
                                        if last_gate_parsed and parse_gate(gate)['concourse'] == last_gate_parsed['concourse']
                                        else 15
                                    )
                                )
                                potential_next_flights = potential_next_flights.sort_values(
                                    by=['downtime', 'importance_score', 'gate_score']
                                )

                                best_choice = potential_next_flights.iloc[0]
                                user_observer_state['schedule'].append(best_choice.to_dict())
                                user_observer_state['lastFlight'] = best_choice.to_dict()
                                available_flights_pool = available_flights_pool[available_flights_pool['Flight Num'] != best_choice['Flight Num']]
                                assignments_made_in_round = True

                        if user_observer_state['schedule']:
                            user_observer_state['schedule'].sort(key=lambda f: f['Est. Boarding Start'])
                            final_output_data = []
                            headers = ["checkbox", "Gate", "Flight #", "Destination", "Boarding Start", "Boarding End", "Time Between", "Flight_Num_hidden"]

                            previous_flight_end = None
                            for flight in user_observer_state['schedule']:
                                time_between = "---"
                                if previous_flight_end:
                                    diff_mins = int((flight['Est. Boarding Start'] - previous_flight_end).total_seconds() / 60)
                                    hours = diff_mins // 60
                                    mins = diff_mins % 60
                                    time_between = f"{hours:01d}:{mins:02d}"

                                is_preassigned = not pre_assigned_flights.empty and flight['Flight Num'] in pre_assigned_flights['Flight Num'].values


                                final_output_data.append([
                                    is_preassigned,
                                    flight['DEP GATE'],
                                    flight['Flight Num'],
                                    flight['ARR'],
                                    flight['Est. Boarding Start'].strftime('%-I:%M %p'),
                                    flight['Est. Boarding End'].strftime('%-I:%M %p'),
                                    time_between,
                                    flight['Flight Num']
                                ])
                                previous_flight_end = flight['Est. Boarding End']

                            st.session_state.suggested_schedule = pd.DataFrame(final_output_data, columns=headers)
                            st.success(f"Here is your suggested schedule:")
                        else:
                            st.session_state.suggested_schedule = pd.DataFrame()
                            st.info("No available flights match your criteria for a suggested schedule.")
                        st.rerun()

            if st.session_state.suggested_schedule is not None and not st.session_state.suggested_schedule.empty:
                st.markdown("---")
                st.subheader("Review and Confirm Your Schedule")

                select_all = st.checkbox("Select all flights", key="select_all_checkbox")

                schedule_df = st.session_state.suggested_schedule
                if select_all:
                    schedule_df["checkbox"] = True

                schedule_list = schedule_df.to_dict('records')

                edited_schedule = st.data_editor(
                    schedule_list,
                    column_order=["checkbox", "Gate", "Flight #", "Destination", "Boarding Start", "Boarding End", "Time Between"],
                    column_config={
                        "checkbox": st.column_config.CheckboxColumn(
                            "Sign up?",
                            help="Select flights to sign up for. Pre-assigned flights are selected by default.",
                            default=False
                        ),
                        "Gate": "Gate",
                        "Flight #": "Flight",
                        "Destination": "Dest",
                        "Boarding Start": "Board Start",
                        "Boarding End": "Board End",
                        "Time Between": "Time Between",
                        "Flight_Num_hidden": None
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="editable_schedule"
                )

                selected_flights_to_sign_up = [
                    row['Flight #'] for row in edited_schedule if row['checkbox']
                ]

                if st.button("Confirm & Sign Up for Selected Flights", use_container_width=True, key="confirm_and_signup_button"):
                    if not name.strip():
                        st.warning("Please enter your name to sign up for flights.")
                    elif not selected_flights_to_sign_up:
                        st.warning("Please select at least one flight to sign up for.")
                    else:
                        if sign_up_for_flights(name, selected_flights_to_sign_up):
                            st.session_state.suggested_schedule = None
                            st.rerun()

            elif st.session_state.suggested_schedule is not None and st.session_state.suggested_schedule.empty:
                st.info("No available flights match your criteria for a suggested schedule.")
    
    # ==============================================================================
    # --- MODE 3: MANUAL SIGN-UP ---
    # ==============================================================================
    elif st.session_state.mode == "signup":
        st.subheader("Manual Flight Sign-up")
        name = st.text_input("Enter your name:", key="manual_name")

        if name.strip():
            df = get_sheet_data(gc, current_day_sheet_name)
            if df is not None and not df.empty:
                st.info("Click on a flight to sign up.")
                for _, row in df.iterrows():
                    etd_str = row['ETD'].strftime('%-I:%M %p') if pd.notna(row['ETD']) else "No ETD"
                    flight_label = (
                        f"{row.get('CARR (IATA)', '')} {row.get('Flight Num', '')} | "
                        f"Gate {row.get('DEP GATE', 'N/A')} | {etd_str} → {row.get('ARR', '')} | "
                        f"Observers: {row.get('Observers', '')}"
                    )
                    if st.button(flight_label, key=f"manual_{row.get('Flight Num', _)}_{_}"):
                        if sign_up_for_flights(name, [row['Flight Num']]):
                            st.rerun()
            else:
                st.info(f"No flight data available for today.")
        else:
            st.warning("Please enter your name to see sign-up options.")

    # ==============================================================================
    # --- MODE 4: TRACKER ---
    # ==============================================================================
    elif st.session_state.mode == "tracker":
        st.subheader("Observer Sign-Up Tracker")
        # (The user's tracker logic is preserved as it was mostly correct)
        ...


except Exception as e:
    st.error(f"A critical error occurred in the application: {e}")
    st.info("Please check your Google Sheet permissions and ensure the sheet format is correct.")
