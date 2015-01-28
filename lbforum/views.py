#!/usr/bin/env python
# -*- coding: UTF-8 -*-
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext
from django.core.urlresolvers import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView,DetailView


from forms import EditPostForm, NewPostForm, ForumForm
from models import Topic, Forum, Post
import settings as lbf_settings
from pydoc_data.topics import topics
from django.core.context_processors import request
from django.views.generic.edit import CreateView, DeleteView
from braces.views._access import LoginRequiredMixin, StaffuserRequiredMixin
from django.core.cache import cache



class IndexView(ListView):
    template_name = 'lbforum/index.html'
    paginate_by = 20
    context_object_name = 'topics'
    def get_queryset(self):
        return Topic.objects.all().order_by('-last_reply_on')
    
index = IndexView.as_view()

class RecentView(ListView):
    template_name = 'lbforum/recent.html'
    
    def get_queryset(self):
        topics = Topic.objects.all().order_by('-last_reply_on')
        return topics.select_related()
    
recent = RecentView.as_view()

class ForumView(DetailView):
    template_name = 'lbforum/forum.html'
    model = Forum
    context_object_name = 'forum'
    def get_context_data(self, **kwargs):
        context = super(ForumView,self).get_context_data(**kwargs)
        topics = self.object.topic_set.all()
        topic_type = self.kwargs.get('topic_type')
        topic_type2 = self.kwargs.get('topic_type2')
        if topic_type and topic_type != 'good':
            topic_type2 = topic_type
            topic_type = ''
        if topic_type == 'good':
            topics = topics.filter(level__gt=30)
        if topic_type2:
            topics = topics.filter(topic_type__slug=topic_type2)
        order_by = self.request.GET.get('order_by','-last_reply_on')
        context['topics'] = topics.order_by('-sticky', order_by).select_related()
        context['form'] = ForumForm(self.request.GET)
        context['topic_type'] = topic_type
        context['topic_type2'] = topic_type2    
        return context
    
forum = ForumView.as_view()

class TopicView(DetailView):
    model = Topic
    context_object_name = 'topic'
    template_name = 'lbforum/topic.html'
    
    def get_context_data(self, **kwargs):
        context = super(TopicView,self).get_context_data(**kwargs)
        posts = self.objects.posts
        if lbf_settings.STICKY_TOPIC_POST:
            posts = posts.filter(topic_post=False)
        posts = posts.order_by('created_on').select_related()
        context['posts'] = posts
        context['has_replied'] = self.object.has_replied(self.request.user)
        return context
    
topic = TopicView.as_view()

def post(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    return HttpResponseRedirect(post.get_absolute_url_ext())


@csrf_exempt
def markitup_preview(request, template_name="lbforum/markitup_preview.html"):
    return render(request, template_name, {'message': request.POST['data']})

def get_cached_obj(pk,model_name,model_class,cache_timeout=500):
    '''
    Using a primary key retrive object from the database or from the cache.
    :param pk: Primary key
    :param model_name: Name of the model to use for the cache key
    :param model_class: The Django model class to query if the object is 
    not in the cache
    '''
    if pk == None:
        return None
    ck = '{0}-forum'.format(pk)
    obj = cache.get(ck)
    if not obj:
        obj = get_object_or_404(model_class,pk=pk)
        cache.set(ck,obj,cache_timeout)
    return obj

class NewPostView(LoginRequiredMixin,CreateView):
    model = Post
    form_class = NewPostForm
    template_name = 'lbforum/post.html'
    
    def get_forum(self):
        forum_id = self.kwargs.get('forum_id')
        topic_id = self.kwargs.get('topic_id')
        
        if forum_id:
            forum = get_cached_obj(forum_id, 'forum', Forum)
        if topic_id:
            forum = get_cached_obj(topic_id, 'topic', Topic).forum
        return forum
    
    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        if form.is_valid() and request.POST.get('submit',None):
            return self.form_valid(form)
        else:
            return self.form_invalid(form)
        
    def get_topic(self):
        try:
            return self._topic
        except AttributeError:
            pass
        self._topic = get_cached_obj(self.kwargs.get('topic_id'),'topic',Topic)
        return self._topic
    
        
    def get_form_kwargs(self):
        kwargs = super(NewPostView,self).get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['forum'] = self.get_forum()
        kwargs['topic'] = get_cached_obj(self.kwargs.get('topic_id'),
                                         'topic', Topic)
        kwargs['ip'] = self.request.META.get('REMOTE_ADDR')
        return kwargs
    
    def get_context_data(self, **kwargs):
        context = super(NewPostView,self).get_context_data(**kwargs)
        topic = self.get_topic()
        if topic:
            first_post = topic.posts.order_by('created_on').select_related()[0]
        else:
            first_post = None
        context.update(
            {'forum':self.get_forum(),'topic':self.get_topic(),
             'first_post':first_post}
                       )
        return context
    
    def get_initial(self):
        initial = super(NewPostView,self).get_initial()
        qid = self.request.GET.get('qid')
        if qid:
            qpost = get_cached_obj(qid, 'post', Post)
            initial['message'] = "[quote={0}]{1}[/quote]".format(
                qpost.posted_by.username, qpost.message)
        return initial
    
    def get_success_url(self):
        topic = self.get_topic()
        if topic:
            return self.object.get_absolute_url_ext()
        return reverse('lbforum_forum',args=[forum.slug])
    
        
        
@login_required
def new_post(request, forum_id=None, topic_id=None, form_class=NewPostForm,
        template_name='lbforum/post.html'):
    qpost = topic = forum = first_post = preview = None
    post_type = _('topic')
    topic_post = True
    if forum_id:
        forum = get_object_or_404(Forum, pk=forum_id)
    if topic_id:
        post_type = _('reply')
        topic_post = False
        topic = get_object_or_404(Topic, pk=topic_id)
        forum = topic.forum
        first_post = topic.posts.order_by('created_on').select_related()[0]
    if request.method == "POST":
        form = form_class(request.POST, user=request.user, forum=forum,
                topic=topic, ip=request.META['REMOTE_ADDR'])
        preview = request.POST.get('preview', '')
        if form.is_valid() and request.POST.get('submit', ''):
            post = form.save()
            if topic:
                return HttpResponseRedirect(post.get_absolute_url_ext())
            else:
                return HttpResponseRedirect(reverse("lbforum_forum",
                                                    args=[forum.slug]))
    else:
        initial = {}
        qid = request.GET.get('qid', '')
        if qid:
            qpost = get_object_or_404(Post, id=qid)
            initial['message'] = "[quote=%s]%s[/quote]"
            initial['message'] %= (qpost.posted_by.username, qpost.message)
        form = form_class(initial=initial, forum=forum)
    ext_ctx = {
        'forum': forum,
        'form': form,
        'topic': topic,
        'first_post': first_post,
        'post_type': post_type,
        'preview': preview
    }
    ext_ctx['unpublished_attachments'] = request.user.attachment_set.filter(activated=False)
    ext_ctx['is_new_post'] = True
    ext_ctx['topic_post'] = topic_post
    ext_ctx['session_key'] = request.session.session_key
    return render(request, template_name, ext_ctx)


@login_required
def edit_post(request, post_id, form_class=EditPostForm,
              template_name="lbforum/post.html"):
    preview = None
    post_type = _('reply')
    edit_post = get_object_or_404(Post, id=post_id)
    if not (request.user.is_staff or request.user == edit_post.posted_by):
        return HttpResponse(ugettext('no right'))
    if edit_post.topic_post:
        post_type = _('topic')
    if request.method == "POST":
        form = form_class(instance=edit_post, user=request.user,
                          data=request.POST)
        preview = request.POST.get('preview', '')
        if form.is_valid() and request.POST.get('submit', ''):
            edit_post = form.save()
            return HttpResponseRedirect('../')
    else:
        form = form_class(instance=edit_post)
    ext_ctx = {
        'form': form,
        'post': edit_post,
        'topic': edit_post.topic,
        'forum': edit_post.topic.forum,
        'post_type': post_type,
        'preview': preview
    }
    ext_ctx['unpublished_attachments'] = request.user.attachment_set.filter(activated=False)
    ext_ctx['topic_post'] = edit_post.topic_post
    ext_ctx['session_key'] = request.session.session_key
    return render(request, template_name, ext_ctx)

class UserTopicsView(ListView):
    context_object_name = 'topics'
    template_name = 'lbforum/account/user_topics.html'
    
    def get_queryset(self):
        view_user = get_cached_obj(self.kwargs.get('user_id'), 'user', User)
        topics = view_user.topic_set.order_by('-created_on').select_related()
        return topics
    
    def get_context_data(self, **kwargs):
        context = super(UserTopicsView,self).get_context_data(**kwargs)
        context['view_user'] = get_cached_obj(self.kwargs.get('user_id'), 'user', User)
        return context
    
user_topics = UserTopicsView.as_view()

class UserPostsView(ListView):
    context_object_name = 'posts'
    template_name = 'lbforum/account/user_posts.html'
    
    def get_queryset(self):
        view_user = get_cached_obj(self.kwargs.get('user_id'), 'user', User)
        posts = view_user.post_set.order_by('-created_on').select_related()
        return posts
    
    def get_context_data(self, **kwargs):
        context = super(UserPostsView,self).get_context_data(**kwargs)
        context['view_user'] = get_cached_obj(self.kwargs.get('user_id'),
                                              'user', User)
        return context
    
user_posts = UserPostsView.as_view()

class DeleteTopicView(StaffuserRequiredMixin,DeleteView):
    model = Topic
    
    def delete(self, request, *args, **kwargs):
        response = super(DeleteTopicView,self).delete(request,*args,**kwargs)
        self.object.forum.update_state_info()
        return response
    
    def get_success_url(self):
        return reverse("lbforum_forum",args=[self.object.forum.slug])

delete_topic = DeleteTopicView.as_view()

class DeletePostView(StaffuserRequiredMixin,DeleteView):
    model = Post
    
    def delete(self, request, *args, **kwargs):
        response = super(DeletePostView,self).delete(request,*args,**kwargs)
        topic = self.object.topic
        topic.update_state_info()
        topic.forum.update_state_info()
        return response
    
    def get_success_url(self):
        return reverse("lbforum_topic",args=[self.object.topic.id])

delete_post = DeletePostView.as_view()


@login_required
def update_topic_attr_as_not(request, topic_id, attr):
    if not request.user.is_staff:
        return HttpResponse(ugettext('no right'))
    topic = get_object_or_404(Topic, id=topic_id)
    if attr == 'sticky':
        topic.sticky = not topic.sticky
    elif attr == 'close':
        topic.closed = not topic.closed
    elif attr == 'hide':
        topic.hidden = not topic.hidden
    elif attr == 'distillate':
        topic.level = 30 if topic.level >= 60 else 60
    topic.save()
    if topic.hidden:
        return HttpResponseRedirect(reverse("lbforum_forum",
                                            args=[topic.forum.slug]))
    else:
        return HttpResponseRedirect(reverse("lbforum_topic", args=[topic.id]))

#Feed...
#Add Post
#Add Topic
