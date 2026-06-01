"""Topic labeling using embedding similarity and keyword matching.

Optimized for edge devices - no LLM required. Uses the existing embedding model
for semantic similarity when keyword matching is insufficient.
"""

import re
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    pass


def _simple_stem(word: str) -> str:
    """Simple suffix-stripping stemmer for common English word endings.

    This is a lightweight alternative to Porter Stemmer that handles
    the most common suffixes without external dependencies.

    Args:
        word: Word to stem (lowercase)

    Returns:
        Stemmed word
    """
    if len(word) <= 3:
        return word

    # Common suffix patterns (order matters - check longer suffixes first)
    suffixes = [
        # -ing endings
        ('pping', 'p'),    # shopping -> shop
        ('tting', 't'),    # getting -> get
        ('nning', 'n'),    # running -> run
        ('mming', 'm'),    # swimming -> swim
        ('dding', 'd'),    # adding -> add
        ('gging', 'g'),    # jogging -> jog
        ('bing', 'b'),     # rubbing -> rub
        ('ying', 'y'),     # studying -> study
        ('eing', 'e'),     # being -> be
        ('uing', 'ue'),    # continuing -> continue
        ('oing', 'o'),     # doing -> do
        ('ting', 't'),     # writing -> writ (close enough)
        ('ning', 'n'),     # planning -> plan
        ('ming', 'm'),     # coming -> com
        ('king', 'k'),     # working -> work
        ('ding', 'd'),     # building -> build
        ('ring', 'r'),     # during -> dur
        ('ling', 'l'),     # traveling -> travel
        ('sing', 's'),     # processing -> process
        ('zing', 'z'),     # analyzing -> analyz
        ('cing', 'c'),     # dancing -> danc
        ('ping', 'p'),     # developing -> develop
        ('ing', ''),       # general -ing removal

        # -ed endings
        ('pped', 'p'),     # shopped -> shop
        ('tted', 't'),     # submitted -> submit
        ('nned', 'n'),     # planned -> plan
        ('mmed', 'm'),     # programmed -> program
        ('dded', 'd'),     # added -> add
        ('gged', 'g'),     # jogged -> jog
        ('bbed', 'b'),     # rubbed -> rub
        ('ied', 'y'),      # studied -> study
        ('eed', 'ee'),     # agreed -> agree
        ('ued', 'ue'),     # continued -> continue
        ('owed', 'ow'),    # followed -> follow
        ('awed', 'aw'),    # thawed -> thaw
        ('wed', 'w'),      # viewed -> view
        ('ted', 't'),      # created -> creat
        ('ned', 'n'),      # learned -> learn
        ('med', 'm'),      # named -> nam
        ('ked', 'k'),      # worked -> work
        ('ded', 'd'),      # added -> add
        ('red', 'r'),      # stored -> stor
        ('led', 'l'),      # traveled -> travel
        ('sed', 's'),      # processed -> process
        ('zed', 'z'),      # analyzed -> analyz
        ('ced', 'c'),      # danced -> danc
        ('ped', 'p'),      # developed -> develop
        ('ved', 've'),     # saved -> save
        ('ed', ''),        # general -ed removal

        # -s and -es endings
        ('ies', 'y'),      # studies -> study
        ('ches', 'ch'),    # matches -> match
        ('shes', 'sh'),    # dishes -> dish
        ('xes', 'x'),      # boxes -> box
        ('zes', 'z'),      # quizzes -> quiz
        ('ses', 's'),      # classes -> class
        ('oes', 'o'),      # does -> do
        ('es', 'e'),       # games -> game
        ('ss', 'ss'),      # class -> class (don't strip)
        ('us', 'us'),      # status -> status (don't strip)
        ('is', 'is'),      # analysis -> analysis (don't strip)
        ('s', ''),         # general -s removal

        # -er/-or endings
        ('ier', 'y'),      # happier -> happy
        ('pper', 'p'),     # shopper -> shop
        ('tter', 't'),     # fitter -> fit
        ('nner', 'n'),     # runner -> run
        ('mmer', 'm'),     # swimmer -> swim
        ('dder', 'd'),     # adder -> add
        ('gger', 'g'),     # jogger -> jog
        ('bber', 'b'),     # robber -> rob
        ('ler', 'l'),      # traveler -> travel
        ('ner', 'n'),      # learner -> learn
        ('ter', 't'),      # writer -> writ
        ('ser', 's'),      # processor -> process
        ('zer', 'z'),      # analyzer -> analyz
        ('cer', 'c'),      # dancer -> danc
        ('per', 'p'),      # developer -> develop
        ('ker', 'k'),      # worker -> work
        ('der', 'd'),      # builder -> build
        ('er', ''),        # general -er removal
        ('or', ''),        # general -or removal (actor -> act)

        # -tion/-sion endings
        ('ation', ''),     # education -> educ
        ('ition', ''),     # nutrition -> nutrit
        ('ution', ''),     # solution -> solut
        ('tion', ''),      # general -tion
        ('sion', ''),      # general -sion

        # -ment endings
        ('ment', ''),      # investment -> invest

        # -ness endings
        ('iness', 'y'),    # happiness -> happy
        ('ness', ''),      # fitness -> fit

        # -ly endings
        ('ily', 'y'),      # happily -> happy
        ('ally', 'al'),    # finally -> final
        ('ly', ''),        # quickly -> quick

        # -ful/-less endings
        ('ful', ''),       # helpful -> help
        ('less', ''),      # careless -> care

        # -able/-ible endings
        ('able', ''),      # programmable -> programm
        ('ible', ''),      # flexible -> flex

        # -ity endings
        ('ity', ''),       # security -> secur

        # -ive endings
        ('ative', ''),     # creative -> creat
        ('itive', ''),     # competitive -> compet
        ('ive', ''),       # active -> act

        # -ous endings
        ('ious', ''),      # serious -> ser
        ('eous', ''),      # gorgeous -> gorg
        ('ous', ''),       # famous -> fam

        # -al endings
        ('ical', 'ic'),    # medical -> medic
        ('ual', ''),       # visual -> vis
        ('al', ''),        # personal -> person
    ]

    for suffix, replacement in suffixes:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            return word[:-len(suffix)] + replacement

    return word


# Build stemmed keyword map at module load time for efficiency
def _build_stemmed_keyword_map(keyword_map: Dict[str, str]) -> Dict[str, str]:
    """Build a map from stemmed keywords to topics.

    This allows matching word variations like:
    - "programming", "programmer", "programs" -> "program" -> programming topic
    - "exercising", "exercised", "exercises" -> "exercis" -> health topic
    """
    stemmed_map = {}
    for keyword, topic in keyword_map.items():
        # Add original keyword
        stemmed_map[keyword] = topic
        # Add stemmed version
        stemmed = _simple_stem(keyword)
        if stemmed != keyword and stemmed not in stemmed_map:
            stemmed_map[stemmed] = topic
    return stemmed_map


# Default predefined topics for classification
# Aligned with frontend DataCategory for consistent filtering
DEFAULT_TOPICS = [
    "health",
    "finance",
    "work",
    "personal",
    "social",
    "legal",
    "travel",
    "education",
    "programming",
    "sports",
    "technology",
    "shopping",
    "family",
    "news",
    "general",
]

# Keyword to topic mapping for classification
# Comprehensive keyword list with weights (higher weight = more topic-specific)
# Format: keyword -> (topic, weight) where weight is 1.0 (general) to 3.0 (highly specific)
WEIGHTED_KEYWORD_MAP = {
    # Sports (extensive coverage)
    "basketball": ("sports", 3.0), "football": ("sports", 3.0), "soccer": ("sports", 3.0),
    "baseball": ("sports", 3.0), "tennis": ("sports", 3.0), "golf": ("sports", 3.0),
    "hockey": ("sports", 3.0), "volleyball": ("sports", 3.0), "cricket": ("sports", 3.0),
    "rugby": ("sports", 3.0), "swimming": ("sports", 2.0), "marathon": ("sports", 3.0),
    "olympics": ("sports", 3.0), "nba": ("sports", 3.0), "nfl": ("sports", 3.0),
    "mlb": ("sports", 3.0), "fifa": ("sports", 3.0), "ufc": ("sports", 3.0),
    "mma": ("sports", 3.0), "boxing": ("sports", 3.0), "wrestling": ("sports", 2.5),
    "athlete": ("sports", 2.5), "championship": ("sports", 2.5), "tournament": ("sports", 2.0),
    "league": ("sports", 2.0), "playoffs": ("sports", 2.5), "stadium": ("sports", 2.0),
    "coach": ("sports", 2.0), "referee": ("sports", 2.5), "quarterback": ("sports", 3.0),
    "touchdown": ("sports", 3.0), "homerun": ("sports", 3.0), "slam": ("sports", 2.0),
    "goal": ("sports", 1.5), "score": ("sports", 1.5), "winning": ("sports", 1.5),
    "team": ("sports", 1.5), "player": ("sports", 2.0), "game": ("sports", 1.0),
    "match": ("sports", 1.5), "overtime": ("sports", 2.0), "halftime": ("sports", 3.0),

    # Technology (comprehensive)
    "smartphone": ("technology", 3.0), "iphone": ("technology", 3.0), "android": ("technology", 3.0),
    "computer": ("technology", 2.5), "laptop": ("technology", 2.5), "tablet": ("technology", 2.5),
    "software": ("technology", 2.5), "hardware": ("technology", 2.5), "gadget": ("technology", 2.5),
    "app": ("technology", 2.0), "application": ("technology", 1.5), "device": ("technology", 2.0),
    "digital": ("technology", 2.0), "internet": ("technology", 2.5), "wifi": ("technology", 2.5),
    "bluetooth": ("technology", 2.5), "processor": ("technology", 2.5), "cpu": ("technology", 3.0),
    "gpu": ("technology", 3.0), "ram": ("technology", 2.5), "storage": ("technology", 1.5),
    "camera": ("technology", 2.0), "screen": ("technology", 1.5), "display": ("technology", 1.5),
    "battery": ("technology", 2.0), "charger": ("technology", 2.0), "wireless": ("technology", 2.0),
    "cloud": ("technology", 2.0), "streaming": ("technology", 2.0), "download": ("technology", 1.5),
    "upload": ("technology", 1.5), "update": ("technology", 1.0), "upgrade": ("technology", 1.5),
    "tech": ("technology", 2.0), "gadgets": ("technology", 2.5), "electronics": ("technology", 2.5),
    "robotics": ("technology", 3.0), "ai": ("technology", 2.5), "automation": ("technology", 2.5),

    # Shopping (extensive)
    "bought": ("shopping", 2.5), "purchased": ("shopping", 3.0), "store": ("shopping", 2.0),
    "mall": ("shopping", 3.0), "shopping": ("shopping", 3.0), "shop": ("shopping", 2.5),
    "sale": ("shopping", 2.5), "discount": ("shopping", 2.5), "price": ("shopping", 2.0),
    "cart": ("shopping", 2.5), "checkout": ("shopping", 3.0), "order": ("shopping", 2.0),
    "delivery": ("shopping", 2.0), "shipping": ("shopping", 2.5), "retail": ("shopping", 2.5),
    "amazon": ("shopping", 3.0), "ebay": ("shopping", 3.0), "walmart": ("shopping", 3.0),
    "target": ("shopping", 2.5), "costco": ("shopping", 3.0), "coupon": ("shopping", 3.0),
    "deals": ("shopping", 2.5), "promo": ("shopping", 2.5), "refund": ("shopping", 2.5),
    "return": ("shopping", 1.5), "exchange": ("shopping", 1.5), "receipt": ("shopping", 2.5),
    "dress": ("shopping", 2.0), "shoes": ("shopping", 2.0), "clothes": ("shopping", 2.0),
    "clothing": ("shopping", 2.5), "fashion": ("shopping", 2.5), "outfit": ("shopping", 2.5),
    "purchase": ("shopping", 2.5), "buy": ("shopping", 2.0), "seller": ("shopping", 2.0),
    "vendor": ("shopping", 2.0), "product": ("shopping", 1.5), "item": ("shopping", 1.5),

    # Health/Medical (comprehensive)
    "doctor": ("health", 3.0), "medicine": ("health", 3.0), "prescription": ("health", 3.0),
    "hospital": ("health", 3.0), "clinic": ("health", 3.0), "treatment": ("health", 2.5),
    "diagnosis": ("health", 3.0), "symptom": ("health", 3.0), "patient": ("health", 2.5),
    "nurse": ("health", 3.0), "surgery": ("health", 3.0), "antibiotic": ("health", 3.0),
    "antibiotics": ("health", 3.0), "prescribed": ("health", 2.5), "infection": ("health", 2.5),
    "therapy": ("health", 2.5), "medical": ("health", 2.5), "dental": ("health", 3.0),
    "dentist": ("health", 3.0), "physician": ("health", 3.0), "specialist": ("health", 2.0),
    "vaccine": ("health", 3.0), "vaccination": ("health", 3.0), "immunization": ("health", 3.0),
    "pharmacy": ("health", 3.0), "medication": ("health", 3.0), "dosage": ("health", 3.0),
    "health": ("health", 2.5), "healthy": ("health", 2.0), "wellness": ("health", 2.5),
    "fitness": ("health", 2.5), "exercise": ("health", 2.0), "workout": ("health", 2.5),
    "diet": ("health", 2.5), "nutrition": ("health", 2.5), "vitamin": ("health", 2.5),
    "supplement": ("health", 2.5), "calories": ("health", 2.5), "protein": ("health", 2.0),
    "gym": ("health", 2.5), "yoga": ("health", 2.5), "meditation": ("health", 2.0),
    "mental": ("health", 2.0), "anxiety": ("health", 3.0), "depression": ("health", 3.0),
    "stress": ("health", 2.0), "sleep": ("health", 2.0), "insomnia": ("health", 3.0),
    # Eye care / vision (medical context - higher weight than education "exam")
    "ophthalmologist": ("health", 3.0), "optometrist": ("health", 3.0), "optometry": ("health", 3.0),
    "retina": ("health", 3.0), "cornea": ("health", 3.0), "macula": ("health", 3.0),
    "glaucoma": ("health", 3.0), "cataract": ("health", 3.0), "astigmatism": ("health", 3.0),
    "myopia": ("health", 3.0), "hyperopia": ("health", 3.0), "presbyopia": ("health", 3.0),
    "intraocular": ("health", 3.0), "dilated": ("health", 2.5), "fundus": ("health", 3.0),
    "acuity": ("health", 3.0), "refraction": ("health", 3.0), "tonometry": ("health", 3.0),
    "lenses": ("health", 2.0), "eyeglasses": ("health", 2.5), "contacts": ("health", 2.0),

    # Family (comprehensive)
    "parents": ("family", 3.0), "children": ("family", 2.5), "kids": ("family", 2.5),
    "siblings": ("family", 3.0), "relatives": ("family", 3.0), "grandparents": ("family", 3.0),
    "grandmother": ("family", 3.0), "grandfather": ("family", 3.0), "grandson": ("family", 3.0),
    "granddaughter": ("family", 3.0), "cousins": ("family", 3.0), "reunion": ("family", 2.0),
    "mother": ("family", 3.0), "father": ("family", 3.0), "mom": ("family", 3.0),
    "dad": ("family", 3.0), "brother": ("family", 3.0), "sister": ("family", 3.0),
    "son": ("family", 3.0), "daughter": ("family", 3.0), "uncle": ("family", 3.0),
    "aunt": ("family", 3.0), "nephew": ("family", 3.0), "niece": ("family", 3.0),
    "spouse": ("family", 3.0), "husband": ("family", 3.0), "wife": ("family", 3.0),
    "baby": ("family", 2.5), "toddler": ("family", 2.5), "infant": ("family", 2.5),
    "parenting": ("family", 3.0), "pregnancy": ("family", 3.0), "maternity": ("family", 3.0),
    "family": ("family", 2.5), "household": ("family", 2.0), "home": ("family", 1.5),

    # Programming (extensive - technical terms)
    "code": ("programming", 2.5), "coding": ("programming", 3.0), "programming": ("programming", 3.0),
    "python": ("programming", 3.0), "javascript": ("programming", 3.0), "typescript": ("programming", 3.0),
    "java": ("programming", 3.0), "csharp": ("programming", 3.0), "cpp": ("programming", 3.0),
    "golang": ("programming", 3.0), "rust": ("programming", 3.0), "ruby": ("programming", 3.0),
    "swift": ("programming", 3.0), "kotlin": ("programming", 3.0), "php": ("programming", 3.0),
    "function": ("programming", 2.5), "class": ("programming", 2.0), "method": ("programming", 2.0),
    "api": ("programming", 2.5), "endpoint": ("programming", 3.0), "rest": ("programming", 2.5),
    "graphql": ("programming", 3.0), "debug": ("programming", 3.0), "debugger": ("programming", 3.0),
    "compile": ("programming", 3.0), "compiler": ("programming", 3.0), "runtime": ("programming", 2.5),
    "algorithm": ("programming", 3.0), "def": ("programming", 3.0), "return": ("programming", 2.0),
    "import": ("programming", 2.0), "export": ("programming", 2.0), "module": ("programming", 2.0),
    "variable": ("programming", 2.5), "loop": ("programming", 2.5), "array": ("programming", 2.5),
    "object": ("programming", 2.0), "string": ("programming", 2.0), "integer": ("programming", 2.5),
    "boolean": ("programming", 3.0), "null": ("programming", 2.5), "undefined": ("programming", 3.0),
    "developer": ("programming", 3.0), "programmer": ("programming", 3.0), "engineer": ("programming", 2.0),
    "quicksort": ("programming", 3.0), "recursion": ("programming", 3.0), "recursive": ("programming", 3.0),
    "github": ("programming", 3.0), "git": ("programming", 3.0), "commit": ("programming", 3.0),
    "repository": ("programming", 2.5), "branch": ("programming", 2.0), "merge": ("programming", 2.5),
    "docker": ("programming", 3.0), "kubernetes": ("programming", 3.0), "container": ("programming", 2.5),
    "react": ("programming", 3.0), "angular": ("programming", 3.0), "vue": ("programming", 3.0),
    "nodejs": ("programming", 3.0), "django": ("programming", 3.0), "flask": ("programming", 3.0),
    "fastapi": ("programming", 3.0), "express": ("programming", 3.0), "spring": ("programming", 3.0),
    # SQL/Database
    "select": ("programming", 2.0), "from": ("programming", 1.0), "where": ("programming", 2.0),
    "join": ("programming", 2.0), "sql": ("programming", 3.0), "database": ("programming", 2.5),
    "query": ("programming", 2.0), "table": ("programming", 1.5), "insert": ("programming", 2.5),
    "update": ("programming", 1.5), "delete": ("programming", 1.5), "postgresql": ("programming", 3.0),
    "mysql": ("programming", 3.0), "mongodb": ("programming", 3.0), "redis": ("programming", 3.0),
    "nosql": ("programming", 3.0), "schema": ("programming", 2.5), "orm": ("programming", 3.0),

    # Finance (comprehensive)
    "money": ("finance", 2.5), "budget": ("finance", 3.0), "investment": ("finance", 3.0),
    "bank": ("finance", 2.5), "banking": ("finance", 3.0), "savings": ("finance", 2.5),
    "loan": ("finance", 3.0), "credit": ("finance", 2.5), "debit": ("finance", 2.5),
    "tax": ("finance", 3.0), "taxes": ("finance", 3.0), "irs": ("finance", 3.0),
    "income": ("finance", 2.5), "salary": ("finance", 2.5), "wage": ("finance", 2.5),
    "expense": ("finance", 2.5), "expenses": ("finance", 2.5), "spending": ("finance", 2.0),
    "profit": ("finance", 2.5), "loss": ("finance", 2.0), "revenue": ("finance", 2.5),
    "stock": ("finance", 3.0), "stocks": ("finance", 3.0), "shares": ("finance", 3.0),
    "bonds": ("finance", 3.0), "portfolio": ("finance", 3.0), "dividend": ("finance", 3.0),
    "trading": ("finance", 3.0), "forex": ("finance", 3.0), "crypto": ("finance", 3.0),
    "bitcoin": ("finance", 3.0), "ethereum": ("finance", 3.0), "cryptocurrency": ("finance", 3.0),
    "mortgage": ("finance", 3.0), "interest": ("finance", 2.0), "apr": ("finance", 3.0),
    "retirement": ("finance", 2.5), "401k": ("finance", 3.0), "ira": ("finance", 3.0),
    "pension": ("finance", 3.0), "insurance": ("finance", 2.5), "premium": ("finance", 2.0),
    "debt": ("finance", 2.5), "payment": ("finance", 2.0), "billing": ("finance", 2.0),
    "invoice": ("finance", 2.5), "accounting": ("finance", 3.0), "accountant": ("finance", 3.0),
    "financial": ("finance", 2.5), "economy": ("finance", 2.5), "economic": ("finance", 2.5),

    # Education (extensive)
    "school": ("education", 3.0), "university": ("education", 3.0), "college": ("education", 3.0),
    "learning": ("education", 2.5), "student": ("education", 3.0), "students": ("education", 3.0),
    "teacher": ("education", 3.0), "professor": ("education", 3.0), "instructor": ("education", 2.5),
    "course": ("education", 2.5), "courses": ("education", 2.5), "curriculum": ("education", 3.0),
    "study": ("education", 2.5), "studying": ("education", 2.5), "exam": ("education", 3.0),
    "examination": ("education", 3.0), "test": ("education", 2.0), "quiz": ("education", 2.5),
    "homework": ("education", 3.0), "assignment": ("education", 2.5), "essay": ("education", 2.5),
    "thesis": ("education", 3.0), "dissertation": ("education", 3.0), "research": ("education", 2.0),
    "lecture": ("education", 3.0), "seminar": ("education", 2.5), "classroom": ("education", 3.0),
    "degree": ("education", 3.0), "diploma": ("education", 3.0), "certificate": ("education", 2.5),
    "graduation": ("education", 3.0), "graduate": ("education", 2.5), "undergraduate": ("education", 3.0),
    "masters": ("education", 3.0), "phd": ("education", 3.0), "doctorate": ("education", 3.0),
    "academic": ("education", 2.5), "campus": ("education", 3.0), "tuition": ("education", 3.0),
    "scholarship": ("education", 3.0), "textbook": ("education", 3.0), "tutorial": ("education", 2.5),
    "education": ("education", 2.5), "educational": ("education", 2.5), "lesson": ("education", 2.5),

    # Travel (comprehensive)
    "vacation": ("travel", 3.0), "trip": ("travel", 2.5), "flight": ("travel", 3.0),
    "hotel": ("travel", 3.0), "motel": ("travel", 3.0), "resort": ("travel", 3.0),
    "airbnb": ("travel", 3.0), "hostel": ("travel", 3.0), "accommodation": ("travel", 2.5),
    "destination": ("travel", 3.0), "airport": ("travel", 3.0), "tourism": ("travel", 3.0),
    "tourist": ("travel", 3.0), "sightseeing": ("travel", 3.0), "landmark": ("travel", 2.5),
    "passport": ("travel", 3.0), "visa": ("travel", 3.0), "luggage": ("travel", 3.0),
    "baggage": ("travel", 3.0), "boarding": ("travel", 2.5), "departure": ("travel", 2.5),
    "arrival": ("travel", 2.5), "itinerary": ("travel", 3.0), "booking": ("travel", 2.5),
    "reservation": ("travel", 2.5), "cruise": ("travel", 3.0), "tour": ("travel", 2.5),
    "travel": ("travel", 3.0), "traveling": ("travel", 3.0), "journey": ("travel", 2.5),
    "adventure": ("travel", 2.0), "explore": ("travel", 2.0), "backpacking": ("travel", 3.0),
    "abroad": ("travel", 2.5), "international": ("travel", 2.0), "domestic": ("travel", 2.0),
    "airline": ("travel", 3.0), "carrier": ("travel", 2.0), "layover": ("travel", 3.0),

    # Legal (comprehensive)
    "lawyer": ("legal", 3.0), "attorney": ("legal", 3.0), "court": ("legal", 3.0),
    "law": ("legal", 2.5), "legal": ("legal", 2.5), "lawsuit": ("legal", 3.0),
    "litigation": ("legal", 3.0), "contract": ("legal", 2.5), "agreement": ("legal", 2.0),
    "judge": ("legal", 3.0), "jury": ("legal", 3.0), "verdict": ("legal", 3.0),
    "trial": ("legal", 3.0), "hearing": ("legal", 2.5), "testimony": ("legal", 3.0),
    "witness": ("legal", 2.5), "evidence": ("legal", 2.5), "plaintiff": ("legal", 3.0),
    "defendant": ("legal", 3.0), "prosecution": ("legal", 3.0), "defense": ("legal", 2.0),
    "settlement": ("legal", 2.5), "damages": ("legal", 2.5), "liability": ("legal", 2.5),
    "statute": ("legal", 3.0), "regulation": ("legal", 2.5), "compliance": ("legal", 2.5),
    "patent": ("legal", 3.0), "copyright": ("legal", 3.0), "trademark": ("legal", 3.0),
    "intellectual": ("legal", 2.0), "property": ("legal", 1.5), "rights": ("legal", 2.0),
    "constitution": ("legal", 3.0), "amendment": ("legal", 3.0), "legislation": ("legal", 3.0),

    # Work (comprehensive)
    "job": ("work", 3.0), "career": ("work", 3.0), "office": ("work", 2.5),
    "workplace": ("work", 3.0), "meeting": ("work", 2.0), "project": ("work", 2.0),
    "deadline": ("work", 2.5), "colleague": ("work", 3.0), "coworker": ("work", 3.0),
    "boss": ("work", 3.0), "manager": ("work", 2.5), "supervisor": ("work", 3.0),
    "employee": ("work", 3.0), "employer": ("work", 3.0), "staff": ("work", 2.5),
    "work": ("work", 2.0), "working": ("work", 1.5), "employment": ("work", 3.0),
    "hire": ("work", 2.5), "hiring": ("work", 2.5), "recruit": ("work", 2.5),
    "resume": ("work", 3.0), "interview": ("work", 2.5), "promotion": ("work", 3.0),
    "corporate": ("work", 2.5), "company": ("work", 2.0), "business": ("work", 2.0),
    "professional": ("work", 2.0), "occupation": ("work", 3.0), "position": ("work", 2.0),
    "department": ("work", 2.5), "team": ("work", 1.5), "hr": ("work", 3.0),
    "human": ("work", 1.0), "resources": ("work", 1.5), "performance": ("work", 2.0),
    "review": ("work", 1.5), "appraisal": ("work", 3.0), "productivity": ("work", 2.5),

    # Personal (comprehensive)
    "diary": ("personal", 3.0), "journal": ("personal", 3.0), "thoughts": ("personal", 2.5),
    "feelings": ("personal", 2.5), "myself": ("personal", 2.5), "private": ("personal", 2.5),
    "personal": ("personal", 2.5), "reflection": ("personal", 2.5), "memoir": ("personal", 3.0),
    "life": ("personal", 1.5), "experience": ("personal", 1.5), "memories": ("personal", 2.5),
    "emotions": ("personal", 2.5), "self": ("personal", 2.0), "growth": ("personal", 2.0),
    "mindfulness": ("personal", 2.5), "gratitude": ("personal", 2.5), "goals": ("personal", 2.0),
    "habits": ("personal", 2.0), "routine": ("personal", 2.0), "lifestyle": ("personal", 2.0),
    "hobbies": ("personal", 2.5), "hobby": ("personal", 2.5), "interests": ("personal", 2.0),
    "dreams": ("personal", 2.0), "aspirations": ("personal", 2.5), "bucket": ("personal", 2.0),

    # News (current events, politics, world affairs)
    "headline": ("news", 3.0), "headlines": ("news", 3.0), "breaking": ("news", 3.0),
    "reporter": ("news", 3.0), "journalist": ("news", 3.0), "journalism": ("news", 3.0),
    "press": ("news", 2.5), "media": ("news", 2.5), "newspaper": ("news", 3.0),
    "article": ("news", 2.0), "editorial": ("news", 3.0), "opinion": ("news", 2.0),
    "politics": ("news", 3.0), "political": ("news", 3.0), "politician": ("news", 3.0),
    "election": ("news", 3.0), "elections": ("news", 3.0), "campaign": ("news", 2.5),
    "president": ("news", 3.0), "congress": ("news", 3.0), "senate": ("news", 3.0),
    "parliament": ("news", 3.0), "government": ("news", 2.5), "governor": ("news", 3.0),
    "mayor": ("news", 3.0), "minister": ("news", 2.5), "policy": ("news", 2.5),
    "democrat": ("news", 3.0), "republican": ("news", 3.0), "liberal": ("news", 2.5),
    "conservative": ("news", 2.5), "bipartisan": ("news", 3.0), "vote": ("news", 2.5),
    "voting": ("news", 3.0), "ballot": ("news", 3.0), "referendum": ("news", 3.0),
    "protest": ("news", 3.0), "rally": ("news", 2.5), "demonstration": ("news", 2.5),
    "crisis": ("news", 2.5), "conflict": ("news", 2.5), "war": ("news", 3.0),
    "military": ("news", 3.0), "troops": ("news", 3.0), "sanctions": ("news", 3.0),
    "diplomacy": ("news", 3.0), "ambassador": ("news", 3.0), "summit": ("news", 3.0),
    "climate": ("news", 2.5), "emissions": ("news", 3.0), "environmental": ("news", 2.5),
    "disaster": ("news", 3.0), "earthquake": ("news", 3.0), "hurricane": ("news", 3.0),
    "flood": ("news", 3.0), "wildfire": ("news", 3.0), "pandemic": ("news", 3.0),
    "outbreak": ("news", 3.0), "ceasefire": ("news", 3.0), "treaty": ("news", 3.0),
    "geopolitical": ("news", 3.0), "scandal": ("news", 3.0), "corruption": ("news", 3.0),
    "impeachment": ("news", 3.0), "indictment": ("news", 3.0), "investigation": ("news", 2.5),
    "cnn": ("news", 3.0), "bbc": ("news", 3.0), "reuters": ("news", 3.0),
    "associated": ("news", 1.5), "nytimes": ("news", 3.0), "washington": ("news", 2.0),

    # Social (comprehensive)
    "friends": ("social", 3.0), "friend": ("social", 3.0), "friendship": ("social", 3.0),
    "party": ("social", 2.5), "parties": ("social", 2.5), "gathering": ("social", 2.5),
    "socializing": ("social", 3.0), "hangout": ("social", 3.0), "meetup": ("social", 3.0),
    "community": ("social", 2.5), "networking": ("social", 2.5), "social": ("social", 2.5),
    "event": ("social", 2.0), "events": ("social", 2.0), "celebration": ("social", 2.5),
    "birthday": ("social", 2.5), "wedding": ("social", 3.0), "anniversary": ("social", 2.5),
    "festival": ("social", 2.5), "holiday": ("social", 2.0), "relationship": ("social", 2.5),
    "dating": ("social", 3.0), "date": ("social", 2.0), "romance": ("social", 3.0),
    "love": ("social", 2.0), "boyfriend": ("social", 3.0), "girlfriend": ("social", 3.0),
    "partner": ("social", 2.5), "group": ("social", 1.5), "club": ("social", 2.0),
    "organization": ("social", 1.5), "volunteer": ("social", 2.5), "charity": ("social", 2.5),
}

# Build simple keyword map for backward compatibility
KEYWORD_TO_TOPIC_MAP = {k: v[0] for k, v in WEIGHTED_KEYWORD_MAP.items()}

# Build stemmed keyword map for fuzzy matching
# This allows matching word variations like "programmer" -> "program" -> programming topic
STEMMED_KEYWORD_MAP = _build_stemmed_keyword_map(KEYWORD_TO_TOPIC_MAP)

# Topic descriptions for embedding-based similarity matching
# These are used to create topic embeddings for comparison with document content
TOPIC_DESCRIPTIONS = {
    "health": "health medical doctor medicine hospital treatment wellness fitness exercise nutrition diet therapy symptom patient clinic healthcare prescription nurse",
    "finance": "finance money budget investment banking savings loan credit tax payment financial income expense profit stock trading wealth",
    "work": "work job office meeting project deadline colleague boss career professional business workplace employment corporate promotion salary",
    "personal": "personal diary journal thoughts feelings myself private reflection life experience memories emotions self growth mindfulness",
    "social": "social friends party gathering community networking relationship people event celebration birthday wedding festival group",
    "legal": "legal lawyer court law contract attorney lawsuit litigation rights regulation compliance agreement legal counsel judiciary",
    "travel": "travel vacation trip flight hotel destination airport tourism journey adventure explore visiting touring abroad international",
    "education": "education school university college learning student teacher course study exam academic lecture research degree graduation",
    "programming": "programming code software developer function class API algorithm debug python javascript database SQL coding technical",
    "sports": "sports basketball football soccer tennis golf hockey game team player match athletic competition tournament fitness",
    "technology": "technology smartphone computer laptop software hardware app device digital internet gadget innovation tech mobile electronics",
    "shopping": "shopping buy purchase store mall sale discount price order delivery retail clothes product online ecommerce checkout",
    "family": "family parents children kids siblings relatives grandparents reunion mother father brother sister aunt uncle nephew",
    "general": "general information content document text note article miscellaneous various other topics",
}


@dataclass
class TopicResult:
    """Result of topic labeling for a document."""
    topics: List[str]
    primary_topic: str
    confidence: float
    method: str = "keyword_match"


class TopicLabeler:
    """Topic labeling using keyword matching and embedding similarity.

    This class provides topic classification without requiring an LLM.
    It uses a two-stage approach:
    1. Keyword matching (fast, reliable for known terms)
    2. Embedding similarity (semantic understanding for ambiguous content)

    Attributes:
        embedding_model: Optional embedding model for similarity-based classification
        verbose: Whether to print debug information
    """

    def __init__(
        self,
        embedding_model: Optional[Any] = None,
        verbose: bool = False,
        **kwargs  # Accept and ignore legacy parameters for backward compatibility
    ):
        """Initialize the topic labeler.

        Args:
            embedding_model: Embedding model instance for similarity-based classification.
                            If None, only keyword matching is used.
            verbose: Whether to print debug information.
            **kwargs: Ignored (for backward compatibility with old LLM-based parameters)
        """
        self.embedding_model = embedding_model
        self.verbose = verbose
        self._topic_embeddings: Optional[Dict[str, Any]] = None

        # Ignore legacy parameters with warning
        legacy_params = {'model_path', 'cache_dir', 'device', 'n_ctx', 'n_gpu_layers'}
        used_legacy = set(kwargs.keys()) & legacy_params
        if used_legacy and verbose:
            print(f"TopicLabeler: Ignoring legacy parameters: {used_legacy}")

    def _ensure_topic_embeddings(self) -> bool:
        """Pre-compute topic embeddings for similarity matching.

        Returns:
            True if embeddings are available, False otherwise.
        """
        if self._topic_embeddings is not None:
            return True

        if self.embedding_model is None:
            return False

        try:
            import numpy as np

            self._topic_embeddings = {}
            for topic, description in TOPIC_DESCRIPTIONS.items():
                # Get embedding for topic description
                embedding = self.embedding_model.embed(description)
                if embedding is not None:
                    # Handle both single embedding and batch results
                    if hasattr(embedding, 'shape') and len(embedding.shape) > 1:
                        embedding = embedding[0]
                    self._topic_embeddings[topic] = np.array(embedding)

            if self.verbose:
                print(f"TopicLabeler: Pre-computed embeddings for {len(self._topic_embeddings)} topics")
            return True

        except Exception as e:
            if self.verbose:
                print(f"TopicLabeler: Failed to compute topic embeddings: {e}")
            self._topic_embeddings = None
            return False

    def _cosine_similarity(self, vec1, vec2) -> float:
        """Compute cosine similarity between two vectors."""
        import numpy as np
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))

    def generate_topics(
        self,
        text: str,
        num_topics: int = 3,
        predefined_topics: Optional[List[str]] = None,
        max_text_length: int = 1000,
        use_default_topics: bool = True
    ) -> TopicResult:
        """Generate topic labels for a piece of text.

        Uses a two-stage approach:
        1. Keyword matching (fast path for documents with clear topic indicators)
        2. Embedding similarity (for ambiguous content when embedding model available)

        Args:
            text: The document text to label
            num_topics: Maximum number of topics to generate (1-5)
            predefined_topics: Optional list of allowed topics.
                              If None and use_default_topics=True, uses DEFAULT_TOPICS.
            max_text_length: Maximum characters of text to analyze.
            use_default_topics: If True (default) and predefined_topics is None,
                               uses DEFAULT_TOPICS.

        Returns:
            TopicResult with topics, primary_topic, and confidence
        """
        # Use default topics if none provided
        topics_to_use = predefined_topics
        if topics_to_use is None and use_default_topics:
            topics_to_use = DEFAULT_TOPICS

        # Handle empty or very short text
        if not text or len(text.strip()) < 3:
            return TopicResult(
                topics=["general"],
                primary_topic="general",
                confidence=0.0,
                method="empty_text"
            )

        # Truncate text for processing
        text_to_analyze = text[:max_text_length] if len(text) > max_text_length else text

        # Stage 1: Try weighted keyword matching first (fast and reliable)
        if topics_to_use:
            keyword_result = self._classify_by_keywords(text_to_analyze, topics_to_use, num_topics)

            # Check if result is clear or ambiguous
            is_clear_result = (
                keyword_result.primary_topic != "general" and
                keyword_result.confidence >= 0.6
            )

            # If we have a clear result, return it
            if is_clear_result:
                return keyword_result

            # If result is ambiguous (low confidence or multiple close topics), use ML
            is_ambiguous = (
                keyword_result.primary_topic != "general" and
                keyword_result.confidence < 0.6
            )

        # Stage 2: Use embedding similarity for ambiguous or no keyword match
        if self.embedding_model is not None and self._ensure_topic_embeddings():
            embedding_result = self._classify_by_embedding(
                text_to_analyze, topics_to_use, num_topics
            )

            # If embedding has higher confidence, prefer it
            if embedding_result.confidence > 0.4:
                # Merge with keyword results if both found topics
                if topics_to_use and keyword_result.primary_topic != "general":
                    # Combine results - weight keyword matches into embedding scores
                    merged_topics = self._merge_topic_results(
                        keyword_result, embedding_result, num_topics
                    )
                    if merged_topics:
                        return merged_topics

                return embedding_result

        # Return keyword result if we have one
        if topics_to_use and keyword_result.primary_topic != "general":
            return keyword_result

        # Fallback: return general topic
        return TopicResult(
            topics=["general"],
            primary_topic="general",
            confidence=0.2,
            method="fallback"
        )

    def _merge_topic_results(
        self,
        keyword_result: TopicResult,
        embedding_result: TopicResult,
        num_topics: int
    ) -> Optional[TopicResult]:
        """Merge keyword and embedding results using weighted combination.

        Keyword matches are weighted by their specificity, embedding matches
        by their similarity scores.
        """
        # Combine topics from both sources, prioritizing overlap
        combined_scores: Dict[str, float] = {}

        # Add keyword topics with their confidence as weight
        for topic in keyword_result.topics:
            combined_scores[topic] = combined_scores.get(topic, 0) + keyword_result.confidence * 0.6

        # Add embedding topics with their confidence as weight
        for topic in embedding_result.topics:
            combined_scores[topic] = combined_scores.get(topic, 0) + embedding_result.confidence * 0.4

        if not combined_scores:
            return None

        # Sort by combined score
        sorted_topics = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        top_topics = [t for t, s in sorted_topics[:num_topics]]
        top_score = sorted_topics[0][1]

        return TopicResult(
            topics=top_topics,
            primary_topic=top_topics[0],
            confidence=min(0.95, top_score),
            method="keyword_embedding_merged"
        )

    def _classify_by_keywords(
        self,
        text: str,
        predefined_topics: List[str],
        num_topics: int = 3
    ) -> TopicResult:
        """Classify text by matching keywords with weighted scoring.

        Uses:
        1. Weighted keyword matching (higher weight = more topic-specific)
        2. Stemming to match word variations
        3. Detection of ambiguous cases for ML fallback

        Returns a TopicResult with confidence indicating clarity of classification.
        Low confidence (<0.6) suggests the result is ambiguous and ML should be used.
        """
        text_lower = text.lower()
        predefined_set = set(t.lower() for t in predefined_topics)

        # Extract words from text (handle common punctuation)
        words = re.split(r'[\s,.:;!?()\[\]{}"\'/\\]+', text_lower)

        # Track weighted scores per topic
        topic_scores: Dict[str, float] = {}
        topic_keyword_counts: Dict[str, int] = {}

        for word in words:
            word = word.strip()
            if not word or len(word) < 2:
                continue

            topic = None
            weight = 1.0

            # Priority 1: Exact weighted keyword match
            if word in WEIGHTED_KEYWORD_MAP:
                topic, weight = WEIGHTED_KEYWORD_MAP[word]
            else:
                # Priority 2: Stemmed match
                stemmed = _simple_stem(word)
                if stemmed in STEMMED_KEYWORD_MAP:
                    topic = STEMMED_KEYWORD_MAP[stemmed]
                    # Stemmed matches get slightly lower weight
                    weight = 0.8 * weight if topic else 1.0

            # Accumulate weighted score if topic is in predefined set
            if topic and topic in predefined_set:
                topic_scores[topic] = topic_scores.get(topic, 0) + weight
                topic_keyword_counts[topic] = topic_keyword_counts.get(topic, 0) + 1

        # Calculate total score and determine confidence
        if topic_scores:
            # Sort by weighted score (most matched/weighted first)
            sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
            matched_topics = [t for t, s in sorted_topics]
            top_score = sorted_topics[0][1]

            # Calculate confidence based on:
            # 1. Total weighted score
            # 2. Score differential from second topic (clarity)
            # 3. Number of keywords matched

            # Base confidence from score
            if top_score >= 10.0:
                base_confidence = 0.9
            elif top_score >= 6.0:
                base_confidence = 0.8
            elif top_score >= 3.0:
                base_confidence = 0.65
            elif top_score >= 1.5:
                base_confidence = 0.5
            else:
                base_confidence = 0.35

            # Ambiguity penalty - if second topic is close to first
            if len(sorted_topics) > 1:
                second_score = sorted_topics[1][1]
                score_ratio = second_score / top_score if top_score > 0 else 0
                if score_ratio > 0.8:
                    # Very close scores - ambiguous
                    base_confidence *= 0.7
                elif score_ratio > 0.6:
                    # Moderately close - somewhat ambiguous
                    base_confidence *= 0.85

            # Boost for multiple keywords matched
            keyword_count = topic_keyword_counts.get(matched_topics[0], 0)
            if keyword_count >= 5:
                base_confidence = min(0.95, base_confidence + 0.1)
            elif keyword_count >= 3:
                base_confidence = min(0.95, base_confidence + 0.05)

            confidence = min(0.95, base_confidence)

            return TopicResult(
                topics=matched_topics[:num_topics],
                primary_topic=matched_topics[0],
                confidence=confidence,
                method="weighted_keyword_match"
            )

        return TopicResult(
            topics=["general"],
            primary_topic="general",
            confidence=0.2,
            method="keyword_no_match"
        )

    def _classify_by_embedding(
        self,
        text: str,
        predefined_topics: Optional[List[str]],
        num_topics: int
    ) -> TopicResult:
        """Classify text using embedding similarity to topic descriptions."""
        import numpy as np

        try:
            # Get embedding for the document
            doc_embedding = self.embedding_model.embed(text)
            if doc_embedding is None:
                return self._fallback_result()

            # Handle batch results
            if hasattr(doc_embedding, 'shape') and len(doc_embedding.shape) > 1:
                doc_embedding = doc_embedding[0]
            doc_embedding = np.array(doc_embedding)

            # Compute similarity to each topic
            similarities = {}
            topics_to_check = predefined_topics if predefined_topics else list(TOPIC_DESCRIPTIONS.keys())

            for topic in topics_to_check:
                topic_lower = topic.lower()
                if topic_lower in self._topic_embeddings:
                    sim = self._cosine_similarity(doc_embedding, self._topic_embeddings[topic_lower])
                    similarities[topic_lower] = sim

            if not similarities:
                return self._fallback_result()

            # Sort by similarity
            sorted_topics = sorted(similarities.items(), key=lambda x: x[1], reverse=True)

            # Filter to topics with reasonable similarity (> 0.3 threshold)
            threshold = 0.3
            good_matches = [(t, s) for t, s in sorted_topics if s > threshold]

            if good_matches:
                top_topics = [t for t, s in good_matches[:num_topics]]
                top_score = good_matches[0][1]
                return TopicResult(
                    topics=top_topics,
                    primary_topic=top_topics[0],
                    confidence=float(top_score),
                    method="embedding_similarity"
                )

            # No good matches - return general with low confidence
            return TopicResult(
                topics=["general"],
                primary_topic="general",
                confidence=float(sorted_topics[0][1]) if sorted_topics else 0.0,
                method="embedding_low_match"
            )

        except Exception as e:
            if self.verbose:
                print(f"TopicLabeler: Embedding classification error: {e}")
            return self._fallback_result()

    def _fallback_result(self) -> TopicResult:
        """Return a fallback result when classification fails."""
        return TopicResult(
            topics=["general"],
            primary_topic="general",
            confidence=0.1,
            method="fallback"
        )

    def batch_generate_topics(
        self,
        texts: List[str],
        num_topics: int = 3,
        predefined_topics: Optional[List[str]] = None
    ) -> List[TopicResult]:
        """Generate topics for multiple texts.

        Args:
            texts: List of document texts to label
            num_topics: Maximum topics per document
            predefined_topics: Optional allowed topics list

        Returns:
            List of TopicResult, one per input text
        """
        results = []
        for text in texts:
            result = self.generate_topics(
                text,
                num_topics=num_topics,
                predefined_topics=predefined_topics
            )
            results.append(result)
        return results

    def is_model_loaded(self) -> bool:
        """Check if embedding model is available for enhanced classification.

        Note: This always returns True since keyword matching is always available.
        The embedding model is optional for enhanced semantic classification.
        """
        return True  # Keyword matching is always available

    def unload_model(self) -> None:
        """Clear cached topic embeddings.

        Note: This does not unload the embedding model as it may be shared
        with other components.
        """
        self._topic_embeddings = None
        if self.verbose:
            print("TopicLabeler: Cleared topic embeddings cache")

    def reset_load_state(self) -> None:
        """Reset state to allow re-initialization.

        For backward compatibility with old API.
        """
        self._topic_embeddings = None

    def set_embedding_model(self, embedding_model: Any) -> None:
        """Set or update the embedding model.

        Args:
            embedding_model: Embedding model instance for similarity-based classification.
        """
        self.embedding_model = embedding_model
        self._topic_embeddings = None  # Clear cache to recompute with new model

    def __repr__(self) -> str:
        has_embedding = "with_embeddings" if self.embedding_model is not None else "keywords_only"
        return f"TopicLabeler({has_embedding})"
