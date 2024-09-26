from flask import Flask, render_template, jsonify, request
import requests
import time
import logging

app = Flask(__name__, template_folder='templates')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PLACES_API_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
PLACE_DETAILS_API_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PHOTO_API_URL = "https://maps.googleapis.com/maps/api/place/photo"
DIRECTIONS_API_URL = "https://maps.googleapis.com/maps/api/directions/json"
MAX_RESULTS = 10
api_key = "API_KEY" 

CURRENT_LOCATION = "41.0369,28.9850"

def translate_to_turkish(text):
    translations = {
        "hours": "saat",
        "hour": "saat",
        "mins": "dakika",
        "min": "dakika",
        "km": "km",
        "m": "m"
    }
    for en, tr in translations.items():
        text = text.replace(en, tr)
    return text

def fetch_places(location, api_key):
    places = []
    params = {
        "location": location,
        "radius": 5000,
        "type": "restaurant",
        "key": api_key
    }
    response = requests.get(PLACES_API_URL, params=params)
    response.raise_for_status()
    data = response.json()

    if "error_message" in data:
        logger.error(f"API hatası: {data['error_message']}")
        return places

    places.extend(data.get('results', []))

    next_page_token = data.get('next_page_token')

    while next_page_token:
        time.sleep(2)
        params = {
            "pagetoken": next_page_token,
            "key": api_key
        }
        response = requests.get(PLACES_API_URL, params=params)
        response.raise_for_status()
        data = response.json()

        if "error_message" in data:
            logger.error(f"API hatası: {data['error_message']}")
            break

        places.extend(data.get('results', []))
        next_page_token = data.get('next_page_token')

    return places

def find_worst_restaurants(places, limit=MAX_RESULTS):
    rated_places = [
        place for place in places
        if place.get('rating') is not None and place.get('user_ratings_total', 0) >= 5
    ]
    worst_places = sorted(
        rated_places,
        key=lambda p: (p['rating'], -p['user_ratings_total'])
    )
    return worst_places[:limit]

def get_place_details(place_id, api_key):
    params = {
        "place_id": place_id,
        "fields": "place_id,name,rating,reviews,user_ratings_total,photos,vicinity,geometry,url",
        "key": api_key
    }
    try:
        response = requests.get(PLACE_DETAILS_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "error_message" in data:
            logger.error(f"API hatası: {data['error_message']}")
            return {}
        result = data.get('result', {})
        if result.get('place_id') != place_id:
            logger.error(f"Yanlış place_id: {place_id}")
            return {}
        return result
    except requests.RequestException as e:
        logger.error(f"Detaylar getirilemedi: {place_id} - {e}")
        return {}

def analyze_reviews(reviews):
    bad_comments = []
    review_ids = set()
    for review in reviews:
        if 'text' in review and 'author_name' in review and 'rating' in review and 'time' in review:
            review_id = f"{review['author_name']}_{review['time']}"
            if review['rating'] <= 2 and review_id not in review_ids:
                bad_comments.append({
                    'author': review['author_name'],
                    'rating': review['rating'],
                    'text': review['text']
                })
                review_ids.add(review_id)
    return bad_comments

def get_photo_reference(photo_reference, max_width=200):
    if not photo_reference:
        return None
    params = {
        "photoreference": photo_reference,
        "maxwidth": max_width,
        "key": api_key
    }
    return requests.Request('GET', PHOTO_API_URL, params=params).prepare().url

def find_good_alternatives(location, api_key):
    params = {
        "location": location,
        "radius": 1000,
        "type": "restaurant",
        "minprice": 0,
        "maxprice": 4,
        "key": api_key
    }

    places = []
    try:
        response = requests.get(PLACES_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if "error_message" in data:
            logger.error(f"API hatası: {data['error_message']}")
            return places
        results = data.get('results', [])
        for place in results:
            if place.get('rating', 0) >= 4.0 and place.get('user_ratings_total', 0) >= 10:
                places.append(place)
    except Exception as e:
        logger.error(f"Alternatifler getirilemedi: {location} - {e}")

    return sorted(
        places,
        key=lambda p: (-p['rating'], -p.get('user_ratings_total', 0))
    )[:3]

def get_directions(origin, destination, mode='walking'):
    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": api_key
    }
    try:
        response = requests.get(DIRECTIONS_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data['status'] != 'OK':
            logger.error(f"Error fetching directions: {data.get('error_message', data['status'])}")
            return None

        directions = data['routes'][0]['legs'][0]
        directions['distance']['text'] = translate_to_turkish(directions['distance']['text'])
        directions['duration']['text'] = translate_to_turkish(directions['duration']['text'])
        return directions
    except Exception as e:
        logger.error(f"Error fetching directions: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results', methods=['POST'])
def results():
    logger.info(f"Yakın restoranlar getiriliyor: {CURRENT_LOCATION}")
    places = fetch_places(CURRENT_LOCATION, api_key)
    logger.info(f"Toplam restoran sayısı: {len(places)}")

    worst_restaurants = find_worst_restaurants(places)

    restaurant_details = []
    for restaurant in worst_restaurants:
        logger.info(f"Restoran işleniyor: {restaurant.get('name')}")
        details = get_place_details(restaurant['place_id'], api_key)
        if not details:
            continue
        bad_comments = analyze_reviews(details.get('reviews', []))
        if not bad_comments:
            logger.info(f"Kötü yorum bulunamadı: {restaurant.get('name')}")
            continue

        photo_reference = details.get('photos', [{}])[0].get('photo_reference')
        photo_url = get_photo_reference(photo_reference) if photo_reference else None

        restaurant_location = f"{details['geometry']['location']['lat']},{details['geometry']['location']['lng']}"
        alternatives = find_good_alternatives(restaurant_location, api_key)

        restaurant_url = details.get('url')
        if not restaurant_url:
            restaurant_url = f"https://www.google.com/maps/place/?q=place_id:{restaurant['place_id']}"

        directions_to_restaurant = get_directions(CURRENT_LOCATION, restaurant_location)

        alternatives_with_directions = []
        for alt in alternatives:
            alt_location = f"{alt['geometry']['location']['lat']},{alt['geometry']['location']['lng']}"
            alt_directions = get_directions(CURRENT_LOCATION, alt_location)
            alt_url = f"https://www.google.com/maps/place/?q=place_id:{alt['place_id']}"
            alternatives_with_directions.append({
                "place": alt,
                "directions": alt_directions,
                "url": alt_url
            })

        restaurant_details.append({
            "restaurant": details,
            "bad_comments": bad_comments,
            "photo_url": photo_url,
            "restaurant_url": restaurant_url,
            "directions": directions_to_restaurant,
            "alternatives": alternatives_with_directions
        })

    if not restaurant_details:
        logger.warning("Kötü yorum içeren restoran bulunamadı.")
        return render_template('no_results.html')

    return render_template('results.html', restaurant_details=restaurant_details)

if __name__ == "__main__":
    app.run(debug=True)
