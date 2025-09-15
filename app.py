import streamlit as st
from PIL import Image
from ics import Calendar, Event
from datetime import datetime, timedelta
from dateutil.parser import parse as date_parser
import json
import fitz  # PyMuPDF
import io
import re
import anthropic
import base64

# --- Configuration ---
st.set_page_config(layout="wide", page_title="Flyer to Calendar", page_icon="📅")

# --- Anthropic API Key (pulled from st.secrets) ---
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]

    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        default_headers={"anthropic-version": "2023-06-01"}
    )
except Exception as e:
    st.error(f"🔴 Anthropic API Configuration Error: {e}")
    st.stop()

# --- Core Functions ---

def image_to_base64(image: Image.Image):
    """
    Converts a PIL Image to a base64 encoded string and determines the correct media type.
    """
    buffered = io.BytesIO()
    media_type = ""
    if image.mode in ("RGBA", "P"):
        image.save(buffered, format="PNG")
        media_type = "image/png"
    else:
        image.save(buffered, format="JPEG")
        media_type = "image/jpeg"
        
    return base64.b64encode(buffered.getvalue()).decode("utf-8"), media_type


def get_anthropic_response_for_multiple_events(image: Image.Image):
    """
    Calls the Anthropic (Claude) API to extract details for MULTIPLE events from an image.
    Returns a list of event dictionaries.
    """
    try:
        image_b64, media_type = image_to_base64(image)

        prompt = """
        Analyze the image of this event flyer and extract ALL distinct event details.
        Provide the output as a clean, raw JSON ARRAY, where each element in the array
        is a JSON object representing one event, with these exact keys:
        "title", "start_time", "end_time", "location", "description".
        """

        response = client.messages.create(
            model="claude-sonnet-4-20250514", 
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )

        response_text = response.content[0].text

        # Extract JSON array
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            try:
                events_list = json.loads(json_match.group(0))
                if isinstance(events_list, list) and all(isinstance(item, dict) for item in events_list):
                    return events_list
                else:
                    st.error("API response is not a valid list of event objects.")
                    st.code(response_text, language="text")
                    return []
            except json.JSONDecodeError:
                st.error("Could not parse the extracted JSON array.")
                st.code(response_text, language="text")
                return []
        else:
            st.error("Could not find a valid JSON array in the API response.")
            st.code(response_text, language="text")
            return []

    except Exception as e:
        st.error(f"An error occurred while calling the Anthropic API: {e}")
        return []


def create_ics_file(event_data: dict) -> str:
    c = Calendar()
    e = Event()
    e.name = event_data.get('title', 'Untitled Event')
    e.location = event_data.get('location', 'Not specified')
    e.description = event_data.get('description', 'No description provided.')

    try:
        begin_dt = date_parser(event_data['start_time'])
    except (ValueError, KeyError, TypeError):
        begin_dt = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        st.warning(f"Could not parse start_time for '{e.name}'. Using default: {begin_dt}")

    try:
        end_dt = date_parser(event_data['end_time'])
    except (ValueError, KeyError, TypeError):
        end_dt = begin_dt + timedelta(hours=2)
        st.warning(f"Could not parse end_time for '{e.name}'. Using default: {end_dt}")

    e.begin = begin_dt
    e.end = end_dt
    c.events.add(e)
    return str(c)


def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    text = re.sub(r'[-\s]+', '-', text)
    return text


# --- Streamlit App UI ---
st.title("📅 Flyer to Calendar Event")
st.markdown("""
Upload one or more event flyers (as images or PDFs) to extract event details 
and generate calendar invites (`.ics` files). If a flyer contains multiple events, 
separate invites will be generated for each.
""")

uploaded_files = st.file_uploader(
    "Upload your event flyers (PNG, JPG, PDF)...",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    st.divider()
    for uploaded_file in uploaded_files:
        st.header(f"Processing: {uploaded_file.name}")
        image = None
        if uploaded_file.type == "application/pdf":
            try:
                pdf_bytes = uploaded_file.getvalue()
                pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
                if len(pdf_document) > 0:
                    page = pdf_document.load_page(0)
                    pix = page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")
                    image = Image.open(io.BytesIO(img_bytes))
                    st.info("PDF detected. Processing the first page as an image.")
                else:
                    st.warning(f"PDF file '{uploaded_file.name}' is empty.")
                    continue
            except Exception as e:
                st.error(f"Failed to process PDF '{uploaded_file.name}': {e}")
                continue
        else:
            try:
                image = Image.open(uploaded_file)
            except Exception as e:
                st.error(f"Failed to open image '{uploaded_file.name}': {e}")
                continue
        
        if image:
            with st.spinner("🤖 Claude is analyzing the flyer for all events..."):
                all_extracted_events = get_anthropic_response_for_multiple_events(image)
            
            if all_extracted_events:
                st.success(f"✅ Extracted {len(all_extracted_events)} event(s) successfully!")
                col1, col2 = st.columns([2, 1])
                with col2:
                    st.image(image, caption=f"Uploaded Flyer: {uploaded_file.name}", use_column_width=True)

                with col1:
                    st.subheader("Extracted Events:")
                    for i, event_data in enumerate(all_extracted_events):
                        st.markdown(f"**--- Event {i+1} ---**")
                        st.subheader(event_data.get("title", f"Event {i+1} (No Title Found)"))
                        st.write(f"**📍 Location:** {event_data.get('location', 'N/A')}")
                        st.write(f"**🕒 Starts:** {event_data.get('start_time', 'N/A')}")
                        st.write(f"**🕒 Ends:** {event_data.get('end_time', 'N/A')}")

                        with st.expander(f"See description & raw data for '{event_data.get('title', f'Event {i+1}')}'"):
                            st.write(f"**Description:** {event_data.get('description', 'N/A')}")
                            st.json(event_data)

                        try:
                            ics_content = create_ics_file(event_data)
                            file_name = f"{slugify(event_data.get('title', f'event_{i+1}'))}.ics"
                            st.download_button(
                                label=f"📅 Add '{event_data.get('title', f'Event {i+1}')}' to Calendar",
                                data=ics_content,
                                file_name=file_name,
                                mime="text/calendar",
                                use_container_width=True,
                                key=f"download_button_{uploaded_file.name}_{i}"
                            )
                        except Exception as e:
                            st.error(f"Could not generate .ics file for '{event_data.get('title', f'Event {i+1}')}': {e}")
                        st.markdown("---")
            else:
                st.error("No events could be extracted from this file.")
        st.divider()
else:
    st.info("Upload a file to get started.")
