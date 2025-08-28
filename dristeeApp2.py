import streamlit as st
import sqlite3
import io
from PIL import Image
import os
from datetime import datetime
import uuid
import re
import base64
import numpy as np
import face_recognition  # For face swap
from dotenv import load_dotenv

# Load environment variables for secure password
load_dotenv()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Fallback for testing

DB_PATH = "gallery.db"

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
    """Initialize SQLite database with folders, images, and surveys tables."""
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
        return True
    except sqlite3.IntegrityError:
        st.error(f"Folder '{folder}' already exists.")
        return False
    except Exception as e:
        st.error(f"Error adding folder: {str(e)}")
        return False

def load_images_to_db(uploaded_files, folder, download_allowed=True):
    """Load images into the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for uploaded_file in uploaded_files:
        image_data = uploaded_file.read()
        extension = os.path.splitext(uploaded_file.name)[1].lower()
        random_filename = f"{uuid.uuid4()}{extension}"
        c.execute("SELECT COUNT(*) FROM images WHERE folder = ? AND name = ?", (folder, random_filename))
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO images (name, folder, image_data, download_allowed) VALUES (?, ?, ?, ?)",
                      (random_filename, folder, image_data, download_allowed))
    conn.commit()
    conn.close()

def swap_image(folder, old_image_name, new_image_file):
    """Replace an existing image with a new uploaded image."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        new_image_data = new_image_file.read()
        c.execute("UPDATE images SET image_data = ? WHERE folder = ? AND name = ?",
                  (new_image_data, folder, old_image_name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error swapping image: {str(e)}")
        return False

def perform_face_swap(source_image_data, target_image_data):
    """Perform face swap between source and target images using face_recognition."""
    try:
        # Convert image data to PIL Images
        source_img = Image.open(io.BytesIO(source_image_data)).convert("RGB")
        target_img = Image.open(io.BytesIO(target_image_data)).convert("RGB")

        # Convert to numpy arrays for face_recognition
        source_array = np.array(source_img)
        target_array = np.array(target_img)

        # Detect faces in both images
        source_faces = face_recognition.face_locations(source_array)
        target_faces = face_recognition.face_locations(target_array)

        if not source_faces or not target_faces:
            st.error("No faces detected in one or both images.")
            return None

        # Get the first face from each image
        source_top, source_right, source_bottom, source_left = source_faces[0]
        target_top, target_right, target_bottom, target_left = target_faces[0]

        # Extract face regions
        source_face = source_array[source_top:source_bottom, source_left:source_right]
        target_face = target_array[target_top:target_bottom, target_left:target_right]

        # Resize source face to match target face dimensions
        source_face_pil = Image.fromarray(source_face)
        target_face_size = (target_right - target_left, target_bottom - target_top)
        source_face_resized = source_face_pil.resize(target_face_size, Image.LANCZOS)

        # Replace target face with source face
        target_array[target_top:target_bottom, target_left:target_right] = np.array(source_face_resized)

        # Convert back to PIL Image
        result_img = Image.fromarray(target_array)

        # Save to bytes
        output = io.BytesIO()
        result_img.save(output, format="PNG")
        return output.getvalue()
    except Exception as e:
        st.error(f"Error during face swap: {str(e)}")
        return None

def update_download_permission(folder, image_name, download_allowed):
    """Update download permission for an image."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE images SET download_allowed = ? WHERE folder = ? AND name = ?",
              (download_allowed, folder, image_name))
    conn.commit()
    conn.close()

def delete_image(folder, name):
    """Delete an image from the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM images WHERE folder = ? AND name = ?", (folder, name))
    conn.commit()
    conn.close()

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

def delete_survey_entry(folder, timestamp):
    """Delete a survey entry from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM surveys WHERE folder = ? AND timestamp = ?", (folder, timestamp))
    conn.commit()
    conn.close()

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

        st.subheader("Face Swap")
        folder_choice_face = st.selectbox("Select Folder for Face Swap", [item["folder"] for item in data], key="face_folder")
        images = get_images(folder_choice_face)
        if images:
            target_image = st.selectbox("Select Target Image", [img["name"] for img in images], key="face_target")
            source_image = st.file_uploader("Upload Source Image (for face)", type=['jpg', 'jpeg', 'png'], key="face_upload")
            if st.button("Perform Face Swap") and source_image:
                target_img_data = next(img["data"] for img in images if img["name"] == target_image)
                result_data = perform_face_swap(source_image.read(), target_img_data)
                if result_data:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    new_filename = f"{uuid.uuid4()}.png"
                    c.execute("INSERT INTO images (name, folder, image_data, download_allowed) VALUES (?, ?, ?, ?)",
                              (new_filename, folder_choice_face, result_data, True))
                    conn.commit()
                    conn.close()
                    st.success(f"Face-swapped image saved as '{new_filename}' in '{folder_choice_face}'!")
                    st.rerun()

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
