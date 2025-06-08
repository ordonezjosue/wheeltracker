import streamlit as st
import pandas as pd
import os
from datetime import date

st.set_page_config(page_title="Wheel Strategy Tracker", layout="wide")
st.title("🛞 Wheel Strategy Tracker")

# --- Path to your GitHub-tracked CSV file ---
CSV_PATH = "data/wheel_trades.csv"

# --- Load or create CSV ---
if os.path.exists(CSV_PATH):
    df = pd.read_csv(CSV_PATH, parse_dates=["Open Date", "Close/Assignment Date"])
else:
    df = pd.DataFrame(columns=[
        "Ticker", "Trade Type", "Open Date", "Close/Assignment Date",
        "Strike", "Premium", "Qty", "Expiration", "Result",
        "Underlying Price", "Assigned Price", "Notes"
    ])
    df.to_csv(CSV_PATH, index=False)

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
        new_row = pd.DataFrame([{
            "Ticker": ticker,
            "Trade Type": trade_type,
            "Open Date": open_date,
            "Close/Assignment Date": close_date,
            "Strike": strike,
            "Premium": premium,
            "Qty": qty,
            "Expiration": expiration,
            "Result": result,
            "Underlying Price": price,
            "Assigned Price": assigned_price,
            "Notes": notes
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(CSV_PATH, index=False)
        st.sidebar.success("✅ Trade saved to wheel_trades.csv!")

# --- Display Trade Log ---
st.subheader("📋 Trade Log")
st.dataframe(df.sort_values("Open Date", ascending=False).reset_index(drop=True))

# --- Performance Summary ---
st.subheader("📈 Performance Summary")
total_premium = (df["Premium"] * df["Qty"]).sum()
total_trades = len(df)
assignments = df[df["Result"] == "Assigned"]

col1, col2, col3 = st.columns(3)
col1.metric("Total Premium Collected", f"${total_premium:,.2f}")
col2.metric("Total Trades", total_trades)
col3.metric("Assignments", len(assignments))

# --- Export Option ---
st.download_button("📥 Download CSV", df.to_csv(index=False), file_name="wheel_trades.csv")
