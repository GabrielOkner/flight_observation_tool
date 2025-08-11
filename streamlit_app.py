import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time, timedelta, date
import pytz

st.set_page_config(page_title="Flight Observer", layout="centered")
st.title("LAX Flight Observation")

# Authorize Google Sheets
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    st.secrets["google_service_account"], scopes=scope
)
gc = gspread.authorize(credentials)

SHEET_URL = "https://docs.google.com/spreadsheets/d/109xeylSzvDEMTRjqYTllbzj3nElbfVCTSzZxfn4caBQ/edit?usp=sharing"
master_sheet = gc.open_by_url(SHEET_URL)
all_sheets = master_sheet.worksheets()
sheet_map = {sheet.title: sheet for sheet in all_sheets} #maps sheet name to sheet object

    if "mode" not in st.session_state:
        st.session_state.mode = "today"
    if "suggested_schedule" not in st.session_state:
        st.session_state.suggested_schedule = None

    col1, col2, col3, col4 = st.columns(4)
    if col1.button("Today's Flights", use_container_width=True):
        st.session_state.mode = "today"
    if col2.button("Suggest My Schedule", use_container_width=True):
        st.session_state.mode = "suggest"
    if col3.button("Manual Sign-up", use_container_width=True):
        st.session_state.mode = "signup"
    if col4.button("View Tracker", use_container_width=True):
        st.session_state.mode = "tracker"

# Load sheet only if needed
if st.session_state.mode in ["signup", "today"]:
    if st.session_state.mode == "signup":
        day_options = list(sheet_map.keys())
        selected_day = st.selectbox("Select a day to sign up for:", day_options)
    elif st.session_state.mode == "today":
    # Automatically determine today's sheet name for IAH (Central Time)
    central_tz = pytz.timezone("America/Chicago")
    today = datetime.now(central_tz)
    # Format: "Tuesday 8/5". Use '%-m' and '%-d' for non-padded day/month.
    selected_day = today.strftime("%A %-m/%-d")
    sheet = sheet_map[selected_day]
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

# Sign-up Mode
if st.session_state.mode == "signup":
    if "name" not in st.session_state:
        st.session_state.name = ""
    if "signup_active" not in st.session_state:
        st.session_state.signup_active = False
    if "selected_flight" not in st.session_state:
        st.session_state.selected_flight = None
    if "override_requested" not in st.session_state:
        st.session_state.override_requested = None

    name = st.text_input("Enter your name:", value=st.session_state.name)

    if name:
        st.session_state.name = name

    if st.button("Sign up"):
        if not name:
            st.warning("Please enter your name before signing up.")
        else:
            st.session_state.signup_active = True
            st.success(f"Hi {name}, please select flights you'd like to observe!")

    if st.session_state.signup_active and st.session_state.name:
        for i, row in df.iterrows():
            with st.container():
                current_obs = row["Observers"].split(", ") if row["Observers"] else []
                category = row.get("Fleet Type Grouped", "").strip().capitalize()
                flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {row['SCHED DEP']} → {row['ARR']} | {category} | Passengers: {row['PAX TOTAL']} | {row['Has Equipment']}"
                has_observers = bool(row["Observers"])

                styled_label = (
                    f"<span style='color:red; font-weight:bold;'>{flight_label}</span>"
                    if has_observers else f"<span style='font-weight:bold;'>{flight_label}</span>"
                )

                cols = st.columns([5, 2])
                cols[0].markdown(styled_label, unsafe_allow_html=True)

                if cols[1].button("Observe", key=f"observe_{i}"):
                    st.session_state.selected_flight = i
                    st.session_state.override_requested = None
                    st.rerun()

                if st.session_state.selected_flight == i:
                    selected_time = None
                    try:
                        selected_time = datetime.strptime(row["SCHED DEP"], "%H:%M")
                    except ValueError:
                        st.error(f"Invalid time format for flight: {row['SCHED DEP']}")
                        continue

                    conflict = False
                    for j, other_row in df.iterrows():
                        if other_row["Observers"]:
                            observers = other_row["Observers"].split(", ")
                            if st.session_state.name in observers:
                                try:
                                    other_time = datetime.strptime(other_row["SCHED DEP"], "%H:%M")
                                    diff = abs((selected_time - other_time).total_seconds()) / 60
                                    if diff < 50 and j != i:
                                        conflict = True
                                        break
                                except:
                                    continue

                    if st.session_state.name in current_obs:
                        st.info("You already signed up for this flight.")
                        st.session_state.selected_flight = None

                    elif conflict and st.session_state.override_requested != i:
                        st.warning("You’ve already signed up for a flight within 50 minutes of this one.")
                        if cols[1].button("Sign Up Despite Conflict", key=f"override_btn_{i}"):
                            st.session_state.override_requested = i
                            st.rerun()
                    else:
                        sign_up_for_flights(name, selected_flights_to_sign_up)

            elif st.session_state.suggested_schedule is not None and st.session_state.suggested_schedule.empty:
                st.info("No available flights match your criteria for a suggested schedule.")

    # ==============================================================================
    # --- MODE 3: MANUAL SIGN-UP ---
    # ==============================================================================
    elif st.session_state.mode == "signup":
        st.subheader("Manual Flight Sign-up")

        display_options = []
        default_index = 0
        for i, day in enumerate(available_days_for_selection):
            if day == current_day_sheet_name:
                display_options.append("Today")
                default_index = i
            else:
                display_options.append(day)

        selected_display_name = st.selectbox("Select a Day:", options=display_options, index=default_index, key="day_selector_signup_mode")
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
                    # --- FIX START ---
                    # Safely access the 'ETD/ACT' column, providing a fallback if it doesn't exist
                    etd_str = "N/A"
                    if 'ETD/ACT' in row and pd.notna(row['ETD/ACT']):
                        try:
                            etd_str = row['ETD/ACT'].strftime('%-I:%M %p')
                        except AttributeError:
                            etd_str = str(row['ETD/ACT']) # Fallback for non-datetime types
                    # --- FIX END ---
                    
                    flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {etd_str} → {row['ARR']} | Observers: {row['Observers']}"
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
        
        observer_data = {}
        fleet_type_counts = {}
        concourse_counts = {}
        region_counts = {}

        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        relevant_sheet_names = [s.title for s in all_sheets if s.title in days_of_week]

        for sheet_name in relevant_sheet_names:
            df_sheet = get_sheet_data(gc, sheet_name)
            
            required_cols = ["Observers", "Fleet Type Grouped", "DEP GATE", "Region"]
            if df_sheet is not None and not df_sheet.empty and all(col in df_sheet.columns for col in required_cols):
                df_sheet.dropna(subset=["Observers"], inplace=True)
                
                for _, row in df_sheet.iterrows():
                    num_signups = len(row["Observers"].split(", ")) if row["Observers"] else 0
                    category = row["Fleet Type Grouped"].strip().lower()
                    if category in {"widebody", "narrowbody", "express"}:
                        summary_data.append({
                            "Day": sheet_name,
                            "Category": category,
                            "Signups": num_signups,
                            "Continent": row.get("Continent", "Unknown").strip().capitalize()
                        })
        except Exception as e:
            st.warning(f"Error reading {sheet_name}: {e}")

    if summary_data:
        df_summary = pd.DataFrame(summary_data)
        chart_data = df_summary.pivot_table(
            index="Day",
            columns="Category",
            values="Signups",
            aggfunc="sum",
            fill_value=0
        ).reindex(columns=["widebody", "narrowbody", "express"]).sort_index()

        st.markdown("### Signups by Day and Category")
        st.data_editor(chart_data,column_config={col: st.column_config.NumberColumn(width="small") for col in chart_data.columns}, use_container_width=True, disabled=True)

        # Total per category across all days
        total_by_category = chart_data.sum(axis=0)

        st.markdown("### Total Progress Toward 10 Signups per Category")
        cols = st.columns(3)
        for i, category in enumerate(["widebody", "narrowbody", "express"]):
            count = total_by_category.get(category, 0)
            progress = min(count / GOAL_PER_CATEGORY, 1.0)
            cols[i].progress(progress, text=f"{category.capitalize()}: {int(count)}/10")

        
        st.markdown("### Flights Observed by Continent")
        df_continent = df_summary.groupby("Continent")["Signups"].sum().sort_values(ascending=False)

        st.markdown("### Total Progress by Continent")
        cols = st.columns(min(5, len(df_continent))) 

        for i, (continent, count) in enumerate(df_continent.items()):
            col = cols[i % len(cols)]  # Cycle through columns
            progress = min(count / 10, 1.0)
            col.progress(progress, text=f"{continent}: {int(count)}/10")


    else:
        st.info("No signup data available.")



# Only show upcoming flights in "today" mode
if st.session_state.mode == "today":
    st.markdown("---")
    st.subheader("Upcoming Flights for Today")

    def parse_time(t):
        try:
            return datetime.strptime(t.strip(), "%H:%M").time()
        except:
            return None

    if "Parsed Time" not in df.columns:
        df["Parsed Time"] = df["SCHED DEP"].apply(parse_time)

    # Use the correct timezone for IAH (Central Time)
    central_tz = pytz.timezone("America/Chicago")
    now_ct = datetime.now(central_tz).replace(second=0, microsecond=0).time()
    filtered_df = df[df["Parsed Time"].notnull() & (df["Parsed Time"] >= now_ct)]

    if not filtered_df.empty:
        # Define the columns to display and their new names
        cols_to_display = {
            "DEP GATE": "Gate",
            "Flight Num": "Flight Num",
            "ARR": "Dest",
            "SCHED DEP": "Dep",
            "Est. Boarding Start": "Board Start",
            "Est. Boarding End": "Board End",
            "PAX TOTAL": "Pax",
            "Observers": "Observers"
        }
        
        # Create a new dataframe with only the columns we want
        display_df = filtered_df[list(cols_to_display.keys())]
        
        # Rename the columns for display
        display_df = display_df.rename(columns=cols_to_display)
        
        st.dataframe(display_df, hide_index=True, use_container_width=True)
    else:
        st.info("No upcoming flights found.")

except Exception as e:
    st.error(f"A critical error occurred: {e}")
    st.info("Please check your Google Sheet permissions and ensure the sheet format is correct.")