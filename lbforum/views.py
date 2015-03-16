#!/usr/bin/env python
# -*- coding: UTF-8 -*-

from braces.views import LoginRequiredMixin, StaffuserRequiredMixin,\
    GroupRequiredMixin, UserPassesTestMixin

from django.http import HttpResponseRedirect, HttpResponse, HttpResponseNotFound
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext
from django.core.urlresolvers import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView,DetailView,CreateView, DeleteView,RedirectView
from django.core.cache import cache
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from lbforum.models import ForumFile
from forms import EditPostForm, NewPostForm, ForumForm

from models import Topic, Forum, Post
import settings as lbf_settings
from lbforum.forms import ForumFileForm

from django.conf import settings

def get_objs_groups(obj):
    ck = '{0}-{1}-groups'.format(obj.pk,obj.__class__.__name__.lower())
    groups = cache.get(ck)
    if not groups:
        groups = obj.groups.values_list("name",flat=True)
        cache.set(ck,groups,500)
    return groups

class IndexView(ListView):
    template_name = 'lbforum/index.html'
    paginate_by = 20
    context_object_name = 'forums'
    model = Forum
    show_exam_aid = False
    
    def get_queryset(self):
        if self.show_exam_aid:
            qs = self.model.objects.all()
        else:
            qs = self.model.objects.exclude(
                groups__name=settings.FORUM_EXAM_AID_GROUP_NAME)
        
        users_forums = []
        for forum in qs:
            forum_groups = get_objs_groups(forum)
            if len(forum_groups) != 0:
                if self.request.user.is_authenticated():
                    if self.request.user.is_superuser:
                        users_forums.append(forum)
                    else:
                        user_groups = get_objs_groups(self.request.user)
                        is_authorized = bool(set(forum_groups).intersection(user_groups))
                        if is_authorized:
                            users_forums.append(forum)
            else:
                users_forums.append(forum)
        return users_forums
    
index = IndexView.as_view()

class MyGroups(IndexView):
    show_exam_aid = True
    template_name = 'lbforum/my-groups.html'
    paginate_by = None
    
my_groups = MyGroups.as_view()

class RecentView(ListView):
    template_name = 'lbforum/recent.html'
    
    def get_queryset(self):
        topics = Topic.objects.all().order_by('-last_reply_on')
        return topics.select_related()
    
recent = RecentView.as_view()

class ForumGroupRequiredMixin(GroupRequiredMixin):
    
    def get_forum(self):
        raise NotImplementedError
    
    def check_membership(self, groups):
        if groups == None:
            return True
        return super(ForumGroupRequiredMixin,self).check_membership(groups)
    
    def get_group_required(self):
        groups = self.get_forum().groups.values_list("name", flat=True)
        if groups:
            return groups
        return None
        
    def dispatch(self, request, *args, **kwargs):
        response = super(GroupRequiredMixin,self).dispatch(request,*args,**kwargs)
        self.request = request
        try:
            self.object = self.get_object()
        except AttributeError:
            pass
        if not self.get_group_required():
            return response
        in_group = False
        if self.request.user.is_authenticated():
            in_group = self.check_membership(self.get_group_required())

        if not in_group:
            if self.raise_exception:
                raise PermissionDenied
            else:
                messages.error(request, 'You do not have permission to view this page.')
                return redirect_to_login(
                    request.get_full_path(),
                    self.get_login_url(),
                    self.get_redirect_field_name())
        return response
    
class ForumView(ForumGroupRequiredMixin,DetailView):
    template_name = 'lbforum/forum.html'
    model = Forum
    context_object_name = 'forum'
    slug_url_kwarg = 'forum_slug'
    def get_forum(self):
        return self.object
    
    def get_context_data(self, **kwargs):
        context = super(ForumView,self).get_context_data(**kwargs)
        topics = self.object.topic_set.all()
        order_by = self.request.GET.get('order_by','-last_reply_on')
        context['topics'] = topics.order_by('-sticky', order_by).select_related()
        context['form'] = ForumForm(self.request.GET)
        context['FORUM_PAGE_SIZE'] = 20
        return context
    
forum = ForumView.as_view()

class TopicView(ForumGroupRequiredMixin,DetailView):
    model = Topic
    context_object_name = 'topic'
    template_name = 'lbforum/topic.html'
    pk_url_kwarg = 'topic_id'
    def get_forum(self):
        return self.object.forum
    
    def get_context_data(self, **kwargs):
        context = super(TopicView,self).get_context_data(**kwargs)
        posts = self.object.posts
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

def get_cached_obj(pk,model_name,model_class,cache_timeout=500,get_or_404=True):
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
        if get_or_404:
            obj = get_object_or_404(model_class,pk=pk)
        else:
            try:
                obj = model_class.objects.get(pk=pk)
            except model_class.DoesNotExist:
                obj = None
        if obj:
            cache.set(ck,obj,cache_timeout)
    return obj

class NewPostView(ForumGroupRequiredMixin,LoginRequiredMixin,CreateView):
    model = Post
    form_class = NewPostForm
    template_name = 'lbforum/post.html'
    
    def dispatch(self, request, *args, **kwargs):
        handler = super(NewPostView,self).dispatch(request,*args,**kwargs)
        self.forum_id = self.kwargs.get('forum_id')
        self.topic_id = self.kwargs.get('topic_id')
        self._forum = self.get_forum()
        self._topic = self.get_topic()
        return handler
    
    def get_forum(self):
        try:
            return self._forum
        except AttributeError:
            pass
        if self.topic_id:
            self._forum = get_cached_obj(self.topic_id, 'topic', Topic).forum
            return self._forum
        self._forum = get_cached_obj(self.forum_id, 'forum', Forum)
        return self._forum
    
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
        self._topic = get_cached_obj(self.topic_id,'topic',Topic,get_or_404=False)
        return self._topic
    
        
    def get_form_kwargs(self):
        kwargs = super(NewPostView,self).get_form_kwargs()
        kwargs.update({'user':self.request.user,'forum':self._forum,
                       'topic':get_cached_obj(self.topic_id, 'topic', Topic),
                       'ip':self.request.META.get('REMOTE_ADDR')})
        return kwargs
    
    def get_first_post(self):
        topic = self.get_topic()
        if topic:
            first_post = topic.posts.order_by('created_on').select_related()[0]
        else:
            first_post = None
        return first_post
    
    
    
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
        return reverse_lazy('lbforum_forum',args=[forum.slug])
    
    def get_context_data(self, **kwargs):
        context = super(NewPostView,self).get_context_data(**kwargs)
        preview = None
        if self.request.method == 'POST':
            preview = self.request.POST.get('preview', '')
        if self._topic:
            post_type = _('reply')
            topic_post = False
        else:
            post_type = _('topic')
            topic_post = True
        context.update(
            {'forum':self._forum,'topic':self.get_topic(),
             'first_post':self.get_first_post(),
             'post_type':post_type,'preview':preview,
             'unpublished_attachments':self.request.user.attachment_set.filter(activated=False),
             'is_new_post':True,'topic_post':topic_post,
             'session_key':self.request.session.session_key}
                       )
        return context
        
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
    pk_url_kwarg = 'topic_id'
    def delete(self, request, *args, **kwargs):
        response = super(DeleteTopicView,self).delete(request,*args,**kwargs)
        self.object.forum.update_state_info()
        return response
    
    def get_success_url(self):
        return reverse_lazy("lbforum_forum",args=[self.object.forum.slug])

delete_topic = DeleteTopicView.as_view()

class DeletePostView(StaffuserRequiredMixin,DeleteView):
    model = Post
    pk_url_kwarg = 'post_id'
    def get(self, *args, **kwargs):
        return self.delete(*args, **kwargs)
    
    def delete(self, request, *args, **kwargs):
        response = super(DeletePostView,self).delete(request,*args,**kwargs)
        topic = self.object.topic
        topic.update_state_info()
        topic.forum.update_state_info()
        return response
    
    def get_success_url(self):
        return reverse_lazy("lbforum_topic",args=[self.object.topic.id])

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
    

class FileForumGroupRequiredMixin(ForumGroupRequiredMixin):
    def get_forum(self):
        try:
            #If we've already called get forum earlier just return the self._forum attribute
            return self._forum
        except AttributeError:
            pass
        try:
            self._forum = Forum.objects.get(slug=self.kwargs.get('forum_slug'))
            return self._forum
        except Forum.DoesNotExist:
            raise HttpResponseNotFound
    
class ForumFileListView(LoginRequiredMixin,FileForumGroupRequiredMixin,ListView):
    model = ForumFile
    template_name = 'lbforum/files.html'
    paginate_by = 20
    def get_queryset(self):
        return self.model.objects.filter(forum=self.get_forum())

    def get_context_data(self, **kwargs):
        context = super(ForumFileListView,self).get_context_data(**kwargs)
        context['forum'] = self.get_forum()
        return context
forum_files = ForumFileListView.as_view()
    
class ForumFileCreateView(LoginRequiredMixin,FileForumGroupRequiredMixin,CreateView):
    model = ForumFile
    template_name = 'lbforum/upload-file.html'
    form_class = ForumFileForm
    
    def get_success_url(self):
        return reverse_lazy('lbforum_forum_files',args=[self.get_forum().slug])
    
    def form_valid(self, form):
        obj = form.save(commit=False)
        user = self.request.user
        user_pk = user.pk
        obj.uploaded_by = user
        obj.forum = self.get_forum()
        obj.save()
        return super(ForumFileCreateView,self).form_valid(form)
    
forum_files_upload = ForumFileCreateView.as_view()

class ExamAidTopicListView(ForumView):
    model = Topic
    template_name = 'lbforum/exam-aid-topic-list.html'
        
    def get_queryset(self):
        return Topic.objects.filter(forum=self.get_forum())
    

class ExamAidTopicDetailView(LoginRequiredMixin,FileForumGroupRequiredMixin,TopicView):
    template_name = 'lbform/exam-aid-topic-detail.html'
    