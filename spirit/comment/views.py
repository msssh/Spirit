# -*- coding: utf-8 -*-

from __future__ import unicode_literals

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import Http404
from django.conf import settings

from djconfig import config

from ..core.utils.ratelimit.decorators import ratelimit
from ..core.utils.decorators import moderator_required
from ..core.utils import markdown, paginator, render_form_errors, json_response
from ..topic.models import Topic
from .models import Comment
from .forms import CommentForm, CommentMoveForm, CommentImageForm
from .utils import comment_posted, post_comment_update, pre_comment_update


@login_required
@ratelimit(rate=settings.ST_RATELIMIT_FOR_PUBLISH)
def publish(request, topic_id, pk=None):
    user = request.user
    topic = get_object_or_404(
        Topic.objects.opened().unremoved()._access(user=request.user).can_comment(user=request.user),
        pk=topic_id
    )

    if request.method == 'POST':
        form = CommentForm(user=user, topic=topic, data=request.POST)

        if not request.is_limited() and form.is_valid():
            if not user.st.update_post_hash(form.get_comment_hash()):
                # Hashed comment may have not been saved yet
                return redirect(
                    request.POST.get('next', None) or
                    Comment.get_last_for_topic(topic_id)
                           .get_absolute_url())

            comment = form.save()
            comment_posted(comment=comment, mentions=form.mentions)
            return redirect(request.POST.get('next', comment.get_absolute_url()))
    else:
        initial = None

        if pk:  # todo: move to form
            comment = get_object_or_404(Comment.objects.for_access(user=user), pk=pk)
            quote = markdown.quotify(comment.comment, comment.user.username)
            initial = {'comment': quote}

        form = CommentForm(user=user, initial=initial)

    context = {
        'form': form,
        'topic': topic}

    return render(request, 'spirit/comment/publish.html', context)


@login_required
def update(request, pk):
    user = request.user
    comment = Comment.objects.for_update_or_404(pk, request.user)

    if request.method == 'POST':
        form = CommentForm(user=user, data=request.POST, instance=comment)

        if form.is_valid():
            pre_comment_update(comment=Comment.objects.get(pk=comment.pk))
            comment = form.save()
            post_comment_update(comment=comment)
            return redirect(request.POST.get('next', comment.get_absolute_url()))
    else:
        form = CommentForm(user=user, instance=comment)

    context = {'form': form, }

    return render(request, 'spirit/comment/update.html', context)


@moderator_required
def delete(request, pk, remove=True):
    comment = get_object_or_404(Comment, pk=pk)

    if request.method == 'POST':
        Comment.objects\
            .filter(pk=pk)\
            .update(is_removed=remove)

        return redirect(comment.get_absolute_url())

    context = {'comment': comment, }

    return render(request, 'spirit/comment/moderate.html', context)


@require_POST
@moderator_required
def move(request, topic_id):
    topic = get_object_or_404(Topic, pk=topic_id)
    form = CommentMoveForm(topic=topic, data=request.POST)

    if form.is_valid():
        comments = form.save()

        for comment in comments:
            comment_posted(comment=comment, mentions=None)
            topic.decrease_comment_count()
    else:
        messages.error(request, render_form_errors(form))

    return redirect(request.POST.get('next', topic.get_absolute_url()))


def find(request, pk):
    comment = get_object_or_404(Comment.objects.can_access(request.user), pk=pk)
    comment_number = Comment.objects.filter(topic=comment.topic, date__lte=comment.date).count()
    url = paginator.get_url(comment.topic.get_absolute_url(),
                            comment_number,
                            config.comments_per_page,
                            'page')
    return redirect(url)


@require_POST
@login_required
def image_upload_ajax(request):
    if not request.is_ajax():
        return Http404()

    form = CommentImageForm(user=request.user, data=request.POST, files=request.FILES)

    if form.is_valid():
        image = form.save()
        return json_response({'url': image.url, })

    return json_response({'error': dict(form.errors.items()), })
