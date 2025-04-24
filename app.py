import os
import json
import time
import streamlit as st
import tempfile
from PIL import Image
import google.generativeai as genai
from instagram_private_api import Client, ClientCookieExpiredError, ClientLoginRequiredError
from instagram_private_api.errors import ClientError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set page config
st.set_page_config(page_title="Instagram Post Generator", page_icon="📸", layout="wide")

# Function to handle Instagram API authentication
def load_instagram_session():
    session_file = 'session.json'
    
    if os.path.isfile(session_file):
        try:
            with open(session_file, 'r') as f:
                cached_settings = json.load(f)
            
            device_id = cached_settings.get('device_id')
            
            # Try to reuse auth settings
            api = Client(
                username="",  # Will be populated from saved session
                password="",  # Will be populated from saved session
                settings=cached_settings
            )
            
            st.success("Successfully logged in using saved session!")
            return api
            
        except (ClientCookieExpiredError, ClientLoginRequiredError) as e:
            logger.warning("Session expired, need to login again")
            # If session expired, we need to login again
            return None
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None
    else:
        logger.info("No saved session found")
        return None

# Function to save Instagram session
def save_instagram_session(api):
    session_file = 'session.json'
    cached_settings = api.settings
    
    # Save cookies and device_id to session file
    with open(session_file, 'w') as f:
        json.dump(cached_settings, f)
    
    logger.info("Session saved successfully")

# Function to initialize Gemini AI
def initialize_gemini():
    try:
        # Get Gemini API key from Streamlit secrets using the flat structure
        api_key = st.secrets["gemini_api_key"]
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro-vision')
        return model
    except Exception as e:
        st.error(f"Failed to initialize Gemini: {e}")
        return None

# Function to generate caption with Gemini
def generate_caption(model, image_path):
    try:
        image = Image.open(image_path)
        response = model.generate_content(
            ["Write a catchy, engaging Instagram caption for this image.", image]
        )
        return response.text
    except Exception as e:
        st.error(f"Failed to generate caption: {e}")
        return "Failed to generate caption. Please try again or use your own caption."

# Function to login to Instagram with credentials from secrets
def instagram_login():
    try:
        # Get Instagram credentials from Streamlit secrets using the flat structure
        username = st.secrets["instagram_username"]
        password = st.secrets["instagram_password"]
        
        with st.spinner("Logging in to Instagram..."):
            api = Client(username, password)
            save_instagram_session(api)
            return api
    except Exception as e:
        error_message = str(e)
        if isinstance(e, ClientError):
            try:
                error_message = json.loads(e.error_response).get('message', str(e))
            except:
                pass
        st.error(f"Instagram login failed: {error_message}")
        return None

# Main function
def main():
    st.title("📸 Instagram Post Generator")
    st.write("Upload an image, generate a caption with Gemini AI, and post to Instagram!")
    
    # Initialize session state
    if 'api' not in st.session_state:
        st.session_state.api = None
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'gemini_model' not in st.session_state:
        st.session_state.gemini_model = None
    if 'uploaded_image' not in st.session_state:
        st.session_state.uploaded_image = None
    if 'image_path' not in st.session_state:
        st.session_state.image_path = None
    if 'generated_caption' not in st.session_state:
        st.session_state.generated_caption = ""
    if 'use_custom_caption' not in st.session_state:
        st.session_state.use_custom_caption = False
    
    # Initialize Gemini model
    if not st.session_state.gemini_model:
        st.session_state.gemini_model = initialize_gemini()
    
    # Setup sidebar for Instagram authentication
    with st.sidebar:
        st.header("Instagram Authentication")
        
        if not st.session_state.logged_in:
            # Try to load existing session
            api = load_instagram_session()
            
            if api:
                st.session_state.api = api
                st.session_state.logged_in = True
                st.success("Logged in using saved session!")
            else:
                # Login with credentials from secrets
                if st.button("Login to Instagram"):
                    api = instagram_login()
                    if api:
                        st.session_state.api = api
                        st.session_state.logged_in = True
                        st.success("Successfully logged in!")
        else:
            st.success("Logged in to Instagram")
            if st.button("Logout"):
                st.session_state.api = None
                st.session_state.logged_in = False
                
                # Remove session file if it exists
                if os.path.exists('session.json'):
                    os.remove('session.json')
                    
                st.success("Logged out successfully")
                st.rerun()
    
    # Main content area
    if st.session_state.logged_in:
        # Image upload section
        st.subheader("Upload Image")
        uploaded_file = st.file_uploader("Choose an image", type=["jpg", "jpeg", "png"])
        
        if uploaded_file:
            # Save the uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                st.session_state.image_path = tmp_file.name
                st.session_state.uploaded_image = uploaded_file
            
            # Display the uploaded image
            col1, col2 = st.columns([1, 1])
            with col1:
                st.image(uploaded_file, caption='Uploaded Image', use_column_width=True)
            
            # Caption generation section
            with col2:
                st.subheader("Caption Generation")
                
                if st.session_state.gemini_model and st.button("Generate Caption with Gemini"):
                    with st.spinner("Generating caption..."):
                        st.session_state.generated_caption = generate_caption(
                            st.session_state.gemini_model, 
                            st.session_state.image_path
                        )
                
                # Caption selection UI
                st.session_state.use_custom_caption = st.checkbox("Use my own caption", value=st.session_state.use_custom_caption)
                
                if st.session_state.use_custom_caption:
                    custom_caption = st.text_area("Your Caption", height=100)
                    final_caption = custom_caption
                else:
                    st.text_area("AI Generated Caption", value=st.session_state.generated_caption, height=100, disabled=True)
                    final_caption = st.session_state.generated_caption
                
                # Post to Instagram button
                if st.button("Post to Instagram"):
                    if not st.session_state.image_path:
                        st.error("Please upload an image first")
                    elif not final_caption:
                        st.error("Please provide a caption")
                    else:
                        try:
                            with st.spinner("Posting to Instagram..."):
                                # Convert image to compatible format if needed
                                with open(st.session_state.image_path, 'rb') as image_file:
                                    photo_data = image_file.read()
                                
                                # Post the photo
                                st.session_state.api.post_photo(
                                    photo_data=photo_data,
                                    caption=final_caption
                                )
                                
                                st.success("Posted successfully to Instagram!")
                                
                                # Clean up temporary file
                                os.unlink(st.session_state.image_path)
                                st.session_state.image_path = None
                                st.session_state.uploaded_image = None
                                st.session_state.generated_caption = ""
                                
                        except Exception as e:
                            st.error(f"Failed to post to Instagram: {e}")
    else:
        st.info("Please log in to Instagram using the sidebar to continue")

# Create a secrets.toml file guide if running locally
if not st.session_state.get('shown_secrets_guide') and not os.path.exists('.streamlit/secrets.toml'):
    st.sidebar.markdown("""
    ### Local Development Setup
    
    Create a `.streamlit/secrets.toml` file with:
    ```toml
    instagram_username = "your_username"
    instagram_password = "your_password"
    gemini_api_key = "your_gemini_api_key"
    ```
    
    For deployed apps, add these secrets in the Streamlit Cloud dashboard.
    """)
    st.session_state.shown_secrets_guide = True

if __name__ == "__main__":
    main()
