import os
import sys
import json
from datetime import date
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import database as db

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Hostel Mess Portal", 
    page_icon="🍽️", 
    layout="wide"
)

# ----------------- DATABASE INITIALIZATION -----------------
db.init_db()

# ----------------- SAFE COMPONENT PATH RESOLUTION -----------------
current_dir = os.path.dirname(os.path.abspath(__file__))

# Check for lowercase 'frontend' first, then capitalized 'Frontend'
component_path = os.path.join(current_dir, "frontend")
if not os.path.exists(component_path):
    component_path = os.path.join(current_dir, "Frontend")

if not os.path.exists(component_path) or not os.path.exists(os.path.join(component_path, "index.html")):
    st.error(
        f"🚨 **Component folder missing:** Could not locate `frontend/index.html` at: `{component_path}`.\n\n"
        "Please ensure your `frontend` directory with `index.html` is tracked and pushed to your GitHub repository."
    )
    st.stop()

mess_chart_editor = components.declare_component("mess_chart_editor", path=component_path)

# ----------------- CONSTANTS & GLOBALS -----------------
DAYS = [str(i) for i in range(1, 32)]
MEALS = ["Nasta", "Lunch", "Dinner"]
TOTAL_MEMBERS = 6

def calculate_member_meals(records):
    """
    Computes each member's maximum meal count and total mess meals.
    'x' or empty strings are treated as 0.
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

# ----------------- SESSION STATE -----------------
if "records" not in st.session_state:
    st.session_state.records = db.load_meal_records()

if "current_view" not in st.session_state:
    st.session_state.current_view = "HOME"

# --------------------------------------------------
# 1. HOME VIEW
# --------------------------------------------------
if st.session_state.current_view == "HOME":
    st.markdown("<h1 style='text-align: center; margin-top: 25px;'>🍽️ Hostel Mess Management</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Select a section below to get started</p>", unsafe_allow_html=True)
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

# --------------------------------------------------
# 2. MESS MEAL CHART VIEW
# --------------------------------------------------
elif st.session_state.current_view == "MEAL_CHART":
    top_col1, top_col2 = st.columns([1, 8])
    with top_col1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top_col2:
        st.subheader("📋 Mess Meal Chart (Days 1 - 31)")

    # Render table component
    updated_records = mess_chart_editor(
        records=st.session_state.records,
        days=DAYS,
        meals=MEALS,
        key="mess_table_editor_main"
    )

    if updated_records is not None and updated_records != st.session_state.records:
        st.session_state.records = updated_records
        db.save_meal_records(updated_records)
        st.toast("Saved directly to Database!", icon="💾")

# --------------------------------------------------
# 3. MESS EXPENDITURE VIEW
# --------------------------------------------------
elif st.session_state.current_view == "EXPENDITURE":
    top_col1, top_col2 = st.columns([1, 8])
    with top_col1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top_col2:
        st.subheader("💰 Mess Expenditure & Member Settlements")

    purchases = db.load_purchases()
    total_meals, member_meals = calculate_member_meals(st.session_state.records)
    active_members = list(member_meals.keys())

    # Overall Metrics
    total_spent = sum(float(p.get("amount", 0.0)) for p in purchases)
    per_meal_rate = (total_spent / total_meals) if total_meals > 0 else 0.0

    # Top KPI summary
    m1, m2, m3 = st.columns(3)
    m1.metric("💵 Total Mess Expenditure", f"₹{total_spent:,.2f}")
    m2.metric("🍲 Total Meals Eaten", f"{total_meals:.1f}")
    m3.metric("📈 Per-Meal Rate", f"₹{per_meal_rate:.2f}")

    st.divider()

    # Subtop Member Overview Table
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

    # Add Purchase Form
    with st.expander("➕ Add New Purchase / Expense", expanded=False):
        with st.form("purchase_form", clear_on_submit=True):
            col_d, col_item, col_buyer, col_amt = st.columns([2, 4, 3, 2])
            
            with col_d:
                p_date = st.date_input("Date", value=date.today())
            with col_item:
                p_item = st.text_input("Item Name", placeholder="e.g. Vegetables, Chicken, Masala, Oil")
            with col_buyer:
                p_buyer = st.selectbox("Purchased By", active_members)
            with col_amt:
                p_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0, value=0.0)

            submitted = st.form_submit_button("Record Purchase Entry", use_container_width=True, type="primary")
            if submitted:
                if p_amount > 0 and p_item.strip():
                    db.add_purchase(p_date.strftime("%Y-%m-%d"), p_item.strip(), p_buyer, p_amount)
                    st.success(f"Saved: {p_item.strip()} (₹{p_amount:.2f}) paid by {p_buyer}")
                    st.rerun()
                else:
                    st.error("Please enter a valid item name and amount.")

    st.divider()

    # Individual Member Logs / Columns
    st.markdown("### 📑 Individual Member Purchase Logs & Statements")
    member_tabs = st.tabs(active_members)

    for i, member in enumerate(active_members):
        with member_tabs[i]:
            m_meals = member_meals[member]
            m_eaten_cost = m_meals * per_meal_rate
            m_items = member_purchases_map[member]
            m_bought_total = sum(float(x.get("amount", 0.0)) for x in m_items)
            m_net = m_bought_total - m_eaten_cost

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

    st.write("")
    col_del, col_csv = st.columns([2, 2])
    with col_del:
        if purchases and st.button("🗑️ Delete Most Recent Purchase"):
            db.delete_last_purchase()
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