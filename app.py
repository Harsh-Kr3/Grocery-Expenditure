import os
import json
import uuid
import hashlib
import sqlite3
from datetime import date, datetime
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor, execute_values
except ImportError:
    psycopg2 = None
    pool = None
    execute_values = None

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
    return datetime.now().strftime("%d %b %Y, %I:%M %p")

# ----------------- HIGH-SPEED PERSISTENT CONNECTION POOL -----------------
@st.cache_resource
def get_pg_pool():
    """Keeps warm TCP/SSL connections alive across all Streamlit reruns."""
    if IS_CLOUD_DB:
        return pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=CLOUD_DB_URL,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
    return None

@st.cache_resource
def get_sqlite_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_query(query: str, params=(), fetch="none"):
    """Executes SQL using a warm connection pool with auto-reconnect fallback."""
    if IS_CLOUD_DB:
        pg_Query = query.replace("?", "%s")
        pg_pool = get_pg_pool()
        for attempt in range(2):
            conn = pg_pool.getconn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(pg_Query, params)
                    if fetch == "one":
                        row = cursor.fetchone()
                        conn.commit()
                        result = dict(row) if row else None
                    elif fetch == "all":
                        rows = cursor.fetchall()
                        conn.commit()
                        result = [dict(r) for r in rows]
                    else:
                        conn.commit()
                        result = None
                pg_pool.putconn(conn)
                return result
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                try:
                    pg_pool.putconn(conn, close=True)
                except Exception:
                    pass
                if attempt == 1:
                    st.cache_resource.clear()
                    raise
            except Exception:
                conn.rollback()
                pg_pool.putconn(conn)
                raise
    else:
        conn = get_sqlite_conn()
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

def db_batch_upsert_meals(rows):
    """Inserts/Updates hundreds of meal cells in a single network trip."""
    if not rows:
        return
    if IS_CLOUD_DB:
        pg_pool = get_pg_pool()
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO meal_records (group_id, slot_id, meal_type, day, val)
                    VALUES %s
                    ON CONFLICT (group_id, slot_id, meal_type, day)
                    DO UPDATE SET val = EXCLUDED.val
                    """,
                    rows
                )
            conn.commit()
            pg_pool.putconn(conn)
        except Exception:
            conn.rollback()
            pg_pool.putconn(conn)
            raise
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO meal_records (group_id, slot_id, meal_type, day, val)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(group_id, slot_id, meal_type, day)
            DO UPDATE SET val = excluded.val
            """,
            rows
        )
        conn.commit()

# ----------------- ONE-TIME SCHEMA INITIALIZATION -----------------
@st.cache_resource
def init_db_once():
    """Runs ONLY ONCE when the server starts instead of every button click."""
    if IS_CLOUD_DB:
        pg_pool = get_pg_pool()
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        full_name TEXT NOT NULL,
                        password_hash TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS mess_groups (
                        group_id TEXT PRIMARY KEY,
                        group_name TEXT NOT NULL,
                        max_members INTEGER NOT NULL,
                        owner_id TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS group_memberships (
                        group_id TEXT,
                        user_id TEXT,
                        status TEXT NOT NULL,
                        slot_id INTEGER,
                        joined_at TEXT,
                        PRIMARY KEY (group_id, user_id)
                    );
                    CREATE TABLE IF NOT EXISTS group_slots (
                        group_id TEXT,
                        slot_id INTEGER,
                        name TEXT NOT NULL,
                        PRIMARY KEY (group_id, slot_id)
                    );
                    CREATE TABLE IF NOT EXISTS meal_records (
                        group_id TEXT,
                        slot_id INTEGER,
                        meal_type TEXT,
                        day TEXT,
                        val TEXT,
                        PRIMARY KEY (group_id, slot_id, meal_type, day)
                    );
                    CREATE TABLE IF NOT EXISTS purchases (
                        id SERIAL PRIMARY KEY,
                        group_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        item TEXT NOT NULL,
                        buyer TEXT NOT NULL,
                        amount REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS activity_logs (
                        id SERIAL PRIMARY KEY,
                        group_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        actor_name TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        details TEXT NOT NULL
                    );
                """)
            conn.commit()
        finally:
            pg_pool.putconn(conn)
    else:
        conn = get_sqlite_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mess_groups (
                group_id TEXT PRIMARY KEY,
                group_name TEXT NOT NULL,
                max_members INTEGER NOT NULL,
                owner_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_memberships (
                group_id TEXT,
                user_id TEXT,
                status TEXT NOT NULL,
                slot_id INTEGER,
                joined_at TEXT,
                PRIMARY KEY (group_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS group_slots (
                group_id TEXT,
                slot_id INTEGER,
                name TEXT NOT NULL,
                PRIMARY KEY (group_id, slot_id)
            );
            CREATE TABLE IF NOT EXISTS meal_records (
                group_id TEXT,
                slot_id INTEGER,
                meal_type TEXT,
                day TEXT,
                val TEXT,
                PRIMARY KEY (group_id, slot_id, meal_type, day)
            );
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                date TEXT NOT NULL,
                item TEXT NOT NULL,
                buyer TEXT NOT NULL,
                amount REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                details TEXT NOT NULL
            );
        """)
        conn.commit()
    return True

init_db_once()

# ----------------- AUDIT LOGGING HELPER -----------------
def log_activity(group_id: str, actor_name: str, actor_id: str, action_type: str, details_obj):
    details_str = json.dumps(details_obj) if isinstance(details_obj, (dict, list)) else str(details_obj)
    db_query(
        "INSERT INTO activity_logs (group_id, timestamp, actor_name, actor_id, action_type, details) VALUES (?, ?, ?, ?, ?, ?)",
        (group_id, now_str(), actor_name, actor_id, action_type, details_str)
    )

@st.cache_data(ttl=120, show_spinner=False)
def load_activity_logs(group_id: str):
    return db_query(
        "SELECT id, timestamp, actor_name, actor_id, action_type, details FROM activity_logs WHERE group_id = ? ORDER BY id DESC",
        (group_id,),
        fetch="all"
    )

def parse_log_details(log_row):
    raw = log_row.get("details", "")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"summary": raw, "changes": []}

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

def verify_user_password(user_id: str, password: str) -> bool:
    row = db_query(
        "SELECT user_id FROM users WHERE user_id = ? AND password_hash = ?",
        (user_id.strip().lower(), hash_password(password)),
        fetch="one"
    )
    return bool(row)

def change_user_password(user_id: str, current_pwd: str, new_pwd: str):
    if not verify_user_password(user_id, current_pwd):
        return False, "Current password is incorrect."
    if len(new_pwd) < 4:
        return False, "New password must be at least 4 characters."
    db_query(
        "UPDATE users SET password_hash = ? WHERE user_id = ?",
        (hash_password(new_pwd), user_id)
    )
    return True, "Password updated successfully!"

def delete_entire_group(group_id: str):
    db_query("DELETE FROM meal_records WHERE group_id = ?", (group_id,))
    db_query("DELETE FROM group_slots WHERE group_id = ?", (group_id,))
    db_query("DELETE FROM purchases WHERE group_id = ?", (group_id,))
    db_query("DELETE FROM activity_logs WHERE group_id = ?", (group_id,))
    db_query("DELETE FROM group_memberships WHERE group_id = ?", (group_id,))
    db_query("DELETE FROM mess_groups WHERE group_id = ?", (group_id,))
    st.session_state.pop(f"local_chart_cache_{group_id}", None)
    st.cache_data.clear()

def create_mess_group(group_name: str, max_members: int, owner_id: str, owner_name: str):
    group_id = uuid.uuid4().hex[:8].upper()
    ts = datetime.now().isoformat()
    db_query(
        "INSERT INTO mess_groups (group_id, group_name, max_members, owner_id) VALUES (?, ?, ?, ?)",
        (group_id, group_name.strip(), int(max_members), owner_id)
    )
    db_query(
        "INSERT INTO group_memberships (group_id, user_id, status, slot_id, joined_at) VALUES (?, ?, 'APPROVED', 0, ?)",
        (group_id, owner_id, ts)
    )

    meal_rows = []
    for i in range(int(max_members)):
        initial_name = owner_name.strip() if i == 0 else ""
        db_query(
            "INSERT INTO group_slots (group_id, slot_id, name) VALUES (?, ?, ?)",
            (group_id, i, initial_name)
        )
        for m in MEALS:
            default_val = "x" if m == "Nasta" else ""
            for d in DAYS:
                meal_rows.append((group_id, i, m, d, default_val))

    # Single bulk insert instead of 465+ individual queries
    db_batch_upsert_meals(meal_rows)

    log_activity(group_id, owner_name, owner_id, "GROUP_ADMIN", {
        "summary": f"Created group '{group_name.strip()}' ({max_members} slots)",
        "info": f"Group Owner: {owner_name} (@{owner_id})"
    })
    st.cache_data.clear()
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

    ts = datetime.now().isoformat()
    db_query(
        "INSERT INTO group_memberships (group_id, user_id, status, slot_id, joined_at) VALUES (?, ?, 'PENDING', NULL, ?)",
        (group_id, user_id, ts)
    )
    log_activity(group_id, user_name, user_id, "GROUP_ADMIN", {
        "summary": "Requested to join the group",
        "info": f"User {user_name} (@{user_id}) is awaiting approval."
    })
    st.cache_data.clear()
    return True, "Join request sent to the group owner! Waiting for approval."

@st.cache_data(ttl=120, show_spinner=False)
def get_user_groups(user_id: str):
    rows = db_query("""
        SELECT g.group_id, g.group_name, g.max_members, g.owner_id, m.status, m.slot_id, m.joined_at
        FROM group_memberships m
        JOIN mess_groups g ON m.group_id = g.group_id
        WHERE m.user_id = ?
    """, (user_id,), fetch="all")
    rows.sort(key=lambda r: (r.get("joined_at") or ""), reverse=True)
    return rows

@st.cache_data(ttl=120, show_spinner=False)
def get_group_details(group_id: str):
    return db_query("SELECT * FROM mess_groups WHERE group_id = ?", (group_id,), fetch="one")

@st.cache_data(ttl=60, show_spinner=False)
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
    ts = datetime.now().isoformat()

    db_query("""
        UPDATE group_memberships 
        SET status = 'APPROVED', slot_id = ?, joined_at = ? 
        WHERE group_id = ? AND user_id = ?
    """, (assigned_slot, ts, group_id, target_user_id))

    db_query(
        "UPDATE group_slots SET name = ? WHERE group_id = ? AND slot_id = ?",
        (target_full_name.strip(), group_id, assigned_slot)
    )

    log_activity(group_id, owner_name, owner_id, "GROUP_ADMIN", {
        "summary": f"Approved {target_full_name} into Slot #{assigned_slot + 1}",
        "info": f"Member @{target_user_id} approved by {owner_name}."
    })
    st.session_state.pop(f"local_chart_cache_{group_id}", None)
    st.cache_data.clear()
    return True, f"Approved {target_full_name} (Assigned to Slot #{assigned_slot + 1})"

def reject_member(group_id: str, target_user_id: str, target_full_name: str, owner_name: str, owner_id: str):
    db_query("DELETE FROM group_memberships WHERE group_id = ? AND user_id = ?", (group_id, target_user_id))
    log_activity(group_id, owner_name, owner_id, "GROUP_ADMIN", {
        "summary": f"Rejected join request from {target_full_name}",
        "info": f"Request from @{target_user_id} was declined."
    })
    st.cache_data.clear()

# ----------------- INSTANT CACHED MEAL & EXPENSE OPERATIONS -----------------
@st.cache_data(ttl=120, show_spinner=False)
def _fetch_meal_records_from_db(group_id: str):
    slots = db_query("SELECT slot_id FROM group_slots WHERE group_id = ? ORDER BY slot_id ASC", (group_id,), fetch="all")
    approved_holders = db_query("""
        SELECT m.slot_id, u.full_name
        FROM group_memberships m
        JOIN users u ON m.user_id = u.user_id
        WHERE m.group_id = ? AND m.status = 'APPROVED' AND m.slot_id IS NOT NULL
    """, (group_id,), fetch="all")
    holder_by_slot = {r["slot_id"]: r["full_name"].strip() for r in approved_holders}

    all_meals = db_query("SELECT slot_id, meal_type, day, val FROM meal_records WHERE group_id = ?", (group_id,), fetch="all")
    meal_lookup = {(r["slot_id"], r["meal_type"], r["day"]): r["val"] for r in all_meals}

    records = []
    for s in slots:
        s_id = s["slot_id"]
        locked_account_name = holder_by_slot.get(s_id, "")
        meals_dict = {
            meal: {
                d: meal_lookup.get((s_id, meal, d), "x" if meal == "Nasta" else "")
                for d in DAYS
            }
            for meal in MEALS
        }
        records.append({"name": locked_account_name, "meals": meals_dict})
    return records

def load_meal_records(group_id: str):
    cache_key = f"local_chart_cache_{group_id}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    records = _fetch_meal_records_from_db(group_id)
    st.session_state[cache_key] = records
    return records

def save_meal_records_with_audit(group_id: str, old_records, new_records, actor_name: str, actor_id: str):
    structured_changes = []
    batch_rows = []
    cache_key = f"local_chart_cache_{group_id}"

    for slot_id, new_rec in enumerate(new_records):
        if slot_id >= len(old_records):
            continue
        old_rec = old_records[slot_id]
        locked_member_name = old_rec.get("name", "").strip()
        new_rec["name"] = locked_member_name

        if not locked_member_name:
            continue

        new_meals = new_rec.get("meals", {})
        old_meals = old_rec.get("meals", {})

        for meal in MEALS:
            new_day_dict = new_meals.get(meal, {})
            old_day_dict = old_meals.get(meal, {})
            for d in DAYS:
                new_val = str(new_day_dict.get(d, "")).strip()
                old_val = str(old_day_dict.get(d, "")).strip()
                if new_val != old_val:
                    structured_changes.append({
                        "kind": "cell",
                        "slot_id": slot_id,
                        "member": locked_member_name,
                        "meal": meal,
                        "day": str(d),
                        "old": old_val if old_val != "" else "(blank)",
                        "new": new_val if new_val != "" else "(blank)"
                    })
                    batch_rows.append((group_id, slot_id, meal, d, new_val))

    if batch_rows:
        # Update session memory immediately and send 1 batched query to Supabase
        st.session_state[cache_key] = new_records
        db_batch_upsert_meals(batch_rows)
        affected_members = list(dict.fromkeys(c["member"] for c in structured_changes))
        short_summary = f"Updated {len(structured_changes)} chart cell(s) ({', '.join(affected_members[:2])})"
        log_activity(group_id, actor_name, actor_id, "MEAL_UPDATE", {
            "summary": short_summary,
            "changes": structured_changes
        })
        _fetch_meal_records_from_db.clear()
        load_activity_logs.clear()

    return len(structured_changes)

@st.cache_data(ttl=120, show_spinner=False)
def load_purchases(group_id: str):
    return db_query("SELECT id, date, item, buyer, amount FROM purchases WHERE group_id = ? ORDER BY id ASC", (group_id,), fetch="all")

def add_purchase(group_id: str, date_str: str, item: str, buyer: str, amount: int, actor_name: str, actor_id: str):
    db_query(
        "INSERT INTO purchases (group_id, date, item, buyer, amount) VALUES (?, ?, ?, ?, ?)",
        (group_id, date_str, item, buyer, float(amount))
    )
    log_activity(
        group_id, actor_name, actor_id, "EXPENSE_ADD",
        {
            "summary": f"Added ₹{int(amount):,} for {item}",
            "item": item,
            "amount": int(amount),
            "buyer": buyer,
            "date": date_str
        }
    )
    load_purchases.clear()
    load_activity_logs.clear()

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
            {
                "summary": f"Deleted ₹{int(float(last_row['amount'])):,} ({last_row['item']})",
                "item": last_row["item"],
                "amount": int(float(last_row["amount"])),
                "buyer": last_row["buyer"],
                "date": last_row["date"]
            }
        )
        load_purchases.clear()
        load_activity_logs.clear()
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
    for rec in records:
        name = rec.get("name", "").strip()
        if not name:
            continue
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

# ----------------- PROFILE PANEL HELPER (RIGHT-HAND SIDE) -----------------
def render_profile_popover(current_user, user_groups, active_gid, active_group_info=None):
    with st.popover(f"👤 {current_user['full_name']}", use_container_width=True):
        st.markdown(f"### 👤 {current_user['full_name']}")
        db_badge = "☁️ Cloud DB Connected" if IS_CLOUD_DB else "💻 Local SQLite Mode"
        st.caption(f"**User ID:** `@{current_user['user_id']}` • {db_badge}")
        st.divider()

        st.markdown("**🏘️ My Joined Groups**")
        if user_groups:
            for g in user_groups:
                is_current = (g["group_id"] == active_gid)
                role_icon = "👑" if g["owner_id"] == current_user["user_id"] else "👤"
                if g["status"] == "APPROVED":
                    if is_current:
                        st.markdown(f"✅ **{g['group_name']}** — *Active*")
                    else:
                        if st.button(f"{role_icon} Switch to {g['group_name']}", key=f"prof_sw_{g['group_id']}", use_container_width=True):
                            st.session_state.active_group_id = g["group_id"]
                            st.session_state.show_group_lobby = False
                            st.session_state.delete_grp_step = 0
                            st.session_state.current_view = "HOME"
                            st.rerun()
                else:
                    st.caption(f"⏳ {g['group_name']} — *Pending Approval*")
        else:
            st.caption("No groups joined yet.")

        if st.button("➕ Create / Join Another Group", use_container_width=True):
            st.session_state.show_group_lobby = True
            st.session_state.delete_grp_step = 0
            st.rerun()

        if st.button("🔄 Sync Latest Cloud Data", use_container_width=True):
            if active_gid:
                st.session_state.pop(f"local_chart_cache_{active_gid}", None)
            st.cache_data.clear()
            st.rerun()

        st.divider()

        with st.expander("🔐 Change Password", expanded=False):
            with st.form("change_pwd_form", clear_on_submit=True):
                curr_pwd = st.text_input("Current Password", type="password")
                new_pwd = st.text_input("New Password", type="password")
                conf_pwd = st.text_input("Confirm New Password", type="password")
                if st.form_submit_button("Update Password", use_container_width=True, type="primary"):
                    if not curr_pwd or not new_pwd:
                        st.error("Please fill all fields.")
                    elif new_pwd != conf_pwd:
                        st.error("New passwords do not match.")
                    else:
                        ok, msg = change_user_password(current_user["user_id"], curr_pwd, new_pwd)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)

        if active_group_info and active_group_info["owner_id"] == current_user["user_id"]:
            st.divider()
            with st.expander("🗑️ Delete Group", expanded=(st.session_state.delete_grp_step > 0)):
                if st.session_state.delete_grp_step == 0:
                    st.caption(f"Delete **{active_group_info['group_name']}** permanently.")
                    if st.button("🗑️ Delete This Group", key="init_del_grp", use_container_width=True):
                        st.session_state.delete_grp_step = 1
                        st.rerun()

                elif st.session_state.delete_grp_step == 1:
                    st.markdown("**Step 1: Enter Account Password**")
                    del_pwd = st.text_input("Password", type="password", key="del_grp_pwd_input")
                    c_p1, c_p2 = st.columns(2)
                    if c_p1.button("Verify", key="verify_del_pwd", type="primary", use_container_width=True):
                        if verify_user_password(current_user["user_id"], del_pwd):
                            st.session_state.delete_grp_step = 2
                            st.rerun()
                        else:
                            st.error("Incorrect password.")
                    if c_p2.button("Cancel", key="cancel_del_1", use_container_width=True):
                        st.session_state.delete_grp_step = 0
                        st.rerun()

                elif st.session_state.delete_grp_step == 2:
                    st.warning(
                        f"⚠️ **2nd Verification:** Are you 100% sure you want to permanently delete **{active_group_info['group_name']}** and all its meal & expense data?"
                    )
                    c_y, c_n = st.columns(2)
                    if c_y.button("⚠️ Yes, Delete", key="final_del_grp", type="primary", use_container_width=True):
                        delete_entire_group(active_gid)
                        st.session_state.active_group_id = None
                        st.session_state.delete_grp_step = 0
                        st.toast(f"Group '{active_group_info['group_name']}' deleted.", icon="🗑️")
                        st.rerun()
                    if c_n.button("✖️ Cancel", key="cancel_del_2", use_container_width=True):
                        st.session_state.delete_grp_step = 0
                        st.rerun()

        st.divider()

        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            st.session_state.user = None
            st.session_state.active_group_id = None
            st.session_state.show_group_lobby = False
            st.session_state.confirm_delete_expense = False
            st.session_state.delete_grp_step = 0
            st.rerun()

# ----------------- SESSION & QUERY PARAM INITIALIZATION -----------------
if "user" not in st.session_state:
    st.session_state.user = None
if "active_group_id" not in st.session_state:
    st.session_state.active_group_id = None
if "show_group_lobby" not in st.session_state:
    st.session_state.show_group_lobby = False
if "current_view" not in st.session_state:
    st.session_state.current_view = "HOME"
if "confirm_delete_expense" not in st.session_state:
    st.session_state.confirm_delete_expense = False
if "selected_log_id" not in st.session_state:
    st.session_state.selected_log_id = None
if "delete_grp_step" not in st.session_state:
    st.session_state.delete_grp_step = 0

invite_code_param = st.query_params.get("join", "").strip().upper()

# ==============================================================================
# PHASE 1: AUTHENTICATION
# ==============================================================================
if st.session_state.user is None:
    st.markdown("<h1 style='text-align: center;'>🍽️ Hostel Mess Portal</h1>", unsafe_allow_html=True)
    if invite_code_param:
        grp_info = get_group_details(invite_code_param)
        if grp_info:
            st.info(f"🔗 Invited to join **{grp_info['group_name']}**. Log in or create an account below!")

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
                reg_name = st.text_input("Your Full Name (Shown on Meal Chart)", placeholder="e.g. Harsh Kumar")
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
# AUTO-SELECT MOST RECENTLY JOINED APPROVED GROUP
# ==============================================================================
current_user = st.session_state.user
user_groups = get_user_groups(current_user["user_id"])
approved_groups = [g for g in user_groups if g["status"] == "APPROVED"]

if st.session_state.active_group_id is None and approved_groups and not st.session_state.show_group_lobby:
    st.session_state.active_group_id = approved_groups[0]["group_id"]
    st.session_state.current_view = "HOME"

# ==============================================================================
# PHASE 2: GROUP CREATION / JOIN PAGE
# ==============================================================================
if st.session_state.active_group_id is None or st.session_state.show_group_lobby:
    top_l, top_r = st.columns([7, 2])
    with top_l:
        st.markdown("## 🏠 Create or Join a Mess Group")
    with top_r:
        render_profile_popover(current_user, user_groups, st.session_state.active_group_id, None)

    if approved_groups and st.button("⬅️ Back to My Active Group"):
        st.session_state.show_group_lobby = False
        if st.session_state.active_group_id is None:
            st.session_state.active_group_id = approved_groups[0]["group_id"]
        st.rerun()

    pending_my_groups = [g for g in user_groups if g["status"] == "PENDING"]
    if pending_my_groups:
        for pg in pending_my_groups:
            st.warning(f"⏳ Your request to join **{pg['group_name']}** is awaiting approval from the group owner.")

    st.divider()
    c_create, c_join = st.columns(2)
    with c_create:
        st.subheader("➕ Create a New Mess Group")
        with st.form("create_group_form"):
            g_name = st.text_input("Group / Mess Name", placeholder="e.g. Hostel Block-B Mess")
            g_max = st.number_input("Number of Members", min_value=2, max_value=25, value=5, step=1, format="%d")
            if st.form_submit_button("Create Group", use_container_width=True, type="primary"):
                if g_name.strip():
                    new_gid = create_mess_group(g_name, g_max, current_user["user_id"], current_user["full_name"])
                    st.session_state.active_group_id = new_gid
                    st.session_state.show_group_lobby = False
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
# PHASE 3: ACTIVE GROUP FRONT PAGE
# ==============================================================================
active_gid = st.session_state.active_group_id
group_info = get_group_details(active_gid)
if not group_info:
    st.session_state.active_group_id = None
    st.rerun()

is_owner = (group_info["owner_id"] == current_user["user_id"])

if is_owner:
    hdr_left, hdr_share, hdr_profile = st.columns([6, 2, 2])
    with hdr_left:
        st.markdown(
            f"<h2 style='margin:0;'>🏠 {group_info['group_name']} "
            f"<span style='font-size:15px; color:#94a3b8; font-weight:normal;'>(👑 Owner)</span></h2>",
            unsafe_allow_html=True
        )
    with hdr_share:
        with st.popover("🔗 Share Group Link", use_container_width=True):
            st.markdown("**Share Group Link:**")
            st.code(f"https://grocery-expenditure-m.streamlit.app/?join={active_gid}", language="text")
            st.markdown("**Group Invite Code:**")
            st.code(active_gid, language="text")
    with hdr_profile:
        render_profile_popover(current_user, user_groups, active_gid, group_info)
else:
    hdr_left, hdr_profile = st.columns([8, 2])
    with hdr_left:
        st.markdown(
            f"<h2 style='margin:0;'>🏠 {group_info['group_name']} "
            f"<span style='font-size:15px; color:#94a3b8; font-weight:normal;'>(👤 Member)</span></h2>",
            unsafe_allow_html=True
        )
    with hdr_profile:
        render_profile_popover(current_user, user_groups, active_gid, group_info)

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

# ----------------- 1. GROUP HOME VIEW -----------------
if st.session_state.current_view == "HOME":
    st.markdown("<h3 style='text-align: center; margin-top: 10px;'>🍽️ Mess Portal Dashboard</h3>", unsafe_allow_html=True)
    st.write("")

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
    group_records = load_meal_records(active_gid)
    top1, top2 = st.columns([1, 8])
    with top1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top2:
        st.subheader(f"📋 Mess Meal Chart (1 - 31) — {group_info['max_members']} Members")

    st.caption("🔒 Member names are locked to registered account holders and cannot be edited.")

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
    group_records = load_meal_records(active_gid)
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
    m1.metric("💵 Total Mess Expenditure", f"₹{total_spent:,.0f}")
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
            "Grocery Bought (₹)": int(round(bought_amt)),
            "Eaten Cost (₹)": round(eaten_cost, 2),
            "Net Balance (₹)": round(balance, 2),
            "Settlement Status": "Refund Due" if balance >= 0 else "To Pay"
        })

    df_summary = pd.DataFrame(summary_rows)
    if not df_summary.empty:
        styled_summary = df_summary.style.map(
            lambda val: f"color: {'#15803d' if val >= 0 else '#dc2626'}; font-weight: bold;",
            subset=["Net Balance (₹)"]
        )
        st.dataframe(styled_summary, use_container_width=True, hide_index=True)

    with st.expander("➕ Add New Purchase / Expense", expanded=True):
        with st.form("purchase_form", clear_on_submit=True):
            col_d, col_item, col_buyer, col_amt = st.columns([2, 4, 3, 2])
            with col_d:
                p_date = st.date_input("Date", value=date.today())
            with col_item:
                p_item = st.text_input("Item Name")
            with col_buyer:
                p_buyer = st.selectbox("Purchased By", active_members)
            with col_amt:
                p_amount = st.number_input("₹ Amount", min_value=1, step=1, value=None, format="%d", placeholder="₹")

            if st.form_submit_button("Add Expense", use_container_width=True, type="primary"):
                if p_amount is not None and p_amount > 0 and p_item.strip():
                    add_purchase(
                        active_gid,
                        p_date.strftime("%Y-%m-%d"),
                        p_item.strip(),
                        p_buyer,
                        int(p_amount),
                        current_user["full_name"],
                        current_user["user_id"]
                    )
                    st.session_state.confirm_delete_expense = False
                    st.toast(f"Added ₹{int(p_amount):,} for {p_item.strip()}", icon="✅")
                    st.rerun()
                else:
                    st.error("Please enter an item name and amount.")

    st.divider()
    st.markdown("### 📑 Individual Member Purchase Logs & Statements")
    if active_members:
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
                c2.metric("Total Grocery Bought", f"₹{m_bought_total:,.0f}")
                c3.metric("Amount Eaten", f"₹{m_eaten_cost:,.2f}")
                c4.metric(f"Balance ({'Refund' if m_net >= 0 else 'Due to Pay'})", f"₹{abs(m_net):,.2f}")

                if m_items:
                    df_m = pd.DataFrame(m_items)[["date", "item", "amount"]].copy()
                    df_m["amount"] = df_m["amount"].apply(lambda x: f"₹{int(float(x)):,}")
                    df_m = df_m.rename(columns={"date": "Date", "item": "Item Name", "amount": "Amount (₹)"})
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
                    f"⚠️ **Confirm Deletion of Last Updated Expense?**\n\n"
                    f"- **Item:** {last_exp['item']}\n"
                    f"- **Amount:** ₹{int(float(last_exp['amount'])):,}\n"
                    f"- **Purchased By:** {last_exp['buyer']} (Date: {last_exp['date']})\n\n"
                    f"*This deletion will be permanently logged in the Activity History.*"
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

# ----------------- 4. COMPACT HISTORY + SIDE VISUAL DIFF INSPECTOR -----------------
elif st.session_state.current_view == "HISTORY":
    top1, top2 = st.columns([1, 8])
    with top1:
        if st.button("⬅️ Back"):
            st.session_state.current_view = "HOME"
            st.rerun()
    with top2:
        st.subheader("📜 Activity History & Visual Change Inspector")

    logs = load_activity_logs(active_gid)
    if not logs:
        st.info("No activity recorded for this group yet.")
    else:
        if st.session_state.selected_log_id is None or not any(l["id"] == st.session_state.selected_log_id for l in logs):
            st.session_state.selected_log_id = logs[0]["id"]

        left_col, right_col = st.columns([4, 6], gap="large")

        with left_col:
            st.markdown("#### 🕒 Recent Actions (Click to Inspect)")
            badge_icons = {
                "MEAL_UPDATE": "🍽️",
                "EXPENSE_ADD": "➕",
                "EXPENSE_DELETE": "🗑️",
                "GROUP_ADMIN": "👑"
            }

            for log_item in logs:
                parsed = parse_log_details(log_item)
                icon = badge_icons.get(log_item["action_type"], "📌")
                short_title = parsed.get("summary", log_item["action_type"])
                is_selected = (log_item["id"] == st.session_state.selected_log_id)

                with st.container(border=True):
                    c_info, c_btn = st.columns([4, 1.3])
                    with c_info:
                        st.markdown(f"**{icon} {short_title}**")
                        st.caption(f"👤 {log_item['actor_name']} • 🕒 {log_item['timestamp']}")
                    with c_btn:
                        btn_label = "Viewing" if is_selected else "🔍 View"
                        btn_type = "primary" if is_selected else "secondary"
                        if st.button(btn_label, key=f"sel_log_{log_item['id']}", use_container_width=True, type=btn_type):
                            st.session_state.selected_log_id = log_item["id"]
                            st.rerun()

        with right_col:
            selected_log = next((l for l in logs if l["id"] == st.session_state.selected_log_id), logs[0])
            parsed_sel = parse_log_details(selected_log)
            act_type = selected_log["action_type"]

            with st.container(border=True):
                st.markdown(f"### 🔎 Action Details")
                st.markdown(
                    f"**Performed By:** `{selected_log['actor_name']}` (`@{selected_log['actor_id']}`)  \n"
                    f"**Timestamp:** `{selected_log['timestamp']}`"
                )
                st.divider()

                if act_type == "MEAL_UPDATE":
                    changes = parsed_sel.get("changes", [])
                    if changes:
                        st.markdown("#### 🎨 Highlighted Cell Changes on Meal Chart")
                        cards_html = "<div style='display:flex; flex-direction:column; gap:10px; margin-bottom:18px;'>"
                        for ch in changes:
                            day_badge = f"Day {ch['day']}" if ch.get("day") != "-" else "Member Name"
                            cards_html += f"""
                            <div style="background:#1e293b; border-left:5px solid #f59e0b; padding:12px 16px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; color:#f8fafc;">
                                <div>
                                    <span style="background:#3b82f6; color:white; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:700; margin-right:8px;">{ch.get('member')}</span>
                                    <span style="font-weight:600; font-size:14px; color:#e2e8f0;">{ch.get('meal')}</span>
                                    <span style="color:#fbbf24; font-weight:700; margin-left:8px;">({day_badge})</span>
                                </div>
                                <div style="display:flex; align-items:center; gap:10px;">
                                    <span style="background:#7f1d1d; color:#fca5a5; padding:4px 10px; border-radius:6px; text-decoration:line-through; font-weight:600;">{ch.get('old')}</span>
                                    <span style="color:#94a3b8; font-weight:bold;">➔</span>
                                    <span style="background:#14532d; color:#86efac; padding:4px 12px; border-radius:6px; font-weight:800; border:1px solid #22c55e;">{ch.get('new')}</span>
                                </div>
                            </div>
                            """
                        cards_html += "</div>"
                        st.markdown(cards_html, unsafe_allow_html=True)

                        cell_changes = [c for c in changes if c.get("kind") == "cell"]
                        if cell_changes:
                            st.markdown("#### 🗺️ Meal Chart Highlight Preview (Modified Cells in Orange/Green)")
                            affected_members_map = {}
                            for c in cell_changes:
                                m_name = c["member"]
                                affected_members_map.setdefault(m_name, {})[(c["meal"], str(c["day"]))] = c

                            changed_days = sorted(list({int(c["day"]) for c in cell_changes if str(c["day"]).isdigit()}))
                            preview_html = "<div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; font-size:12px; text-align:center;'>"
                            preview_html += "<tr style='background:#0b57d0; color:white;'><th style='padding:6px; border:1px solid #334155;'>Member</th><th style='padding:6px; border:1px solid #334155;'>Meal</th>"
                            for d_num in changed_days:
                                preview_html += f"<th style='padding:6px; border:1px solid #334155; background:#d97706;'>Day {d_num}</th>"
                            preview_html += "</tr>"

                            for m_name, coords in affected_members_map.items():
                                for m_idx, meal_type in enumerate(MEALS):
                                    preview_html += "<tr>"
                                    if m_idx == 0:
                                        preview_html += f"<td rowspan='3' style='background:#1e3a8a; color:white; font-weight:bold; padding:6px; border:1px solid #334155;'>{m_name}</td>"
                                    preview_html += f"<td style='background:#1d4ed8; color:white; font-weight:600; padding:5px; border:1px solid #334155;'>{meal_type}</td>"
                                    for d_num in changed_days:
                                        key_coord = (meal_type, str(d_num))
                                        if key_coord in coords:
                                            ch_item = coords[key_coord]
                                            preview_html += (
                                                f"<td style='background:#fef08a; color:#0f172a; font-weight:800; padding:6px; border:2px solid #f59e0b;'>"
                                                f"<span style='color:#dc2626; text-decoration:line-through; font-size:11px; margin-right:4px;'>{ch_item['old']}</span>"
                                                f"<span style='color:#15803d; font-size:13px;'>{ch_item['new']}</span>"
                                                f"</td>"
                                            )
                                        else:
                                            preview_html += "<td style='background:#0f172a; color:#64748b; padding:5px; border:1px solid #334155;'>—</td>"
                                    preview_html += "</tr>"
                            preview_html += "</table></div>"
                            st.markdown(preview_html, unsafe_allow_html=True)
                    else:
                        st.info(parsed_sel.get("summary", "Meal chart updated."))

                elif act_type == "EXPENSE_ADD":
                    st.markdown(
                        f"""
                        <div style="background:#064e3b; border-left:6px solid #10b981; padding:16px; border-radius:8px; color:#ecfdf5;">
                            <h4 style="margin:0 0 8px 0; color:#6ee7b7;">➕ New Grocery Expense Added</h4>
                            <p style="margin:4px 0;"><b>Item Purchased:</b> {parsed_sel.get('item', '-')}</p>
                            <p style="margin:4px 0;"><b>Amount:</b> <span style="font-size:18px; font-weight:800; color:#34d399;">₹{parsed_sel.get('amount', 0):,}</span></p>
                            <p style="margin:4px 0;"><b>Paid By:</b> {parsed_sel.get('buyer', '-')}</p>
                            <p style="margin:4px 0;"><b>Purchase Date:</b> {parsed_sel.get('date', '-')}</p>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                elif act_type == "EXPENSE_DELETE":
                    st.markdown(
                        f"""
                        <div style="background:#450a0a; border-left:6px solid #ef4444; padding:16px; border-radius:8px; color:#fef2f2;">
                            <h4 style="margin:0 0 8px 0; color:#fca5a5;">🗑️ Expense Entry Deleted</h4>
                            <p style="margin:4px 0;"><b>Deleted Item:</b> {parsed_sel.get('item', '-')}</p>
                            <p style="margin:4px 0;"><b>Deleted Amount:</b> <span style="font-size:18px; font-weight:800; color:#f87171; text-decoration:line-through;">₹{parsed_sel.get('amount', 0):,}</span></p>
                            <p style="margin:4px 0;"><b>Originally Paid By:</b> {parsed_sel.get('buyer', '-')}</p>
                            <p style="margin:4px 0;"><b>Original Date:</b> {parsed_sel.get('date', '-')}</p>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                else:
                    st.info(f"**{parsed_sel.get('summary', '')}**\n\n{parsed_sel.get('info', '')}")