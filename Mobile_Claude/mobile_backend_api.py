# Backend API for Flyer to Calendar Mobile App
# This FastAPI backend will serve both iOS and Android apps

import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import anthropic
import base64
from datetime import datetime, timedelta
from dateutil.parser import parse as date_parser
import json
import re
import stripe
from jose import JWTError, jwt
import os
from enum import Enum

# Initialize FastAPI app
app = FastAPI(title="Flyer to Calendar API", version="1.0.0")

# CORS configuration for mobile apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-here")
JWT_ALGORITHM = "HS256"

# Initialize clients
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
stripe.api_key = STRIPE_API_KEY

# --- Data Models ---

class SubscriptionTier(str, Enum):
    FREE = "free"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"

class User(BaseModel):
    id: str
    email: str
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    scan_count: int = 0
    subscription_expires: Optional[datetime] = None
    created_at: datetime

class ImageRequest(BaseModel):
    image_base64: str
    image_type: str = "image/jpeg"  # or "image/png"

class Event(BaseModel):
    title: str
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: str = ""
    description: str = ""

class EventsResponse(BaseModel):
    events: List[Event]
    total_events: int
    processing_time: float

class SubscriptionRequest(BaseModel):
    plan: SubscriptionTier
    payment_token: str  # Stripe payment token from mobile app

class CalendarEvent(BaseModel):
    title: str
    start_datetime: str  # ISO format
    end_datetime: str    # ISO format
    location: str
    description: str
    
# --- Authentication ---

async def get_current_user(authorization: str = Header(None)):
    """Verify JWT token and return current user"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        # In production, fetch user from database
        return {"id": user_id, "subscription_tier": payload.get("tier", "free")}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- Subscription Management ---

def check_scan_limits(user):
    """Check if user has exceeded scan limits"""
    if user["subscription_tier"] == SubscriptionTier.FREE:
        # Free users get 3 scans per month
        if user.get("scan_count", 0) >= 3:
            return False, "Free trial limit reached. Please upgrade to continue."
    return True, "OK"

# --- Core Event Extraction ---

def extract_events_from_image(image_base64: str, image_type: str) -> List[Event]:
    """Extract multiple events from image using Anthropic Claude"""
    
    prompt = """
    Analyze this image and identify ALL individual events mentioned. This could be an email, flyer, or document with multiple dates and events listed.
    
    Extract EACH event as a separate item. Return a JSON object with a single key "events" containing an array of event objects.
    
    Each event object should have these exact keys:
    - "title": The event name/title
    - "date": The date mentioned (e.g., "September 1", "September 5", etc.)
    - "start_time": The start time if mentioned, otherwise null
    - "end_time": The end time if mentioned, otherwise null
    - "location": The location if mentioned, otherwise empty string ""
    - "description": Any additional details about this specific event
    
    Important: Create a SEPARATE event object for EACH date mentioned.
    Return ONLY the JSON object, no other text.
    """
    
    try:
        response = anthropic_client.messages.create(
            # model="claude-3-sonnet-20241022",
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
                                "media_type": image_type,
                                "data": image_base64,
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
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        
        if json_match:
            data = json.loads(json_match.group(0))
            events = data.get("events", [])
            return [Event(**event) for event in events]
        
        return []
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")

def parse_event_datetime(event: Event) -> tuple:
    """Convert event date/time to ISO format datetime strings"""
    current_year = datetime.now().year
    
    try:
        date_str = event.date
        if not re.search(r'\d{4}', date_str):
            date_str = f"{date_str} {current_year}"
        
        event_date = date_parser(date_str, fuzzy=True)
        
        # Parse start time
        if event.start_time:
            try:
                start_datetime_str = f"{event_date.strftime('%Y-%m-%d')} {event.start_time}"
                start_datetime = date_parser(start_datetime_str, fuzzy=True)
            except:
                start_datetime = event_date.replace(hour=9, minute=0)
        else:
            start_datetime = event_date.replace(hour=9, minute=0)
        
        # Parse end time
        if event.end_time:
            try:
                end_datetime_str = f"{event_date.strftime('%Y-%m-%d')} {event.end_time}"
                end_datetime = date_parser(end_datetime_str, fuzzy=True)
            except:
                end_datetime = start_datetime + timedelta(hours=1)
        else:
            end_datetime = start_datetime + timedelta(hours=1)
        
        return start_datetime.isoformat(), end_datetime.isoformat()
        
    except Exception:
        # Default fallback
        now = datetime.now()
        return now.isoformat(), (now + timedelta(hours=1)).isoformat()

# --- API Endpoints ---

@app.get("/")
async def root():
    return {
        "message": "Flyer to Calendar API",
        "version": "1.0.0",
        "endpoints": ["/extract-events", "/subscribe", "/user/profile"]
    }

@app.post("/extract-events", response_model=EventsResponse)
async def extract_events(
    request: ImageRequest,
    current_user: dict = Depends(get_current_user)
):
    """Extract events from uploaded image"""
    
    # Check subscription limits
    can_scan, message = check_scan_limits(current_user)
    if not can_scan:
        raise HTTPException(status_code=403, detail=message)
    
    # Process the image
    start_time = datetime.now()
    events = extract_events_from_image(request.image_base64, request.image_type)
    processing_time = (datetime.now() - start_time).total_seconds()
    
    # Increment scan count for free users
    # In production, update this in database
    if current_user["subscription_tier"] == SubscriptionTier.FREE:
        # Update scan count in database
        pass
    
    return EventsResponse(
        events=events,
        total_events=len(events),
        processing_time=processing_time
    )

@app.post("/events/format-for-calendar")
async def format_for_calendar(
    events: List[Event],
    current_user: dict = Depends(get_current_user)
):
    """Convert events to calendar-ready format with ISO datetimes"""
    
    calendar_events = []
    for event in events:
        start_dt, end_dt = parse_event_datetime(event)
        calendar_events.append(CalendarEvent(
            title=event.title,
            start_datetime=start_dt,
            end_datetime=end_dt,
            location=event.location,
            description=event.description
        ))
    
    return {"calendar_events": calendar_events}

@app.post("/subscribe")
async def subscribe(
    request: SubscriptionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Handle subscription purchase"""
    
    try:
        # Define price IDs for Stripe
        price_ids = {
            SubscriptionTier.MONTHLY: "price_monthly_999",  # $9.99/month
            SubscriptionTier.YEARLY: "price_yearly_7999",   # $79.99/year
            SubscriptionTier.LIFETIME: "price_lifetime_199" # $199 one-time
        }
        
        if request.plan == SubscriptionTier.LIFETIME:
            # One-time payment
            payment = stripe.PaymentIntent.create(
                amount=19900,  # $199.00 in cents
                currency="usd",
                payment_method=request.payment_token,
                confirm=True
            )
        else:
            # Recurring subscription
            subscription = stripe.Subscription.create(
                customer=current_user["id"],  # Assumes Stripe customer exists
                items=[{"price": price_ids[request.plan]}],
                payment_method=request.payment_token,
                expand=["latest_invoice.payment_intent"]
            )
        
        # Update user subscription in database
        # In production, update database with new subscription tier
        
        return {
            "success": True,
            "message": f"Successfully subscribed to {request.plan} plan",
            "subscription_tier": request.plan
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """Get current user profile and subscription status"""
    
    # In production, fetch from database
    return {
        "user_id": current_user["id"],
        "subscription_tier": current_user["subscription_tier"],
        "scans_remaining": 3 if current_user["subscription_tier"] == "free" else "unlimited",
        "features": {
            "max_events_per_scan": "unlimited",
            "cloud_sync": current_user["subscription_tier"] != "free",
            "priority_processing": current_user["subscription_tier"] in ["yearly", "lifetime"],
            "no_ads": current_user["subscription_tier"] != "free"
        }
    }

@app.post("/auth/register")
async def register(email: str, password: str):
    """Register new user"""
    # In production: Hash password, create user in database
    # Return JWT token
    access_token = jwt.encode(
        {"sub": email, "tier": "free"},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/login")
async def login(email: str, password: str):
    """Login existing user"""
    # In production: Verify credentials against database
    access_token = jwt.encode(
        {"sub": email, "tier": "free"},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )
    return {"access_token": access_token, "token_type": "bearer"}

# --- Health Check ---

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "anthropic": "connected",
            "stripe": "connected"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)