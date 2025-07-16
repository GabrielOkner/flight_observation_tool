import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

st.set_page_config(page_title="Flight Observer", layout="centered")
st.title("Flight Observation Sign Up!")

# Authorize Google Sheets with updated scopes
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    st.secrets["google_service_account"], scopes=scope
)
gc = gspread.authorize(credentials)

# Use full URL to open shared sheet
SHEET_URL = "https://docs.google.com/spreadsheets/d/109xeylSzvDEMTRjqYTllbzj3nElbfVCTSzZxfn4caBQ/edit?usp=sharing"
sheet = gc.open_by_url(SHEET_URL).sheet1

# Load data into DataFrame
data = sheet.get_all_records()
df = pd.DataFrame(data)

# Name input
name = st.text_input("Enter your name:")
signup_clicked = st.button("Sign up")

if signup_clicked and name:
    st.success(f"Hi {name}, please select the flights you'd like to observe!")

    for i, row in df.iterrows():
        with st.container():
            flight_label = f"{row['CARR (IATA)']} | {row['AIRCRAFT']} | Gate {row['DEP GATE']} | {row['SCHED DEP']} → {row['ARR']}"
            cols = st.columns([5, 1])
            cols[0].markdown(f"**{flight_label}**")

            if cols[1].button("Observe", key=f"observe_{i}"):
                current_obs = row["Observers"].split(", ") if row["Observers"] else []
                if name not in current_obs:
                    current_obs.append(name)
                    df.at[i, "Observers"] = ", ".join(current_obs)
                    updated_row = df.iloc[i].tolist()
                    sheet.update(f"A{i+2}:Z{i+2}", [updated_row])  # update full row
                    st.success(f"{name}, you've signed up for this flight!")
                else:
                    st.info("You already signed up for this flight.")

# Show table with current observers
st.markdown("---")
st.subheader("Today's Flights")
st.dataframe(df[["DEP GATE", "FLIGHT OUT", "ARR", "SCHED DEP", "Observers"]])
