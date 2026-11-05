import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import AnnouncementImage

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=AnnouncementImage)
def delete_announcement_image_file(sender, instance, **kwargs):
    # Also fires for each image when its announcement is deleted (cascade).
    if instance.image:
        try:
            instance.image.delete(save=False)
        except OSError:
            logger.warning("Could not delete announcement image %s", instance.image.name)
