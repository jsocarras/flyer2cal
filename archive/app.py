# gemini_api_key = AIzaSyAZsenG_sU-W8AahjWLzbqMGnun5Hb7L10

import streamlit as st
import google.generativeai as genai
from PIL import Image
from ics import Calendar, Event
from datetime import datetime
from dateutil.parser import parse as date_parser
import json
import fitz  # PyMuPDF
import io
import re

# --- Configuration ---
# Set page configuration for a cleaner look
st.set_page_config(layout="wide", page_title="Flyer to Calendar", page_icon="📅")

# Hard-coded Gemini API Key (as requested)
# IMPORTANT: In a real-world application, use st.secrets or environment variables.
GEMINI_API_KEY = "AIzaSyAZsenG_sU-W8AahjWLzbqMGnun5Hb7L10"

# Configure the Gemini API
try:
    genai.configure(api_key=GEMINI_API_KEY)
    # Check if the API key is valid by listing models
    # This will raise an exception if the key is bad
    genai.list_models() 
except Exception as e:
    st.error(f"🔴 Gemini API Configuration Error: The provided API key is invalid or has expired. Please check the key. Details: {e}")
    st.stop() # Stop the app if the API key is not working

# --- Core Functions ---

def get_gemini_response(image: Image.Image):
    """
    Calls the Gemini Vision API to extract event details from an image.
    
    Args:
        image (PIL.Image.Image): The image of the flyer.

    Returns:
        dict: A dictionary with the extracted event details or None on failure.
    """
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # This prompt is crucial for getting structured, reliable output.
    prompt = """
    Analyze the image of this event flyer and extract the following details.
    Provide the output in a clean, raw JSON format with these exact keys:
    "title", "start_time", "end_time", "location", "description".
    
    - "title": The main title of the event.
    - "start_time": The start date and time. Use a full ISO 8601 format (e.g., '2024-08-15T19:00:00').
    - "end_time": The end date and time. If not specified, estimate it to be 2 hours after the start time. Use the same format.
    - "location": The physical address or venue name. If not found, use an empty string "".
    - "description": A brief summary of the event, including any key details or contact info. If not found, use an empty string "".

    Do not include any text before or after the JSON object.
    """
    
    try:
        response = model.generate_content([prompt, image])
        # Clean up the response to extract only the JSON part
        json_text = re.search(r'```json\n({.*?})\n```', response.text, re.DOTALL)
        if json_text:
            return json.loads(json_text.group(1))
        else:
            # Fallback for when Gemini doesn't use markdown
            return json.loads(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        st.error(f"Could not parse Gemini's response as JSON. Error: {e}")
        st.text("Raw Gemini Response:")
        st.code(response.text, language="text")
        return None
    except Exception as e:
        st.error(f"An error occurred while calling the Gemini API: {e}")
        return None


def create_ics_file(event_data: dict) -> str:
    """
    Creates an iCalendar (.ics) file content from event data.

    Args:
        event_data (dict): Dictionary containing event details.

    Returns:
        str: The content of the .ics file as a string.
    """
    c = Calendar()
    e = Event()

    e.name = event_data.get('title', 'Untitled Event')
    e.location = event_data.get('location', 'Not specified')
    e.description = event_data.get('description', 'No description provided.')

    try:
        # dateutil.parser is very flexible with input formats
        e.begin = date_parser(event_data['start_time'])
        e.end = date_parser(event_data['end_time'])
    except (ValueError, KeyError) as e:
        st.warning(f"Could not parse date/time: {e}. Using default times.")
        e.begin = datetime.now()
        e.end = datetime.now()

    c.events.add(e)
    return str(c)

def slugify(text: str) -> str:
    """
    Simple function to create a clean filename from a title.
    """
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    text = re.sub(r'[-\s]+', '-', text)
    return text

# --- Streamlit App UI ---

st.title("📅 Flyer to Calendar Event")
st.markdown("""
Upload one or more event flyers (as images or PDFs) to instantly extract the details 
and generate a calendar invite (`.ics` file) for each one.
""")

# File Uploader
uploaded_files = st.file_uploader(
    "Upload your event flyers (PNG, JPG, PDF)...",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    st.divider()
    
    for uploaded_file in uploaded_files:
        st.header(f"Processing: `{uploaded_file.name}`")
        
        images_to_process = []
        
        # --- Handle different file types ---
        if uploaded_file.type == "application/pdf":
            try:
                # Use PyMuPDF to open the PDF from bytes
                pdf_bytes = uploaded_file.getvalue()
                pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
                # We'll just process the first page for flyers
                page = pdf_document.load_page(0)
                pix = page.get_pixmap(dpi=200) # Render at higher DPI for better OCR
                img_bytes = pix.tobytes("png")
                image = Image.open(io.BytesIO(img_bytes))
                images_to_process.append(image)
                st.info(f"PDF detected. Processing the first page as an image.")
            except Exception as e:
                st.error(f"Failed to process PDF file '{uploaded_file.name}': {e}")
                continue # Skip to the next file
        else:
            # For standard image files
            try:
                image = Image.open(uploaded_file)
                images_to_process.append(image)
            except Exception as e:
                st.error(f"Failed to open image file '{uploaded_file.name}': {e}")
                continue # Skip to the next file

        # --- Process each extracted image ---
        for i, image in enumerate(images_to_process):
            with st.spinner("🤖 Gemini is analyzing the flyer..."):
                event_data = get_gemini_response(image)

            if event_data:
                st.success("✅ Details Extracted Successfully!")
                
                # Display the extracted data and the download button in columns
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.subheader(event_data.get("title", "No Title Found"))
                    st.write(f"**📍 Location:** {event_data.get('location', 'N/A')}")
                    st.write(f"**🕒 Starts:** {event_data.get('start_time', 'N/A')}")
                    st.write(f"**🕒 Ends:** {event_data.get('end_time', 'N/A')}")
                    with st.expander("See full description & raw data"):
                        st.write(f"**Description:** {event_data.get('description', 'N/A')}")
                        st.json(event_data)
                
                with col2:
                    st.image(image, caption=f"Uploaded Flyer: {uploaded_file.name}", use_column_width=True)
                    
                    # Generate ICS file and create download button
                    try:
                        ics_content = create_ics_file(event_data)
                        file_name = f"{slugify(event_data.get('title', 'event'))}.ics"
                        
                        st.download_button(
                            label="📅 Add to Calendar",
                            data=ics_content,
                            file_name=file_name,
                            mime="text/calendar",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f"Could not generate .ics file: {e}")

            else:
                st.error("Could not extract details for this file.")
        
        st.divider()

else:
    st.info("Upload a file to get started.")