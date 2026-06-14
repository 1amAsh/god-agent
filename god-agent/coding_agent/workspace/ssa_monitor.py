import requests
import json
import time
from datetime import datetime, timedelta

# API Endpoints
ISS_API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
NASA_NEO_FEED_URL = "https://api.nasa.gov/neo/rest/v1/feed"
NOAA_KP_INDEX_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

# NASA API Key (using DEMO_KEY as specified)
NASA_API_KEY = "DEMO_KEY"

def fetch_iss_data():
    """Fetches current ISS location and velocity data."""
    try:
        response = requests.get(ISS_API_URL)
        response.raise_for_status() # Raise an exception for HTTP errors
        data = response.json()
        return {
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "altitude": data.get("altitude"),
            "velocity": data.get("velocity")
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching ISS data: {e}")
        return None

def fetch_neo_data(date_str):
    """Fetches Near Earth Objects data for a specific date."""
    params = {
        "start_date": date_str,
        "end_date": date_str,
        "api_key": NASA_API_KEY
    }
    try:
        response = requests.get(NASA_NEO_FEED_URL, params=params)
        response.raise_for_status() # Raise an exception for HTTP errors
        data = response.json()
        return data.get("near_earth_objects", {}).get(date_str, [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching NEO data: {e}")
        return None

def fetch_kp_index():
    """Fetches the latest NOAA Planetary K-index."""
    try:
        response = requests.get(NOAA_KP_INDEX_URL)
        response.raise_for_status() # Raise an exception for HTTP errors
        data = response.json()
        if data:
            # Kp from the last element of the array
            return float(data[-1].get("Kp", 0))
        return 0.0
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Kp index: {e}")
        return None
    except (ValueError, TypeError) as e:
        print(f"Error parsing Kp index data: {e}")
        return None

def classify_kp(kp_value):
    """Classifies the Kp value into risk categories."""
    if kp_value is None:
        return "UNKNOWN"
    if kp_value < 5:
        return "NOMINAL"
    elif 5 <= kp_value <= 7:
        return "AMBER storm"
    else: # kp_value > 7
        return "RED severe storm"

def determine_overall_risk(has_hazardous_asteroids, kp_classification):
    """Determines the overall risk based on hazardous asteroids and Kp classification."""
    if kp_classification == "RED severe storm":
        return "RED"
    elif has_hazardous_asteroids:
        return "AMBER"
    else:
        return "GREEN"

def main():
    print("Starting SSA Monitor...")
    today_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d") # Using 2026-06-14 as per instructions, but dynamically calculating for demonstration. For the task, I will hardcode 2026-06-14.
    # For the specific task requirement, hardcode the date to 2026-06-14
    neo_date_for_task = "2026-06-14"

    for cycle in range(1, 3): # Run for exactly 2 cycles
        print(f"\n--- Cycle {cycle} ---")

        # 1. Fetch ISS Data
        iss_data = fetch_iss_data()
        if iss_data:
            print(f"ISS Location: Latitude={iss_data['latitude']:.2f}, Longitude={iss_data['longitude']:.2f}")
            print(f"ISS Altitude: {iss_data['altitude']:.2f} km")
        else:
            print("Could not fetch ISS data.")

        # 2. Fetch NASA NEO Feed Data
        neo_objects = fetch_neo_data(neo_date_for_task)
        hazardous_asteroids = []
        if neo_objects:
            for neo in neo_objects:
                if neo.get("is_potentially_hazardous_asteroid"):
                    hazardous_asteroids.append(neo.get("name", "Unknown"))
            print(f"Hazardous Asteroids for {neo_date_for_task}: {len(hazardous_asteroids)} detected")
            for asteroid_name in hazardous_asteroids:
                print(f"  - {asteroid_name}")
        else:
            print(f"Could not fetch NEO data for {neo_date_for_task}.")

        # 3. Fetch NOAA Planetary K-index
        kp_value = fetch_kp_index()
        kp_classification = classify_kp(kp_value)
        if kp_value is not None:
            print(f"Current Kp Index: {kp_value} ({kp_classification})")
        else:
            print("Could not fetch Kp index.")

        # Determine Overall Risk
        has_hazardous = len(hazardous_asteroids) > 0
        overall_risk = determine_overall_risk(has_hazardous, kp_classification)
        print(f"Overall Risk: {overall_risk}")

        if cycle < 2:
            print("Waiting for 60 seconds...")
            time.sleep(60)

    print("SSA Monitor finished.")

if __name__ == '__main__':
    main()
