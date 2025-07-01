import streamlit as st
import pandas as pd
import gspread
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date, timedelta
import json
import matplotlib.pyplot as plt

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

# Load PCS Tab
try:
    pcs_tab = client.open(SHEET_NAME).worksheet("PCS")
    pcs_data = pcs_tab.get_all_records()
    df_pcs = pd.DataFrame(pcs_data)

    # Standardize PCS columns
    df_pcs = df_pcs.rename(columns={
        "Date": "Date",
        "Ticker": "Ticker",
        "Short Put": "Strike",
        "Delta": "Delta",
        "DTE": "DTE",
        "Credit Collected": "Credit Collected",
        "Qty": "Qty",
        "Expiration": "Expiration",
        "Notes": "Notes"
    })
    df_pcs["Strategy"] = "Put Credit Spread"
    df_pcs["Process"] = "Sell PCS"
    df_pcs["Result"] = "Open"
    df_pcs["Assigned Price"] = ""
    df_pcs["Current Price at time"] = df_pcs["Ticker"].apply(lambda t: yf.Ticker(t).fast_info.get("last_price"))
    df_pcs["P/L"] = 0
    df_pcs["Shares Owned"] = ""
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


# --- Google Sheets Setup ---
SHEET_NAME = "Wheel Strategy Trades"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# --- Yahoo Finance Price Fetch ---
@st.cache_data(ttl=3600)
def get_current_price(ticker):
    try:
        t = yf.Ticker(ticker)
        return t.fast_info.get("last_price") or t.info.get("regularMarketPrice")
    except:
        return None

# --- Load Sheet Data Safely ---
try:
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df = df.loc[:, df.columns != '']
    df.columns = pd.Index([str(col).strip() for col in df.columns])
except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
    df = pd.DataFrame()

# --- Ensure Columns Exist ---
required_columns = [
    "Strategy", "Process", "Ticker", "Date", "Strike", "Delta", "DTE", "Credit Collected",
    "Qty", "Expiration", "Result", "Assigned Price", "Current Price at time", "P/L", "Shares Owned", "Notes"
]
existing_columns = df.columns.tolist()
for col in required_columns:
    if col not in existing_columns:
        df[col] = ""

# --- Sidebar Strategy Selection ---
st.sidebar.header("➕ Guided Trade Entry")
strategy = st.sidebar.selectbox("Select Strategy", ["Select", "Wheel Strategy", "Put Credit Spread"])

# ============================
# 🔁 WHEEL STRATEGY WORKFLOW
# ============================
if strategy == "Wheel Strategy":
    unique_tickers = sorted(df["Ticker"].dropna().unique())
    ticker_option = st.sidebar.selectbox("Select Ticker or Start New", ["New"] + unique_tickers)

    selected_ticker = st.sidebar.text_input("Enter New Ticker").upper() if ticker_option == "New" else ticker_option
    df = df[df["Ticker"] == selected_ticker] if ticker_option != "New" else df

    step = st.sidebar.selectbox("Step in the Wheel", ["Select", "Sell Put", "Assignment", "Covered Call", "Called Away"])

    if step == "Sell Put":
        st.subheader("Sell Put Entry")
        with st.form("sell_put_form"):
            date_entry = st.date_input("Date", value=date.today())
            dte = st.number_input("Days to Expiration (DTE)", step=1)
            expiration = date_entry + timedelta(days=int(dte))
            strike = st.number_input("Strike Price ($)", step=0.5)
            delta = st.number_input("Delta (Optional)", step=0.01)
            credit = st.number_input("Credit Collected ($)", step=0.01)
            qty = st.number_input("Contracts (Qty)", step=1, value=1)
            current_price = get_current_price(selected_ticker)
            notes = st.text_area("Notes")
            submit = st.form_submit_button("Save Entry")

            if submit:
                row = [
                    "Wheel Strategy", "Sell Put", selected_ticker, date_entry.strftime("%Y-%m-%d"), strike, delta,
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
            assigned_price = st.number_input("Assigned Price", value=float(str(row["Strike"])), format="%.2f")
            current_price = get_current_price(row["Ticker"])
            qty = int(row["Qty"])
            shares_owned = qty * 100
            submit = st.button("Save Assignment")
            if submit:
                sheet.update_cell(selected + 2, df.columns.get_loc("Result") + 1, "Shares")
                sheet.update_cell(selected + 2, df.columns.get_loc("Assigned Price") + 1, assigned_price)
                sheet.update_cell(selected + 2, df.columns.get_loc("Shares Owned") + 1, shares_owned)
                row_data = [
                    "Wheel Strategy", "Assignment", row["Ticker"], date.today().strftime("%Y-%m-%d"), row["Strike"], row["Delta"],
                    row["DTE"], row["Credit Collected"], qty, row["Expiration"], "Shares",
                    assigned_price, current_price, "", shares_owned, ""
                ]
                sheet.append_row([str(x) for x in row_data])
                st.success("✅ Assignment saved. You now hold shares.")
                st.rerun()

    elif step == "Covered Call":
        st.subheader("Covered Call Entry")
        assignments = df[(df["Strategy"] == "Wheel Strategy") & (df["Process"] == "Assignment") & (df["Result"] == "Shares")]
        if assignments.empty:
            st.warning("No share holdings found.")
        else:
            idx = st.selectbox("Select Assigned Position", assignments.index)
            row = assignments.loc[idx]
            ticker = row["Ticker"]
            qty = int(row["Qty"])
            assigned_price = float(str(row["Assigned Price"]))
            cc_strike = st.number_input("Covered Call Strike", step=0.5)
            cc_credit = st.number_input("Credit Collected ($)", step=0.01)
            cc_dte = st.number_input("Days to Expiration", step=1)
            cc_expiration = date.today() + timedelta(days=int(cc_dte))
            result = st.selectbox("Result", ["Open", "Called Away"])
            finalize = st.checkbox("Finalize Wheel and Calculate P/L")
            submit = st.button("Save Covered Call")
            if submit:
                put = df[(df["Process"] == "Sell Put") & (df["Ticker"] == ticker)].sort_values("Date", ascending=False).head(1)
                put_credit = float(str(put["Credit Collected"].values[0])) if not put.empty else 0
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
            st.warning("No covered calls available.")
        else:
            idx = st.selectbox("Select Covered Call", covered_calls.index)
            row = covered_calls.loc[idx]
            try:
                ticker = row["Ticker"]
                qty = int(row["Qty"])
                call_strike = float(str(row["Strike"]))
                cc_credit = float(str(row["Credit Collected"]))
                assigned_price = float(str(row["Assigned Price"]))
                put = df[(df["Strategy"] == "Wheel Strategy") & (df["Process"] == "Sell Put") & (df["Ticker"] == ticker)].sort_values("Date", ascending=False).head(1)
                put_credit = float(str(put["Credit Collected"].values[0])) if not put.empty else 0
                shares_owned = qty * 100
                capital_gain = (call_strike - assigned_price) * shares_owned
                total_credit = (put_credit + cc_credit) * qty * 100
                final_pl = capital_gain + total_credit
                sheet.update_cell(idx + 2, df.columns.get_loc("Result") + 1, "Called Away")
                sheet.update_cell(idx + 2, df.columns.get_loc("P/L") + 1, round(final_pl, 2))
                st.success(f"✅ Finalized. P/L: ${round(final_pl, 2):,.2f}")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")

# ============================
# 🔁 PUT CREDIT SPREAD ENTRY
# ============================
elif strategy == "Put Credit Spread":
    st.subheader("Put Credit Spread Entry")

    # Use the 'PCS' worksheet
    pcs_sheet = client.open(SHEET_NAME).worksheet("PCS")

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
                date_entry.strftime("%Y-%m-%d"),  # Date
                ticker,                           # Ticker
                dte,                              # DTE
                expiration.strftime("%Y-%m-%d"),  # Expiration
                short_put,                        # Short Put
                long_put,                         # Long Put
                width,                            # Width
                delta,                            # Delta
                credit,                           # Credit Collected
                qty,                              # Qty
                notes                             # Notes
            ]
            pcs_sheet.append_row([str(x) for x in row])
            st.success("✅ Put Credit Spread saved to PCS tab.")
            st.rerun()


# ============================
# 📋 TRADE LOG & DASHBOARD
# ============================
st.subheader("📋 Current Trades")

# Load PCS tab
try:
    pcs_tab = client.open(SHEET_NAME).worksheet("PCS")
    pcs_data = pcs_tab.get_all_records()
    df_pcs = pd.DataFrame(pcs_data)

    # Standardize column names to match dashboard
    df_pcs = df_pcs.rename(columns={
        "Date": "Date",
        "Ticker": "Ticker",
        "Short Put": "Strike",
        "Delta": "Delta",
        "DTE": "DTE",
        "Credit Collected": "Credit Collected",
        "Qty": "Qty",
        "Expiration": "Expiration",
        "Notes": "Notes"
    })
    df_pcs["Strategy"] = "Put Credit Spread"
    df_pcs["Process"] = "Sell PCS"
    df_pcs["Result"] = "Open"
    df_pcs["Assigned Price"] = ""
    df_pcs["Current Price at time"] = df_pcs["Ticker"].apply(get_current_price)
    df_pcs["P/L"] = 0
    df_pcs["Shares Owned"] = ""
except Exception as e:
    st.error(f"❌ Failed to load PCS tab: {e}")
    df_pcs = pd.DataFrame()

# Combine both Wheel + PCS data
if df.empty and df_pcs.empty:
    st.warning("No trade data available.")
else:
    combined_df = pd.concat([df, df_pcs], ignore_index=True)
    combined_df["P/L"] = pd.to_numeric(combined_df.get("P/L", 0), errors="coerce").fillna(0.0)
    st.dataframe(combined_df.drop(columns=["Notes"], errors="ignore"))
    st.download_button("💾 Download All Trades as CSV", combined_df.to_csv(index=False), file_name="all_trades.csv")



# ============================
# ✏️ EDIT / DELETE TRADES BY STRATEGY
# ============================
st.subheader("✏️ Edit or Delete Trades by Strategy")

strategy_to_edit = st.selectbox("Select Strategy to Edit", ["Select", "Wheel Strategy", "Put Credit Spread"])

if strategy_to_edit != "Select":

    # --- WHEEL STRATEGY EDIT ---
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

    # --- PCS STRATEGY EDIT ---
    elif strategy_to_edit == "Put Credit Spread":
        try:
            pcs_tab = client.open(SHEET_NAME).worksheet("PCS")
            pcs_data = pcs_tab.get_all_records()
            df_pcs_edit = pd.DataFrame(pcs_data)
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
