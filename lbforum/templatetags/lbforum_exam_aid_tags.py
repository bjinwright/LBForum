from django import template

from lbforum.models import Forum

register = template.Library()

@register.inclusion_tag('lbforum/tags/exam_aid.html', takes_context=True)
def exam_aid_forum(exam_slug):
    try:
        forum = Forum.objects.get(slug=exam_slug)
    except Forum.DoesNotExist:
        forum = None
    if not forum:
        return {}
    
    topics = forum.topics_set.all().order_by(
                        '-last_reply_on').select_related()
    
    return {
        'forum':forum,
        'topics':topics
            }
