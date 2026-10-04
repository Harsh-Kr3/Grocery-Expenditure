import streamlit as st
import json
import os
import pandas as pd
from datetime import date
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Hostel Mess Portal", 
    page_icon="🍽️", 
    layout="wide"
)

# Connect custom component for Meal Chart
_component_path = os.path.join(os.path.dirname(__file__), "frontend")
mess_chart_editor = components.declare_component("mess_chart_editor", path=_component_path)

MEAL_DATA_FILE = "meal_data.json"
EXPENSE_DATA_FILE = "expenditure_data.json"

DAYS = [str(i) for i in range(1, 32)]
MEALS = ["Nasta", "Lunch", "Dinner"]
TOTAL_MEMBERS = 6

# ----------------- DATA PERSISTENCE HELPERS -----------------
def load_meal_data():
    if os.path.exists(MEAL_DATA_FILE):
        try:
            with open(MEAL_DATA_FILE, "r") as f:
                saved = json.load(f)
                if isinstance(saved, list):
                    while len(saved) < TOTAL_MEMBERS:
                        saved.append({
                            "name": "",
                            "meals": {m: {d: ("x" if m == "Nasta" else "") for d in DAYS} for m in MEALS}
                        })
                    return saved[:TOTAL_MEMBERS]
        except Exception:
            pass

    return [
        {
            "name": "",
            "meals": {m: {d: ("x" if m == "Nasta" else "") for d in DAYS} for m in MEALS}
        }
        for _ in range(TOTAL_MEMBERS)
    ]

def save_meal_data(records):
    with open(MEAL_DATA_FILE, "w") as f:
        json.dump(records, f, indent=2)

def load_expense_data():
    if os.path.exists(EXPENSE_DATA_FILE):
        try:
            with open(EXPENSE_DATA_FILE, "r") as f:
                data = json.load(f)
                if "purchases" not in data:
                    data["purchases"] = []
                return data
        except Exception:
            pass
    return {"purchases": []}

def save_expense_data(data):
    with open(EXPENSE_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def calculate_member_meals(records):
    """
    Pulls member names and their maximum meal count directly from the chart.
    """
    member_meals = {}
    total_meals = 0.0

    for idx, rec in enumerate(records):
        name = rec.get("name", "").strip() or f"Member {idx + 1}"
        m_max = 0.0
        meals = rec.get("meals", {})
        for meal_type in MEALS:
            day_dict = meals.get(meal_type, {})
            for d in DAYS:
                val = day_dict.get(d, "")
                if isinstance(val, (int, float)):
                    if val > m_max:
                        m_max = float(val)
                elif isinstance(val, str):
                    clean = val.strip().lower()
                    if clean not in ["x", ""]:
                        try:
                            num = float(clean)
                            if num > m_max:
                                m_max = num
                        except ValueError:
                            pass
        member_meals[name] = m_max
        total_meals += m_max

    return total_meals, member_meals

# Initialize session state
if "records" not in st.session_state:
    st.session_state.records = load_meal_data()

if "expense_data" not in st.session_state:
    st.session_state.expense_data = load_expense_data()

if "current_view" not in st.session_state:
    st.session_state.current_view = "HOME"

# ----------------- HOME VIEW -----------------
if st.session_state.current_view == "HOME":
    st.markdown("<h1 style='text-align: center; margin-top: 30px;'>🍽️ Hostel Mess Management</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Select an option below to proceed</p>", unsafe_allow_html=True)
    st.write("")
    st.write("")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 MESS MEAL CHART", use_container_width=True, type="primary"):
            st.session_state.current_view = "MEAL_CHART"
            st.rerun()

    with col2:
        if st.button("💰 MESS EXPENDITURE", use_container_width=True):
            st.session_state.current_view = "EXPENDITURE"
            st.rerun()

# ----------------- MESS MEAL CHART VIEW -----------------
elif st.session_state.current_view == "MEAL_CHART":
    top_col1, top_col2 = st.columns([1, 8])
    with top_col1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top_col2:
        st.subheader("📋 Mess Meal Chart (1 - 31)")

    updated_records = mess_chart_editor(
        records=st.session_state.records,
        days=DAYS,
        meals=MEALS,
        key="mess_table_editor_stable"
    )

    if updated_records is not None and updated_records != st.session_state.records:
        st.session_state.records = updated_records
        save_meal_data(updated_records)

# ----------------- MESS EXPENDITURE VIEW -----------------
elif st.session_state.current_view == "EXPENDITURE":
    top_col1, top_col2 = st.columns([1, 8])
    with top_col1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top_col2:
        st.subheader("💰 Mess Expenditure & Member Settlements")

    purchases = st.session_state.expense_data.get("purchases", [])
    total_meals, member_meals = calculate_member_meals(st.session_state.records)
    active_members = list(member_meals.keys())

    # Overall Calculation
    total_spent = sum(float(p.get("amount", 0.0)) for p in purchases)
    per_meal_rate = (total_spent / total_meals) if total_meals > 0 else 0.0

    # 1. TOP STATS (Total Purchases Logged removed as requested)
    m1, m2, m3 = st.columns(3)
    m1.metric("💵 Total Mess Expenditure", f"₹{total_spent:,.2f}")
    m2.metric("🍲 Total Meals Eaten", f"{total_meals:.1f}")
    m3.metric("📈 Per-Meal Rate", f"₹{per_meal_rate:.2f}")

    st.divider()

    # 2. SUBTOP MEMBER OVERVIEW TABLE & SUMMARY
    st.markdown("### 📊 Member Summary & Settlement Overview")
    st.caption("Formula: **Net Balance = Total Grocery Bought - (Meals Eaten × Per-Meal Rate)**")

    summary_rows = []
    member_purchases_map = {m: [] for m in active_members}
    for p in purchases:
        buyer = p.get("buyer", "")
        if buyer in member_purchases_map:
            member_purchases_map[buyer].append(p)

    for member in active_members:
        meals_eaten = member_meals[member]
        eaten_cost = meals_eaten * per_meal_rate
        bought_amt = sum(float(p.get("amount", 0.0)) for p in member_purchases_map[member])
        balance = bought_amt - eaten_cost

        summary_rows.append({
            "Member": member,
            "Meals Eaten": meals_eaten,
            "Grocery Bought (₹)": round(bought_amt, 2),
            "Eaten Cost (₹)": round(eaten_cost, 2),
            "Net Balance (₹)": round(balance, 2),
            "Settlement Status": "Refund Due" if balance >= 0 else "To Pay"
        })

    df_summary = pd.DataFrame(summary_rows)

    def color_net_balance(val):
        color = "#15803d" if val >= 0 else "#dc2626"
        return f"color: {color}; font-weight: bold;"

    styled_summary = df_summary.style.map(color_net_balance, subset=["Net Balance (₹)"])
    st.dataframe(styled_summary, use_container_width=True, hide_index=True)

    st.write("")

    # 3. ADD PURCHASE FORM
    with st.expander("➕ Add New Purchase / Expense", expanded=False):
        with st.form("purchase_form", clear_on_submit=True):
            col_d, col_item, col_buyer, col_amt = st.columns([2, 4, 3, 2])
            
            with col_d:
                p_date = st.date_input("Date", value=date.today())
            with col_item:
                p_item = st.text_input("Item Name", placeholder="e.g. Rice, Chicken, Spices, Milk")
            with col_buyer:
                p_buyer = st.selectbox("Purchased By", active_members)
            with col_amt:
                p_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0, value=0.0)

            submitted = st.form_submit_button("Record Purchase Entry", use_container_width=True, type="primary")
            if submitted:
                if p_amount > 0 and p_item.strip():
                    new_entry = {
                        "id": len(purchases) + 1,
                        "date": p_date.strftime("%Y-%m-%d"),
                        "item": p_item.strip(),
                        "buyer": p_buyer,
                        "amount": float(p_amount)
                    }
                    st.session_state.expense_data["purchases"].append(new_entry)
                    save_expense_data(st.session_state.expense_data)
                    st.success(f"Added: {p_item.strip()} (₹{p_amount:.2f}) paid by {p_buyer}")
                    st.rerun()
                else:
                    st.error("Please enter a valid item name and amount.")

    st.divider()

    # 4. INDIVIDUAL MEMBER COLUMNS (EXPENSES WITH DATE, TOTALS, AND WHAT THEY ATE)
    st.markdown("### 📑 Individual Member Purchase Logs & Statements")

    # Tabs for each member to see their specific column/log clearly
    member_tabs = st.tabs(active_members)

    for i, member in enumerate(active_members):
        with member_tabs[i]:
            m_meals = member_meals[member]
            m_eaten_cost = m_meals * per_meal_rate
            m_items = member_purchases_map[member]
            m_bought_total = sum(float(x.get("amount", 0.0)) for x in m_items)
            m_net = m_bought_total - m_eaten_cost

            # Quick metric summary cards for this member
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Meals Eaten", f"{m_meals:.1f}")
            c2.metric("Total Grocery Bought", f"₹{m_bought_total:,.2f}")
            c3.metric("Amount Eaten", f"₹{m_eaten_cost:,.2f}")
            status_label = "Refund" if m_net >= 0 else "Due to Pay"
            c4.metric(f"Balance ({status_label})", f"₹{abs(m_net):,.2f}")

            st.write(f"#### Expense Log for {member}")
            if m_items:
                df_m = pd.DataFrame(m_items)[["date", "item", "amount"]].rename(
                    columns={"date": "Date", "item": "Item Name", "amount": "Amount (₹)"}
                )
                st.dataframe(df_m, use_container_width=True, hide_index=True)
            else:
                st.info(f"No grocery purchases recorded for {member} yet.")

    # Global options
    st.write("")
    col_del, col_csv = st.columns([2, 2])
    with col_del:
        if purchases and st.button("🗑️ Delete Most Recent Purchase"):
            st.session_state.expense_data["purchases"].pop()
            save_expense_data(st.session_state.expense_data)
            st.rerun()

    with col_csv:
        if purchases:
            csv_data = pd.DataFrame(purchases).to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Full Purchase Log (CSV)",
                data=csv_data,
                file_name="mess_purchases.csv",
                mime="text/csv",
                use_container_width=True
            )