import streamlit as st
import pandas as pd
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import pytz

st.set_page_config(page_title="Flight Observer", layout="centered")
st.title("IAH Flight Observation")

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

# Set Default Mode to Today Flights View
if "mode" not in st.session_state:
    st.session_state.mode = "today"

#Create Buttons for Mode Switch
col1, col2, col3 = st.columns(3)
if col1.button("Click to Sign Up"):
    st.session_state.mode = "signup"
if col2.button("Show Today's Flights"):
    st.session_state.mode = "today"
if col3.button("View Signup Tracker"):
    st.session_state.mode = "tracker"

# Load sheet only if needed
if st.session_state.mode in ["signup", "today"]:
    if st.session_state.mode == "signup":
        day_options = list(sheet_map.keys())
        selected_day = st.selectbox("Select a day to sign up for:", day_options)
    elif st.session_state.mode == "today":
        selected_day = "Monday 8/4"  # REMEMBER TO CHANGE (Figure out how to make automatic)
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
                        current_obs.append(st.session_state.name)
                        df.at[i, "Observers"] = ", ".join(current_obs)
                        observer_col_index = df.columns.get_loc("Observers") + 1
                        sheet.update_cell(i + 2, observer_col_index, df.at[i, "Observers"])
                        if conflict:
                            st.success(f"{st.session_state.name}, you've signed up for this flight despite the conflict!")
                        else:
                            st.success(f"{st.session_state.name}, you've signed up for this flight!")
                        st.session_state.selected_flight = None
                        st.session_state.override_requested = None
                        st.rerun()

        st.markdown("###")
        if st.button("Done Signing Up"):
            st.session_state.signup_active = False
            st.rerun()



elif st.session_state.mode == "tracker":
    st.subheader("Observer Sign-Up Tracker")
    GOAL_PER_CATEGORY = 10

    summary_data = []

    for sheet_name, sheet in sheet_map.items():
        try:
            records = sheet.get_all_records()
            df_sheet = pd.DataFrame(records)

            if "Observers" in df_sheet.columns and "Fleet Type Grouped" in df_sheet.columns:
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

    iad_time = pytz.timezone("America/Los_Angeles")
    now_ct = datetime.now(iad_time).replace(second=0, microsecond=0).time()
    filtered_df = df[df["Parsed Time"].notnull() & (df["Parsed Time"] >= now_ct)]

    if not filtered_df.empty:
        st.dataframe(filtered_df[["DEP GATE", "Flight Num", "ARR", "SCHED DEP", "Est. Boarding Start", "Observers"]], hide_index = True)
    else:
        st.info("No upcoming flights found.")
