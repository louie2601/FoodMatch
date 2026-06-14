from django.db import models


class FoodItem(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ResearchPaper(models.Model):
    title = models.CharField(max_length=200)
    authors = models.CharField(max_length=200)
    abstract = models.TextField()
    published_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
