import streamlit as st
import pandas as pd
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, timedelta
import json

st.set_page_config(page_title="ThetaFlowz Tracker", layout="wide")

# ============================
# 📘 TITLE + GOOGLE SHEETS SETUP
# ============================
st.title("📘 ThetaFlowz Tracker")

SHEET_NAME = "Wheel Strategy Trades"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Load Wheel Strategy Sheet
sheet = client.open(SHEET_NAME).sheet1
try:
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df = df.loc[:, df.columns != '']
    df.columns = pd.Index([str(col).strip() for col in df.columns])
except Exception as e:
    st.error(f"❌ Failed to load Wheel data: {e}")
    df = pd.DataFrame()

# --- Yahoo Finance Price Fetch ---
@st.cache_data(ttl=3600)
def get_current_price(ticker):
    try:
        t = yf.Ticker(ticker)
        return t.fast_info.get("last_price") or t.info.get("regularMarketPrice")
    except:
        return None

# Load PCS Tab
try:
    pcs_tab = client.open(SHEET_NAME).worksheet("PCS")
    pcs_data = pcs_tab.get_all_records()
    df_pcs = pd.DataFrame(pcs_data)

    df_pcs = df_pcs.rename(columns={
        "Date": "Date", "Ticker": "Ticker", "Short Put": "Strike",
        "Delta": "Delta", "DTE": "DTE", "Credit Collected": "Credit Collected",
        "Qty": "Qty", "Expiration": "Expiration", "Notes": "Notes"
    })

    for col in ["Result", "Assigned Price", "Current Price at time", "P/L", "Shares Owned", "Long Put", "Width"]:
        if col not in df_pcs.columns:
            df_pcs[col] = ""

    df_pcs["Result"] = df_pcs["Result"].replace("", "Open")
    df_pcs["P/L"] = pd.to_numeric(df_pcs.get("P/L", 0), errors="coerce").fillna(0)
    df_pcs["Strategy"] = "Put Credit Spread"
    df_pcs["Process"] = "Sell PCS"
    df_pcs["Current Price at time"] = df_pcs["Ticker"].apply(get_current_price)

except Exception as e:
    st.error(f"❌ Failed to load PCS tab: {e}")
    df_pcs = pd.DataFrame()

# ============================
# 📊 METRICS DASHBOARD
# ============================
if not df.empty or not df_pcs.empty:
    combined_df = pd.concat([df, df_pcs], ignore_index=True)
    combined_df["P/L"] = pd.to_numeric(combined_df.get("P/L", 0), errors="coerce").fillna(0.0)

    st.markdown("### 📊 Performance Summary")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("📄 Total Trades", len(combined_df))
        st.metric("💰 Total Profit", f"${combined_df['P/L'].sum():,.2f}")
    with col2:
        st.metric("🔁 Active Trades", (combined_df["Result"] == "Open").sum())
        st.metric("💹 Avg P/L per Trade", f"${combined_df['P/L'].mean():.2f}")

    win_rate = (combined_df["P/L"] > 0).mean() * 100
    st.metric("✅ Win Rate", f"{win_rate:.2f}%")

# Ensure Wheel columns
required_columns = [
    "Strategy", "Process", "Ticker", "Date", "Strike", "Delta", "DTE", "Credit Collected",
    "Qty", "Expiration", "Result", "Assigned Price", "Current Price at time", "P/L", "Shares Owned", "Notes"
]
for col in required_columns:
    if col not in df.columns:
        df[col] = ""

# ============================
# ➕ SIDEBAR STRATEGY SELECTION
# ============================
st.sidebar.header("➕ Guided Trade Entry")
strategy = st.sidebar.selectbox("Select Strategy", ["Select", "Wheel Strategy", "Put Credit Spread"])

# ============================
# 🔁 PCS ENTRY + BUY TO CLOSE
# ============================
if strategy == "Put Credit Spread":
    pcs_action = st.sidebar.selectbox("Select PCS Action", ["New Entry", "Buy To Close", "Roll (Coming Soon)"])
    pcs_sheet = client.open(SHEET_NAME).worksheet("PCS")

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
                row = [
                    date_entry.strftime("%Y-%m-%d"), ticker, dte, expiration.strftime("%Y-%m-%d"),
                    short_put, long_put, width, delta, credit, qty, notes
                ]
                pcs_sheet.append_row([str(x) for x in row])
                st.success("✅ Put Credit Spread saved to PCS tab.")
                st.rerun()

    elif pcs_action == "Buy To Close":
        st.subheader("🔒 Close Existing PCS Position")
        open_pcs = df_pcs[df_pcs["Result"] == "Open"]
        if open_pcs.empty:
            st.warning("No open PCS trades available.")
        else:
            idx = st.selectbox("Select PCS Trade", open_pcs.index, format_func=lambda i: f"{i} | {open_pcs.loc[i, 'Ticker']} | {open_pcs.loc[i, 'Date']}")
            row = open_pcs.loc[idx]
            close_price = st.number_input("Amount Paid to Close ($)", step=0.01)
            submit = st.button("Finalize Close")
            if submit:
                try:
                    credit = float(row["Credit Collected"])
                    qty = int(row["Qty"])
                    pl = (credit - close_price) * qty * 100
                    pcs_tab.update_cell(idx + 2, df_pcs.columns.get_loc("Result") + 1, "Closed")
                    pcs_tab.update_cell(idx + 2, df_pcs.columns.get_loc("P/L") + 1, round(pl, 2))
                    st.success(f"✅ Trade closed. P/L: ${round(pl, 2):,.2f}")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error updating PCS trade: {e}")

# ============================
# 📋 TRADE LOG
# ============================
st.subheader("📋 Current Trades")
if df.empty and df_pcs.empty:
    st.warning("No trade data available.")
else:
    combined_df = pd.concat([df, df_pcs], ignore_index=True)
    combined_df["P/L"] = pd.to_numeric(combined_df.get("P/L", 0), errors="coerce").fillna(0.0)
    st.dataframe(combined_df.drop(columns=["Notes"], errors="ignore"))
    st.download_button("💾 Download All Trades as CSV", combined_df.to_csv(index=False), file_name="all_trades.csv")

# ============================
# ✏️ EDIT / DELETE SECTION
# ============================
st.subheader("✏️ Edit or Delete Trades by Strategy")
strategy_to_edit = st.selectbox("Select Strategy to Edit", ["Select", "Wheel Strategy", "Put Credit Spread"])

if strategy_to_edit == "Wheel Strategy":
    if df.empty:
        st.info("No Wheel Strategy trades available.")
    else:
        edit_index = st.selectbox("Select Wheel Trade", df.index, format_func=lambda i: f"{i} | {df.loc[i, 'Ticker']} | {df.loc[i, 'Date']}", key="wheel_edit_dropdown")
        selected_row = df.loc[edit_index]
        with st.form("edit_wheel_form"):
            edited = {col: st.text_input(col, value=str(selected_row[col]), key=f"wheel_{col}") for col in df.columns}
            action = st.radio("Action", ["Edit", "Delete"], key="wheel_action")
            confirm = st.form_submit_button("Submit Wheel Change")
            if confirm:
                row_number = edit_index + 2
                if action == "Delete":
                    sheet.delete_rows(row_number)
                    st.success("✅ Wheel trade deleted.")
                else:
                    for i, col in enumerate(df.columns):
                        sheet.update_cell(row_number, i + 1, edited[col])
                    st.success("✅ Wheel trade updated.")
                st.rerun()

elif strategy_to_edit == "Put Credit Spread":
    try:
        pcs_tab = client.open(SHEET_NAME).worksheet("PCS")
        pcs_data = pcs_tab.get_all_records()
        df_pcs_edit = pd.DataFrame(pcs_data)
        for col in ["Result", "P/L", "Delta", "Qty", "Credit Collected", "Ticker", "Date"]:
            if col not in df_pcs_edit.columns:
                df_pcs_edit[col] = ""
    except Exception as e:
        st.error(f"❌ Failed to load PCS data: {e}")
        df_pcs_edit = pd.DataFrame()

    if df_pcs_edit.empty:
        st.info("No PCS trades available.")
    else:
        edit_index_pcs = st.selectbox("Select PCS Trade", df_pcs_edit.index, format_func=lambda i: f"{i} | {df_pcs_edit.loc[i, 'Ticker']} | {df_pcs_edit.loc[i, 'Date']}", key="pcs_edit_dropdown")
        selected_row_pcs = df_pcs_edit.loc[edit_index_pcs]
        with st.form("edit_pcs_form"):
            edited_pcs = {col: st.text_input(col, value=str(selected_row_pcs[col]), key=f"pcs_{col}") for col in df_pcs_edit.columns}
            action_pcs = st.radio("Action", ["Edit", "Delete"], key="pcs_action")
            confirm_pcs = st.form_submit_button("Submit PCS Change")
            if confirm_pcs:
                row_number = edit_index_pcs + 2
                if action_pcs == "Delete":
                    pcs_tab.delete_rows(row_number)
                    st.success("✅ PCS trade deleted.")
                else:
                    for i, col in enumerate(df_pcs_edit.columns):
                        pcs_tab.update_cell(row_number, i + 1, edited_pcs[col])
                    st.success("✅ PCS trade updated.")
                st.rerun()
