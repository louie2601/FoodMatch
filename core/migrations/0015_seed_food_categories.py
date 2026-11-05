from django.db import migrations

CATEGORY_TREE = {
    "Rice & Grain Dishes": [
        "Fried Rice", "Rice Bowls", "Risotto", "Porridge", "Paella", "Grain Bowls",
    ],
    "Noodles & Pasta": [
        "Spaghetti", "Ramen", "Udon", "Soba", "Pad Thai", "Pancit", "Macaroni", "Lasagna",
    ],
    "Meat": [
        "Beef", "Pork", "Chicken", "Lamb", "Goat", "Turkey", "Duck",
    ],
    "Seafood": [
        "Fish", "Shrimp", "Crab", "Squid", "Octopus", "Shellfish", "Lobster",
    ],
    "Vegetables": [
        "Leafy Greens", "Root Vegetables", "Legumes", "Mushrooms", "Cruciferous Vegetables", "Squash", "Eggplant",
    ],
    "Fruits": [
        "Tropical Fruits", "Citrus Fruits", "Berries", "Stone Fruits", "Melons", "Apples & Pears", "Dried Fruits",
    ],
    "Soups & Stews": [
        "Broth-based Soups", "Cream Soups", "Vegetable Soups", "Meat Stews", "Seafood Soups", "Noodle Soups",
    ],
    "Salads": [
        "Green Salads", "Fruit Salads", "Pasta Salads", "Grain Salads", "Seafood Salads", "Meat Salads",
    ],
    "Bread & Bakery": [
        "Bread", "Buns", "Rolls", "Croissants", "Muffins", "Bagels", "Pastries",
    ],
    "Breakfast Foods": [
        "Eggs", "Pancakes", "Waffles", "Cereal", "Oatmeal", "Breakfast Sandwiches", "Breakfast Bowls",
    ],
    "Appetizers & Starters": [
        "Spring Rolls", "Dumplings", "Nachos", "Fries", "Wings", "Skewers", "Bruschetta",
    ],
    "Main Courses": [
        "Grilled", "Fried", "Roasted", "Baked", "Steamed", "Stir-Fried", "Braised",
    ],
    "Fast Food": [
        "Burgers", "Pizza", "Hot Dogs", "Fried Chicken", "Sandwiches", "Tacos", "Wraps",
    ],
    "Desserts": [
        "Cakes", "Ice Cream", "Cookies", "Brownies", "Puddings", "Pies", "Cheesecake", "Donuts", "Chocolates",
    ],
    "Snacks": [
        "Chips", "Crackers", "Popcorn", "Nuts", "Trail Mix", "Sandwich Snacks", "Energy Bars",
    ],
    "Dairy & Dairy Alternatives": [
        "Milk", "Cheese", "Yogurt", "Cream", "Butter", "Plant-Based Milk",
    ],
    "Sauces & Condiments": [
        "Ketchup", "Mayonnaise", "Mustard", "Soy Sauce", "Vinegar", "Hot Sauce", "Gravy", "Dips",
    ],
    "Beverages": [
        "Water", "Coffee", "Tea", "Juice", "Smoothies", "Milkshakes", "Soft Drinks", "Energy Drinks",
    ],
}


def seed_categories(apps, schema_editor):
    FoodCategory = apps.get_model("core", "FoodCategory")
    for parent_name, child_names in CATEGORY_TREE.items():
        parent, _ = FoodCategory.objects.get_or_create(name=parent_name, parent=None)
        for child_name in child_names:
            FoodCategory.objects.get_or_create(name=child_name, parent=parent)


def remove_seeded_categories(apps, schema_editor):
    FoodCategory = apps.get_model("core", "FoodCategory")
    FoodCategory.objects.filter(name__in=list(CATEGORY_TREE.keys()), parent__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_add_food_category"),
    ]

    operations = [
        migrations.RunPython(seed_categories, remove_seeded_categories),
    ]
