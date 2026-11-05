"""Food research relevance check.

FOOD MATCH only keeps food research, so every upload (Submit Research, Add
Research, Similarity Check) is screened first.

The check uses a fixed food vocabulary in two groups:

  * general food words (food, menu, meal, restaurant, drink...), which also
    show up in non-food papers, e.g. an IT "food ordering system", and
  * specific food-research terms: named ingredients and dishes, cooking and
    preservation methods, nutrients, sensory evaluation (taste, aroma,
    texture, hedonic...).

A paper counts as food research when enough *different* specific terms
appear, and they make up a minimum share of the paper's content words, so a
single passing mention ("the canteen serves chicken") is not enough.

No training is needed. The result can always be explained by listing the
specific terms that were found.
"""
import re

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# Tuned on the food papers already in the repository and on sample non-food
# papers (IT systems incl. food-ordering apps, education, criminology,
# tourism, engineering, nursing, business, psychology, agriculture).
FULL_TEXT_MIN_WORDS = 300          # file text at least this long -> judge the full paper
FULL_MIN_SPECIFIC_TERMS = 5
FULL_MIN_SPECIFIC_DENSITY = 0.003  # 3 per 1,000 content words
SHORT_MIN_SPECIFIC_TERMS = 2       # only title/abstract/keywords to go on
SHORT_MIN_SPECIFIC_DENSITY = 0.01

_GENERAL_WORDS = """
food foods foodstuff menu menus meal meals dining restaurant restaurants eatery canteen cafeteria
catering caterer kitchen chef eat eating eaten drink drinks beverage beverages snack snacks dessert
desserts rice delicious appetite dish dishes delicacy delicacies cuisine culinary juice coffee tea
soda sanitation hygiene acceptability moisture diet dietary formulation formulations fat fats chip
chips spread preserve preserves sugar salt
""".split()

_SPECIFIC_WORDS = """
foodborne food-safety haccp shelf-life spoilage recipe recipes ingredient ingredients cook cooking
cooked bake baking baked bakery baker edible taste tasting tasty flavor flavour flavors flavored
flavoured aroma aromatic texture palatable palatability appetizer sweetness sourness bitterness
saltiness crispness crispy crunchy chewy
wine vinegar smoothie milk dairy cheese butter yogurt yoghurt cream ice-cream margarine
nutrition nutritional nutrient nutrients nutritive nutritious protein proteins carbohydrate
carbohydrates lipid fiber fibre vitamin vitamins calorie calories caloric antioxidant antioxidants
proximate
flour starch dough bread breads cake cakes cookie cookies biscuit biscuits pastry pastries pie muffin
muffins brownies noodle noodles pasta cracker crackers nugget nuggets sausage sausages ham bacon
jerky patty patties burger jam jelly jellies sauce sauces condiment condiments seasoning seasonings
spice spices ketchup syrup honey candy candies chocolate cacao cocoa sweetener
vegetable vegetables fruit fruits meat meats pork beef chicken poultry fish seafood shrimp crab squid
snail snails shellfish egg eggs tofu
banana mango coconut cassava taro ube yam calamansi malunggay moringa squash tomato tomatoes potato
potatoes corn mung beans bean legume legumes peanut peanuts soy soybean ginger garlic onion onions
pepper chili pineapple papaya guava jackfruit avocado lemon orange grapes apple strawberry pumpkin
carrot carrots eggplant okra cabbage spinach kangkong pechay sago tapioca oat oats wheat barley
sorghum sesame cinnamon turmeric oregano pandan
lumpia chicharon chicharron adobo sinigang puto bibingka suman kakanin polvoron longganisa tocino
tapa daing tuyo bagoong patis atchara turon halo-halo leche biko kutsinta palitaw sapin-sapin
espasol pastillas yema ensaymada pandesal
pickle pickled pickling ferment fermented fermentation preservation dehydrated dehydration fried
frying steamed boiled roasted grilled smoked blanched marinated extruded
sensory organoleptic hedonic panelist panelists
""".split()

# Two-word terms are joined with "-" before matching.
_FOOD_PHRASES = {
    "shelf life": "shelf-life",
    "food safety": "food-safety",
    "ice cream": "ice-cream",
    "halo halo": "halo-halo",
    "sapin sapin": "sapin-sapin",
}

_WORD_RE = re.compile(r"[a-z][a-z\-]*")


def _stem(word):
    """Simple singular form so 'crackers' and 'cracker' count as one term."""
    if len(word) > 4:
        if word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith("oes"):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
    return word


GENERAL_FOOD_TERMS = {_stem(w) for w in _GENERAL_WORDS}
SPECIFIC_FOOD_TERMS = {_stem(w) for w in _SPECIFIC_WORDS} - GENERAL_FOOD_TERMS


def _content_words(text):
    lowered = (text or "").lower()
    for phrase, joined in _FOOD_PHRASES.items():
        lowered = re.sub(r"\b" + phrase.replace(" ", r"[\s\-]+") + r"\b", joined, lowered)
    words = (w.strip("-") for w in _WORD_RE.findall(lowered))
    return [w for w in words if len(w) > 1 and w not in ENGLISH_STOP_WORDS]


def assess_food_relevance(title="", abstract="", keywords="", document_text=""):
    """Decide whether a paper is food research.

    Returns {"is_food", "specific_terms", "specific_density", "general_terms",
    "content_words", "mode"}; `specific_terms` lists the food-research terms
    found, most frequent first, so the decision can be shown and explained.
    """
    document_words = _content_words(document_text)
    words = _content_words(" ".join([title or "", abstract or "", keywords or ""])) + document_words
    specific, general = {}, set()
    for word in words:
        stem = _stem(word)
        if stem in SPECIFIC_FOOD_TERMS:
            specific[stem] = specific.get(stem, 0) + 1
        elif stem in GENERAL_FOOD_TERMS:
            general.add(stem)
    total = len(words)
    density = sum(specific.values()) / total if total else 0.0

    if len(document_words) >= FULL_TEXT_MIN_WORDS:
        mode = "full text"
        is_food = len(specific) >= FULL_MIN_SPECIFIC_TERMS and density >= FULL_MIN_SPECIFIC_DENSITY
    else:
        mode = "title and abstract"
        is_food = len(specific) >= SHORT_MIN_SPECIFIC_TERMS and density >= SHORT_MIN_SPECIFIC_DENSITY

    return {
        "is_food": is_food,
        "specific_terms": sorted(specific, key=lambda t: (-specific[t], t)),
        "specific_density": round(density, 4),
        "general_terms": sorted(general),
        "content_words": total,
        "mode": mode,
    }


def not_food_research_error(assessment):
    """User-facing message for a paper that was turned away."""
    found = assessment.get("specific_terms") or []
    if found:
        detail = f" Only {len(found)} food research term{'s' if len(found) != 1 else ''} found: {', '.join(found[:5])}."
    else:
        detail = " No food research terms (ingredients, recipes, nutrients, sensory evaluation...) were found."
    return (
        "This does not look like food research. FOOD MATCH only accepts food research "
        "(food products, ingredients, recipes, nutrition, food processing, sensory evaluation, etc.)."
        + detail
    )


def check_uploaded_research(uploaded_file, title="", abstract="", keywords="", text=None):
    """Read an uploaded research file and judge it. `text` is the file's own
    text when the caller already read it. A scanned file with too little
    readable text is read again with OCR before deciding."""
    from .utils import extract_text_from_uploaded_file

    if text is None:
        try:
            text = extract_text_from_uploaded_file(uploaded_file, use_ocr=False)
        except Exception:
            text = ""
    if len(_content_words(text)) < FULL_TEXT_MIN_WORDS:
        try:
            ocr_text = extract_text_from_uploaded_file(uploaded_file, use_ocr=True)
        except Exception:
            ocr_text = ""
        if len(ocr_text) > len(text):
            text = ocr_text
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    return assess_food_relevance(title, abstract, keywords, text)
