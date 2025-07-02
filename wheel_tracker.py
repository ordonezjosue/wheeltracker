# thetaflowz_app.py

import streamlit as st
import pandas as pd
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, timedelta
from functools import lru_cache
import json

# ============================
# 🔐 Google Sheets Setup
# ============================
st.set_page_config(page_title="ThetaFlowz Tracker", layout="wide")
st.title("📘 ThetaFlowz Tracker")

SHEET_NAME = "Wheel Strategy Trades"
HEADER_OFFSET = 2  # Data starts from row 2
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ============================
# 📊 Data Loaders
# ============================
@st.cache_data(ttl=600)
def load_sheet(sheet_name):
    try:
        tab = client.open(SHEET_NAME).worksheet(sheet_name)
        records = tab.get_all_records()
        return tab, pd.DataFrame(records)
    except Exception as e:
        st.error(f"❌ Failed to load '{sheet_name}' tab: {e}")
        return None, pd.DataFrame()

@lru_cache(maxsize=128)
def get_current_price(ticker):
    try:
        t = yf.Ticker(ticker)
        return t.fast_info.get("last_price") or t.info.get("regularMarketPrice")
    except:
        return None

# ============================
# 📥 Load Data
# ============================
sheet, df_wheel = load_sheet("Wheel")
pcs_tab, df_pcs = load_sheet("PCS")

required_columns = [
    "Strategy", "Process", "Ticker", "Date", "Strike", "Delta", "DTE", "Credit Collected",
    "Qty", "Expiration", "Result", "Assigned Price", "Current Price at time", "P/L", "Shares Owned", "Notes"
]

# Ensure Wheel columns
for col in required_columns:
    if col not in df_wheel.columns:
        df_wheel[col] = ""

# Ensure PCS columns
pcs_expected = [
    "Date", "Ticker", "Short Put", "Delta", "DTE", "Credit Collected", "Qty",
    "Expiration", "Notes", "Result", "Assigned Price", "Current Price at time",
    "P/L", "Shares Owned", "Long Put", "Width"
]
for col in pcs_expected:
    if col not in df_pcs.columns:
        df_pcs[col] = ""

df_pcs["P/L"] = pd.to_numeric(df_pcs["P/L"], errors="coerce").fillna(0)
df_pcs["Strategy"] = "Put Credit Spread"
df_pcs["Process"] = "Sell PCS"
df_pcs["Current Price at time"] = df_pcs["Ticker"].astype(str).apply(get_current_price)

# ============================
# 📊 Metrics Dashboard
# ============================
if not df_wheel.empty or not df_pcs.empty:
    combined_df = pd.concat([df_wheel, df_pcs], ignore_index=True)
    combined_df["P/L"] = pd.to_numeric(combined_df["P/L"], errors="coerce").fillna(0.0)
    
    st.markdown("### 📊 Performance Summary")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("📄 Total Trades", f"{len(combined_df):,}")
        st.metric("💰 Total Profit", f"${combined_df['P/L'].sum():,.2f}")
    with col2:
        st.metric("🔁 Active Trades", f"{(combined_df['Result'] == 'Open').sum():,}")
        st.metric("💹 Avg P/L per Trade", f"${combined_df['P/L'].mean():.2f}")
    win_rate = round((combined_df['P/L'] > 0).mean() * 100, 2)
    st.metric("✅ Win Rate", f"{win_rate:.2f}%")

# ============================
# ➕ Strategy Entry Sidebar
# ============================
st.sidebar.header("➕ Guided Trade Entry")
strategy = st.sidebar.selectbox("Select Strategy", ["Select", "Wheel Strategy", "Put Credit Spread"])

if strategy == "Put Credit Spread":
    pcs_action = st.sidebar.selectbox("Select PCS Action", ["New Entry", "Buy To Close", "Roll (Coming Soon)"])
    if pcs_action == "New Entry":
        st.subheader("Put Credit Spread Entry")
        with st.form("pcs_form"):
            date_entry = st.date_input("Date", value=date.today())
            ticker = st.text_input("Ticker").upper()
            short_put = st.number_input("Short Put Strike ($)", step=0.5)
            long_put = st.number_input("Long Put Strike ($)", step=0.5)
            credit = st.number_input("Total Credit Collected ($)", step=0.01)
            qty = st.number_input("Contracts (Qty)", step=1, value=1)
            dte = st.number_input("Days to Expiration (DTE)", step=1)
            expiration = date_entry + timedelta(days=int(dte))
            delta = st.number_input("Short Strike Delta (Optional)", step=0.01)
            notes = st.text_area("Notes")
            submit = st.form_submit_button("Save PCS Entry")

            if submit:
                width = round(abs(short_put - long_put), 2)
                row_dict = {
                    "Date": date_entry.strftime("%Y-%m-%d"), "Ticker": ticker,
                    "Short Put": short_put, "Long Put": long_put, "Width": width, "Delta": delta,
                    "Credit Collected": credit, "Qty": qty, "DTE": dte,
                    "Expiration": expiration.strftime("%Y-%m-%d"), "Notes": notes,
                    "Result": "Open", "P/L": "", "Assigned Price": "",
                    "Current Price at time": "", "Shares Owned": ""
                }
                row = [str(row_dict.get(col, "")) for col in pcs_expected]
                pcs_tab.append_row(row)
                st.success("✅ Put Credit Spread saved to PCS tab.")
                st.rerun()

    elif pcs_action == "Buy To Close":
        st.subheader("🔒 Close Existing PCS Position")
        open_pcs = df_pcs[df_pcs["Result"] == "Open"]
        if open_pcs.empty:
            st.warning("No open PCS trades available.")
        else:
            idx = st.selectbox(
                "Select PCS Trade",
                open_pcs.index,
                format_func=lambda i: f"{i} | {open_pcs.loc[i, 'Ticker']} | {open_pcs.loc[i, 'Date']}"
            )
            row = open_pcs.loc[idx]
            close_price = st.number_input("Amount Paid to Close ($)", step=0.01)
            submit = st.button("Finalize Close")

            if submit:
                try:
                    credit = float(str(row["Credit Collected"]).replace("$", "").strip())
                    qty = int(row["Qty"])
                    pl = (credit - close_price) * qty * 100
                    result_col = df_pcs.columns.get_loc("Result") + 1
                    pl_col = df_pcs.columns.get_loc("P/L") + 1
                    pcs_tab.update_cell(idx + HEADER_OFFSET, result_col, "Closed")
                    pcs_tab.update_cell(idx + HEADER_OFFSET, pl_col, round(pl, 2))
                    st.success(f"✅ Trade closed. P/L: ${round(pl, 2):,.2f}")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error updating PCS trade: {e}")

# ============================
# 📋 Display Current Trades
# ============================
st.subheader("📋 Current Trades")
if df_wheel.empty and df_pcs.empty:
    st.warning("No trade data available.")
else:
    combined_df = pd.concat([df_wheel, df_pcs], ignore_index=True)
    combined_df["P/L"] = pd.to_numeric(combined_df["P/L"], errors="coerce").fillna(0.0)
    combined_df["Delta"] = pd.to_numeric(combined_df["Delta"], errors="coerce")
    column_order = [
        "Strategy", "Process", "Ticker", "Date", "Strike",
        "Long Put", "Width", "Delta", "DTE", "Credit Collected", "Qty", "Expiration",
        "Result", "Current Price at time", "Assigned Price", "P/L", "Shares Owned"
    ]
    display_df = combined_df[[col for col in column_order if col in combined_df.columns]].fillna("")
    st.dataframe(display_df)
    st.download_button("💾 Download All Trades as CSV", display_df.to_csv(index=False), file_name="all_trades.csv")
