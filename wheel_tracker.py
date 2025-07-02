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

for col in required_columns:
    if col not in df_wheel.columns:
        df_wheel[col] = ""

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
# 📂 Tastytrade CSV Upload
# ============================
tt_file = st.sidebar.file_uploader("📥 Upload Tastytrade CSV", type="csv")
df_tt = pd.DataFrame()

if tt_file is not None:
    try:
        df_tt_raw = pd.read_csv(tt_file)
        df_tt_raw.columns = df_tt_raw.columns.str.strip()  # Normalize column names
        df_tt_raw = df_tt_raw[~df_tt_raw["Underlying Symbol"].astype(str).str.contains("/", na=False)].copy()

        pcs_trades = []
        open_trades = {}

        for _, row in df_tt_raw.iterrows():
            symbol = row.get("Underlying Symbol")
            action = row.get("Action")
            date_str = row.get("Date")
            qty = int(row.get("Quantity", 0))
            price = float(row.get("Price", 0))
            strike = float(row.get("Strike Price", 0))
            exp = row.get("Expiration Date")
            leg_id = f"{symbol}_{exp}_{strike}_{'PUT' if 'Put' in str(row.get('Type', '')) else 'CALL'}"

            if action == "SELL_TO_OPEN":
                open_trades[leg_id] = {
                    "Date": date_str, "Ticker": symbol, "Strike": strike, "Qty": abs(qty),
                    "Credit Collected": price * abs(qty), "Expiration": exp
                }
            elif action == "BUY_TO_CLOSE" and leg_id in open_trades:
                entry = open_trades.pop(leg_id)
                pl = (entry["Credit Collected"] - price * abs(qty)) * 100
                pcs_trades.append({
                    "Date": entry["Date"], "Ticker": entry["Ticker"], "Short Put": entry["Strike"],
                    "Delta": "", "DTE": "", "Credit Collected": entry["Credit Collected"],
                    "Qty": entry["Qty"], "Expiration": entry["Expiration"], "Notes": "Imported from Tastytrade",
                    "Result": "Closed", "Assigned Price": "", "Current Price at time": "",
                    "P/L": round(pl, 2), "Shares Owned": "", "Long Put": "", "Width": ""
                })

        if pcs_trades:
            for trade in pcs_trades:
                row = [str(trade.get(col, "")) for col in pcs_expected]
                pcs_tab.append_row(row)
            st.success(f"✅ Imported {len(pcs_trades)} PCS trades from Tastytrade CSV.")

    except Exception as e:
        st.error(f"❌ Failed to process Tastytrade CSV: {e}. Columns found: {list(df_tt_raw.columns) if 'df_tt_raw' in locals() else 'None'}")

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
# 📋 Display Current Trades
# ============================
st.subheader("📋 Current Trades")
if df_wheel.empty and df_pcs.empty:
    st.warning("No trade data available.")
else:
    combined_df = pd.concat([df_wheel, df_pcs], ignore_index=True)
    combined_df["P/L"] = pd.to_numeric(combined_df["P/L"], errors="coerce").fillna(0.0)
    combined_df["Delta"] = pd.to_numeric(combined_df.get("Delta", ""), errors="coerce")
    column_order = [
        "Strategy", "Process", "Ticker", "Date", "Strike",
        "Long Put", "Width", "Delta", "DTE", "Credit Collected", "Qty", "Expiration",
        "Result", "Current Price at time", "Assigned Price", "P/L", "Shares Owned"
    ]
    display_df = combined_df[[col for col in column_order if col in combined_df.columns]].fillna("")
    st.dataframe(display_df)
    st.download_button("💾 Download All Trades as CSV", display_df.to_csv(index=False), file_name="all_trades.csv")
