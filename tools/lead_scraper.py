"""
Real lead scraper — multi-source.
Priority: Apollo.io (B2B contacts) → Google Maps Places → Yelp → OpenStreetMap (free, no key).
No fake data: unknown fields are left empty or marked "por verificar".
"""

import time
import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

# ── City targets — high Latino business concentration ─────────────────────────
LATINO_CITIES = [
    "Miami, FL",
    "Los Angeles, CA",
    "Houston, TX",
    "New York, NY",
    "Chicago, IL",
    "Dallas, TX",
    "San Antonio, TX",
    "Phoenix, AZ",
    "San Diego, CA",
    "El Paso, TX",
    "McAllen, TX",
    "Hialeah, FL",
    "Doral, FL",
    "Bronx, NY",
    "East Los Angeles, CA",
]

# Bounding boxes [south, west, north, east] for Overpass queries
CITY_BBOX = {
    "Miami, FL":             (25.709, -80.320, 25.855, -80.139),
    "Los Angeles, CA":       (33.970, -118.450, 34.080, -118.330),
    "Houston, TX":           (29.650, -95.500, 29.820, -95.270),
    "New York, NY":          (40.680, -74.020, 40.780, -73.910),
    "Chicago, IL":           (41.790, -87.750, 41.920, -87.600),
    "Dallas, TX":            (32.700, -96.870, 32.820, -96.750),
    "San Antonio, TX":       (29.370, -98.570, 29.530, -98.420),
    "Phoenix, AZ":           (33.390, -112.150, 33.530, -112.010),
    "San Diego, CA":         (32.680, -117.170, 32.780, -117.080),
    "El Paso, TX":           (31.720, -106.550, 31.840, -106.430),
    "McAllen, TX":           (26.180, -98.290, 26.280, -98.180),
    "Hialeah, FL":           (25.820, -80.330, 25.890, -80.270),
    "Doral, FL":             (25.800, -80.390, 25.850, -80.330),
    "Bronx, NY":             (40.810, -73.940, 40.910, -73.830),
    "East Los Angeles, CA":  (34.010, -118.180, 34.060, -118.130),
}

# ── ICP industry → Google Maps search terms ───────────────────────────────────
# OSM amenity/shop/craft tags per industry
INDUSTRY_TO_OSM = {
    "restaurantes":        [('amenity', 'restaurant'), ('amenity', 'cafe'), ('amenity', 'fast_food')],
    "gym":                 [('leisure', 'fitness_centre'), ('leisure', 'sports_centre')],
    "consultorios medicos":[('amenity', 'clinic'), ('amenity', 'doctors'), ('amenity', 'dentist')],
    "agentes de seguro":   [('office', 'insurance')],
    "realtors":            [('office', 'estate_agent')],
    "plomeros":            [('craft', 'plumber')],
    "fences":              [('craft', 'fence_contractor')],
    "constructions":       [('craft', 'construction_worker'), ('office', 'construction_company')],
    "cleaners":            [('shop', 'laundry'), ('craft', 'cleaning')],
}

INDUSTRY_TO_GMAPS_QUERY = {
    "restaurantes":        "restaurante latino",
    "gym":                 "gym fitness latino",
    "consultorios medicos":"clinica medica latina",
    "agentes de seguro":   "agente de seguro hispano",
    "realtors":            "agente de bienes raices hispano",
    "plomeros":            "plomero latino plumbing",
    "fences":              "fence company latino",
    "constructions":       "construction company latino",
    "cleaners":            "cleaning service latina",
}

# ── ICP industry → Yelp categories ───────────────────────────────────────────
INDUSTRY_TO_YELP = {
    "restaurantes":        "restaurants",
    "gym":                 "gyms",
    "consultorios medicos":"doctors",
    "agentes de seguro":   "insurance",
    "realtors":            "realestate",
    "plomeros":            "plumbing",
    "fences":              "fences",
    "constructions":       "contractors",
    "cleaners":            "homecleaning",
}

# ── Apollo.io industry tags (common IDs) ─────────────────────────────────────
INDUSTRY_TO_APOLLO_TAGS = {
    "restaurantes":        ["restaurants", "food & beverages"],
    "gym":                 ["health, wellness and fitness"],
    "consultorios medicos":["medical practice", "hospital & health care"],
    "agentes de seguro":   ["insurance"],
    "realtors":            ["real estate"],
    "plomeros":            ["construction"],
    "fences":              ["construction"],
    "constructions":       ["construction"],
    "cleaners":            ["facilities services"],
}


# ── Source 1: Google Maps Places API ─────────────────────────────────────────

def _gmaps_search(query: str, city: str, count: int) -> list[dict]:
    key = settings.GOOGLE_MAPS_API_KEY
    if not key:
        return []
    results = []
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": f"{query} {city}", "language": "es", "key": key},
            timeout=15,
        )
        data = r.json()
        for place in data.get("results", [])[:count]:
            place_id = place.get("place_id", "")
            detail   = _gmaps_detail(place_id, key)
            phone   = detail.get("formatted_phone_number", "")
            website = detail.get("website", "")
            address = place.get("formatted_address", "")
            name    = place.get("name", "")
            rating  = place.get("rating", "")
            n_reviews = place.get("user_ratings_total", 0)
            results.append({
                "company":      name,
                "name":         "Dueño — por verificar",
                "job_title":    "Owner",
                "email":        "",
                "phone":        phone,
                "website":      website,
                "address":      address,
                "industry":     query,
                "company_size": "1-50",
                "language":     "es",
                "source":       "google_maps",
                "notes":        (f"{name} en {city}. "
                                 f"Rating: {rating}/5 ({n_reviews} reseñas). "
                                 f"Web: {website or 'sin web'}."),
                "_place_id":    place_id,
            })
            time.sleep(0.3)
    except Exception as e:
        logger.warning(f"[gmaps] {e}")
    return results


def _gmaps_detail(place_id: str, key: str) -> dict:
    if not place_id:
        return {}
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields":   "formatted_phone_number,website",
                "key":      key,
            },
            timeout=10,
        )
        return r.json().get("result", {})
    except Exception:
        return {}


# ── Source 2: Apollo.io People Search ────────────────────────────────────────

def _apollo_search(titles: list, industry: str, location: str, count: int) -> list[dict]:
    key = settings.APOLLO_API_KEY
    if not key:
        return []
    industry_tags = INDUSTRY_TO_APOLLO_TAGS.get(industry, [industry])
    results = []
    try:
        r = requests.post(
            "https://api.apollo.io/v1/mixed_people/search",
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
            json={
                "api_key":             key,
                "person_titles":       titles,
                "organization_industry_tag_ids": industry_tags,
                "person_locations":    [location],
                "contact_email_status":["verified", "likely to engage"],
                "per_page":            min(count, 25),
                "page":                1,
            },
            timeout=20,
        )
        data = r.json()
        for p in data.get("people", []):
            org    = p.get("organization") or {}
            emails = p.get("email") or ""
            results.append({
                "name":         f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                "job_title":    p.get("title", "Owner"),
                "email":        emails,
                "phone":        p.get("phone_numbers", [{}])[0].get("sanitized_number", "") if p.get("phone_numbers") else "",
                "company":      org.get("name", ""),
                "website":      org.get("website_url", ""),
                "linkedin_url": p.get("linkedin_url", ""),
                "industry":     industry,
                "company_size": _apollo_size(org.get("estimated_num_employees", 0)),
                "language":     "es",
                "source":       "apollo",
                "notes":        (f"{p.get('title','')} en {org.get('name','')}. "
                                 f"LinkedIn: {p.get('linkedin_url','N/A')}"),
            })
    except Exception as e:
        logger.warning(f"[apollo] {e}")
    return results


def _apollo_size(n: int) -> str:
    if n <= 10:  return "1-10"
    if n <= 50:  return "11-50"
    if n <= 200: return "51-200"
    return "200+"


# ── Source 3: Yelp Fusion API ─────────────────────────────────────────────────

def _yelp_search(category: str, location: str, count: int) -> list[dict]:
    key = settings.YELP_API_KEY
    if not key:
        return []
    results = []
    try:
        r = requests.get(
            "https://api.yelp.com/v3/businesses/search",
            headers={"Authorization": f"Bearer {key}"},
            params={
                "categories": category,
                "location":   location,
                "limit":      min(count, 50),
                "sort_by":    "review_count",
            },
            timeout=15,
        )
        for biz in r.json().get("businesses", []):
            cats  = ", ".join(c["title"] for c in biz.get("categories", []))
            loc   = biz.get("location", {})
            addr  = ", ".join(filter(None, [
                loc.get("address1",""), loc.get("city",""),
                loc.get("state",""), loc.get("zip_code",""),
            ]))
            results.append({
                "company":      biz.get("name", ""),
                "name":         "Dueño — por verificar",
                "job_title":    "Owner",
                "email":        "",
                "phone":        biz.get("phone", ""),
                "website":      biz.get("url", ""),
                "address":      addr,
                "industry":     category,
                "company_size": "1-50",
                "language":     "es",
                "source":       "yelp",
                "notes":        (f"{biz.get('name','')} en {loc.get('city','')}. "
                                 f"Rating: {biz.get('rating','')}/5 "
                                 f"({biz.get('review_count',0)} reseñas). "
                                 f"Categorías: {cats}."),
                "_yelp_id":     biz.get("id", ""),
            })
    except Exception as e:
        logger.warning(f"[yelp] {e}")
    return results


# ── Source 4: OpenStreetMap Overpass API (free, no key, real data) ────────────

def _osm_search(industry: str, city: str, count: int) -> list[dict]:
    """
    Query OpenStreetMap via Overpass API. Completely free, no key required.
    Returns real business listings with name, phone, website when available.
    """
    osm_tags = INDUSTRY_TO_OSM.get(industry, [('amenity', 'restaurant')])
    bbox = CITY_BBOX.get(city)
    if not bbox:
        # Geocode city via Nominatim
        bbox = _nominatim_bbox(city)
    if not bbox:
        return []

    s, w, n, e = bbox
    results = []

    for tag_key, tag_val in osm_tags:
        if len(results) >= count:
            break
        need = count - len(results)
        query = (
            f'[out:json][timeout:20];'
            f'(node["{tag_key}"="{tag_val}"]({s},{w},{n},{e});'
            f' way["{tag_key}"="{tag_val}"]({s},{w},{n},{e}););'
            f'out body {need * 3};'
        )
        try:
            r = requests.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
                headers={"User-Agent": "VoxifyAgent/1.0 (contact@voxify.ai)"},
                timeout=25,
            )
            elements = r.json().get("elements", [])
            for el in elements:
                tags = el.get("tags", {})
                biz_name = tags.get("name", "")
                if not biz_name:
                    continue
                phone   = tags.get("phone") or tags.get("contact:phone", "")
                website = tags.get("website") or tags.get("contact:website", "")
                city_name = tags.get("addr:city", city.split(",")[0])
                street    = tags.get("addr:street", "")
                housenumber = tags.get("addr:housenumber", "")
                address   = " ".join(filter(None, [housenumber, street, city_name]))
                results.append({
                    "company":      biz_name,
                    "name":         "Dueño — por verificar",
                    "job_title":    "Owner",
                    "email":        "",
                    "phone":        _clean_phone(phone),
                    "website":      website,
                    "address":      address or city,
                    "industry":     industry,
                    "company_size": "1-50",
                    "language":     "es",
                    "source":       "openstreetmap",
                    "notes":        (f"{biz_name} en {city_name}. "
                                     f"Tipo: {tag_val}. "
                                     f"{'Web: ' + website if website else 'Sin web en OSM.'}"),
                    "_osm_id":      el.get("id", ""),
                })
                if len(results) >= count:
                    break
            time.sleep(1)  # Overpass rate limit courtesy
        except Exception as e:
            logger.warning(f"[osm] {tag_key}={tag_val} en {city}: {e}")

    return results


def _nominatim_bbox(city: str) -> tuple | None:
    """Get bounding box for a city name via Nominatim."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": city, "format": "json", "limit": 1, "addressdetails": 0},
            headers={"User-Agent": "VoxifyAgent/1.0"},
            timeout=10,
        )
        results = r.json()
        if results:
            bb = results[0].get("boundingbox", [])
            if len(bb) == 4:
                return float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3])
    except Exception:
        pass
    return None


def _clean_phone(phone: str) -> str:
    if not phone:
        return ""
    import re
    digits = re.sub(r"[^\d+]", "", phone)
    return digits if len(digits) >= 7 else phone


# ── Optional enrichment: Hunter.io email finder ───────────────────────────────

def _enrich_email(domain: str, first: str = "", last: str = "") -> str:
    """Try to find a verified email for a contact at a domain."""
    key = settings.HUNTER_API_KEY
    if not key or not domain:
        return ""
    try:
        r = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first,
                    "last_name": last, "api_key": key},
            timeout=10,
        )
        data = r.json().get("data", {})
        if data.get("score", 0) >= 50:
            return data.get("email", "")
    except Exception:
        pass
    return ""


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_leads(icp: dict, count: int = 10,
                 source_hint: str = "") -> tuple[list[dict], str]:
    """
    Scrape real leads from multiple sources based on ICP.
    Returns (leads, error_message).
    """
    industries = icp.get("target_industries", [])
    titles     = icp.get("decision_maker_titles", ["owner", "manager"])
    geo        = icp.get("geography", "")

    # Pick target cities — from source_hint or rotate through LATINO_CITIES
    if source_hint:
        cities = [source_hint]
    else:
        cities = LATINO_CITIES[:6]

    if not industries:
        return [], "El ICP no tiene industrias configuradas."

    leads: list[dict] = []
    per_industry = max(1, count // len(industries))

    for industry in industries:
        if len(leads) >= count:
            break

        need = min(per_industry, count - len(leads))
        city = cities[len(leads) % len(cities)]

        # 1. Apollo.io (best quality — has contact name + email)
        if settings.APOLLO_API_KEY:
            batch = _apollo_search(titles, industry, city, need)
            if batch:
                leads.extend(batch[:need])
                logger.info(f"[scraper] Apollo: {len(batch)} leads para '{industry}' en {city}")
                continue

        # 2. Google Maps Places (real businesses with phone + web)
        if settings.GOOGLE_MAPS_API_KEY:
            query = INDUSTRY_TO_GMAPS_QUERY.get(industry, industry)
            batch = _gmaps_search(query, city, need)
            if batch:
                # Try to enrich emails via Hunter.io
                if settings.HUNTER_API_KEY:
                    for lead in batch:
                        if lead.get("website") and not lead.get("email"):
                            domain = lead["website"].replace("https://","").replace("http://","").split("/")[0]
                            email  = _enrich_email(domain)
                            if email:
                                lead["email"] = email
                leads.extend(batch[:need])
                logger.info(f"[scraper] Google Maps: {len(batch)} leads para '{industry}' en {city}")
                continue

        # 3. Yelp Fusion
        if settings.YELP_API_KEY:
            yelp_cat = INDUSTRY_TO_YELP.get(industry, industry)
            batch    = _yelp_search(yelp_cat, city, need)
            if batch:
                leads.extend(batch[:need])
                logger.info(f"[scraper] Yelp: {len(batch)} leads para '{industry}' en {city}")
                continue

        # 4. OpenStreetMap Overpass API (free, no key, real data)
        batch = _osm_search(industry, city, need)
        if batch:
            leads.extend(batch[:need])
            logger.info(f"[scraper] OSM: {len(batch)} leads para '{industry}' en {city}")
        else:
            logger.warning(f"[scraper] Sin resultados para '{industry}' en {city}")

    if not leads:
        return [], ("No se encontraron leads reales. "
                    "Configura GOOGLE_MAPS_API_KEY o APOLLO_API_KEY en .env para mejores resultados.")

    return leads[:count], ""


def sources_available() -> list[str]:
    """Return list of configured scraping sources."""
    available = ["openstreetmap"]  # always available, no key needed
    if settings.GOOGLE_MAPS_API_KEY:
        available.append("google_maps")
    if settings.APOLLO_API_KEY:
        available.append("apollo")
    if settings.YELP_API_KEY:
        available.append("yelp")
    if settings.HUNTER_API_KEY:
        available.append("hunter_email_enrichment")
    return available
