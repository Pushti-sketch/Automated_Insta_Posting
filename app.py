import streamlit as st
import tempfile
import os
import subprocess
from pydub import AudioSegment
from moviepy import VideoFileClip, AudioFileClip, ImageClip
import pickle
from instagram_private_api import Client, ClientCookieExpiredError, ClientLoginError
from google import genai
from google.genai.types import HttpOptions, Content, Part
from PIL import Image
import io

# --- Fallback for Local Development ---
# Use default values when secrets are not available (for local development)
INSTAGRAM_USERNAME = st.secrets.get("instagram_username", "default_instagram_username")
INSTAGRAM_PASSWORD = st.secrets.get("instagram_password", "default_instagram_password")
GEMINI_API_KEY = st.secrets.get("gemini_api_key")
SESSION_FILE = st.secrets.get("session_file", "default_session_file.pkl")

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
client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=HttpOptions(api_version="v1"))
    except Exception as e:
        st.error(f"Error initializing Gemini API client: {e}")
else:
    st.error("Gemini API key not found in Streamlit secrets!")

def generate_caption(image_path):
    if client is None:
        return None
    try:
        with open(image_path, "rb") as img_file:
            img_data = img_file.read()

        # Create a Content object with typed Parts and inline_data
        content = Content(
            parts=[
                Part(text="Generate a creative, concise Instagram caption for this image. Only return the caption, nothing else."),
                Part(inline_data={"mime_type": "image/jpeg", "data": img_data})
            ]
        )
        print("Content object:", content)  # Debugging line

        # Generate caption
        response = client.models.generate_content(
            model="gemini-2.0-flash-001",
            contents=[content]
        )
        return response.text.strip()
    except Exception as e:
        st.error(f"Error during caption generation: {e}")
        return None

def generate_caption_test():
    if client is None:
        return None
    try:
        response = client.models.generate_content(
            model="gemini-pro",
            contents="Write a short, creative caption."
        )
        return response.text.strip()
    except Exception as e:
        st.error(f"Error during test caption generation: {e}")
        return None

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
        process = subprocess.run(["yt-dlp", "--extract-audio", "--audio-format", "mp3", "-o", raw_audio_path, spotify_url], capture_output=True)

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
            error_message = process.stderr.decode('utf-8')
            st.error(f"❌ Failed to download audio. Try another link. Error from yt-dlp: {error_message}")

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

    if st.button("Generate Caption with Google Generative AI") and client:
        generated_caption = generate_caption(temp_image_path)
        if generated_caption:
            st.session_state["generated_caption"] = generated_caption
            st.success("Caption generated!")

    if st.button("Test Caption") and client:
        test_caption = generate_caption_test()
        if test_caption:
            st.write(f"Test Caption: {test_caption}")

    # Choose caption
    use_generated = st.radio("Use generated caption?", ["Yes", "No"])
    final_caption = ""

    if use_generated == "Yes" and "generated_caption" in st.session_state:
        final_caption = st.session_state["generated_caption"]
        st.text_area("Generated Caption", final_caption, height=100)
    else:
        final_caption = st.text_area("Custom Caption", "", height=100)

    # --- Instagram Post Button ---
    if st.button("📸 Post to Instagram"):
        try:
            api = get_api()
            upload_result = api.upload_photo(temp_image_path, caption=final_caption)
            st.success(f"✅ Image posted successfully! Media ID: {upload_result.get('media_id')}")
        except Exception as e:
            st.error(f"Error during Instagram post: {e}")

    # Add selected music to video/image
    if "audio_clip_path" in st.session_state:
        audio_path = st.session_state["audio_clip_path"]
        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration

        if uploaded_file.name.lower().endswith(('jpg', 'jpeg', 'png')):  # Image
            # Convert image to video with music (max 15 seconds for Reels with music)
            video_duration = min(15, audio_duration)
            img_clip = ImageClip(temp_image_path).set_duration(video_duration).set_fps(24)
            final_audio_clip = audio_clip.subclip(0, video_duration)
            img_clip = img_clip.set_audio(final_audio_clip)
            output_path = os.path.join(temp_dir, "final_video.mp4")
            img_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")
        else:  # Video
            video = VideoFileClip(temp_image_path)
            video_duration = video.duration
            final_video_duration = min(15, video_duration, audio_duration)
            final_video = video.subclip(0, final_video_duration)
            final_audio_clip = audio_clip.subclip(0, final_video_duration)
            final_video = final_video.set_audio(final_audio_clip)
            output_path = os.path.join(temp_dir, "final_video.mp4")
            final_video.write_videofile(output_path, codec="libx264", audio_codec="aac")

        st.video(output_path)

        # Option to upload to Instagram Reels
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
                    try:
                        user = api.user_info_by_username(username)
                        api.media_like(media.pk)
                        api.media_comment(media.pk, f"@{username}")
                    except Exception as e:
                        st.warning(f"Could not tag user {username}: {e}")

                st.success("✅ Reels video uploaded successfully!")
            except Exception as e:
                st.error(f"Error during Instagram Reels upload: {e}")

# Clean up temporary directory
import shutil
shutil.rmtree(temp_dir, ignore_errors=True)
