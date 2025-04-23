import streamlit as st
import tempfile
import os
import subprocess
from pydub import AudioSegment
from moviepy import VideoFileClip, AudioFileClip, ImageClip
import pickle
from instagram_private_api import Client, ClientCookieExpiredError, ClientLoginError
from google.generativeai import Client as GenerativeClient

# --- Load from secrets ---
INSTAGRAM_USERNAME = st.secrets["instagram_username"]
INSTAGRAM_PASSWORD = st.secrets["instagram_password"]
GEMINI_API_KEY = st.secrets["gemini_api_key"]
SESSION_FILE = st.secrets["session_file"]

# Predefined user groups
usernames_of_group = ['group_user1', 'group_user2']
usernames_of_staff = ['staff_user1', 'staff_user2']

# --- Session Handling ---
def save_session(api):
    with open(SESSION_FILE, 'wb') as f:
        pickle.dump({'cookie': api.cookie_jar, 'settings': api.settings}, f)

def load_session():
    with open(SESSION_FILE, 'rb') as f:
        data = pickle.load(f)
        return Client(
            auto_patch=True,
            authenticate=False,
            settings=data['settings'],
            cookie=data['cookie']
        )

def login():
    api = Client()
    api.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
    save_session(api)
    return api

def get_api():
    if os.path.exists(SESSION_FILE):
        try:
            st.info("🔁 Loading saved session...")
            api = load_session()
            api.current_user()
            st.success("✅ Logged in using saved session.")
            return api
        except (ClientCookieExpiredError, ClientLoginError):
            st.warning("❌ Session expired. Logging in again...")

    st.info("🔐 Logging in...")
    return login()

# --- Caption Generation with Google Generative AI ---
def generate_caption(image_path):
    # Initialize the Google Generative AI Client with your API key
    client = GenerativeClient(api_key=GEMINI_API_KEY)
    
    with open(image_path, 'rb') as img_file:
        img_data = img_file.read()

    # Requesting the generative AI model to create a caption
    response = client.generate_content(
        model="gemini-2.0-pro-vision",
        contents=[{
            "parts": [{"text": "Generate a creative, concise Instagram caption for this image. Only return the caption, nothing else."}],
            "inline_data": {"mime_type": "image/jpeg", "data": img_data}
        }]
    )

    return response.candidates[0].content.parts[0].text.strip()

# Function to download audio using yt-dlp
def download_audio(spotify_url, save_path):
    command = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "-o", save_path,
        spotify_url
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- Streamlit UI ---
st.title("🎵 Instagram Uploader with Music + Caption Generation")

# Spotify URL input
spotify_url = st.text_input("Enter Spotify URL (fallback to YouTube)", placeholder="https://open.spotify.com/track/...")

temp_dir = tempfile.mkdtemp()

if spotify_url:
    with st.spinner("Downloading audio..."):
        raw_audio_path = os.path.join(temp_dir, "track.%(ext)s")
        final_audio_path = os.path.join(temp_dir, "track.mp3")
        download_audio(spotify_url, raw_audio_path)

        # Ensure file was saved
        if os.path.exists(final_audio_path):
            st.success("✅ Audio downloaded!")
            audio = AudioSegment.from_file(final_audio_path, format="mp3")
            total_duration = int(audio.duration_seconds)

            # Range slider for trimming
            start_sec, end_sec = st.slider("🎧 Select trim range (seconds)", 0, total_duration, (0, min(15, total_duration)), step=1)

            # Automatically update preview
            trimmed = audio[start_sec * 1000:end_sec * 1000]
            trimmed_path = os.path.join(temp_dir, "preview.mp3")
            trimmed.export(trimmed_path, format="mp3")

            st.audio(trimmed_path, format="audio/mp3")
            st.caption(f"Previewing audio from {start_sec}s to {end_sec}s")

            st.session_state['audio_clip_path'] = trimmed_path
            st.session_state['audio_clip_range'] = (start_sec, end_sec)
        else:
            st.error("❌ Failed to download audio. Try another link.")

# Image/Video upload for Instagram
uploaded_file = st.file_uploader("Upload an image or video", type=["jpg", "jpeg", "png", "mp4"])

# User mentions
mention_options = {
    'Group': usernames_of_group,
    'Staff': usernames_of_staff,
}
selected_mentions = []

for group, users in mention_options.items():
    if st.checkbox(f"Include {group} Mentions"):
        selected_mentions.extend(users)

if st.checkbox("Add Custom Mentions"):
    custom_mentions = st.text_area("Custom usernames (comma separated)", "")
    selected_mentions.extend([u.strip() for u in custom_mentions.split(',') if u.strip()])

# File handling & caption
if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
        tmp_file.write(uploaded_file.read())
        temp_image_path = tmp_file.name

    st.image(temp_image_path, caption="Preview", use_column_width=True)

    if st.button("Generate Caption with Google Generative AI"):
        generated_caption = generate_caption(temp_image_path)
        st.session_state["generated_caption"] = generated_caption
        st.success("Caption generated!")

# Choose caption
use_generated = st.radio("Use generated caption?", ["Yes", "No"])
final_caption = ""

if use_generated == "Yes" and "generated_caption" in st.session_state:
    final_caption = st.session_state["generated_caption"]
    st.text_area("Generated Caption", final_caption, height=100)
else:
    final_caption = st.text_area("Custom Caption", "", height=100)

if uploaded_file:
    # Add selected music to video/image
    if "audio_clip_path" in st.session_state:
        audio_path = st.session_state["audio_clip_path"]
        audio_clip = AudioFileClip(audio_path)

        if uploaded_file.name.lower().endswith(('jpg', 'jpeg', 'png')):  # Image
            # Convert image to 15s video with music
            img_clip = ImageClip(temp_image_path).set_duration(audio_clip.duration).set_fps(24)
            img_clip = img_clip.set_audio(audio_clip)
            output_path = os.path.join(temp_dir, "final_video.mp4")
            img_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")
        else:  # Video
            video = VideoFileClip(temp_image_path)
            final_video = video.set_audio(audio_clip)
            output_path = os.path.join(temp_dir, "final_video.mp4")
            final_video.write_videofile(output_path, codec="libx264", audio_codec="aac")

        st.video(output_path)

        # Option to upload to Instagram
        if st.button("🚀 Upload Reels"):
            try:
                api = get_api()

                # Prepare media file and cover
                video_path = output_path
                cover_image_path = temp_image_path  # Use the uploaded image as the cover

                # Upload to Instagram Reels
                media = api.video_upload_to_reel(video_path, caption=final_caption, cover=cover_image_path)

                # Tag users in the video
                for username in selected_mentions:
                    user = api.user_info_by_username(username)
                    api.media_like(media.pk)
                    api.media_comment(media.pk, f"@{username}")

                st.success("✅ Reels video uploaded successfully!")
            except Exception as e:
                st.error(f"Error: {e}")
