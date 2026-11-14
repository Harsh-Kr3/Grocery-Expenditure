# 🍽️ Hostel Mess Portal

**Live Application:** [https://grocery-expenditure-m.streamlit.app](https://grocery-expenditure-m.streamlit.app)

A full-stack, cloud-synced web application designed to automate hostel mess meal tracking, daily grocery expenditure logging, per-meal cost calculations, and monthly member settlements. Built with a custom **Deep Aubergine, Ice Silver & Marigold** royal interface, real-time audit logging, and an ultra-compact native PDF archival engine.

---

## ✨ Key Features

### 📊 1. Interactive 31-Day Meal Chart
* **Custom Spreadsheet Editor:** Full 1–31 day grid tracking **Nasta**, **Lunch**, and **Dinner** for every group member.
* **Account-Locked Member Slots:** Member names on the meal chart are strictly locked to verified account holders and cannot be tampered with.
* **Zero-Latency Syncing:** Powered by in-memory session caching and single-trip bulk SQL upserts (`execute_values`).

### 📈 2. Automated Expenditure & Settlement Engine
* **Live Per-Meal Rate Calculation:** Automatically computes total mess expenditure, total meals consumed, and the exact per-meal rate:
  $$\text{Per-Meal Rate} = \frac{\text{Total Mess Expenditure}}{\text{Total Meals Consumed}}$$
* **Member Settlement Overview:** Tracks each member's total grocery contributions against their meal consumption cost to display net balances (**Refund Due** vs. **To Pay**).
* **Individual Member Ledgers:** Dedicated member tabs detailing personal meal counts, itemized grocery purchases, and CSV ledger exports.

### 🔍 3. Activity History & Visual Diff Inspector
* **Complete Audit Trail:** Logs every meal cell edit, grocery purchase addition, entry deletion, and administrative action with user IDs and timestamps.
* **Side-by-Side Visual Change Inspector:** Highlights exact cell modifications (`Old Value ➔ New Value`) on a mini meal chart preview so every change is transparent.

### 📑 4. Monthly Billing Cycles & Native PDF Archiving (`< 10 KB`)
* **Dynamic Month Denotation:** Automatically labels the active billing cycle (e.g., `November 2026`) and dynamically spans multi-month cycles (e.g., `November - December 2026`).
* **Owner-Only Cycle Controls:** Group owners can initialize a new month cycle and close out the previous month behind password verification.
* **Zero-Dependency Native PDF Generator:** Compiles the entire month's settlement summary, 1–31 meal chart, and purchase ledger into a compressed, FlateDecoded PDF (`< 10 KB`) that is saved to the cloud database and automatically downloaded to the owner's device before old raw records are purged.

### 🔐 5. Multi-Group Workspace & Role Security
* **Invite Links & Approval Workflow:** Group owners can share direct invite URLs (`?join=GROUP_CODE`) and approve or decline pending join requests.
* **Dual-Engine Database Architecture:** Seamlessly runs on **Supabase (PostgreSQL)** with persistent connection pooling (`ThreadedConnectionPool`) in production and automatically falls back to **SQLite** (`mess_portal_v2.db`) for isolated local development.

---

## 🛠️ Tech Stack

* **Frontend:** Streamlit, Custom HTML5/CSS3/JS Component (`mess_chart_editor`), Plus Jakarta Sans UI
* **Backend:** Python 3.x, Pandas
* **Cloud Database:** Supabase PostgreSQL (`psycopg2-binary` with `ThreadedConnectionPool`)
* **Local Database:** SQLite3 (automatic fallback for local testing)
* **PDF Engine:** Custom native PDF-1.4 binary generator with `zlib` FlateDecode compression

---

## 📂 Project Structure

```text
Grocery-Expenditure/
├── Frontend/
│   └── index.html          # Custom interactive 31-day meal chart component
├── app.py                  # Main application, database engine, PDF archiver & UI
├── requirements.txt        # Python dependencies for cloud deployment
├── .gitignore              # Protects local databases and secrets from Git tracking
└── README.md               # Project documentation
