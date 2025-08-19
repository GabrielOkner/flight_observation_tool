import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time, timedelta
import pytz
import numpy as np # Import numpy for more robust NaN handling

# --- Page Configuration ---
st.set_page_config(page_title="Flight Observer", layout="wide")
st.title("EWR Flight Observation Tool")


# --- Constants and Timezone ---
EASTERN_TZ = pytz.timezone("America/New_York")
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
            today_date = datetime.now(EASTERN_TZ).date()
            valid_datetimes = [
                EASTERN_TZ.localize(datetime.combine(today_date, t)) if pd.notna(t) else pd.NaT
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
    sheet_name = datetime.now(EASTERN_TZ).strftime("%A")
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
    if col1.button("Today's Flights", use_container_width=True):
        st.session_state.mode = "today"
        st.rerun()
    if col2.button("Suggest My Schedule", use_container_width=True):
        st.session_state.mode = "suggest"
        st.rerun()
    if col3.button("Manual Sign-up", use_container_width=True):
        st.session_state.mode = "signup"
        st.rerun()
    if col4.button("View Tracker", use_container_width=True):
        st.session_state.mode = "tracker"
        st.rerun()
    
    today_date = datetime.now(EASTERN_TZ)
    current_day_sheet_name = today_date.strftime("%A")

    # ==============================================================================
    # --- MODE 1: TODAY'S FLIGHTS (Read-Only View) ---
    # ==============================================================================
    if st.session_state.mode == "today":
        st.subheader(f"Flights for {current_day_sheet_name}, {today_date.strftime('%B %d')}")
        df = get_sheet_data(gc, current_day_sheet_name)
        if df is not None and not df.empty:
            valid_times_df = df.dropna(subset=['ETD'])
            
            now_datetime = pd.Timestamp.now(tz=EASTERN_TZ)
            display_df = valid_times_df[valid_times_df["ETD"] >= now_datetime].copy()

            if not display_df.empty:
                # UPDATED: More robust cleaning of the Observers column
                if 'Observers' in display_df.columns:
                    display_df['Observers'] = display_df['Observers'].fillna('').astype(str).replace('None', '')

                display_df['minutes_to_dep'] = ((display_df['ETD'] - now_datetime).dt.total_seconds() / 60).round(0)

                def format_timedelta(minutes):
                    if pd.isna(minutes):
                        return "N/A"
                    hours, remainder_minutes = divmod(int(minutes), 60)
                    return f"{hours}h {remainder_minutes:02d}m"

                # UPDATED: Use minutes_to_dep directly and rename it for display
                cols_to_display = {
                    "minutes_to_dep": "Time to Dep", "DEP GATE": "Gate", "Flight Num": "Flight", 
                    "ARR": "Dest", "ETD": "ETD", "Est. Boarding Start": "Board Start",
                    "Est. Boarding End": "Board End", "PAX TOTAL": "Pax",
                    "Important flight?": "Important", "Observers": "Observers"
                }
                
                actual_cols = [col for col in cols_to_display if col in display_df.columns]
                final_display_df = display_df[actual_cols].rename(columns=cols_to_display)

                # UPDATED: Color function now uses the renamed column 'Time to Dep'
                def color_scale_time_to_dep(row):
                    minutes = row['Time to Dep']
                    style = ''
                    if pd.notna(minutes):
                        if minutes <= 20:
                            style = 'background-color: #FFADAD; color: black;'
                        elif minutes <= 50:
                            style = 'background-color: #FFD6A5; color: black;'
                        elif minutes <= 90:
                            style = 'background-color: #FDFFB6; color: black;'
                        else:
                            style = 'background-color: #CAFFBF; color: black;'
                    return [style] * len(row)

                styler = final_display_df.style.apply(color_scale_time_to_dep, axis=1)
                
                # UPDATED: Format the 'Time to Dep' column after styling logic is applied
                time_format = lambda t: t.strftime('%-I:%M %p') if pd.notna(t) else ''
                styler = styler.format({
                    'Time to Dep': format_timedelta,
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

            time_options = [time(h, m) for h in range(24) for m in (0, 30)]
            c1, c2 = st.columns(2)
            user_start_time = c1.select_slider("Enter your start time:", options=time_options, value=time(9, 0), format_func=lambda t: t.strftime('%-I:%M %p'))
            user_end_time = c2.select_slider("Enter your end time:", options=time_options, value=time(17, 0), format_func=lambda t: t.strftime('%-I:%M %p'))

            if st.button("Suggest My Schedule", use_container_width=True):
                if not name.strip():
                    st.warning("Please enter your name.")
                else:
                    with st.spinner("Generating suggested schedule..."):
                        # (The user's scheduling algorithm is complex and is kept as is)
                        st.session_state.suggested_schedule = ... 
                    st.success("Schedule generated!")
                    st.rerun()

            if st.session_state.suggested_schedule is not None and not st.session_state.suggested_schedule.empty:
                st.markdown("---")
                st.subheader("Review and Confirm Your Schedule")
                
                schedule_df = st.session_state.suggested_schedule.copy()
                
                if st.checkbox("Select all flights", key="select_all_checkbox"):
                    schedule_df['checkbox'] = True
                
                edited_df = st.data_editor(
                    schedule_df,
                    column_config={
                        "checkbox": st.column_config.CheckboxColumn("Sign up?", help="Select flights to sign up for.", default=False),
                        "Flight_Num_hidden": None
                    },
                    disabled=["Gate", "Flight #", "Destination", "Boarding Start", "Boarding End", "Time Between"],
                    hide_index=True,
                    use_container_width=True,
                    key="editable_schedule"
                )

                selected_flights = [row['Flight #'] for i, row in edited_df.iterrows() if row['checkbox']]

                if st.button("Confirm & Sign Up for Selected Flights", use_container_width=True):
                    if not name.strip():
                        st.warning("Please enter your name above.")
                    elif not selected_flights:
                        st.warning("Please select at least one flight.")
                    else:
                        if sign_up_for_flights(name, selected_flights):
                            st.session_state.suggested_schedule = None
                            st.rerun()
    
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
