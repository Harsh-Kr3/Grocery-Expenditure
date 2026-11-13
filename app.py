import os
import sys
import uuid
import hashlib
import sqlite3
from datetime import date, datetime
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Hostel Mess Portal", 
    page_icon="🍽️", 
    layout="wide"
)

# ----------------- CONSTANTS -----------------
DB_FILE = "mess_portal_v2.db"
DAYS = [str(i) for i in range(1, 32)]
MEALS = ["Nasta", "Lunch", "Dinner"]

# Check if Cloud Database URL is configured in Streamlit Secrets or Env
CLOUD_DB_URL = None
try:
    if "DATABASE_URL" in st.secrets:
        CLOUD_DB_URL = st.secrets["DATABASE_URL"]
except Exception:
    pass
if not CLOUD_DB_URL:
    CLOUD_DB_URL = os.environ.get("DATABASE_URL")

IS_CLOUD_DB = bool(CLOUD_DB_URL and psycopg2 is not None)

# ----------------- SECURITY & TIME HELPERS -----------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

# ----------------- UNIVERSAL DATABASE ENGINE -----------------
def get_connection():
    if IS_CLOUD_DB:
        return psycopg2.connect(CLOUD_DB_URL, cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def db_query(query: str, params=(), fetch="none"):
    """Executes SQL seamlessly on both PostgreSQL (Supabase) and SQLite."""
    if IS_CLOUD_DB:
        query = query.replace("?", "%s")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch == "one":
            row = cursor.fetchone()
            conn.commit()
            return dict(row) if row else None
        elif fetch == "all":
            rows = cursor.fetchall()
            conn.commit()
            return [dict(r) for r in rows]
        else:
            conn.commit()
            return None

def init_db():
    serial_type = "SERIAL PRIMARY KEY" if IS_CLOUD_DB else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    db_query("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    db_query("""
        CREATE TABLE IF NOT EXISTS mess_groups (
            group_id TEXT PRIMARY KEY,
            group_name TEXT NOT NULL,
            max_members INTEGER NOT NULL,
            owner_id TEXT NOT NULL
        )
    """)
    db_query("""
        CREATE TABLE IF NOT EXISTS group_memberships (
            group_id TEXT,
            user_id TEXT,
            status TEXT NOT NULL,
            slot_id INTEGER,
            PRIMARY KEY (group_id, user_id)
        )
    """)
    db_query("""
        CREATE TABLE IF NOT EXISTS group_slots (
            group_id TEXT,
            slot_id INTEGER,
            name TEXT NOT NULL,
            PRIMARY KEY (group_id, slot_id)
        )
    """)
    db_query("""
        CREATE TABLE IF NOT EXISTS meal_records (
            group_id TEXT,
            slot_id INTEGER,
            meal_type TEXT,
            day TEXT,
            val TEXT,
            PRIMARY KEY (group_id, slot_id, meal_type, day)
        )
    """)
    db_query(f"""
        CREATE TABLE IF NOT EXISTS purchases (
            id {serial_type},
            group_id TEXT NOT NULL,
            date TEXT NOT NULL,
            item TEXT NOT NULL,
            buyer TEXT NOT NULL,
            amount REAL NOT NULL
        )
    """)
    # 7. Audit / Activity Logs Table
    db_query(f"""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id {serial_type},
            group_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            details TEXT NOT NULL
        )
    """)

init_db()

# ----------------- AUDIT LOGGING HELPER -----------------
def log_activity(group_id: str, actor_name: str, actor_id: str, action_type: str, details: str):
    db_query(
        "INSERT INTO activity_logs (group_id, timestamp, actor_name, actor_id, action_type, details) VALUES (?, ?, ?, ?, ?, ?)",
        (group_id, now_str(), actor_name, actor_id, action_type, details)
    )

def load_activity_logs(group_id: str):
    return db_query(
        "SELECT id, timestamp, actor_name, actor_id, action_type, details FROM activity_logs WHERE group_id = ? ORDER BY id DESC",
        (group_id,),
        fetch="all"
    )

# ----------------- USER & GROUP OPERATIONS -----------------
def register_user(user_id: str, full_name: str, password: str):
    user_id = user_id.strip().lower()
    existing = db_query("SELECT user_id FROM users WHERE user_id = ?", (user_id,), fetch="one")
    if existing:
        return False, "User ID already exists. Please choose another."
    db_query(
        "INSERT INTO users (user_id, full_name, password_hash) VALUES (?, ?, ?)",
        (user_id, full_name.strip(), hash_password(password))
    )
    return True, "Account created successfully!"

def authenticate_user(user_id: str, password: str):
    user_id = user_id.strip().lower()
    return db_query(
        "SELECT user_id, full_name FROM users WHERE user_id = ? AND password_hash = ?",
        (user_id, hash_password(password)),
        fetch="one"
    )

def create_mess_group(group_name: str, max_members: int, owner_id: str, owner_name: str):
    group_id = uuid.uuid4().hex[:8].upper()
    db_query(
        "INSERT INTO mess_groups (group_id, group_name, max_members, owner_id) VALUES (?, ?, ?, ?)",
        (group_id, group_name.strip(), int(max_members), owner_id)
    )
    db_query(
        "INSERT INTO group_memberships (group_id, user_id, status, slot_id) VALUES (?, ?, 'APPROVED', 0)",
        (group_id, owner_id)
    )
    for i in range(int(max_members)):
        initial_name = owner_name if i == 0 else ""
        db_query(
            "INSERT INTO group_slots (group_id, slot_id, name) VALUES (?, ?, ?)",
            (group_id, i, initial_name)
        )
        for m in MEALS:
            for d in DAYS:
                db_query(
                    "INSERT INTO meal_records (group_id, slot_id, meal_type, day, val) VALUES (?, ?, ?, ?, ?)",
                    (group_id, i, m, d, "x" if m == "Nasta" else "")
                )
    log_activity(group_id, owner_name, owner_id, "GROUP_ADMIN", f"Created group '{group_name.strip()}' with {max_members} member slots.")
    return group_id

def request_join_group(group_id: str, user_id: str, user_name: str):
    group_id = group_id.strip().upper()
    group = db_query("SELECT * FROM mess_groups WHERE group_id = ?", (group_id,), fetch="one")
    if not group:
        return False, "Group not found. Please check the Group Code."

    existing = db_query(
        "SELECT status FROM group_memberships WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
        fetch="one"
    )
    if existing:
        return False, f"You already have a membership status ({existing['status']}) in this group."

    db_query(
        "INSERT INTO group_memberships (group_id, user_id, status, slot_id) VALUES (?, ?, 'PENDING', NULL)",
        (group_id, user_id)
    )
    log_activity(group_id, user_name, user_id, "GROUP_ADMIN", f"Requested to join the group.")
    return True, "Join request sent to the group owner! Waiting for approval."

def get_user_groups(user_id: str):
    return db_query("""
        SELECT g.group_id, g.group_name, g.max_members, g.owner_id, m.status, m.slot_id
        FROM group_memberships m
        JOIN mess_groups g ON m.group_id = g.group_id
        WHERE m.user_id = ?
    """, (user_id,), fetch="all")

def get_group_details(group_id: str):
    return db_query("SELECT * FROM mess_groups WHERE group_id = ?", (group_id,), fetch="one")

def get_pending_requests(group_id: str):
    return db_query("""
        SELECT m.user_id, u.full_name
        FROM group_memberships m
        JOIN users u ON m.user_id = u.user_id
        WHERE m.group_id = ? AND m.status = 'PENDING'
    """, (group_id,), fetch="all")

def approve_member(group_id: str, target_user_id: str, target_full_name: str, owner_name: str, owner_id: str):
    grp = db_query("SELECT max_members FROM mess_groups WHERE group_id = ?", (group_id,), fetch="one")
    max_members = grp["max_members"]

    cnt_row = db_query(
        "SELECT COUNT(*) as cnt FROM group_memberships WHERE group_id = ? AND status = 'APPROVED'",
        (group_id,), fetch="one"
    )
    approved_count = cnt_row["cnt"]
    if approved_count >= max_members:
        return False, f"Group is already full ({max_members}/{max_members} members)."

    slots = db_query("SELECT slot_id, name FROM group_slots WHERE group_id = ? ORDER BY slot_id ASC", (group_id,), fetch="all")
    taken_rows = db_query(
        "SELECT slot_id FROM group_memberships WHERE group_id = ? AND status = 'APPROVED' AND slot_id IS NOT NULL",
        (group_id,), fetch="all"
    )
    taken_slots = {r["slot_id"] for r in taken_rows}

    assigned_slot = next((s["slot_id"] for s in slots if s["slot_id"] not in taken_slots), approved_count)

    db_query("""
        UPDATE group_memberships 
        SET status = 'APPROVED', slot_id = ? 
        WHERE group_id = ? AND user_id = ?
    """, (assigned_slot, group_id, target_user_id))

    curr_slot = db_query("SELECT name FROM group_slots WHERE group_id = ? AND slot_id = ?", (group_id, assigned_slot), fetch="one")
    if curr_slot and not curr_slot["name"].strip():
        db_query("UPDATE group_slots SET name = ? WHERE group_id = ? AND slot_id = ?", (target_full_name, group_id, assigned_slot))

    log_activity(group_id, owner_name, owner_id, "GROUP_ADMIN", f"Approved member '{target_full_name}' (@{target_user_id}) into Slot #{assigned_slot + 1}.")
    return True, f"Approved {target_full_name} (Assigned to Slot #{assigned_slot + 1})"

def reject_member(group_id: str, target_user_id: str, target_full_name: str, owner_name: str, owner_id: str):
    db_query("DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?", (group_id, target_user_id))
    log_activity(group_id, owner_name, owner_id, "GROUP_ADMIN", f"Rejected join request from '{target_full_name}' (@{target_user_id}).")

# ----------------- MEAL & EXPENSE DB OPERATIONS (WITH DIFF AUDIT LOGGING) -----------------
def load_meal_records(group_id: str):
    members = db_query("SELECT slot_id, name FROM group_slots WHERE group_id = ? ORDER BY slot_id ASC", (group_id,), fetch="all")
    all_meals = db_query("SELECT slot_id, meal_type, day, val FROM meal_records WHERE group_id = ?", (group_id,), fetch="all")
    
    meal_lookup = {}
    for r in all_meals:
        meal_lookup[(r["slot_id"], r["meal_type"], r["day"])] = r["val"]

    records = []
    for m in members:
        s_id = m["slot_id"]
        meals_dict = {
            meal: {
                d: meal_lookup.get((s_id, meal, d), "x" if meal == "Nasta" else "")
                for d in DAYS
            }
            for meal in MEALS
        }
        records.append({"name": m["name"], "meals": meals_dict})
    return records

def save_meal_records_with_audit(group_id: str, old_records, new_records, actor_name: str, actor_id: str):
    changes_made = []

    for slot_id, new_rec in enumerate(new_records):
        old_rec = old_records[slot_id] if slot_id < len(old_records) else {"name": "", "meals": {}}
        
        old_name = old_rec.get("name", "").strip()
        new_name = new_rec.get("name", "").strip()
        member_label = new_name or old_name or f"Slot #{slot_id + 1}"

        if old_name != new_name:
            changes_made.append(f"Changed Slot #{slot_id + 1} Name: '{old_name or '(empty)'}' → '{new_name or '(empty)'}'")
            db_query("UPDATE group_slots SET name = ? WHERE group_id = ? AND slot_id = ?", (new_name, group_id, slot_id))

        new_meals = new_rec.get("meals", {})
        old_meals = old_rec.get("meals", {})

        for meal in MEALS:
            new_day_dict = new_meals.get(meal, {})
            old_day_dict = old_meals.get(meal, {})
            for d in DAYS:
                new_val = str(new_day_dict.get(d, "")).strip()
                old_val = str(old_day_dict.get(d, "")).strip()
                if new_val != old_val:
                    changes_made.append(
                        f"[{member_label}] {meal} (Day {d}): '{old_val or '(blank)'}' → '{new_val or '(blank)'}'"
                    )
                    db_query("""
                        INSERT INTO meal_records (group_id, slot_id, meal_type, day, val)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(group_id, slot_id, meal_type, day) DO UPDATE SET val = excluded.val
                    """, (group_id, slot_id, meal, d, new_val))

    if changes_made:
        summary_text = "; ".join(changes_made)
        log_activity(group_id, actor_name, actor_id, "MEAL_UPDATE", summary_text)

    return len(changes_made)

def load_purchases(group_id: str):
    return db_query("SELECT id, date, item, buyer, amount FROM purchases WHERE group_id = ? ORDER BY id ASC", (group_id,), fetch="all")

def add_purchase(group_id: str, date_str: str, item: str, buyer: str, amount: float, actor_name: str, actor_id: str):
    db_query(
        "INSERT INTO purchases (group_id, date, item, buyer, amount) VALUES (?, ?, ?, ?, ?)",
        (group_id, date_str, item, buyer, float(amount))
    )
    log_activity(
        group_id, actor_name, actor_id, "EXPENSE_ADD",
        f"Added expense: '{item}' of ₹{float(amount):,.2f} (Purchased by {buyer} on {date_str})"
    )

def delete_last_purchase(group_id: str, actor_name: str, actor_id: str):
    last_row = db_query(
        "SELECT id, date, item, buyer, amount FROM purchases WHERE group_id = ? ORDER BY id DESC LIMIT 1",
        (group_id,),
        fetch="one"
    )
    if last_row:
        db_query("DELETE FROM purchases WHERE id = ?", (last_row["id"],))
        log_activity(
            group_id, actor_name, actor_id, "EXPENSE_DELETE",
            f"Deleted last expense: '{last_row['item']}' of ₹{float(last_row['amount']):,.2f} (Originally bought by {last_row['buyer']} on {last_row['date']})"
        )
        return last_row
    return None

# ----------------- DYNAMIC FRONTEND COMPONENT RESOLVER -----------------
current_dir = os.path.dirname(os.path.abspath(__file__))
component_path = None
for item in os.listdir(current_dir):
    if item.lower() == "frontend" and os.path.isdir(os.path.join(current_dir, item)):
        component_path = os.path.join(current_dir, item)
        break
if not component_path:
    component_path = os.path.join(current_dir, "Frontend")

mess_chart_editor = components.declare_component("mess_chart_editor", path=component_path)

# ----------------- CALCULATION HELPER -----------------
def calculate_member_meals(records):
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

# ----------------- SESSION & QUERY PARAM INITIALIZATION -----------------
if "user" not in st.session_state:
    st.session_state.user = None
if "active_group_id" not in st.session_state:
    st.session_state.active_group_id = None
if "current_view" not in st.session_state:
    st.session_state.current_view = "HOME"
if "confirm_delete_expense" not in st.session_state:
    st.session_state.confirm_delete_expense = False

invite_code_param = st.query_params.get("join", "").strip().upper()

# ==============================================================================
# PHASE 1: AUTHENTICATION
# ==============================================================================
if st.session_state.user is None:
    st.markdown("<h1 style='text-align: center;'>🍽️ Hostel Mess Portal</h1>", unsafe_allow_html=True)
    if invite_code_param:
        grp_info = get_group_details(invite_code_param)
        if grp_info:
            st.info(f"🔗 Invited to join **{grp_info['group_name']}** (`{invite_code_param}`). Log in or create an account below!")

    col_s1, col_auth, col_s2 = st.columns([1, 2, 1])
    with col_auth:
        tab_login, tab_signup = st.tabs(["🔑 Login", "📝 Create Account"])
        with tab_login:
            with st.form("login_form"):
                login_uid = st.text_input("User ID", placeholder="e.g. harsh_01")
                login_pwd = st.text_input("Password", type="password")
                if st.form_submit_button("Login", use_container_width=True, type="primary"):
                    user_obj = authenticate_user(login_uid, login_pwd)
                    if user_obj:
                        st.session_state.user = user_obj
                        if invite_code_param:
                            ok, msg = request_join_group(invite_code_param, user_obj["user_id"], user_obj["full_name"])
                            st.toast(msg)
                        st.rerun()
                    else:
                        st.error("Invalid User ID or Password.")

        with tab_signup:
            with st.form("signup_form"):
                reg_name = st.text_input("Your Full Name", placeholder="e.g. Harsh Kumar")
                reg_uid = st.text_input("Choose a User ID", placeholder="e.g. harsh_01")
                reg_pwd = st.text_input("Create Password", type="password")
                if st.form_submit_button("Sign Up & Continue", use_container_width=True, type="primary"):
                    if not reg_name.strip() or not reg_uid.strip() or not reg_pwd:
                        st.error("All fields are required.")
                    else:
                        ok, msg = register_user(reg_uid, reg_name, reg_pwd)
                        if ok:
                            st.session_state.user = {"user_id": reg_uid.strip().lower(), "full_name": reg_name.strip()}
                            if invite_code_param:
                                ok_j, msg_j = request_join_group(
                                    invite_code_param,
                                    st.session_state.user["user_id"],
                                    st.session_state.user["full_name"]
                                )
                                st.toast(msg_j)
                            st.rerun()
                        else:
                            st.error(msg)
    st.stop()

# ==============================================================================
# PHASE 2: GROUP LOBBY
# ==============================================================================
current_user = st.session_state.user
u_col1, u_col2 = st.columns([6, 2])
with u_col1:
    db_badge = "☁️ Cloud DB Connected" if IS_CLOUD_DB else "💻 Local SQLite Mode"
    st.caption(f"👤 **{current_user['full_name']}** (`@{current_user['user_id']}`) | {db_badge}")
with u_col2:
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.user = None
        st.session_state.active_group_id = None
        st.session_state.confirm_delete_expense = False
        st.rerun()

if st.session_state.active_group_id is None:
    st.markdown("## 🏠 My Mess Groups")
    user_groups = get_user_groups(current_user["user_id"])
    if user_groups:
        cols = st.columns(min(len(user_groups), 3))
        for idx, g in enumerate(user_groups):
            with cols[idx % 3]:
                with st.container(border=True):
                    role_badge = "👑 Owner" if g["owner_id"] == current_user["user_id"] else "👤 Member"
                    st.markdown(f"### {g['group_name']}")
                    st.write(f"**Role:** {role_badge} | **Capacity:** {g['max_members']} members")
                    st.write(f"**Group Code:** `{g['group_id']}`")
                    if g["status"] == "APPROVED":
                        if st.button(f"Open {g['group_name']} ➡️", key=f"open_{g['group_id']}", use_container_width=True, type="primary"):
                            st.session_state.active_group_id = g["group_id"]
                            st.session_state.current_view = "HOME"
                            st.session_state.confirm_delete_expense = False
                            st.rerun()
                    else:
                        st.warning("⏳ Status: **Pending Owner Approval**")
    else:
        st.info("Create a new mess group or join an existing one with a code below!")

    st.divider()
    c_create, c_join = st.columns(2)
    with c_create:
        st.subheader("➕ Create a New Mess Group")
        with st.form("create_group_form"):
            g_name = st.text_input("Group / Mess Name", placeholder="e.g. Hostel Block-B Mess")
            g_max = st.number_input("Number of Members", min_value=2, max_value=25, value=5, step=1)
            if st.form_submit_button("Create Group", use_container_width=True, type="primary"):
                if g_name.strip():
                    new_gid = create_mess_group(g_name, g_max, current_user["user_id"], current_user["full_name"])
                    st.session_state.active_group_id = new_gid
                    st.session_state.current_view = "HOME"
                    st.rerun()
                else:
                    st.error("Please enter a valid group name.")

    with c_join:
        st.subheader("🔗 Join an Existing Group")
        with st.form("join_group_form"):
            join_code_input = st.text_input("Enter Group Invite Code", value=invite_code_param, placeholder="e.g. A1B2C3D4")
            if st.form_submit_button("Send Join Request", use_container_width=True):
                if join_code_input.strip():
                    ok, msg = request_join_group(join_code_input, current_user["user_id"], current_user["full_name"])
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("Please enter a Group Code.")
    st.stop()

# ==============================================================================
# PHASE 3: ACTIVE GROUP WORKSPACE
# ==============================================================================
active_gid = st.session_state.active_group_id
group_info = get_group_details(active_gid)
is_owner = (group_info["owner_id"] == current_user["user_id"])

hdr1, hdr2, hdr3 = st.columns([2, 5, 2])
with hdr1:
    if st.button("🔄 Switch Group"):
        st.session_state.active_group_id = None
        st.session_state.confirm_delete_expense = False
        st.rerun()
with hdr2:
    st.markdown(f"<h3 style='margin:0;'>🏠 {group_info['group_name']} (Code: <code>{active_gid}</code>)</h3>", unsafe_allow_html=True)
with hdr3:
    with st.popover("🔗 Share Group Link", use_container_width=True):
        st.markdown("**Invite Link:**")
        st.code(f"https://grocery-expenditure-m.streamlit.app/?join={active_gid}", language="text")
        st.markdown("**Invite Code:**")
        st.code(active_gid, language="text")

if is_owner:
    pending_list = get_pending_requests(active_gid)
    if pending_list:
        with st.expander(f"🔔 Pending Member Join Requests ({len(pending_list)})", expanded=True):
            for req in pending_list:
                r1, r2, r3 = st.columns([5, 2, 2])
                r1.write(f"👤 **{req['full_name']}** (`@{req['user_id']}`) wants to join.")
                if r2.button("✅ Approve", key=f"app_{req['user_id']}", use_container_width=True, type="primary"):
                    ok, msg = approve_member(
                        active_gid, req["user_id"], req["full_name"],
                        current_user["full_name"], current_user["user_id"]
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                if r3.button("❌ Reject", key=f"rej_{req['user_id']}", use_container_width=True):
                    reject_member(
                        active_gid, req["user_id"], req["full_name"],
                        current_user["full_name"], current_user["user_id"]
                    )
                    st.rerun()

st.divider()
group_records = load_meal_records(active_gid)

# ----------------- 1. GROUP HOME VIEW -----------------
if st.session_state.current_view == "HOME":
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📋 MESS MEAL CHART", use_container_width=True, type="primary"):
            st.session_state.current_view = "MEAL_CHART"
            st.rerun()
    with col2:
        if st.button("💰 MESS EXPENDITURE", use_container_width=True):
            st.session_state.current_view = "EXPENDITURE"
            st.session_state.confirm_delete_expense = False
            st.rerun()
    with col3:
        if st.button("📜 ACTIVITY HISTORY", use_container_width=True):
            st.session_state.current_view = "HISTORY"
            st.rerun()

# ----------------- 2. MESS MEAL CHART VIEW -----------------
elif st.session_state.current_view == "MEAL_CHART":
    top1, top2 = st.columns([1, 8])
    with top1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top2:
        st.subheader(f"📋 Mess Meal Chart (1 - 31) — {group_info['max_members']} Members")

    updated_records = mess_chart_editor(
        records=group_records,
        days=DAYS,
        meals=MEALS,
        key=f"mess_editor_{active_gid}"
    )

    if updated_records is not None and updated_records != group_records:
        num_changes = save_meal_records_with_audit(
            active_gid,
            group_records,
            updated_records,
            current_user["full_name"],
            current_user["user_id"]
        )
        if num_changes > 0:
            st.toast(f"Saved {num_changes} change(s) & logged to Activity History!", icon="💾")
            st.rerun()

# ----------------- 3. MESS EXPENDITURE VIEW -----------------
elif st.session_state.current_view == "EXPENDITURE":
    top1, top2 = st.columns([1, 8])
    with top1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.session_state.confirm_delete_expense = False
            st.rerun()
    with top2:
        st.subheader("💰 Mess Expenditure & Member Settlements")

    purchases = load_purchases(active_gid)
    total_meals, member_meals = calculate_member_meals(group_records)
    active_members = list(member_meals.keys())

    total_spent = sum(float(p.get("amount", 0.0)) for p in purchases)
    per_meal_rate = (total_spent / total_meals) if total_meals > 0 else 0.0

    m1, m2, m3 = st.columns(3)
    m1.metric("💵 Total Mess Expenditure", f"₹{total_spent:,.2f}")
    m2.metric("🍲 Total Meals Eaten", f"{total_meals:.1f}")
    m3.metric("📈 Per-Meal Rate", f"₹{per_meal_rate:.2f}")

    st.divider()
    st.markdown("### 📊 Member Summary & Settlement Overview")

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
    styled_summary = df_summary.style.map(
        lambda val: f"color: {'#15803d' if val >= 0 else '#dc2626'}; font-weight: bold;",
        subset=["Net Balance (₹)"]
    )
    st.dataframe(styled_summary, use_container_width=True, hide_index=True)

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

            if st.form_submit_button("Record Purchase Entry", use_container_width=True, type="primary"):
                if p_amount > 0 and p_item.strip():
                    add_purchase(
                        active_gid,
                        p_date.strftime("%Y-%m-%d"),
                        p_item.strip(),
                        p_buyer,
                        p_amount,
                        current_user["full_name"],
                        current_user["user_id"]
                    )
                    st.session_state.confirm_delete_expense = False
                    st.rerun()
                else:
                    st.error("Please enter a valid item name and amount.")

    st.divider()
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
            c4.metric(f"Balance ({'Refund' if m_net >= 0 else 'Due to Pay'})", f"₹{abs(m_net):,.2f}")

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
        if purchases:
            if not st.session_state.confirm_delete_expense:
                if st.button("🗑️ Delete Most Recent Purchase", use_container_width=True):
                    st.session_state.confirm_delete_expense = True
                    st.rerun()
            else:
                last_exp = purchases[-1]
                st.warning(
                    f"⚠️ **Are you sure you want to delete the last added expense?**\n\n"
                    f"- **Item:** {last_exp['item']}\n"
                    f"- **Amount:** ₹{float(last_exp['amount']):,.2f}\n"
                    f"- **Purchased By:** {last_exp['buyer']} (Date: {last_exp['date']})\n\n"
                    f"*Note: This deletion will be recorded in the group Activity History.*"
                )
                c_yes, c_no = st.columns(2)
                if c_yes.button("⚠️ Yes, Permanently Delete", type="primary", use_container_width=True):
                    delete_last_purchase(active_gid, current_user["full_name"], current_user["user_id"])
                    st.session_state.confirm_delete_expense = False
                    st.toast("Last purchase deleted & recorded in History.", icon="🗑️")
                    st.rerun()
                if c_no.button("✖️ Cancel", use_container_width=True):
                    st.session_state.confirm_delete_expense = False
                    st.rerun()

    with col_csv:
        if purchases:
            csv_data = pd.DataFrame(purchases).to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Full Purchase Log (CSV)",
                data=csv_data,
                file_name=f"mess_purchases_{active_gid}.csv",
                mime="text/csv",
                use_container_width=True
            )

# ----------------- 4. ACTIVITY & AUDIT HISTORY VIEW -----------------
elif st.session_state.current_view == "HISTORY":
    top1, top2 = st.columns([1, 8])
    with top1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top2:
        st.subheader("📜 Group Activity & Audit History")

    st.caption("Every meal chart edit, name change, expense addition, and expense deletion made by any group member is permanently logged here.")

    logs = load_activity_logs(active_gid)
    if logs:
        df_logs = pd.DataFrame(logs)

        f_col1, f_col2 = st.columns(2)
        with f_col1:
            action_types = ["All Actions"] + sorted(df_logs["action_type"].unique().tolist())
            selected_action = st.selectbox("Filter by Action Type:", action_types)
        with f_col2:
            actors = ["All Members"] + sorted(df_logs["actor_name"].unique().tolist())
            selected_actor = st.selectbox("Filter by Member:", actors)

        filtered_df = df_logs.copy()
        if selected_action != "All Actions":
            filtered_df = filtered_df[filtered_df["action_type"] == selected_action]
        if selected_actor != "All Members":
            filtered_df = filtered_df[filtered_df["actor_name"] == selected_actor]

        display_logs = filtered_df[["timestamp", "actor_name", "actor_id", "action_type", "details"]].rename(
            columns={
                "timestamp": "Timestamp",
                "actor_name": "Member Name",
                "actor_id": "User ID",
                "action_type": "Action Category",
                "details": "Change Details (Before → After)"
            }
        )
        st.dataframe(display_logs, use_container_width=True, hide_index=True)

        csv_history = display_logs.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Audit History (CSV)",
            data=csv_history,
            file_name=f"mess_audit_history_{active_gid}.csv",
            mime="text/csv"
        )
    else:
        st.info("No activity recorded for this group yet.")