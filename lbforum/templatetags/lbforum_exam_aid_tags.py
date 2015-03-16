from django import template

from lbforum.models import Forum

register = template.Library()

@register.inclusion_tag('lbforum/tags/exam_aid.html')
def exam_aid_forum(exam_slug):
    try:
        forum = Forum.objects.get(slug=exam_slug)
    except Forum.DoesNotExist:
        forum = None
    if not forum:
        return {}
    
    topics = forum.topic_set.all().order_by(
                        '-last_reply_on').select_related()[:10]
    
    return {
        'forum':forum,
        'topics':topics
            }
