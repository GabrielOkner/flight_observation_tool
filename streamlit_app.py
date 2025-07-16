import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

st.set_page_config(page_title="Flight Observer", layout="centered")
st.title("Flight Observation Sign Up!")

# Authorize Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    st.secrets["google_service_account"], scopes=scope
)
gc = gspread.authorize(credentials)

# Open sheet
SHEET_NAME = "7_16_flights"
sheet = gc.open(SHEET_NAME).sheet1

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
                    # Update Google Sheet
                    sheet.update_cell(i + 2, df.columns.get_loc("Observers") + 1, df.at[i, "Observers"])
                    st.success(f"{name}, you've signed up for this flight!")
                else:
                    st.info("You already signed up for this flight.")

# Display updated table
st.markdown("---")
st.subheader("Today's Flights")
st.dataframe(df[["DEP GATE", "FLIGHT OUT", "ARR", "SCHED DEP", "Observers"]])
