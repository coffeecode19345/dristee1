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
    # Create images table
    c.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            folder TEXT NOT NULL,
            image_data BLOB NOT NULL
        )
    """)
    # Create surveys table
    c.execute("""
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder TEXT NOT NULL,
            rating INTEGER NOT NULL,
            feedback TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# -------------------------------
# Load images into database from folders
# -------------------------------
def load_images_to_db(folders):
    conn = sqlite3.connect("gallery.db")
    c = conn.cursor()
    for folder in folders:
        folder_path = folder
        if os.path.exists(folder_path):
            for image_file in os.listdir(folder_path):
                if image_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                    image_path = os.path.join(folder_path, image_file)
                    with open(image_path, 'rb') as f:
                        image_data = f.read()
                    # Check if image already exists to avoid duplicates
                    c.execute("SELECT COUNT(*) FROM images WHERE name = ? AND folder = ?", (image_file, folder))
                    if c.fetchone()[0] == 0:
                        c.execute("INSERT INTO images (name, folder, image_data) VALUES (?, ?, ?)",
                                  (image_file, folder, image_data))
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
        image = Image.open(io.BytesIO(image_data))
        images.append((name, image))
    conn.close()
    return images

# -------------------------------
# Data for the two test folders
# -------------------------------
data = [
    {"name": "Sarika", "age": 28, "profession": "Photographer", "category": "Artists", "folder": "sarika"},
    {"name": "Jamuna", "age": 32, "profession": "Sculptor", "category": "Artists", "folder": "jamuna"},
]

# -------------------------------
# Initialize database and load images
# -------------------------------
init_db()
load_images_to_db([item["folder"] for item in data])

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
# -------------------------------
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
                st.warning(f"No images found for {item['folder']}")

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
