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
st.sidebar.header("➕ Guided Trade Entry")
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
            submit = st.form_submit_button("Save Entry")

            if submit:
                row = [
                    "Wheel Strategy", "Sell Put", ticker, date_entry.strftime("%Y-%m-%d"), strike, delta,
                    dte, credit, qty, expiration.strftime("%Y-%m-%d"),
                    "Open", current_price, notes
                ]
                sheet.append_row([str(x) for x in row])
                st.success("✅ Sell Put entry saved.")
                st.rerun()

    elif step == "Assignment":
        st.subheader("Assignment Entry")
        required_cols = {"Strategy", "Process", "Result"}

        if df.empty or not required_cols.issubset(df.columns):
            st.warning("Missing required columns in your sheet (Strategy, Process, Result). Please check your header row.")
        else:
            puts = df[
                (df["Strategy"].str.strip().str.lower() == "wheel strategy") &
                (df["Process"].str.strip().str.lower() == "sell put") &
                (df["Result"].str.strip().str.lower() == "open")
            ]
            if puts.empty:
                st.warning("No open puts available for assignment.")
            else:
                assigned_row = st.selectbox("Select Put to Assign", puts.index)
                ticker = puts.loc[assigned_row, "Ticker"]
                date_entry = puts.loc[assigned_row, "Date"]
                strike = puts.loc[assigned_row, "Strike"]
                delta = puts.loc[assigned_row, "Delta"]
                dte = puts.loc[assigned_row, "DTE"]
                credit = puts.loc[assigned_row, "Credit Collected"]
                qty = puts.loc[assigned_row, "Qty"]
                expiration = puts.loc[assigned_row, "Expiration"]
                notes = puts.loc[assigned_row, "Notes"]
                current_price = get_current_price(ticker)

                with st.form("assignment_form"):
                    assigned_price = st.number_input("Assigned Price", value=strike)
                    submit = st.form_submit_button("Save Assignment")
                    if submit:
                        sheet.update_cell(assigned_row + 2, df.columns.get_loc("Result") + 1, "Assigned")
                        sheet.update_cell(assigned_row + 2, df.columns.get_loc("Assigned Price") + 1, assigned_price)
                        st.success("✅ Assignment recorded. Ready for covered call.")

                        row = [
                            "Wheel Strategy", "Assignment", ticker, date.today().strftime("%Y-%m-%d"), strike, delta,
                            dte, credit, qty, expiration, "Assigned", assigned_price, current_price, f"Assignment from row {assigned_row}"
                        ]
                        sheet.append_row([str(x) for x in row])
                        st.rerun()

    elif step == "Covered Call":
        st.subheader("Covered Call Entry")
        assigned = df[
            (df["Strategy"].str.strip().str.lower() == "wheel strategy") &
            (df["Process"].str.strip().str.lower() == "assignment") &
            (df["Result"].str.strip().str.lower() == "assigned")
        ]
        if assigned.empty:
            st.warning("No assigned positions available to sell a covered call.")
        else:
            assigned_row = st.selectbox("Select Assigned Position", assigned.index)
            ticker = assigned.loc[assigned_row, "Ticker"]
            qty = assigned.loc[assigned_row, "Qty"]
            assigned_price = assigned.loc[assigned_row, "Assigned Price"]
            current_price = get_current_price(ticker)

            with st.form("covered_call_form"):
                cc_strike = st.number_input("Covered Call Strike", step=0.5)
                cc_credit = st.number_input("Credit Collected", step=0.01)
                cc_expiration = st.date_input("Expiration Date")
                result = st.selectbox("Result", ["Open", "Called Away", "Expired Worthless"])
                trigger_close = st.checkbox("Finalize Wheel and Calculate Full P/L")
                submit = st.form_submit_button("Save Covered Call")
                if submit:
                    put_credit = 0.0
                    pl = 0.0
                    if trigger_close:
                        matching_put = df[
                            (df["Ticker"] == ticker) &
                            (df["Process"] == "Sell Put")
                        ].sort_values("Date", ascending=False).head(1)
                        if not matching_put.empty:
                            put_credit = float(matching_put["Credit Collected"].values[0])
                            pl = put_credit + cc_credit + (cc_strike - assigned_price)
                    row = [
                        "Wheel Strategy", "Covered Call", ticker, date.today().strftime("%Y-%m-%d"), cc_strike, "", "",
                        cc_credit, qty, cc_expiration.strftime("%Y-%m-%d"),
                        result, assigned_price, current_price, str(round(pl, 2))
                    ]
                    sheet.append_row([str(x) for x in row])
                    st.success("✅ Covered Call entry saved.")
                    st.rerun()

    elif step == "Called Away":
        st.subheader("Finalize Wheel Cycle - Called Away")
        open_calls = df[
            (df["Strategy"].str.lower() == "wheel strategy") &
            (df["Process"].str.lower() == "covered call") &
            (df["Result"].str.lower() == "open")
        ]
        if open_calls.empty:
            st.warning("No covered calls available to finalize.")
        else:
            idx = st.selectbox("Select Covered Call to Finalize", open_calls.index)
            row_data = open_calls.loc[idx]
            ticker = row_data["Ticker"]
            assigned_price = float(row_data["Assigned Price"])
            cc_strike = float(row_data["Strike"])
            cc_credit = float(row_data["Credit Collected"])
            current_price = get_current_price(ticker)
            put_credit = 0.0
            matching_put = df[
                (df["Ticker"] == ticker) &
                (df["Process"] == "Sell Put") &
                (df["Date"] < row_data["Date"])
            ].sort_values("Date", ascending=False).head(1)
            if not matching_put.empty:
                put_credit = float(matching_put["Credit Collected"].values[0])
            final_pl = round(put_credit + cc_credit + (cc_strike - assigned_price), 2)
            with st.form("finalize_wheel"):
                st.write(f"**Put Credit:** ${put_credit}")
                st.write(f"**Covered Call Credit:** ${cc_credit}")
                st.write(f"**Assigned Price:** ${assigned_price}")
                st.write(f"**Call Strike (Shares Called Away):** ${cc_strike}")
                st.write(f"### Final P/L for {ticker}: ${final_pl}")
                finalize = st.form_submit_button("Finalize and Record")
                if finalize:
                    sheet.update_cell(idx + 2, df.columns.get_loc("Result") + 1, "Called Away")
                    sheet.update_cell(idx + 2, df.columns.get_loc("P/L") + 1, final_pl)
                    st.success("✅ Wheel finalized and P/L recorded.")
                    st.rerun()

# --- Existing Data Viewer ---
st.subheader("\U0001F4CB Current Trades")
if df.empty or "Date" not in df.columns:
    st.warning("No valid data found or missing 'Date' column. Please check your sheet format.")
else:
    df["P/L"] = 0.0
    for idx, row in df.iterrows():
        if row["Process"] == "Covered Call" and row["Result"].lower() == "called away":
            try:
                ticker = row["Ticker"]
                assigned_price = float(row["Assigned Price"])
                cc_credit = float(row["Credit Collected"])
                cc_strike = float(row["Strike"])
                put_row = df[
                    (df["Ticker"] == ticker) &
                    (df["Process"] == "Sell Put") &
                    (df["Date"] < row["Date"])
                ].sort_values("Date", ascending=False).head(1)
                put_credit = float(put_row["Credit Collected"].values[0]) if not put_row.empty else 0.0
                pl = put_credit + cc_credit + (cc_strike - assigned_price)
                df.at[idx, "P/L"] = round(pl, 2)
            except Exception as e:
                df.at[idx, "P/L"] = "Error"

    display_df = df.drop(columns=["Notes"], errors="ignore")
    st.dataframe(display_df.sort_values("Date", ascending=False).reset_index(drop=True))

# --- CSV Download ---
st.download_button("\U0001F4BE Download All Trades as CSV", df.to_csv(index=False), file_name="wheel_trades.csv")
