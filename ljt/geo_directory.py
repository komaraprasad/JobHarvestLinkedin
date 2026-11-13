"""LinkedIn location IDs (geo list) used with locations.resolve / resolve_many. IDs are LinkedIn's own, as provided."""

DIRECTORY = [
    # Countries
    {"id": "102713980", "name": "India", "type": "Country", "country": "India"},
    {"id": "103644278", "name": "United States", "type": "Country", "country": "United States"},
    {"id": "101165590", "name": "United Kingdom", "type": "Country", "country": "United Kingdom"},
    {"id": "101174742", "name": "Canada", "type": "Country", "country": "Canada"},
    {"id": "101452733", "name": "Australia", "type": "Country", "country": "Australia"},
    {"id": "101282230", "name": "Germany", "type": "Country", "country": "Germany"},
    {"id": "102454443", "name": "Singapore", "type": "Country", "country": "Singapore"},
    {"id": "104305787", "name": "United Arab Emirates", "type": "Country", "country": "United Arab Emirates"},
    # India
    {"id": "105214831", "name": "Bengaluru, Karnataka, India", "type": "Metro Area", "country": "India"},
    {"id": "105556991", "name": "Hyderabad, Telangana, India", "type": "Metro Area", "country": "India"},
    {"id": "106832467", "name": "Chennai, Tamil Nadu, India", "type": "Metro Area", "country": "India"},
    {"id": "106155005", "name": "Mumbai, Maharashtra, India", "type": "Metro Area", "country": "India"},
    {"id": "103503525", "name": "Pune, Maharashtra, India", "type": "Metro Area", "country": "India"},
    {"id": "104113949", "name": "Delhi, India", "type": "Metro Area", "country": "India"},
    {"id": "106888324", "name": "Noida, Uttar Pradesh, India", "type": "City", "country": "India"},
    {"id": "104869687", "name": "Gurugram, Haryana, India", "type": "City", "country": "India"},
    {"id": "104910382", "name": "Kolkata, West Bengal, India", "type": "Metro Area", "country": "India"},
    {"id": "103856277", "name": "Ahmedabad, Gujarat, India", "type": "Metro Area", "country": "India"},
    {"id": "103135898", "name": "Coimbatore, Tamil Nadu, India", "type": "City", "country": "India"},
    {"id": "103099905", "name": "Kochi, Kerala, India", "type": "City", "country": "India"},
    {"id": "103671728", "name": "Jaipur, Rajasthan, India", "type": "City", "country": "India"},
    {"id": "103986016", "name": "Chandigarh, India", "type": "City", "country": "India"},
    {"id": "100998375", "name": "Mysuru, Karnataka, India", "type": "City", "country": "India"},
    # LinkedIn's on-screen name for the Bengaluru region (seen on the live search page, 2026-11-11), same ID
    {"id": "105214831", "name": "Greater Bengaluru Area", "type": "Metro Area", "country": "India"},
    # Metro areas elsewhere
    {"id": "90000084", "name": "San Francisco Bay Area", "type": "Metro Area", "country": "United States"},
    {"id": "90000070", "name": "Greater New York City Area", "type": "Metro Area", "country": "United States"},
    {"id": "90009495", "name": "London Area, United Kingdom", "type": "Metro Area", "country": "United Kingdom"},
    {"id": "90010467", "name": "Dubai, United Arab Emirates", "type": "Metro Area", "country": "United Arab Emirates"},
]

# Every place in world_geo.db that carries a LinkedIn ID (54 in the current file) is added too.
from . import geo_db  # noqa: E402

_names = {d["name"] for d in DIRECTORY}
DIRECTORY += [d for d in geo_db.linked_places() if d["name"] not in _names]

BY_ID = {}
for _d in DIRECTORY:
    BY_ID.setdefault(_d["id"], _d)        # first entry = the official name
