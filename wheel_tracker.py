import streamlit as st
import pandas as pd
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, timedelta
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
    df = df.loc[:, df.columns != '']
    df.columns = pd.Index([str(col).strip() for col in df.columns])
except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
    df = pd.DataFrame()

# --- Strategy Selection ---
st.sidebar.header("➕ Guided Trade Entry")
strategy = st.sidebar.selectbox("Select Strategy", ["Select", "Wheel Strategy", "Put Credit Spread"])

# --- Ensure required columns exist for Wheel Strategy ---
required_columns = [
    "Strategy", "Process", "Ticker", "Date", "Strike", "Delta", "DTE", "Credit Collected",
    "Qty", "Expiration", "Result", "Assigned Price", "Current Price at time", "P/L", "Shares Owned", "Notes"
]
existing_columns = df.columns.tolist()
for col in required_columns:
    if col not in existing_columns:
        df[col] = ""

# --- Wheel Strategy Logic ---
if strategy == "Wheel Strategy":
    unique_tickers = sorted(df["Ticker"].dropna().unique())
    ticker_option = st.sidebar.selectbox("Select Ticker or Start New", ["New"] + unique_tickers)

    if ticker_option == "New":
        selected_ticker = st.sidebar.text_input("Enter New Ticker").upper()
    else:
        selected_ticker = ticker_option
        df = df[df["Ticker"] == selected_ticker]

    step = st.sidebar.selectbox("Step in the Wheel", ["Select", "Sell Put", "Assignment", "Covered Call", "Called Away"])

    if step == "Sell Put":
        st.subheader("Sell Put Entry")
        with st.form("sell_put_form"):
            date_entry = st.date_input("Date", value=date.today())
            ticker = selected_ticker
            dte = st.number_input("Days to Expiration (DTE)", step=1)
            expiration = date_entry + timedelta(days=int(dte))
            strike = st.number_input("Strike Price ($)", step=0.5, format="%.2f")
            delta = st.number_input("Delta (Optional)", step=0.01)
            credit = st.number_input("Credit Collected ($)", step=0.01, format="%.2f")
            qty = st.number_input("Contracts (Qty)", step=1, value=1)
            current_price = get_current_price(ticker)
            notes = st.text_area("Notes")
            submit = st.form_submit_button("Save Entry")

            if submit:
                row = [
                    "Wheel Strategy", "Sell Put", ticker, date_entry.strftime("%Y-%m-%d"), strike, delta,
                    dte, credit, qty, expiration.strftime("%Y-%m-%d"),
                    "Open", current_price, "", "", notes
                ]
                sheet.append_row([str(x) for x in row])
                st.success("✅ Sell Put entry saved.")
                st.rerun()

    # ... (Assignment, Covered Call, Called Away logic unchanged for brevity)

# --- Put Credit Spread Strategy Logic ---
elif strategy == "Put Credit Spread":
    pcs_sheet = client.open(SHEET_NAME).worksheet("PCS")
    pcs_data = pcs_sheet.get_all_records()
    pcs_df = pd.DataFrame(pcs_data)
    st.subheader("Put Credit Spread Entry")
    existing_pcs_tickers = sorted(pcs_df["Ticker"].dropna().unique()) if not pcs_df.empty else []
    ticker_option = st.selectbox("Select PCS Ticker or Start New", ["New"] + existing_pcs_tickers)

    if ticker_option == "New":
        selected_ticker = st.text_input("Enter New PCS Ticker").upper()
    else:
        selected_ticker = ticker_option

    with st.form("pcs_form"):
        trade_date = st.date_input("Trade Date", value=date.today())
        dte = st.number_input("DTE (Days to Expiration)", min_value=1)
        expiration = trade_date + timedelta(days=int(dte))
        short_put = st.number_input("Short Put Strike", step=0.5)
        long_put = st.number_input("Long Put Strike", step=0.5)
        spread_width = abs(short_put - long_put)
        delta_short = st.number_input("Delta of Short Leg", step=0.01)
        credit_collected = st.number_input("Credit Collected ($)", step=0.01)
        qty = st.number_input("Contracts", step=1, value=1)
        notes = st.text_area("Notes")
        submit = st.form_submit_button("Save PCS Entry")

        if submit:
            row = [
                trade_date.strftime("%Y-%m-%d"), selected_ticker, dte, expiration.strftime("%Y-%m-%d"),
                short_put, long_put, spread_width, delta_short, credit_collected, qty, notes
            ]
            pcs_sheet.append_row([str(x) for x in row])
            st.success("✅ Put Credit Spread saved.")
            st.rerun()

# --- Chart ---
st.subheader("\U0001F4CB Current Trades")
if df.empty:
    st.warning("No trade data available.")
else:
    df["P/L"] = pd.to_numeric(df.get("P/L", 0), errors="coerce").fillna(0.0)
    st.dataframe(df.drop(columns=["Notes"], errors="ignore"))

st.download_button("\U0001F4BE Download All Trades as CSV", df.to_csv(index=False), file_name="wheel_trades.csv")
