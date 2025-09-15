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
from collections import defaultdict
import zipfile

# --- Page config ---
st.set_page_config(layout="wide", page_title="Flyer to Calendar", page_icon="📅")

# --- Anthropic API Key ---
# Recommended: add to .streamlit/secrets.toml as:
# [general]
# ANTHROPIC_API_KEY="sk-..."
ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", "").strip() or \
    "sk-ant-REPLACE_ME"  # fallback to keep the app runnable if you prefer hard-coding

# Configure the Anthropic API client
try:
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        default_headers={"anthropic-version": "2023-06-01"}
    )
except Exception as e:
    st.error(f"🔴 Anthropic API Configuration Error: Could not initialize the client. Details: {e}")
    st.stop()


# ----------------------------
# Helpers & Core Functionality
# ----------------------------

def image_to_base64(image: Image.Image):
    """Convert PIL Image to base64 and return data + media_type."""
    buffered = io.BytesIO()
    media_type = ""
    if image.mode in ("RGBA", "P"):
        image.save(buffered, format="PNG")
        media_type = "image/png"
    else:
        image.save(buffered, format="JPEG")
        media_type = "image/jpeg"
    return base64.b64encode(buffered.getvalue()).decode("utf-8"), media_type


def _extract_json_block(text: str):
    """Return first JSON object block in text, else None."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else None


def get_events_from_flyer(image: Image.Image):
    """
    Calls the Anthropic (Claude) API to extract *multiple* events.
    Returns a list[dict] of events [{title,start_time,end_time,location,description}, ...].
    """
    try:
        img_b64, media_type = image_to_base64(image)

        prompt = """
You are extracting calendar events from a flyer/email screenshot that often lists many dates and times.

Return ONLY a single raw JSON object with this exact top-level schema:

{
  "events": [
    {
      "title": "...",
      "start_time": "YYYY-MM-DDTHH:MM:SS",
      "end_time": "YYYY-MM-DDTHH:MM:SS",
      "location": "...",
      "description": "..."
    },
    ...
  ]
}

Guidelines:
- Create a SEPARATE event for each distinct line/bullet or activity (e.g., if a date lists "Homecoming Carnival, Pep Rally, Out of Uniform" make 3 events).
- If a line lists multiple grade-specific time slots, create one event per slot and include the grade in the title (e.g., "Pep Rally (PreK–4th)").
- If the flyer shows a month header like "September" with many dates, use that month for all those dates. If no year is printed, use the current year.
- If an end time is not present, set it to 2 hours after start_time.
- If a date range appears without finer granularity (e.g., "Sep 29–30 Book Fair"), create one event per day (00:00 to 23:59:59 each day) with the same title.
- Use ISO 8601 with seconds (e.g., "2025-09-25T09:00:00").
- If a location is not specified, set it to "" (empty string).
- If a description is not specified, set it to "".

Do not include any explanation or markdown—only valid JSON.
"""

        response = client.messages.create(
            # Use your preferred Claude model here
            model="claude-3-5-sonnet-20240620",
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt}
                    ],
                }
            ],
        )

        # Anthropic SDK returns a list of content blocks. We expect the first text block to hold JSON.
        response_text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text" and hasattr(block, "text"):
                response_text += block.text

        json_block = _extract_json_block(response_text)
        if not json_block:
            st.error("Could not find a valid JSON object in Claude's response.")
            st.code(response_text or "[empty response]", language="text")
            return []

        data = json.loads(json_block)

        # Normalize: handle "events" array OR a single event object fallback
        if isinstance(data, dict) and "events" in data and isinstance(data["events"], list):
            events = data["events"]
        elif isinstance(data, dict):
            events = [data]  # single event object fallback
        elif isinstance(data, list):
            events = data
        else:
            events = []

        return _normalize_and_validate_events(events)

    except json.JSONDecodeError as e:
        st.error(f"Could not parse Claude's response as JSON. Error: {e}")
        return []
    except Exception as e:
        st.error(f"An error occurred while calling the Anthropic API: {e}")
        return []


def _normalize_and_validate_events(events):
    """
    - Ensures required keys exist.
    - Fills missing end_time with start_time + 2h.
    - Coerces all datetimes to ISO strings.
    - Drops clearly invalid rows (no parseable start_time).
    """
    normalized = []
    for i, ev in enumerate(events):
        ev = ev or {}
        title = str(ev.get("title") or "Untitled Event").strip()

        # Parse start
        start_raw = ev.get("start_time")
        start_dt = None
        if start_raw:
            try:
                start_dt = date_parser(str(start_raw))
            except Exception:
                start_dt = None

        if not start_dt:
            # Skip events without a parseable start time; they would break ICS anyway
            # (You can soften this by defaulting to today at 9am if you prefer)
            continue

        # Parse end or default +2h
        end_raw = ev.get("end_time")
        end_dt = None
        if end_raw:
            try:
                end_dt = date_parser(str(end_raw))
            except Exception:
                end_dt = None

        if not end_dt:
            end_dt = start_dt + timedelta(hours=2)

        location = str(ev.get("location") or "").strip()
        description = str(ev.get("description") or "").strip()

        normalized.append({
            "title": title,
            "start_time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "end_time": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "location": location,
            "description": description,
        })
    return normalized


def create_ics_for_event(event_data: dict) -> str:
    """Create a single-event .ics string."""
    c = Calendar()
    e = Event()
    e.name = event_data.get('title', 'Untitled Event')
    e.location = event_data.get('location', '')
    e.description = event_data.get('description', '')
    try:
        e.begin = date_parser(event_data['start_time'])
        e.end = date_parser(event_data['end_time'])
    except Exception as err:
        # As last resort, put now..now+2h so file is still valid
        st.warning(f"Could not parse date/time for '{e.name}'. Using default times. Error: {err}")
        now = datetime.now()
        e.begin, e.end = now, now + timedelta(hours=2)
    c.events.add(e)
    return str(c)


def create_ics_for_many(events: list[dict]) -> str:
    """Create a combined .ics string with all events."""
    c = Calendar()
    for ev in events:
        e = Event()
        e.name = ev.get('title', 'Untitled Event')
        e.location = ev.get('location', '')
        e.description = ev.get('description', '')
        try:
            e.begin = date_parser(ev['start_time'])
            e.end = date_parser(ev['end_time'])
        except Exception:
            # Skip any broken entries in the combined file to avoid corrupting the ICS
            continue
        c.events.add(e)
    return str(c)


def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    text = re.sub(r'[-\s]+', '-', text)
    return text or "event"


def group_events_by_date(events: list[dict]):
    """Group events by start date (YYYY-MM-DD)."""
    buckets = defaultdict(list)
    for ev in events:
        try:
            d = date_parser(ev["start_time"]).date()
            buckets[d.isoformat()].append(ev)
        except Exception:
            buckets["unknown-date"].append(ev)
    # Sort groups by actual date key
    return dict(sorted(buckets.items(), key=lambda kv: kv[0]))


def build_zip_of_individual_ics(events: list[dict], base_name: str) -> bytes:
    """Return a .zip (as bytes) that contains one .ics per event."""
    mem_buf = io.BytesIO()
    with zipfile.ZipFile(mem_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ev in events:
            ics = create_ics_for_event(ev)
            fname = f"{slugify(base_name)}-{slugify(ev['title'])}.ics"
            zf.writestr(fname, ics)
    mem_buf.seek(0)
    return mem_buf.read()


# ----------------------------
# Streamlit UI
# ----------------------------

st.title("📅 Flyer → Multiple Calendar Invites")
st.markdown("""
Upload one or more flyers/emails (images or PDFs).  
I’ll extract **every event** and give you **individual .ics files**, a **combined .ics**, and a **.zip**.
""")

uploaded_files = st.file_uploader(
    "Upload your flyers (PNG, JPG, PDF)…",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    st.divider()

for uploaded_file in uploaded_files or []:
    st.header(f"Processing: `{uploaded_file.name}`")

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
                st.divider()
                continue
        except Exception as e:
            st.error(f"Failed to process PDF file '{uploaded_file.name}': {e}")
            st.divider()
            continue
    else:
        try:
            image = Image.open(uploaded_file)
        except Exception as e:
            st.error(f"Failed to open image file '{uploaded_file.name}': {e}")
            st.divider()
            continue

    if not image:
        st.error("No image could be read.")
        st.divider()
        continue

    with st.spinner("🤖 Claude is analyzing the flyer…"):
        events = get_events_from_flyer(image)

    if not events:
        st.error("No events found for this file.")
        st.divider()
        continue

    # Right column shows the flyer; left column shows structured events
    col1, col2 = st.columns([2, 1], gap="large")

    with col2:
        st.image(image, caption=f"Uploaded: {uploaded_file.name}", use_column_width=True)

    with col1:
        st.success(f"✅ Found {len(events)} event(s)")
        # Group by date for a neat overview
        grouped = group_events_by_date(events)
        for date_key, items in grouped.items():
            try:
                pretty = date_parser(date_key).strftime("%A, %B %d, %Y")
            except Exception:
                pretty = date_key
            with st.expander(pretty, expanded=True):
                for idx, ev in enumerate(sorted(items, key=lambda e: e["start_time"])):
                    start_disp = date_parser(ev["start_time"]).strftime("%-I:%M %p")
                    end_disp = date_parser(ev["end_time"]).strftime("%-I:%M %p")
                    st.markdown(f"**{ev['title']}**  —  {start_disp}–{end_disp}")
                    if ev.get("location"):
                        st.write(f"📍 {ev['location']}")
                    if ev.get("description"):
                        st.caption(ev["description"])

                    # Per-event .ics download
                    try:
                        ics_content = create_ics_for_event(ev)
                        file_name = f"{slugify(ev['title'])}.ics"
                        st.download_button(
                            label="📅 Download invite (.ics)",
                            data=ics_content,
                            file_name=file_name,
                            mime="text/calendar",
                            use_container_width=True,
                            key=f"{uploaded_file.name}-{date_key}-{idx}"
                        )
                    except Exception as e:
                        st.error(f"Could not generate .ics for '{ev['title']}': {e}")
                    st.markdown("---")

        # Combined downloads (all events from this flyer)
        st.subheader("Bulk downloads for this flyer")
        try:
            combined_ics = create_ics_for_many(events)
            st.download_button(
                "📥 Download ALL in one .ics (adds every event)",
                data=combined_ics,
                file_name=f"{slugify(uploaded_file.name)}-all-events.ics",
                mime="text/calendar",
                use_container_width=True,
                key=f"combined-{uploaded_file.name}"
            )
        except Exception as e:
            st.error(f"Could not create combined .ics: {e}")

        try:
            zipped = build_zip_of_individual_ics(events, base_name=uploaded_file.name)
            st.download_button(
                "🗂️ Download a .zip of individual .ics files",
                data=zipped,
                file_name=f"{slugify(uploaded_file.name)}-events.zip",
                mime="application/zip",
                use_container_width=True,
                key=f"zip-{uploaded_file.name}"
            )
        except Exception as e:
            st.error(f"Could not build .zip: {e}")

    st.divider()

if not uploaded_files:
    st.info("Upload a flyer to get started.")
