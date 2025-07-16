import streamlit as st
import pandas as pd
import gspread
from datetime import datetime
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

# Load sheet and data
SHEET_URL = "https://docs.google.com/spreadsheets/d/109xeylSzvDEMTRjqYTllbzj3nElbfVCTSzZxfn4caBQ/edit?usp=sharing"
sheet = gc.open_by_url(SHEET_URL).sheet1
data = sheet.get_all_records()
df = pd.DataFrame(data)

# Session state
if "name" not in st.session_state:
    st.session_state.name = ""
if "signup_active" not in st.session_state:
    st.session_state.signup_active = False
if "selected_flight" not in st.session_state:
    st.session_state.selected_flight = None
if "override_requested" not in st.session_state:
    st.session_state.override_requested = None

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

# Flight selection interface
if st.session_state.signup_active and st.session_state.name:
    for i, row in df.iterrows():
        with st.container():
            current_obs = row["Observers"].split(", ") if row["Observers"] else []
            flight_label = f"{row['CARR (IATA)']} {row['FLIGHT OUT']} | Gate {row['DEP GATE']} | {row['SCHED DEP']} → {row['ARR']}"

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

            # Handle confirmation for conflict override
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
                    # Signup (either no conflict or override confirmed)
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

# Final table display
st.markdown("---")
st.subheader("Today's Flights")
st.dataframe(df[["DEP GATE", "FLIGHT OUT", "ARR", "SCHED DEP", "Observers"]])
