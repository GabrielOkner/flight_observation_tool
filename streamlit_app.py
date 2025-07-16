import streamlit as st
import pandas as pd
import gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

st.set_page_config(page_title="Flight Observer", layout="centered")
st.title("Flight Observation Sign Up!")

# Authorize Google Sheets
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    st.secrets["google_service_account"], scopes=scope
)
gc = gspread.authorize(credentials)

# Load sheet with flights
SHEET_URL = "https://docs.google.com/spreadsheets/d/109xeylSzvDEMTRjqYTllbzj3nElbfVCTSzZxfn4caBQ/edit?usp=sharing"
sheet = gc.open_by_url(SHEET_URL).sheet1
data = sheet.get_all_records()
df = pd.DataFrame(data)

# Persist name and signup state
if "name" not in st.session_state:
    st.session_state.name = ""
if "signup_active" not in st.session_state:
    st.session_state.signup_active = False

# Name input
name = st.text_input("Enter your name:", value=st.session_state.name)
if name:
    st.session_state.name = name

if st.button("Sign up"):
    if not name:
        st.warning("Please enter your name before signing up.")
    else:
        st.session_state.signup_active = True
        st.success(f"Hi {name}, please select flights you'd like to observe!")

# Show selection if active
if st.session_state.signup_active and st.session_state.name:
    for i, row in df.iterrows():
        with st.container():
            flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {row['SCHED DEP']} → {row['ARR']}"
            has_observers = bool(row["Observers"])

            if has_observers:
                styled_label = f"<span style='color:red; font-weight:bold;'>{flight_label}</span>"
            else:
                styled_label = f"<span style='font-weight:bold;'>{flight_label}</span>"

            cols = st.columns([5, 1])
            cols[0].markdown(styled_label, unsafe_allow_html=True)

            if cols[1].button("Observe", key=f"observe_{i}"):
                current_obs = row["Observers"].split(", ") if row["Observers"] else []
                if st.session_state.name not in current_obs:
                    try:
                        selected_time = datetime.strptime(row["SCHED DEP"], "%H:%M")
                    except ValueError:
                        st.error(f"Invalid time format for flight: {row['SCHED DEP']}")
                        continue

                    # Check conflicts with user's other signed-up flights
                    conflict = False
                    for _, other_row in df.iterrows():
                        if other_row["Observers"]:
                            observers = other_row["Observers"].split(", ")
                            if st.session_state.name in observers:
                                try:
                                    other_time = datetime.strptime(other_row["SCHED DEP"], "%H:%M")
                                    diff = abs((selected_time - other_time).total_seconds()) / 60
                                    if diff < 50:
                                        conflict = True
                                        break
                                except:
                                    continue

                    if conflict:
                        st.warning("You’ve already signed up for a flight within 50 minutes of this one.")
                    else:
                        current_obs.append(st.session_state.name)
                        df.at[i, "Observers"] = ", ".join(current_obs)
                        observer_col_index = df.columns.get_loc("Observers") + 1
                        sheet.update_cell(i + 2, observer_col_index, df.at[i, "Observers"])
                        st.success(f"{st.session_state.name}, you've signed up for this flight!")
                else:
                    st.info("You already signed up for this flight.")

    st.markdown("###")
    if st.button("Done Signing Up"):
        st.session_state.signup_active = False
        st.rerun()

# Display updated table
st.markdown("---")
st.subheader("Today's Flights")
st.dataframe(df[["DEP GATE", "FLIGHT OUT", "ARR", "SCHED DEP", "Observers"]])
