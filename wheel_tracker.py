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

# Ensure required columns exist
required_columns = [
    "Strategy", "Process", "Ticker", "Date", "Strike", "Delta", "DTE", "Credit Collected",
    "Qty", "Expiration", "Result", "Assigned Price", "Current Price at time", "P/L", "Shares Owned", "Notes"
]
existing_columns = df.columns.tolist()
for col in required_columns:
    if col not in existing_columns:
        df[col] = ""

# --- Trade Entry Logic ---
st.sidebar.header("➕ Guided Trade Entry")
strategy = st.sidebar.selectbox("Select Strategy", ["Select", "Wheel Strategy"])

if strategy == "Wheel Strategy":
    step = st.sidebar.selectbox("Step in the Wheel", ["Select", "Sell Put", "Assignment", "Covered Call", "Called Away"])

    if step == "Sell Put":
        st.subheader("Sell Put Entry")
        with st.form("sell_put_form"):
            date_entry = st.date_input("Date", value=date.today())
            ticker = st.text_input("Ticker", value="SPY").upper()
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

    elif step == "Assignment":
        st.subheader("Assignment Entry")
        puts = df[(df["Strategy"] == "Wheel Strategy") & (df["Process"] == "Sell Put") & (df["Result"] == "Open")]
        if puts.empty:
            st.warning("No open puts available for assignment.")
        else:
            selected = st.selectbox("Select Put to Assign", puts.index)
            row = puts.loc[selected]
            assigned_price = st.number_input("Assigned Price", value=float(row["Strike"]), format="%.2f")
            current_price = get_current_price(row["Ticker"])
            qty = int(row["Qty"])
            shares_owned = qty * 100
            submit = st.button("Save Assignment")
            if submit:
                sheet.update_cell(selected + 2, df.columns.get_loc("Result") + 1, "Assigned")
                sheet.update_cell(selected + 2, df.columns.get_loc("Assigned Price") + 1, assigned_price)
                sheet.update_cell(selected + 2, df.columns.get_loc("Shares Owned") + 1, shares_owned)
                row_data = [
                    "Wheel Strategy", "Assignment", row["Ticker"], date.today().strftime("%Y-%m-%d"), row["Strike"], row["Delta"],
                    row["DTE"], row["Credit Collected"], qty, row["Expiration"], "Assigned",
                    assigned_price, current_price, "", shares_owned, ""
                ]
                sheet.append_row([str(x) for x in row_data])
                st.success("✅ Assignment saved. Ready to sell covered calls.")
                st.rerun()

    elif step == "Covered Call":
        st.subheader("Covered Call Entry")
        assignments = df[(df["Strategy"] == "Wheel Strategy") & (df["Process"] == "Assignment") & (df["Result"] == "Assigned")]
        if assignments.empty:
            st.warning("No assigned positions found.")
        else:
            idx = st.selectbox("Select Assigned Position", assignments.index)
            row = assignments.loc[idx]
            ticker = row["Ticker"]
            qty = int(row["Qty"])
            assigned_price = float(row["Assigned Price"])
            cc_strike = st.number_input("Covered Call Strike", step=0.5)
            cc_credit = st.number_input("Credit Collected ($)", step=0.01)
            cc_dte = st.number_input("Days to Expiration", step=1)
            cc_expiration = date.today() + timedelta(days=int(cc_dte))
            result = st.selectbox("Result", ["Open", "Called Away"])
            finalize = st.checkbox("Finalize Wheel and Calculate P/L")
            submit = st.button("Save Covered Call")
            if submit:
                put = df[(df["Process"] == "Sell Put") & (df["Ticker"] == ticker)].sort_values("Date", ascending=False).head(1)
                put_credit = float(put["Credit Collected"].values[0]) if not put.empty else 0
                pl = 0
                if result == "Called Away":
                    pl = (put_credit + cc_credit) * qty * 100 + (cc_strike - assigned_price) * qty * 100
                call_row = [
                    "Wheel Strategy", "Covered Call", ticker, date.today().strftime("%Y-%m-%d"), cc_strike, "", "", cc_credit,
                    qty, cc_expiration.strftime("%Y-%m-%d"), result, assigned_price, get_current_price(ticker), round(pl, 2), "", ""
                ]
                sheet.append_row([str(x) for x in call_row])
                st.success("✅ Covered Call saved.")
                st.rerun()

    elif step == "Called Away":
        st.subheader("Finalize Wheel Cycle - Called Away")
        covered_calls = df[(df["Strategy"] == "Wheel Strategy") & (df["Process"] == "Covered Call") & (df["Result"] == "Open")]
        if covered_calls.empty:
            st.warning("No covered calls available to finalize.")
        else:
            idx = st.selectbox("Select Covered Call", covered_calls.index)
            row = covered_calls.loc[idx]
            try:
                ticker = row["Ticker"]
                qty = int(row["Qty"])
                call_strike = float(row["Strike"])
                cc_credit = float(row["Credit Collected"])
                assigned_price = float(row["Assigned Price"])
                put = df[(df["Strategy"] == "Wheel Strategy") & (df["Process"] == "Sell Put") & (df["Ticker"] == ticker)].sort_values("Date", ascending=False).head(1)
                put_credit = float(put["Credit Collected"].values[0]) if not put.empty else 0
                shares_owned = qty * 100
                capital_gain = (call_strike - assigned_price) * shares_owned
                total_credit = (put_credit + cc_credit) * qty * 100
                final_pl = capital_gain + total_credit
                sheet.update_cell(idx + 2, df.columns.get_loc("Result") + 1, "Called Away")
                sheet.update_cell(idx + 2, df.columns.get_loc("P/L") + 1, round(final_pl, 2))
                st.success(f"✅ Wheel finalized. Total P/L: ${round(final_pl, 2):,.2f}")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error finalizing: {e}")

# --- Chart ---
st.subheader("\U0001F4CB Current Trades")
if df.empty:
    st.warning("No trade data available.")
else:
    df["P/L"] = pd.to_numeric(df.get("P/L", 0), errors="coerce").fillna(0.0)
    st.dataframe(df.drop(columns=["Notes"], errors="ignore"))

st.download_button("\U0001F4BE Download All Trades as CSV", df.to_csv(index=False), file_name="wheel_trades.csv")
