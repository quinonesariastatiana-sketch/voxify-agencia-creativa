"""One-time script to seed Aroma Beans brand into the DB."""
import sys
sys.path.insert(0, ".")
from database import Database
from config.brands_registry import reload_from_db

db = Database()

SYSTEM_PROMPT = (
    "You are the Digital Creative Director of Aroma Beans — a Colombian specialty coffee "
    "subscription for curious, educated American consumers.\n\n"
    "Mission: Connect U.S. consumers with Colombia's most exceptional coffee, telling each "
    "story with the honesty and respect it deserves — from the farmer's hand to the subscriber's cup.\n\n"
    "== BRAND IDENTITY ==\n"
    'Tagline: "Two coffees. Two stories. One Colombia."\n'
    'Tagline 2: "Where every cup has a name."\n'
    "Model: 2 coffees/month from 2 different Colombian regions. Radical curation over volume.\n"
    'Community: "Los Catadores" — private community, 4 levels.\n\n'
    "== VOICE ==\n"
    "Warmly knowledgeable, not pretentious. Poetic, not purple prose.\n"
    "Always: specific data (altitudes, varieties, harvest dates, farmer names), second person (you/your), explain the WHY.\n"
    'NEVER: "premium", "passionate farmer", "bean-to-cup", "rich and smooth", "world-class", '
    '"handcrafted with love", multiple exclamations.\n'
    "Use concrete details instead of adjectives: not 'amazing flavors' but 'red berry, caramelized sugar, hint of jasmine'.\n\n"
    "== AUDIENCE ==\n"
    "Primary: curious U.S. consumers 25-45 years old who want connection, knowledge and exceptional quality.\n"
    "Three personas: Marcus (curious professional, Austin TX, engineer), "
    "Sofia (Latina Connector, Miami FL, Colombian-American), "
    "Jordan (health-conscious, Portland OR, wellness creator).\n\n"
    "== CONTENT PILLARS ==\n"
    "1. The Origin (30%) — producer stories, regions, Colombia deep dive\n"
    "2. The Craft (25%) — brewing methods, recipes, tasting notes\n"
    "3. The Science (20%) — antioxidants, chemistry, altitude effects\n"
    "4. The Culture (15%) — Colombia beyond coffee: music, art, traditions\n"
    "5. The Community (10%) — Los Catadores experiences, UGC, Q&A with producers\n\n"
    "== CONTENT RATIO ==\n"
    "4 educational/cultural posts for every 1 commercial post.\n\n"
    "== RULES ==\n"
    "- Use specific Colombian geography: Nariño, Huila, Antioquia, Sierra Nevada, Tolima, Cauca\n"
    "- Every producer is a person with a name and surname, never 'a passionate farmer'\n"
    "- Emotions come from facts, not adjectives\n"
    "- The acidity, brightness and complexity of Colombian coffee are features, not bugs\n"
    "- Never overpromise relationships with producers if they are not verified\n"
    "- Language: English (U.S.), with respectful Spanish terms kept authentic\n"
    "- DO NOT publish anything — only generate and save for approval"
)

STRATEGY_90 = (
    "== AROMA BEANS — 90-DAY LAUNCH STRATEGY ==\n"
    "Goal: 1,000 subscribers · $42,000 MRR · Establish authority in Colombian specialty coffee\n\n"
    "== PHASE 1 — AUTHORITY (Days 1-30) ==\n"
    "Objective: Establish Aroma Beans as the definitive voice on Colombian coffee\n"
    "Focus: Educational content, producer stories, science of Colombian arabica\n"
    "KPIs: 2,000 IG followers | 4.5% engagement | 50 email sign-ups/week | 100 subscribers\n\n"
    "Content emphasis:\n"
    "- 50% The Origin (launch the first two regions with full storytelling)\n"
    "- 25% The Science (differentiate through data: antioxidants, altitude, varietals)\n"
    "- 15% The Craft (brewing guides — give value before asking for sale)\n"
    "- 10% Community (seed Los Catadores with founding members)\n\n"
    "== PHASE 2 — TRACTION (Days 31-60) ==\n"
    "Objective: Build community and drive trial subscriptions\n"
    "Focus: UGC, social proof, Los Catadores activation, first unboxing wave\n"
    "KPIs: 5,000 IG followers | 5% engagement | 400 subscribers | First revenue milestone\n\n"
    "Content emphasis:\n"
    "- 35% Community (subscriber unboxings, polls, Q&A)\n"
    "- 30% The Origin (Regions 3 & 4: Antioquia + Cauca)\n"
    "- 20% The Craft (subscriber recipe sharing)\n"
    "- 15% Commercial (waitlist urgency, testimonials)\n\n"
    "== PHASE 3 — CONVERSION (Days 61-90) ==\n"
    "Objective: Accelerate subscriptions, establish retention flywheel\n"
    "Focus: Social proof at scale, referral program, premium tier push\n"
    "KPIs: 10,000 IG followers | 5.5% engagement | 1,000 subscribers | $42k MRR\n\n"
    "Content emphasis:\n"
    "- 40% Social proof & community (scale what worked in Phase 2)\n"
    "- 25% The Science (health angle — strongest purchase driver for Jordan persona)\n"
    "- 20% The Origin (announce Regions 5 & 6)\n"
    "- 15% Commercial (referral program, Connoisseur tier push)\n\n"
    "== POSTING SCHEDULE ==\n"
    "Instagram: Tue-Fri 8am ET (feed) + Daily Stories\n"
    "Facebook: Mon-Fri 10am ET\n"
    "Content type rotation: Carousel (saves) -> Photo (reach) -> Reel (discovery) -> repeat"
)

config = {
    "id": "aroma_beans",
    "name": "Aroma Beans",
    "tagline": "Two coffees. Two stories. One Colombia.",
    "color": "#3D1E0F",
    "text_color": "#F5EDD6",
    "industry": "Specialty Coffee Subscription / E-commerce",
    "geography": "United States — Austin TX, Miami FL, Portland OR · Hispanic & curious coffee enthusiasts 25-45",
    "description": (
        "Subscription service delivering 2 Colombian specialty coffees per month from 2 different regions, "
        "with deep producer storytelling, education about the origin and science of coffee, and a private "
        "community called Los Catadores. Radical curation: only 2 coffees per month, not 20. "
        "Plans: Essential $42/mo · Explorer $79/mo · Connoisseur $145/mo."
    ),
    "mission": (
        "Conectar a consumidores estadounidenses con el cafe colombiano mas excepcional del mundo, "
        "contando cada historia con la honestidad y el respeto que merece — desde la mano del "
        "caficultor hasta la taza de quien lo disfruta."
    ),
    "logo_url": "",
    "values": [
        "Origen Autentico",
        "Profundidad sobre Cantidad",
        "Educacion como Experiencia",
        "Comunidad sobre Transaccion",
        "Colombia como Protagonista",
    ],
    "hashtags": [
        "#AromaBeans", "#LosCatadores", "#ColombiaCoffee", "#SpecialtyCoffee",
        "#CafeColombiano", "#SupportTheFarmer", "#CoffeeOrigin", "#SingleOrigin",
        "#ColombianCoffee", "#CoffeeSubscription",
    ],
    "phase_names": ["Authority", "Traction", "Conversion"],
    "audience": {
        "personas": [
            {
                "name": "Marcus — El Curioso Profesional",
                "age": "28-38",
                "occupation": "Software Engineer / Tech Professional",
                "income": "$95,000-$130,000/year",
                "pain": (
                    "Surrounded by generic coffee. Knows something better exists but doesn't know "
                    "how to find or evaluate it. Feels embarrassed not knowing about coffee when "
                    "colleagues mention it. Distrusts marketing claims without data."
                ),
                "goal": (
                    "Become the person who 'knows about coffee' in their circle. Wants real data, "
                    "not marketing. Deep educational content turns Marcus into an obsessive ambassador."
                ),
            },
            {
                "name": "Sofia — La Latina Connector",
                "age": "32-42",
                "occupation": "Professional / Entrepreneur / Community leader",
                "income": "$65,000-$95,000/year",
                "pain": (
                    "Colombian or Latina in the U.S. — hurts that no one represents Colombian coffee "
                    "as it truly deserves. Uses generic Colombian coffee (Juan Valdez) out of nostalgia "
                    "but knows it's not the best. Wants cultural pride, not just caffeine."
                ),
                "goal": (
                    "Find a coffee that makes her proud of her roots and that she can gift to American "
                    "family/friends as a cultural ambassador for Colombia."
                ),
            },
            {
                "name": "Jordan — El Health-Conscious",
                "age": "25-35",
                "occupation": "Wellness creator / Yoga instructor / Nutritionist",
                "income": "$45,000-$75,000/year",
                "pain": (
                    "Wants quality coffee but can't ignore health impact. Doesn't trust brands that "
                    "aren't transparent about origin and process. Worried about greenwashing and "
                    "mycotoxins. Needs science, not vibes."
                ),
                "goal": (
                    "A coffee with full traceability, documented health benefits (antioxidants, "
                    "low toxins), and alignment with conscious consumption values."
                ),
            },
        ],
        "language": "en",
        "channels": ["instagram", "tiktok", "facebook"],
        "geography": "United States — primarily Austin TX, Miami FL, Portland OR. Hispanic community + educated coffee enthusiasts aged 25-45.",
    },
    "voice": {
        "adjectives": [
            "warmly knowledgeable",
            "poetic but specific",
            "honest",
            "culturally proud",
            "never pretentious",
            "data-driven",
            "educational",
        ],
        "avoid": (
            "NEVER use: premium, passionate farmer, bean-to-cup, rich and smooth, world-class, "
            "handcrafted with love, amazing (without specifics), unique (without explanation), "
            "journey (as cliche), multiple exclamations, purple prose. "
            "No generalities — every sentence must contain a specific real detail. "
            "Do not say 'Colombian coffee is special' — say WHY with data and names."
        ),
        "examples_good": (
            "Nariño coffees grow above 2,000 meters — which is unusual for arabica. At those elevations, "
            "coffee cherries mature more slowly. That's not a bug; it's a feature. Slower maturation means "
            "more time for sugars to concentrate, more complexity in the cup, more of the chlorogenic acids "
            "that make Colombian arabica the highest in antioxidants of any origin studied.\n\n"
            "Don Hernan Munoz has been picking coffee on this hillside since 1987. He remembers the year "
            "a frost killed 30% of his trees. He replanted, and waited. The coffee you're holding right now "
            "came from those trees — the survivors."
        ),
        "examples_bad": (
            "This coffee was lovingly grown by a passionate farmer who pours his heart into every bean. "
            "Premium quality with rich and smooth flavors you'll love! "
            "World-class Colombian coffee, handcrafted with love and care for you."
        ),
        "formality": 0.4,
        "emoji_use": "moderado",
    },
    "positioning": {
        "usp": (
            "The ONLY coffee subscription specialized 100% in Colombia. Only 2 coffees per month — "
            "radical curation over volume. The complete story of the producer, the region, the altitude, "
            "the science of why Colombian arabica has the highest antioxidant content of any studied origin "
            "(136 bioactive compounds). Not a subscription. A Colombia education."
        ),
        "competitors": [
            {
                "name": "Atlas Coffee Club",
                "weakness": (
                    "Generic world tour — no depth in any single origin. Colombia is just one of 50+ "
                    "countries, treated equally. No educational content beyond a postcard."
                ),
                "url": "atlascoffeeclub.com",
            },
            {
                "name": "Trade Coffee",
                "weakness": (
                    "Algorithm-based, no storytelling, no community. Treats coffee like a commodity. "
                    "Zero focus on producer or cultural context."
                ),
                "url": "drinktrade.com",
            },
            {
                "name": "Blue Bottle Coffee",
                "weakness": (
                    "Premium positioning without depth. Minimal producer transparency. "
                    "No community, no education. Brand aesthetic > substance."
                ),
                "url": "bluebottlecoffee.com",
            },
        ],
        "differentiators": [
            "Solo Colombia — 100% focus, unmatched depth vs. any generalist subscription",
            "Solo 2 cafes/mes — radical curation over volume",
            "Historia completa del productor (nombre, finca, historia real)",
            "Comunidad Los Catadores — 4 niveles de engagement exclusivo",
            "5 pilares de contenido educativo estructurado",
            "Ciencia documentada: antioxidantes (136 compuestos bioactivos), altitud, variedades",
            "Regiones en rotacion — 12 meses = 24 cafes unicos de Colombia",
        ],
    },
    "credentials": {
        "meta_access_token": "",
        "instagram_business_account_id": "",
        "facebook_page_id": "",
        "facebook_page_access_token": "",
        "linkedin_access_token": "",
        "linkedin_organization_id": "",
    },
    "posting_schedule": {
        "instagram": {"days": ["tue", "wed", "thu", "fri"], "hour": 8, "minute": 0},
        "facebook": {"days": ["mon", "tue", "wed", "thu", "fri"], "hour": 10, "minute": 0},
        "linkedin": {"days": [], "hour": 8, "minute": 0},
    },
    "content_lines": [
        {"name": "The Origin", "percentage": 0.30, "description": "Producer stories, regions, Colombia deep dive"},
        {"name": "The Craft", "percentage": 0.25, "description": "Brewing methods, recipes, tasting guides"},
        {"name": "The Science", "percentage": 0.20, "description": "Antioxidants, chemistry, altitude effects on flavor"},
        {"name": "The Culture", "percentage": 0.15, "description": "Colombia beyond coffee: music, art, traditions"},
        {"name": "The Community", "percentage": 0.10, "description": "Los Catadores: UGC, Q&A with producers, member stories"},
    ],
    "goals": {
        "30": {
            "instagram_followers": 2000,
            "instagram_engagement_rate": 4.5,
            "facebook_reach": 3000,
            "facebook_interactions": 400,
            "linkedin_followers": 0,
            "leads": 50,
            "clients": 100,
            "revenue_usd": 4200,
        },
        "60": {
            "instagram_followers": 5000,
            "instagram_engagement_rate": 5.0,
            "facebook_reach": 8000,
            "facebook_interactions": 1000,
            "linkedin_followers": 0,
            "leads": 150,
            "clients": 400,
            "revenue_usd": 16800,
        },
        "90": {
            "instagram_followers": 10000,
            "instagram_engagement_rate": 5.5,
            "facebook_reach": 20000,
            "facebook_interactions": 2500,
            "linkedin_followers": 0,
            "leads": 300,
            "clients": 1000,
            "revenue_usd": 42000,
        },
    },
    "system_prompt": SYSTEM_PROMPT,
    "strategy_90days": STRATEGY_90,
    "monthly_targets": {
        1: {"clients": 100, "instagram_followers": 2000, "instagram_engagement_rate": 4.5, "revenue_usd": 4200},
        2: {"clients": 400, "instagram_followers": 5000, "instagram_engagement_rate": 5.0, "revenue_usd": 16800},
        3: {"clients": 1000, "instagram_followers": 10000, "instagram_engagement_rate": 5.5, "revenue_usd": 42000},
    },
}

db.save_brand(config)
reload_from_db(db)

from config.brands_registry import BRANDS
print("Marcas activas:", list(BRANDS.keys()))
b = BRANDS["aroma_beans"]
print("Nombre:", b["name"])
print("Tagline:", b["tagline"])
print("Color:", b["color"])
print("Personas:", len(b["audience"]["personas"]))
print("Competidores:", len(b["positioning"]["competitors"]))
print("Meta 90d clientes:", b["goals"]["90"]["clients"])
print("Meta 90d revenue:", b["goals"]["90"]["revenue_usd"])
print("")
print("Aroma Beans cargada correctamente en la DB.")
