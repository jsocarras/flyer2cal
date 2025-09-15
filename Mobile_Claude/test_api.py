import requests
import base64
import json
from PIL import Image
import io

# API base URL
BASE_URL = "http://localhost:8000"

def create_test_image():
    """Create a simple test image with event text"""
    from PIL import Image, ImageDraw, ImageFont
    
    # Create a white image
    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)
    
    # Add some event text
    text = """
    School Events - September 2024
    
    September 5: Parent Meeting
    Time: 7:30 PM - 8:30 PM
    Location: School Auditorium
    
    September 10: Field Trip
    Time: 9:00 AM - 3:00 PM
    Location: Science Museum
    
    September 25: School Carnival
    Time: 10:00 AM - 2:00 PM
    Location: School Grounds
    """
    
    # Try to use default font, fallback to basic if not available
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except:
        font = ImageFont.load_default()
    
    draw.text((50, 50), text, fill='black', font=font)
    
    # Convert to base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return img_base64

def test_health_check():
    """Test 1: Check if API is running"""
    print("Test 1: Health Check")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print("-" * 50)
    return response.status_code == 200

def test_registration():
    """Test 2: Register a new user"""
    print("Test 2: User Registration")
    response = requests.post(
        f"{BASE_URL}/auth/register",
        params={"email": "test@example.com", "password": "testpass123"}
    )
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    print("-" * 50)
    return data.get("access_token")

def test_login():
    """Test 3: Login"""
    print("Test 3: User Login")
    response = requests.post(
        f"{BASE_URL}/auth/login",
        params={"email": "test@example.com", "password": "testpass123"}
    )
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    print("-" * 50)
    return data.get("access_token")

def test_extract_events(token):
    """Test 4: Extract events from image"""
    print("Test 4: Extract Events from Image")
    
    # Create test image
    img_base64 = create_test_image()
    
    # Make request
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "image_base64": img_base64,
        "image_type": "image/png"
    }
    
    response = requests.post(
        f"{BASE_URL}/extract-events",
        json=payload,
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Events Found: {data['total_events']}")
        print(f"Processing Time: {data['processing_time']} seconds")
        for i, event in enumerate(data['events'], 1):
            print(f"\nEvent {i}:")
            print(f"  Title: {event['title']}")
            print(f"  Date: {event['date']}")
            print(f"  Time: {event.get('start_time', 'N/A')} - {event.get('end_time', 'N/A')}")
            print(f"  Location: {event.get('location', 'N/A')}")
        return data['events']
    else:
        print(f"Error: {response.text}")
        return None
    print("-" * 50)

def test_calendar_format(token, events):
    """Test 5: Format events for calendar"""
    print("\nTest 5: Format Events for Calendar")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{BASE_URL}/events/format-for-calendar",
        json=events,
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        for i, event in enumerate(data['calendar_events'], 1):
            print(f"\nCalendar Event {i}:")
            print(f"  Title: {event['title']}")
            print(f"  Start: {event['start_datetime']}")
            print(f"  End: {event['end_datetime']}")
    else:
        print(f"Error: {response.text}")
    print("-" * 50)

def test_user_profile(token):
    """Test 6: Get user profile"""
    print("Test 6: Get User Profile")
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/user/profile", headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print("-" * 50)

def run_all_tests():
    """Run all tests in sequence"""
    print("=" * 50)
    print("FLYER TO CALENDAR API TESTS")
    print("=" * 50)
    
    # Test 1: Health check
    if not test_health_check():
        print("❌ API is not running. Please start it first!")
        return
    
    # Test 2 & 3: Auth
    token = test_registration()
    if not token:
        token = test_login()
    
    if not token:
        print("❌ Authentication failed!")
        return
    
    print(f"✅ Got auth token: {token[:20]}...")
    
    # Test 4: Extract events
    events = test_extract_events(token)
    
    # Test 5: Format for calendar (only if we got events)
    if events:
        test_calendar_format(token, events)
    
    # Test 6: User profile
    test_user_profile(token)
    
    print("\n" + "=" * 50)
    print("✅ ALL TESTS COMPLETED")
    print("=" * 50)

if __name__ == "__main__":
    run_all_tests()