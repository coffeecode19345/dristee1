import streamlit as st
import sqlite3
import io
from PIL import Image
import os
from datetime import datetime
import uuid
import re
import base64
import json
import git
import requests  # Added for GitHub API
from requests.exceptions import RequestException
import traceback
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Fallback for testing
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # GitHub personal access token
REPO_URL = os.getenv("REPO_URL", "https://github.com/your_username/your_repo.git")  # Replace with your repo URL

DB_PATH = "gallery.db"
BACKUP_PATH = "data/db_backup.json"

# -------------------------------
# GitHub Helper Function
# -------------------------------
def _parse_github_repo_info(repo_url):
    """Return (owner, repo) from a repo url like https://github.com/owner/repo.git or git@github.com:owner/repo.git"""
    import re
    if not repo_url:
        return None, None
    # HTTP(S) form
    m = re.search(r'https?://[^/]+/([^/]+)/([^/]+?)(?:\.git)?$', repo_url)
    if m:
        return m.group(1), m.group(2)
    # SSH form
    m = re.search(r'git@[^:]+:([^/]+)/([^/]+?)(?:\.git)?$', repo_url)
    if m:
        return m.group(1), m.group(2)
    # maybe "owner/repo"
    parts = repo_url.strip().split('/')
    if len(parts) == 2:
        return parts[0], parts[1].replace('.git', '')
    return None, None

# -------------------------------
# Backup and Restore Functions
# -------------------------------
def serialize_db():
    """Serialize the SQLite database to a JSON structure."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    data = {
        "folders": [],
        "images": [],
        "surveys": []
    }
    # Serialize folders
    c.execute("SELECT folder, name, age, profession, category FROM folders")
    data["folders"] = [{"folder": r[0], "name": r[1], "age": r[2], "profession": r[3], "category": r[4]} for r in c.fetchall()]
    # Serialize images (convert image_data BLOB to base64)
    c.execute("SELECT name, folder, image_data, download_allowed FROM images")
    data["images"] = [{"name": r[0], "folder": r[1], "image_data": base64.b64encode(r[2]).decode('utf-8'), "download_allowed": r[3]} for r in c.fetchall()]
    # Serialize surveys
    c.execute("SELECT folder, rating, feedback, timestamp FROM surveys")
    data["surveys"] = [{"folder": r[0], "rating": r[1], "feedback": r[2], "timestamp": r[3]} for r in c.fetchall()]
    conn.close()
    return data

def save_backup():
    """Save the serialized database to db_backup.json."""
    data = serialize_db()
    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
    with open(BACKUP_PATH, "w") as f:
        json.dump(data, f)
    commit_backup_api()  # Use API-based commit (preferred)
    # commit_backup()  # Uncomment to use GitPython instead

def restore_db():
    """Restore gallery.db from db_backup.json if it exists — robust to empty/corrupt backups."""
    if not os.path.exists(BACKUP_PATH):
        return

    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        if not raw or not raw.strip():
            st.warning("Backup file exists but is empty — skipping restore.")
            return

        try:
            backup = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Backup file is not valid JSON: {e}. Please check or regenerate {BACKUP_PATH}.")
            return

        # Basic validation
        if not isinstance(backup, dict):
            st.error("Backup JSON root must be an object/dict. Aborting restore.")
            return
        for key in ("folders", "images", "surveys"):
            if key not in backup:
                st.error(f"Backup missing required key '{key}'. Aborting restore.")
                return
            if not isinstance(backup[key], list):
                st.error(f"Backup key '{key}' must be a list. Aborting restore.")
                return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("BEGIN")
            # Recreate schema
            c.execute("DROP TABLE IF EXISTS folders")
            c.execute("DROP TABLE IF EXISTS images")
            c.execute("DROP TABLE IF EXISTS surveys")

            c.execute("""
                CREATE TABLE folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    age INTEGER NOT NULL,
                    profession TEXT NOT NULL,
                    category TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    image_data BLOB NOT NULL,
                    download_allowed BOOLEAN NOT NULL DEFAULT 1,
                    FOREIGN KEY(folder) REFERENCES folders(folder)
                )
            """)
            c.execute("""
                CREATE TABLE surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    feedback TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(folder) REFERENCES folders(folder)
                )
            """)

            # Insert folders with per-row validation (skip bad rows)
            skipped = {"folders":0, "images":0, "surveys":0}
            for idx, fld in enumerate(backup["folders"]):
                try:
                    folder = fld["folder"]
                    name = fld["name"]
                    age = int(fld["age"])
                    profession = fld["profession"]
                    category = fld["category"]
                    c.execute(
                        "INSERT INTO folders (folder, name, age, profession, category) VALUES (?, ?, ?, ?, ?)",
                        (folder, name, age, profession, category)
                    )
                except Exception as e:
                    skipped["folders"] += 1
                    st.warning(f"Skipping malformed folder entry #{idx}: {e}")

            # Insert images (expect base64 image_data)
            for idx, img in enumerate(backup["images"]):
                try:
                    image_name = img["name"]
                    folder = img["folder"]
                    img_b64 = img.get("image_data")
                    if not isinstance(img_b64, str) or not img_b64.strip():
                        raise ValueError("image_data is missing or not a base64 string")
                    image_bytes = base64.b64decode(img_b64)
                    download_allowed = int(img.get("download_allowed", 1))
                    c.execute(
                        "INSERT INTO images (name, folder, image_data, download_allowed) VALUES (?, ?, ?, ?)",
                        (image_name, folder, image_bytes, download_allowed)
                    )
                except Exception as e:
                    skipped["images"] += 1
                    st.warning(f"Skipping malformed image entry #{idx} ({img.get('name')}): {e}")

            # Insert surveys
            for idx, s in enumerate(backup["surveys"]):
                try:
                    folder = s["folder"]
                    rating = int(s["rating"])
                    feedback = s.get("feedback")
                    timestamp = s["timestamp"]
                    c.execute(
                        "INSERT INTO surveys (folder, rating, feedback, timestamp) VALUES (?, ?, ?, ?)",
                        (folder, rating, feedback, timestamp)
                    )
                except Exception as e:
                    skipped["surveys"] += 1
                    st.warning(f"Skipping malformed survey entry #{idx}: {e}")

            conn.commit()
            msg = f"Restore complete. Skipped: folders={skipped['folders']}, images={skipped['images']}, surveys={skipped['surveys']}."
            st.success(msg)
        except Exception as e:
            conn.rollback()
            st.error(f"Failed to restore database: {e}")
            st.error(traceback.format_exc())
        finally:
            conn.close()

    except Exception as e:
        st.error(f"Unexpected error while restoring backup: {e}")
        st.error(traceback.format_exc())

def commit_backup():
    """Commit db_backup.json to GitHub repository using GitPython."""
    if not GITHUB_TOKEN:
        st.warning("GitHub token not provided; db_backup.json not committed. Download manually to persist changes.")
        return
    try:
        repo = git.Repo(".")
        # Configure Git user
        repo.config_writer().set_value("user", "name", "Streamlit App").release()
        repo.config_writer().set_value("user", "email", "streamlit@app.com").release()
        # Add and commit db_backup.json
        repo.index.add([BACKUP_PATH])
        repo.index.commit("Update db_backup.json")
        # Configure remote with token
        origin = repo.remote(name="origin")
        origin.set_url(f"https://{GITHUB_TOKEN}@{REPO_URL.replace('https://', '')}")
        origin.push()
        st.success("Successfully committed db_backup.json to GitHub!")
    except Exception as e:
        st.error(f"Failed to commit backup to GitHub: {str(e)}")
        st.error(traceback.format_exc())

def commit_backup_api():
    """Commit db_backup.json to GitHub using the GitHub API."""
    if not GITHUB_TOKEN:
        st.warning("GitHub token not provided; db_backup.json not committed. Download manually to persist changes.")
        return
    try:
        owner, repo = _parse_github_repo_info(REPO_URL)
        if not owner or not repo:
            st.error(f"Invalid REPO_URL: {REPO_URL}. Cannot parse owner and repo.")
            return

        # Read db_backup.json
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        # GitHub API headers
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        # Get the current file SHA (if it exists)
        sha = None
        try:
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{BACKUP_PATH}",
                headers=headers
            )
            response.raise_for_status()
            sha = response.json().get("sha")
        except RequestException as e:
            if response.status_code != 404:
                st.error(f"Failed to check existing {BACKUP_PATH}: {str(e)}")
                return

        # Commit the file
        payload = {
            "message": "Update db_backup.json",
            "content": content_b64,
            "branch": "main"  # Adjust if your default branch is different (e.g., "master")
        }
        if sha:
            payload["sha"] = sha

        response = requests.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{BACKUP_PATH}",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        st.success("Successfully committed db_backup.json to GitHub via API!")
    except RequestException as e:
        st.error(f"Failed to commit backup to GitHub via API: {str(e)}")
        st.error(traceback.format_exc())

# -------------------------------
# Helper Functions
# -------------------------------
def image_to_base64(image_data):
    """Convert image data (bytes) to base64 string."""
    return base64.b64encode(image_data).decode('utf-8') if isinstance(image_data, bytes) else image_data.encode('utf-8')

def generate_thumbnail(image, size=(100, 100)):
    """Generate a thumbnail for an image."""
    img = image.copy()
    img.thumbnail(size)
    return img

def validate_folder_name(folder):
    """Validate folder name: alphanumeric, underscores, lowercase, 3-20 characters."""
    pattern = r"^[a-z0-9_]{3,20}$"
    return bool(re.match(pattern, folder))

def init_db():
    """Initialize SQLite database and restore from backup if available."""
    restore_db()  # Restore from db_backup.json if it exists
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            profession TEXT NOT NULL,
            category TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            folder TEXT NOT NULL,
            image_data BLOB NOT NULL,
            download_allowed BOOLEAN NOT NULL DEFAULT 1,
            FOREIGN KEY(folder) REFERENCES folders(folder)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder TEXT NOT NULL,
            rating INTEGER NOT NULL,
            feedback TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(folder) REFERENCES folders(folder)
        )
    """)
    default_folders = [
        {"name": "Sarika", "age": 28, "profession": "Photographer", "category": "Artists", "folder": "sarika"},
        {"name": "Jamuna", "age": 32, "profession": "Sculptor", "category": "Artists", "folder": "jamuna"},
    ]
    for folder_data in default_folders:
        c.execute("SELECT COUNT(*) FROM folders WHERE folder = ?", (folder_data["folder"],))
        if c.fetchone()[0] == 0:
            c.execute("""
                INSERT INTO folders (folder, name, age, profession, category)
                VALUES (?, ?, ?, ?, ?)
            """, (folder_data["folder"], folder_data["name"], folder_data["age"],
                  folder_data["profession"], folder_data["category"]))
    conn.commit()
    conn.close()
    save_backup()  # Save backup after initialization

def load_folders(search_query=""):
    """Load folders from database, optionally filtered by search query."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT folder, name, age, profession, category FROM folders WHERE name LIKE ? OR folder LIKE ? OR profession LIKE ? OR category LIKE ?"
    c.execute(query, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
    folders = [{"folder": r[0], "name": r[1], "age": r[2], "profession": r[3], "category": r[4]} for r in c.fetchall()]
    conn.close()
    return folders

def add_folder(folder, name, age, profession, category):
    """Add a new folder to the database with validation."""
    if not validate_folder_name(folder):
        st.error("Folder name must be 3-20 characters, lowercase alphanumeric or underscores.")
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO folders (folder, name, age, profession, category)
            VALUES (?, ?, ?, ?, ?)
        """, (folder, name, age, profession, category))
        conn.commit()
        conn.close()
        save_backup()  # Save backup after adding folder
        return True
    except sqlite3.IntegrityError:
        st.error(f"Folder '{folder}' already exists.")
        return False
    except Exception as e:
        st.error(f"Error adding folder: {str(e)}")
        return False

def load_images_to_db(uploaded_files, folder, download_allowed=True):
    """Load images into the database with compression."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for uploaded_file in uploaded_files:
        img = Image.open(uploaded_file)
        img = img.convert("RGB")  # Ensure consistent format
        img.thumbnail((800, 800))  # Resize to max 800x800
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)  # Compress to JPEG
        image_data = output.getvalue()
        extension = ".jpg"
        random_filename = f"{uuid.uuid4()}{extension}"
        c.execute("SELECT COUNT(*) FROM images WHERE folder = ? AND name = ?", (folder, random_filename))
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO images (name, folder, image_data, download_allowed) VALUES (?, ?, ?, ?)",
                      (random_filename, folder, image_data, download_allowed))
    conn.commit()
    conn.close()
    save_backup()  # Save backup after uploading images

def swap_image(folder, old_image_name, new_image_file):
    """Replace an existing image with a new uploaded image."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        img = Image.open(new_image_file)
        img = img.convert("RGB")
        img.thumbnail((800, 800))
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)
        new_image_data = output.getvalue()
        c.execute("UPDATE images SET image_data = ? WHERE folder = ? AND name = ?",
                  (new_image_data, folder, old_image_name))
        conn.commit()
        conn.close()
        save_backup()  # Save backup after swapping image
        return True
    except Exception as e:
        st.error(f"Error swapping image: {str(e)}")
        return False

def update_download_permission(folder, image_name, download_allowed):
    """Update download permission for an image."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE images SET download_allowed = ? WHERE folder = ? AND name = ?",
              (download_allowed, folder, image_name))
    conn.commit()
    conn.close()
    save_backup()  # Save backup after updating permissions

def delete_image(folder, name):
    """Delete an image from the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM images WHERE folder = ? AND name = ?", (folder, name))
    conn.commit()
    conn.close()
    save_backup()  # Save backup after deleting image

def load_survey_data():
    """Load survey data from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT folder, rating, feedback, timestamp FROM surveys")
    survey_data = {}
    for row in c.fetchall():
        folder, rating, feedback, timestamp = row
        if folder not in survey_data:
            survey_data[folder] = []
        survey_data[folder].append({"rating": rating, "feedback": feedback, "timestamp": timestamp})
    conn.close()
    return survey_data

def save_survey_data(folder, rating, feedback, timestamp):
    """Save survey data to database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO surveys (folder, rating, feedback, timestamp) VALUES (?, ?, ?, ?)",
              (folder, rating, feedback, timestamp))
    conn.commit()
    conn.close()
    save_backup()  # Save backup after saving survey

def delete_survey_entry(folder, timestamp):
    """Delete a survey entry from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM surveys WHERE folder = ? AND timestamp = ?", (folder, timestamp))
    conn.commit()
    conn.close()
    save_backup()  # Save backup after deleting survey

def get_images(folder):
    """Get images from database for a folder."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, image_data, download_allowed FROM images WHERE folder = ?", (folder,))
    images = []
    for r in c.fetchall():
        name, data, download = r
        try:
            img = Image.open(io.BytesIO(data))
            thumbnail = generate_thumbnail(img)
            base64_image = image_to_base64(data)
            images.append({
                "name": name,
                "image": img,
                "thumbnail": thumbnail,
                "data": data,
                "download": download,
                "base64": base64_image
            })
        except Exception as e:
            st.error(f"Error loading image {name}: {str(e)}")
    conn.close()
    return images

def display_rating_chart(survey_data, folders):
    """Display a bar chart of average ratings per folder."""
    ratings = []
    folder_names = []
    for f in folders:
        if f["folder"] in survey_data and survey_data[f["folder"]]:
            avg_rating = sum(entry["rating"] for entry in survey_data[f["folder"]]) / len(survey_data[f["folder"]])
            ratings.append(avg_rating)
            folder_names.append(f["name"])
    
    if ratings:
        st.markdown("### Average Ratings per Folder")
        chart_config = {
            "type": "bar",
            "data": {
                "labels": folder_names,
                "datasets": [{
                    "label": "Average Rating",
                    "data": ratings,
                    "backgroundColor": ["#4CAF50", "#2196F3", "#FF9800", "#F44336", "#9C27B0"],
                    "borderColor": ["#388E3C", "#1976D2", "#F57C00", "#D32F2F", "#7B1FA2"],
                    "borderWidth": 1
                }]
            },
            "options": {
                "scales": {
                    "y": {"beginAtZero": True, "max": 5, "title": {"display": True, "text": "Rating (1-5)"}},
                    "x": {"title": {"display": True, "text": "Folder"}}
                }
            }
        }
        st.markdown("```chartjs\n" + str(chart_config) + "\n```", unsafe_allow_html=True)
    else:
        st.info("No survey data available to display chart.")

# -------------------------------
# Initialize DB & Session State
# -------------------------------
init_db()
if "zoom_folder" not in st.session_state:
    st.session_state.zoom_folder = None
if "zoom_index" not in st.session_state:
    st.session_state.zoom_index = 0
if "is_author" not in st.session_state:
    st.session_state.is_author = False

# -------------------------------
# Sidebar: Author Controls
# -------------------------------
with st.sidebar:
    st.title("Author Login")
    with st.form(key="login_form"):
        pwd = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.is_author = True
                st.success("Logged in as author!")
            else:
                st.error("Wrong password")
    if st.session_state.is_author and st.button("Logout"):
        st.session_state.is_author = False
        st.success("Logged out")
        st.rerun()

    if st.session_state.is_author:
        st.subheader("Manage Folders & Images")
        with st.form(key="add_folder_form"):
            new_folder = st.text_input("Folder Name (e.g., 'newfolder')")
            new_name = st.text_input("Person Name")
            new_age = st.number_input("Age", min_value=1, max_value=150, step=1)
            new_profession = st.text_input("Profession")
            new_category = st.selectbox("Category", ["Artists", "Engineers", "Teachers"], index=0)
            if st.form_submit_button("Add Folder"):
                if new_folder and new_name and new_profession and new_category:
                    if add_folder(new_folder.lower(), new_name, new_age, new_profession, new_category):
                        st.success(f"Folder '{new_folder}' added successfully!")
                        st.rerun()
                    else:
                        st.error("Failed to add folder. Check input or try a different folder name.")
                else:
                    st.error("Please fill in all fields.")

        st.subheader("Upload Images")
        data = load_folders()
        folder_choice = st.selectbox("Select Folder", [item["folder"] for item in data], key="upload_folder")
        download_allowed = st.checkbox("Allow Downloads for New Images", value=True)
        uploaded_files = st.file_uploader(
            "Upload Images", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'], key="upload_files"
        )
        if st.button("Upload to DB") and uploaded_files:
            load_images_to_db(uploaded_files, folder_choice, download_allowed)
            st.success(f"{len(uploaded_files)} image(s) uploaded to '{folder_choice}'!")
            st.rerun()

        st.subheader("Image Swap")
        folder_choice_swap = st.selectbox("Select Folder for Image Swap", [item["folder"] for item in data], key="swap_folder")
        images = get_images(folder_choice_swap)
        if images:
            image_choice = st.selectbox("Select Image to Swap", [img["name"] for img in images], key="swap_image")
            new_image = st.file_uploader("Upload New Image", type=['jpg', 'jpeg', 'png'], key="swap_upload")
            if st.button("Swap Image") and new_image:
                if swap_image(folder_choice_swap, image_choice, new_image):
                    st.success(f"Image '{image_choice}' swapped in '{folder_choice_swap}'!")
                    st.rerun()
                else:
                    st.error("Failed to swap image.")

        st.subheader("Download Permissions")
        folder_choice_perm = st.selectbox("Select Folder for Download Settings", [item["folder"] for item in data], key=f"download_folder_{uuid.uuid4()}")
        images = get_images(folder_choice_perm)
        if images:
            with st.form(key=f"download_permissions_form_{folder_choice_perm}"):
                st.write("Toggle Download Permissions:")
                download_states = {}
                for img_dict in images:
                    toggle_key = f"download_toggle_{folder_choice_perm}_{img_dict['name']}"
                    download_states[img_dict['name']] = st.checkbox(
                        f"Allow download for {img_dict['name'][:8]}...{img_dict['name'][-4:]}",
                        value=img_dict["download"],
                        key=toggle_key
                    )
                if st.form_submit_button("Apply Download Permissions"):
                    for img_dict in images:
                        if download_states[img_dict['name']] != img_dict["download"]:
                            update_download_permission(folder_choice_perm, img_dict["name"], download_states[img_dict['name']])
                    st.success("Download permissions updated!")
                    st.rerun()

        # Add a download button for db_backup.json (manual backup)
        if os.path.exists(BACKUP_PATH):
            with open(BACKUP_PATH, "rb") as f:
                st.download_button(
                    label="Download db_backup.json",
                    data=f,
                    file_name="db_backup.json",
                    mime="application/json"
                )

# -------------------------------
# CSS Styling
# -------------------------------
st.markdown("""
<style>
.folder-card {background: #f9f9f9; border-radius: 8px; padding: 15px; margin-bottom: 20px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);}
.folder-header {font-size:1.5em; color:#333; margin-bottom:10px;}
.image-grid {display:flex; flex-wrap:wrap; gap:10px;}
img {border-radius:4px; pointer-events: none; user-select: none;}
</style>
""", unsafe_allow_html=True)

# -------------------------------
# Main App UI
# -------------------------------
st.title("📸 Interactive Photo Gallery & Survey")

# Search Bar
search_query = st.text_input("Search by name, folder, profession, or category")
data = load_folders(search_query)
survey_data = load_survey_data()

# Display Rating Chart
display_rating_chart(survey_data, data)

categories = sorted(set(item["category"] for item in data))
tabs = st.tabs(categories)

# Grid View
if st.session_state.zoom_folder is None:
    for cat, tab in zip(categories, tabs):
        with tab:
            cat_folders = [f for f in data if f["category"] == cat]
            for f in cat_folders:
                st.markdown(
                    f'<div class="folder-card"><div class="folder-header">'
                    f'{f["name"]} ({f["age"]}, {f["profession"]})</div>',
                    unsafe_allow_html=True
                )

                images = get_images(f["folder"])
                if images:
                    cols = st.columns(4)
                    for idx, img_dict in enumerate(images):
                        with cols[idx % 4]:
                            if st.button("🔍 View", key=f"view_{f['folder']}_{idx}"):
                                st.session_state.zoom_folder = f["folder"]
                                st.session_state.zoom_index = idx
                                st.rerun()
                            st.image(img_dict["thumbnail"], use_container_width=True)
                else:
                    st.warning(f"No images found for {f['folder']}")

                with st.expander(f"📝 Survey for {f['name']}"):
                    with st.form(key=f"survey_form_{f['folder']}"):
                        rating = st.slider("Rating (1-5)", 1, 5, 3, key=f"rating_{f['folder']}")
                        feedback = st.text_area("Feedback", key=f"feedback_{f['folder']}")
                        if st.form_submit_button("Submit"):
                            timestamp = datetime.now().isoformat()
                            save_survey_data(f["folder"], rating, feedback, timestamp)
                            st.success("✅ Response recorded")
                            st.rerun()

                    if f["folder"] in survey_data and survey_data[f["folder"]]:
                        st.write("### 📊 Previous Feedback:")
                        ratings = [entry['rating'] for entry in survey_data[f["folder"]]]
                        avg_rating = sum(ratings) / len(ratings)
                        st.markdown(f"**Average Rating:** ⭐ {avg_rating:.1f} ({len(ratings)} reviews)")
                        for entry in survey_data[f["folder"]]:
                            cols = st.columns([6, 1])
                            with cols[0]:
                                rating_display = "⭐" * entry["rating"]
                                st.markdown(
                                    f"- {rating_display} — {entry['feedback']}  \n"
                                    f"<sub>🕒 {entry['timestamp']}</sub>",
                                    unsafe_allow_html=True
                                )
                            if st.session_state.is_author:
                                with cols[1]:
                                    if st.button("🗑️", key=f"delete_survey_{f['folder']}_{entry['timestamp']}"):
                                        delete_survey_entry(f["folder"], entry["timestamp"])
                                        st.success("Deleted comment.")
                                        st.rerun()
                    else:
                        st.info("No feedback yet — be the first to leave a comment!")

# Zoom View
else:
    folder = st.session_state.zoom_folder
    images = get_images(folder)
    idx = st.session_state.zoom_index
    if idx >= len(images):
        idx = 0
        st.session_state.zoom_index = 0
    img_dict = images[idx]

    st.subheader(f"🔍 Viewing {folder} ({idx+1}/{len(images)})")
    st.image(img_dict["image"], use_container_width=True)

    col1, col2, col3 = st.columns([1, 8, 1])
    with col1:
        if idx > 0 and st.button("◄ Previous", key=f"prev_{folder}"):
            st.session_state.zoom_index -= 1
            st.rerun()
    with col3:
        if idx < len(images) - 1 and st.button("Next ►", key=f"next_{folder}"):
            st.session_state.zoom_index += 1
            st.rerun()

    if img_dict["download"]:
        mime = "image/jpeg" if img_dict["name"].lower().endswith(('.jpg', '.jpeg')) else "image/png"
        st.download_button("⬇️ Download", data=img_dict["data"], file_name=img_dict["name"], mime=mime)

    if st.session_state.is_author:
        if st.button("🗑️ Delete Image", key=f"delete_{folder}_{img_dict['name']}"):
            delete_image(folder, img_dict["name"])
            st.success("Deleted.")
            st.session_state.zoom_index = max(0, idx - 1)
            if len(get_images(folder)) == 0:
                st.session_state.zoom_folder = None
                st.session_state.zoom_index = 0
            st.rerun()

    if st.button("⬅️ Back to Grid", key=f"back_{folder}"):
        st.session_state.zoom_folder = None
        st.session_state.zoom_index = 0
        st.rerun()
