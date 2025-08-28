import streamlit as st
import sqlite3
import os
from datetime import datetime
import io
from PIL import Image

# -------------------------------
# Database Setup
# -------------------------------
def init_db():
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    # Create folders table
    c.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            profession TEXT NOT NULL,
            category TEXT NOT NULL
        )
    """)
    # Create images table
    c.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            folder TEXT NOT NULL,
            image_data BLOB NOT NULL,
            FOREIGN KEY (folder) REFERENCES folders (folder)
        )
    """)
    # Create surveys table
    c.execute("""
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder TEXT NOT NULL,
            rating INTEGER NOT NULL,
            feedback TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (folder) REFERENCES folders (folder)
        )
    """)
    conn.commit()
    # Initialize default folders if not present
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

# -------------------------------
# Load folders from database
# -------------------------------
def load_folders():
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    c.execute("SELECT folder, name, age, profession, category FROM folders")
    folders = [{"folder": row[0], "name": row[1], "age": row[2], "profession": row[3], "category": row[4]}
               for row in c.fetchall()]
    conn.close()
    return folders

# -------------------------------
# Add new folder to database
# -------------------------------
def add_folder(folder, name, age, profession, category):
    try:
        conn = sqlite3.connect("gallery.db")
        c = conn.cursor()
        c.execute("""
            INSERT INTO folders (folder, name, age, profession, category)
            VALUES (?, ?, ?, ?, ?)
        """, (folder, name, age, profession, category))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False  # Folder already exists
    except Exception as e:
        st.error(f"Error adding folder: {str(e)}")
        return False

# -------------------------------
# Load images into database
# -------------------------------
def load_images_to_db(uploaded_files, folder):
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    for uploaded_file in uploaded_files:
        image_data = uploaded_file.read()
        image_name = uploaded_file.name
        # Check if image already exists to avoid duplicates
        c.execute("SELECT COUNT(*) FROM images WHERE name = ? AND folder = ?", (image_name, folder))
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO images (name, folder, image_data) VALUES (?, ?, ?)",
                      (image_name, folder, image_data))
    conn.commit()
    conn.close()

# -------------------------------
# Load survey data from database
# -------------------------------
def load_survey_data():
    conn = sqlite3.connect("gallery.db")
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

# -------------------------------
# Save survey data to database
# -------------------------------
def save_survey_data(folder, rating, feedback, timestamp):
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    c.execute("INSERT INTO surveys (folder, rating, feedback, timestamp) VALUES (?, ?, ?, ?)",
              (folder, rating, feedback, timestamp))
    conn.commit()
    conn.close()

# -------------------------------
# Delete survey entry from database
# -------------------------------
def delete_survey_entry(folder, timestamp):
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    c.execute("DELETE FROM surveys WHERE folder = ? AND timestamp = ?", (folder, timestamp))
    conn.commit()
    conn.close()

# -------------------------------
# Get images from database
# -------------------------------
def get_images_from_db(folder):
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    c.execute("SELECT name, image_data FROM images WHERE folder = ?", (folder,))
    images = []
    for row in c.fetchall():
        name, image_data = row
        try:
            image = Image.open(io.BytesIO(image_data))
            images.append((name, image))
        except Exception as e:
            st.error(f"Error loading image {name}: {str(e)}")
    conn.close()
    return images

# -------------------------------
# Initialize database
# -------------------------------
init_db()

# -------------------------------
# Sidebar for Folder Creation and Image Upload
# -------------------------------
st.sidebar.title("Manage Folders and Images")
st.sidebar.subheader("Create New Folder")
with st.sidebar.form(key="add_folder_form"):
    new_folder = st.text_input("Folder Name (e.g., 'newfolder')")
    new_name = st.text_input("Person Name")
    new_age = st.number_input("Age", min_value=1, max_value=150, step=1)
    new_profession = st.text_input("Profession")
    new_category = st.text_input("Category", value="Artists")
    if st.form_submit_button("Add Folder"):
        if new_folder and new_name and new_profession and new_category:
            if add_folder(new_folder.lower(), new_name, new_age, new_profession, new_category):
                st.sidebar.success(f"Folder '{new_folder}' added successfully!")
                st.rerun()
            else:
                st.sidebar.error(f"Folder '{new_folder}' already exists or invalid input.")
        else:
            st.sidebar.error("Please fill in all fields.")

st.sidebar.subheader("Upload Images")
data = load_folders()  # Load folders dynamically from database
folder_choice = st.sidebar.selectbox("Select Folder", [item["folder"] for item in data])
uploaded_files = st.sidebar.file_uploader("Upload Images", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])
if uploaded_files and folder_choice:
    load_images_to_db(uploaded_files, folder_choice)
    st.sidebar.success(f"Images uploaded to {folder_choice} folder in database!")
    st.rerun()

# -------------------------------
# CSS Styling + Prevent Right-Click
# -------------------------------
st.markdown("""
    <style>
    .image-container img {
        border: 2px solid #333;
        border-radius: 8px;
        box-shadow: 3px 3px 8px rgba(0, 0, 0, 0.3);
        margin-bottom: 10px;
    }
    img {
        pointer-events: none;
        -webkit-user-drag: none;
        user-drag: none;
        user-select: none;
    }
    body {
        -webkit-user-select: none;
        -ms-user-select: none;
        user-select: none;
    }
    </style>
""", unsafe_allow_html=True)

# -------------------------------
# App UI
# -------------------------------
st.title("📸 Photo Gallery & Survey")

survey_data = load_survey_data()
categories = sorted(set(item["category"] for item in data))
tabs = st.tabs(categories)

# -------------------------------
# Loop through categories
# -----------------------
for category, tab in zip(categories, tabs):
    with tab:
        st.header(category)
        category_data = [item for item in data if item["category"] == category]

        for item in category_data:
            st.subheader(f"{item['name']} ({item['age']}, {item['profession']})")

            images = get_images_from_db(item["folder"])
            if images:
                cols = st.columns(3)  # Show 3 images per row
                for idx, (image_name, image) in enumerate(images):
                    with cols[idx % 3]:
                        st.markdown('<div class="image-container">', unsafe_allow_html=True)
                        st.image(image, use_container_width=True)
                        st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.warning(f"No images found for {item['folder']} in database")

            # -------------------------------
            # Survey form
            # -------------------------------
            with st.expander(f"📝 Survey for {item['name']}"):
                with st.form(key=f"survey_form_{item['folder']}"):
                    rating = st.slider("Rating (1-5)", 1, 5, 3, key=f"rating_{item['folder']}")
                    feedback = st.text_area("Feedback", key=f"feedback_{item['folder']}")
                    if st.form_submit_button("Submit"):
                        timestamp = datetime.now().isoformat()
                        save_survey_data(item["folder"], rating, feedback, timestamp)
                        st.success("✅ Response recorded")
                        st.rerun()

            # -------------------------------
            # Display saved survey data
            # -------------------------------
            if item["folder"] in survey_data and survey_data[item["folder"]]:
                st.subheader(f"💬 Survey Responses for {item['name']}")
                for entry in survey_data[item["folder"]]:
                    with st.expander(f"{entry['timestamp']}"):
                        st.write(f"⭐ {entry['rating']} — {entry['feedback']}")
                        if st.button("🗑️ Delete", key=f"delete_{item['folder']}_{entry['timestamp']}"):
                            delete_survey_entry(item["folder"], entry["timestamp"])
                            st.rerun()
            else:
                st.caption("No survey responses yet.")
