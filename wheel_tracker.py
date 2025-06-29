import streamlit as st
import pandas as pd
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date
import json

st.set_page_config(page_title="Wheel Strategy Tracker", layout="wide")
st.title("\U0001F6DE Wheel Strategy Tracker (Guided Entry)")

# --- Google Sheets Setup ---
SHEET_NAME = "Wheel Strategy Trades"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# --- Helper to fetch price from Yahoo Finance ---
@st.cache_data(ttl=3600)
def get_current_price(ticker):
    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.get("last_price") or t.info.get("regularMarketPrice")
        return price
    except:
        return None

# --- Load data safely ---
try:
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df = df.loc[:, df.columns != '']  # Drop unnamed columns
    df.columns = pd.Index([str(col).strip() for col in df.columns])
except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
    df = pd.DataFrame()

# --- Trade Entry Logic ---
st.sidebar.header("\u2795 Guided Trade Entry")
strategy = st.sidebar.selectbox("Select Strategy", ["Select", "Wheel Strategy", "Put Credit Spread", "Covered Call"])

if strategy == "Wheel Strategy":
    step = st.sidebar.selectbox("Step in the Wheel", ["Select", "Sell Put", "Assignment", "Covered Call", "Called Away"])

    if step == "Sell Put":
        st.subheader("Sell Put Entry")
        with st.form("sell_put_form"):
            date_entry = st.date_input("Date", value=date.today())
            ticker = st.text_input("Ticker", value="SPY").upper()
            dte = st.number_input("Days to Expiration (DTE)", step=1)
            strike = st.number_input("Strike Price", step=0.5)
            delta = st.number_input("Delta (Optional)", step=0.01)
            credit = st.number_input("Credit Collected (excl. fees)", step=0.01)
            qty = st.number_input("Contracts (Qty)", step=1, value=1)
            expiration = st.date_input("Expiration Date")
            current_price = get_current_price(ticker)
            notes = st.text_area("Notes")
            submit = st.form_subm
