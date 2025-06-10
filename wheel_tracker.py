import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date
import json

st.set_page_config(page_title="Wheel Strategy Tracker", layout="wide")
st.title("\U0001F6DE Wheel Strategy Tracker (Google Sheets)")

# --- Google Sheets Setup ---
SHEET_NAME = "Wheel Strategy Trades"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Use secrets when running on Streamlit Cloud
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# --- Load data from Google Sheets ---
data = sheet.get_all_records()
df = pd.DataFrame(data)
df.columns = df.columns.str.strip()  # Remove leading/trailing spaces from column headers

# Parse date columns
for col in ["Open Date", "Close/Assignment Date", "Expiration"]:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")

if "Premium" in df.columns:
    df["Premium"] = pd.to_numeric(df["Premium"], errors="coerce").fillna(0)
if "Qty" in df.columns:
    df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(0)

# --- Trade Entry Form ---
st.sidebar.header("➕ Add New Trade")
with st.sidebar.form("trade_form"):
    ticker = st.text_input("Ticker", value="SPY").upper()
    trade_type = st.selectbox("Trade Type", ["Short Put", "Assignment", "Covered Call"])
    open_date = st.date_input("Open Date", value=date.today())
    close_date = st.date_input("Close/Assignment Date", value=date.today())
    strike = st.number_input("Strike Price", step=0.5)
    premium = st.number_input("Premium Received", step=0.01)
    qty = st.number_input("Contracts (100s)", step=1, value=1)
    expiration = st.date_input("Expiration Date")
    result = st.selectbox("Outcome", ["Open", "Expired Worthless", "Bought Back", "Assigned", "Called Away"])
    price = st.number_input("Underlying Price", step=0.01)
    assigned_price = st.number_input("Assigned Price (if applicable)", step=0.01, value=0.0)
    notes = st.text_area("Notes", "")
    submit = st.form_submit_button("Save Trade")

    if submit:
        new_row = [
            ticker,
            trade_type,
            open_date.strftime("%Y-%m-%d"),
            close_date.strftime("%Y-%m-%d"),
            strike,
            premium,
            qty,
            expiration.strftime("%Y-%m-%d"),
            result,
            price,
            assigned_price,
            notes
        ]
        sheet.append_row(new_row)
        st.sidebar.success("✅ Trade saved to Google Sheets!")

# --- Trade Log ---
st.subheader("\U0001F4CB Trade Log")
try:
    st.dataframe(df.sort_values("Open Date", ascending=False).reset_index(drop=True))
except Exception as e:
    st.error(f"⚠️ Could not sort by Open Date: {e}")
    st.dataframe(df)

# --- Performance Summary ---
st.subheader("\U0001F4C8 Performance Summary")
total_premium = (df["Premium"] * df["Qty"]).sum() if "Premium" in df.columns and "Qty" in df.columns else 0
total_trades = len(df)
assignments = df[df["Result"] == "Assigned"] if "Result" in df.columns else pd.DataFrame()

col1, col2, col3 = st.columns(3)
col1.metric("Total Premium Collected", f"${total_premium:,.2f}")
col2.metric("Total Trades", total_trades)
col3.metric("Assignments", len(assignments))

st.download_button("\U0001F4C5 Download CSV", df.to_csv(index=False), file_name="wheel_trades.csv")
