import random
import string
import os
from datetime import datetime
import collections
import csv
from django.http import HttpResponse
from django.core.urlresolvers import reverse
from django.contrib.auth import login, logout, authenticate
from django.shortcuts import render_to_response, get_object_or_404, redirect
from django.template import RequestContext
from django.http import Http404
from django.db.models import Sum, Max, Q
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.forms.models import inlineformset_factory
from django.utils import timezone
import pytz
from taggit.models import Tag
from itertools import chain
import json
import zipfile
# Local imports.
from yaksh.models import get_model_class, Quiz, Question, QuestionPaper, QuestionSet, Course
from yaksh.models import Profile, Answer, AnswerPaper, User, TestCase, FileUpload,\
                        has_profile
from yaksh.forms import UserRegisterForm, UserLoginForm, QuizForm,\
                QuestionForm, RandomQuestionForm,\
                QuestionFilterForm, CourseForm, ProfileForm, UploadFileForm,\
                get_object_form, FileForm
from settings import URL_ROOT
from yaksh.models import AssignmentUpload
from file_utils import extract_files



def my_redirect(url):
    """An overridden redirect to deal with URL_ROOT-ing. See settings.py
    for details."""
    return redirect(URL_ROOT + url)


def my_render_to_response(template, context=None, **kwargs):
    """Overridden render_to_response.
    """
    if context is None:
        context = {'URL_ROOT': URL_ROOT}
    else:
        context['URL_ROOT'] = URL_ROOT
    return render_to_response(template, context, **kwargs)


def is_moderator(user):
    """Check if the user is having moderator rights"""
    if user.groups.filter(name='moderator').exists():
        return True


def add_to_group(users):
    """ add users to moderator group """
    group = Group.objects.get(name="moderator")
    for user in users:
        if not is_moderator(user):
            user.groups.add(group)


def index(request):
    """The start page.
    """
    user = request.user
    if user.is_authenticated():
        if user.groups.filter(name='moderator').count() > 0:
            return my_redirect('/exam/manage/')
        return my_redirect("/exam/quizzes/")

    return my_redirect("/exam/login/")


def user_register(request):
    """ Register a new user.
    Create a user and corresponding profile and store roll_number also."""

    user = request.user
    ci = RequestContext(request)
    if user.is_authenticated():
        return my_redirect("/exam/quizzes/")

    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            u_name, pwd = form.save()
            new_user = authenticate(username=u_name, password=pwd)
            login(request, new_user)
            return my_redirect("/exam/quizzes/")
        else:
            return my_render_to_response('yaksh/register.html', {'form': form},
                                         context_instance=ci)
    else:
        form = UserRegisterForm()
        return my_render_to_response('yaksh/register.html', {'form': form},
                                      context_instance=ci)


@login_required
def quizlist_user(request):
    """Show All Quizzes that is available to logged-in user."""
    user = request.user
    avail_quizzes = Quiz.objects.get_active_quizzes()
    user_answerpapers = AnswerPaper.objects.filter(user=user)
    courses = Course.objects.filter(active=True, is_trial=False)

    context = { 'quizzes': avail_quizzes,
                'user': user,
                'courses': courses,
                'quizzes_taken': user_answerpapers,
            }
    return my_render_to_response("yaksh/quizzes_user.html", context)


@login_required
def results_user(request):
    """Show list of Results of Quizzes that is taken by logged-in user."""
    user = request.user
    papers = AnswerPaper.objects.get_user_answerpapers(user)
    context = {'papers': papers}
    return my_render_to_response("yaksh/results_user.html", context)


@login_required
def add_question(request):
    """To add a new question in the database.
    Create a new question and store it."""
    user = request.user
    ci = RequestContext(request)

    if request.method == "POST" and 'save_question' in request.POST:
        question_form = QuestionForm(request.POST)
        form = FileForm(request.POST, request.FILES)
        if question_form.is_valid():
            new_question = question_form.save(commit=False)
            new_question.user = user
            new_question.save()
            files = request.FILES.getlist('file_field')
            if files:
                for file in files:
                    FileUpload.objects.get_or_create(question=new_question, file=file)
            return my_redirect("/exam/manage/addquestion/{0}".format(new_question.id))
        else:
            return my_render_to_response('yaksh/add_question.html',
                                         {'form': question_form,
                                          'upload_form': form},
                                         context_instance=ci)
    else:
        question_form = QuestionForm()
        form = FileForm()
        return my_render_to_response('yaksh/add_question.html',
                                     {'form': question_form,
                                      'upload_form': form},
                                     context_instance=ci)

@login_required
def edit_question(request, question_id=None):
    """To add a new question in the database.
    Create a new question and store it."""
    user = request.user
    ci = RequestContext(request)
    if not question_id:
        raise Http404('No Question Found')

    question_instance = Question.objects.get(id=question_id)
    if request.method == "POST" and 'delete_files' in request.POST:
        remove_files_id = request.POST.getlist('clear')
        if remove_files_id:
            files = FileUpload.objects.filter(id__in=remove_files_id)
            for file in files:
                file.remove()
    if request.method == "POST" and 'save_question' in request.POST:
        question_form = QuestionForm(request.POST, instance=question_instance)
        form = FileForm(request.POST, request.FILES)
        files = request.FILES.getlist('file_field')
        extract_files_id = request.POST.getlist('extract')
        if files:
            for file in files:
                FileUpload.objects.get_or_create(question=question_instance, file=file)
        if extract_files_id:
            files = FileUpload.objects.filter(id__in=extract_files_id)
            for file in files:
                file.set_extract_status()
        if question_form.is_valid():
            new_question = question_form.save(commit=False)
            test_case_type = question_form.cleaned_data.get('test_case_type')
            test_case_form_class = get_object_form(model=test_case_type, exclude_fields=['question'])
            test_case_model_class = get_model_class(test_case_type)
            TestCaseInlineFormSet = inlineformset_factory(Question, test_case_model_class, form=test_case_form_class, extra=1)
            test_case_formset = TestCaseInlineFormSet(request.POST, request.FILES, instance=new_question)
            if test_case_formset.is_valid():
                new_question.save()
                test_case_formset.save()
            return my_redirect("/exam/manage/addquestion/{0}".format(new_question.id))
        else:
            test_case_type = question_form.cleaned_data.get('test_case_type')
            test_case_form_class = get_object_form(model=test_case_type, exclude_fields=['question'])
            test_case_model_class = get_model_class(test_case_type)
            TestCaseInlineFormSet = inlineformset_factory(Question, test_case_model_class, form=test_case_form_class, extra=1)
            test_case_formset = TestCaseInlineFormSet(request.POST, request.FILES, instance=question_instance)
            uploaded_files = FileUpload.objects.filter(question_id=question_instance.id)
            return my_render_to_response('yaksh/add_question.html',
                                         {'form': question_form,
                                         'test_case_formset': test_case_formset,
                                         'question_id': question_id,
                                         'upload_form': form,
                                         'uploaded_files': uploaded_files},
                                         context_instance=ci)
    else:
        question_form = QuestionForm(instance=question_instance)
        form = FileForm()
        test_case_type = question_instance.test_case_type
        test_case_form_class = get_object_form(model=test_case_type, exclude_fields=['question'])
        test_case_model_class = get_model_class(test_case_type)
        TestCaseInlineFormSet = inlineformset_factory(Question, test_case_model_class, form=test_case_form_class, extra=1)
        test_case_formset = TestCaseInlineFormSet(instance=question_instance)
        uploaded_files = FileUpload.objects.filter(question_id=question_instance.id)
        return my_render_to_response('yaksh/add_question.html',
                                     {'form': question_form,
                                     'test_case_formset': test_case_formset,
                                     'question_id': question_id,
                                     'upload_form': form,
                                     'uploaded_files': uploaded_files},
                                     context_instance=ci)

@login_required
def add_quiz(request, course_id, quiz_id=None):
    """To add a new quiz in the database.
    Create a new quiz and store it."""
    user = request.user
    course = get_object_or_404(Course, pk=course_id)
    ci = RequestContext(request)
    if not is_moderator(user) or (user != course.creator and user not in course.teachers.all()):
        raise Http404('You are not allowed to view this course !')
    context = {}
    if request.method == "POST":
        if quiz_id is None:
            form = QuizForm(request.POST, user=user, course=course_id)
            if form.is_valid():
                form.save()
                return my_redirect(reverse('yaksh:design_questionpaper'))
            else:
                context["form"] = form
                return my_render_to_response('yaksh/add_quiz.html',
                                             context,
                                             context_instance=ci)
        else:
            quiz = Quiz.objects.get(id=quiz_id)
            form = QuizForm(request.POST, user=user, course=course_id,
                            instance=quiz)
            if form.is_valid():
                form.save()
                context["quiz_id"] = quiz_id
                return my_redirect("/exam/manage/")
    else:
        if quiz_id is None:
            form = QuizForm(course=course_id, user=user)
        else:
            quiz = Quiz.objects.get(id=quiz_id)
            form = QuizForm(user=user,course=course_id, instance=quiz)
            context["quiz_id"] = quiz_id
        context["form"] = form
        return my_render_to_response('yaksh/add_quiz.html',
                                     context,
                                     context_instance=ci)


@login_required
def show_all_questionpapers(request, questionpaper_id=None):
    user = request.user
    ci = RequestContext(request)
    if not user.is_authenticated() or not is_moderator(user):
        raise Http404('You are not allowed to view this page!')

    if questionpaper_id is None:
        qu_papers = QuestionPaper.objects.filter(is_trial=False)
        context = {'papers': qu_papers}
        return my_render_to_response('yaksh/showquestionpapers.html', context,
                                     context_instance=ci)
    else:
        qu_papers = QuestionPaper.objects.get(id=questionpaper_id)
        quiz = qu_papers.quiz
        fixed_questions = qu_papers.fixed_questions.all()
        random_questions = qu_papers.random_questions.all()
        context = {'quiz': quiz, 'fixed_questions': fixed_questions,
                   'random_questions': random_questions}
        return my_render_to_response('yaksh/editquestionpaper.html', context,
                                     context_instance=ci)


@login_required
def prof_manage(request):
    """Take credentials of the user with professor/moderator
rights/permissions and log in."""
    user = request.user
    ci = RequestContext(request)
    if user.is_authenticated() and is_moderator(user):
        question_papers = QuestionPaper.objects.filter(quiz__course__creator=user,
                                                       quiz__is_trial=False
                                                       )
        trial_paper = AnswerPaper.objects.filter(user=user,
                                                 question_paper__quiz__is_trial=True
                                                 )
        if request.method == "POST":
            delete_paper = request.POST.getlist('delete_paper')
            for answerpaper_id in delete_paper:
                answerpaper = AnswerPaper.objects.get(id=answerpaper_id)
                qpaper = answerpaper.question_paper
                if qpaper.quiz.course.is_trial == True:
                    qpaper.quiz.course.delete()
                else:
                    if qpaper.answerpaper_set.count() == 1:
                        qpaper.quiz.delete()
                    else:
                        answerpaper.delete()
        users_per_paper = []
        for paper in question_papers:
            answer_papers = AnswerPaper.objects.filter(question_paper=paper)
            users_passed = AnswerPaper.objects.filter(question_paper=paper,
                    passed=True).count()
            users_failed = AnswerPaper.objects.filter(question_paper=paper,
                    passed=False).count()
            temp = paper, answer_papers, users_passed, users_failed
            users_per_paper.append(temp)
        context = {'user': user, 'users_per_paper': users_per_paper,
                   'trial_paper': trial_paper
                   }
        return my_render_to_response('manage.html', context, context_instance=ci)
    return my_redirect('/exam/login/')


def user_login(request):
    """Take the credentials of the user and log the user in."""

    user = request.user
    ci = RequestContext(request)
    if user.is_authenticated():
        if user.groups.filter(name='moderator').count() > 0:
            return my_redirect('/exam/manage/')
        return my_redirect("/exam/quizzes/")

    if request.method == "POST":
        form = UserLoginForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data
            login(request, user)
            if user.groups.filter(name='moderator').count() > 0:
                return my_redirect('/exam/manage/')
            return my_redirect('/exam/login/')
        else:
            context = {"form": form}
            return my_render_to_response('yaksh/login.html', context,
                                         context_instance=ci)
    else:
        form = UserLoginForm()
        context = {"form": form}
        return my_render_to_response('yaksh/login.html', context,
                                     context_instance=ci)



@login_required
def start(request, questionpaper_id=None, attempt_num=None):
    """Check the user cedentials and if any quiz is available,
    start the exam."""
    user = request.user
    ci = RequestContext(request)
    # check conditions
    try:
        quest_paper = QuestionPaper.objects.get(id=questionpaper_id)
    except QuestionPaper.DoesNotExist:
        msg = 'Quiz not found, please contact your '\
            'instructor/administrator. Please login again thereafter.'
        return complete(request, msg, attempt_num, questionpaper_id=None)
    if not quest_paper.quiz.course.is_enrolled(user):
        raise Http404('You are not allowed to view this page!')
    # prerequisite check and passing criteria
    if quest_paper.quiz.is_expired():
        if is_moderator(user):
            return redirect("/exam/manage")
        return redirect("/exam/quizzes")
    if quest_paper.quiz.has_prerequisite() and not quest_paper.is_prerequisite_passed(user):
        if is_moderator(user):
            return redirect("/exam/manage")
        return redirect("/exam/quizzes")
    # if any previous attempt
    last_attempt = AnswerPaper.objects.get_user_last_attempt(
            questionpaper=quest_paper, user=user)
    if last_attempt and last_attempt.is_attempt_inprogress():
        return show_question(request, last_attempt.current_question(), last_attempt)
    # allowed to start
    if not quest_paper.can_attempt_now(user):
        if is_moderator(user):
            return redirect("/exam/manage")
        return redirect("/exam/quizzes")
    if attempt_num is None:
        attempt_number = 1 if not last_attempt else last_attempt.attempt_number +1
        context = {'user': user, 'questionpaper': quest_paper,
                   'attempt_num': attempt_number}
        if is_moderator(user):
            context["user"] = "moderator"
        return my_render_to_response('yaksh/intro.html', context,
                                     context_instance=ci)
    else:
        ip = request.META['REMOTE_ADDR']
        if not hasattr(user, 'profile'):
            msg = 'You do not have a profile and cannot take the quiz!'
            raise Http404(msg)
        new_paper = quest_paper.make_answerpaper(user, ip, attempt_num)
        # Make user directory.
        user_dir = new_paper.user.profile.get_user_dir()
        return show_question(request, new_paper.current_question(), new_paper)


@login_required
def show_question(request, question, paper, error_message=None):
    """Show a question if possible."""
    user = request.user
    if not question:
        msg = 'Congratulations!  You have successfully completed the quiz.'
        return complete(request, msg, paper.attempt_number, paper.question_paper.id)
    if not paper.question_paper.quiz.active:
        reason = 'The quiz has been deactivated!'
        return complete(request, reason, paper.attempt_number, paper.question_paper.id)
    if paper.time_left() <= 0:
        reason='Your time is up!'
        return complete(request, reason, paper.attempt_number, paper.question_paper.id)
    test_cases = question.get_test_cases()
    files = FileUpload.objects.filter(question_id=question.id)
    context = {'question': question, 'paper': paper, 'error_message': error_message,
                'test_cases': test_cases, 'files': files,
                'last_attempt': question.snippet.encode('unicode-escape')}
    answers = paper.get_previous_answers(question)
    if answers:
        last_attempt = answers[0].answer
        context['last_attempt'] = last_attempt.encode('unicode-escape')
    ci = RequestContext(request)
    return my_render_to_response('yaksh/question.html', context,
                                 context_instance=ci)


@login_required
def skip(request, q_id, next_q=None, attempt_num=None, questionpaper_id=None):
    user = request.user
    paper = get_object_or_404(AnswerPaper, user=request.user, attempt_number=attempt_num,
            question_paper=questionpaper_id)
    question = get_object_or_404(Question, pk=q_id)
    if question in paper.questions_answered.all():
        next_q = paper.next_question(q_id)
        return show_question(request, next_q, paper)

    if request.method == 'POST' and question.type == 'code':
        user_code = request.POST.get('answer')
        new_answer = Answer(question=question, answer=user_code,
                            correct=False, skipped=True)
        new_answer.save()
        paper.answers.add(new_answer)
    if next_q is not None:
        next_q = get_object_or_404(Question, pk=next_q)
        if next_q not in paper.questions_unanswered.all():
            return show_question(request, question,  paper)
    else:
        next_q = paper.next_question(q_id)
    return show_question(request, next_q, paper)


@login_required
def check(request, q_id, attempt_num=None, questionpaper_id=None):
    """Checks the answers of the user for particular question"""
    user = request.user
    paper = get_object_or_404(AnswerPaper, user=request.user, attempt_number=attempt_num,
            question_paper=questionpaper_id)
    question = get_object_or_404(Question, pk=q_id)
    if question in paper.questions_answered.all():
        next_q = paper.next_question(q_id)
        return show_question(request, next_q, paper)

    if request.method == 'POST':
        snippet_code = request.POST.get('snippet')
        # Add the answer submitted, regardless of it being correct or not.
        if question.type == 'mcq':
            user_answer = request.POST.get('answer')
        elif question.type == 'mcc':
            user_answer = request.POST.getlist('answer')
        elif question.type == 'upload':
            assign = AssignmentUpload()
            assign.user = user.profile
            assign.assignmentQuestion = question
            # if time-up at upload question then the form is submitted without
            # validation
            if 'assignment' in request.FILES:
                assign.assignmentFile = request.FILES['assignment']
            assign.save()
            user_answer = 'ASSIGNMENT UPLOADED'
            next_q = paper.completed_question(question.id)
            return show_question(request, next_q, paper)
        else:
            user_code = request.POST.get('answer')
            user_answer = snippet_code + "\n" + user_code if snippet_code else user_code
        new_answer = Answer(question=question, answer=user_answer,
                            correct=False)
        new_answer.save()
        paper.answers.add(new_answer)
        if not user_answer:
            msg = "Please submit a valid option or code"
            return show_question(request, question, paper, msg)
        # If we were not skipped, we were asked to check.  For any non-mcq
        # questions, we obtain the results via XML-RPC with the code executed
        # safely in a separate process (the code_server.py) running as nobody.
        json_data = question.consolidate_answer_data(user_answer) \
                        if question.type == 'code' else None
        correct, result = paper.validate_answer(user_answer, question, json_data)
        if correct:
            new_answer.correct = correct
            new_answer.marks = question.points
            new_answer.error = result.get('error')
        else:
            new_answer.error = result.get('error')
        new_answer.save()
        paper.update_marks('inprogress')
        paper.set_end_time(timezone.now())
        if not result.get('success'):  # Should only happen for non-mcq questions.
            new_answer.answer = user_code
            new_answer.save()
            return show_question(request, question, paper, result.get('error'))
        else:
            next_q = paper.completed_question(question.id)
            return show_question(request, next_q, paper)
    else:
        return show_question(request, question, paper)



def quit(request, reason=None, attempt_num=None, questionpaper_id=None):
    """Show the quit page when the user logs out."""
    paper = AnswerPaper.objects.get(user=request.user,
                                    attempt_number=attempt_num,
                                    question_paper=questionpaper_id)
    context = {'paper': paper, 'message': reason}
    return my_render_to_response('yaksh/quit.html', context,
                                 context_instance=RequestContext(request))


@login_required
def complete(request, reason=None, attempt_num=None, questionpaper_id=None):
    """Show a page to inform user that the quiz has been compeleted."""
    user = request.user
    if questionpaper_id is None:
        logout(request)
        message = reason or "You are successfully logged out."
        context = {'message': message}
        return my_render_to_response('yaksh/complete.html', context)
    else:
        q_paper = QuestionPaper.objects.get(id=questionpaper_id)
        paper = AnswerPaper.objects.get(user=user, question_paper=q_paper,
                attempt_number=attempt_num)
        paper.update_marks()
        paper.set_end_time(timezone.now())
        if paper.percent == 100:
            message = "You answered all the questions correctly.\
                       You have been logged out successfully,\
                       Thank You !"
        else:
            message = reason or "You are successfully logged out"
        context = {'message':  message, 'paper': paper}
        return my_render_to_response('yaksh/complete.html', context)


@login_required
def add_course(request):
    user = request.user
    ci = RequestContext(request)
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            new_course = form.save(commit=False)
            new_course.creator = user
            new_course.save()
            return my_render_to_response('manage.html', {'course': new_course})
        else:
            return my_render_to_response('yaksh/add_course.html',
                                         {'form': form},
                                         context_instance=ci)
    else:
        form = CourseForm()
        return my_render_to_response('yaksh/add_course.html', {'form': form},
                                     context_instance=ci)


@login_required
def enroll_request(request, course_id):
    user = request.user
    ci = RequestContext(request)
    course = get_object_or_404(Course, pk=course_id)
    course.request(user)
    if is_moderator(user):
        return my_redirect('/exam/manage/')
    else:
        return my_redirect('/exam/quizzes/')


@login_required
def self_enroll(request, course_id):
    user = request.user
    ci = RequestContext(request)
    course = get_object_or_404(Course, pk=course_id)
    if course.is_self_enroll():
        was_rejected = False
        course.enroll(was_rejected, user)
    if is_moderator(user):
        return my_redirect('/exam/manage/')
    else:
        return my_redirect('/exam/quizzes/')


@login_required
def courses(request):
    user = request.user
    ci = RequestContext(request)
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')
    courses = Course.objects.filter(creator=user, is_trial=False)
    allotted_courses = Course.objects.filter(teachers=user, is_trial=False)
    
    context = {'courses': courses, "allotted_courses": allotted_courses}
    return my_render_to_response('yaksh/courses.html', context,
                                 context_instance=ci)


@login_required
def course_detail(request, course_id):
    user = request.user
    ci = RequestContext(request)

    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')

    course = get_object_or_404(Course, pk=course_id)
    if not course.is_creator(user) and not course.is_teacher(user):
        raise Http404('This course does not belong to you')

    return my_render_to_response('yaksh/course_detail.html', {'course': course},
                                context_instance=ci)


@login_required
def enroll(request, course_id, user_id=None, was_rejected=False):
    user = request.user
    ci = RequestContext(request)
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')

    course = get_object_or_404(Course, pk=course_id)
    if not course.is_creator(user) and not course.is_teacher(user):
        raise Http404('This course does not belong to you')

    if request.method == 'POST':
        enroll_ids = request.POST.getlist('check')
    else:
        enroll_ids = user_id
    if not enroll_ids:
        return my_render_to_response('yaksh/course_detail.html', {'course': course},
                                            context_instance=ci)
    users = User.objects.filter(id__in=enroll_ids)
    course.enroll(was_rejected, *users)
    return course_detail(request, course_id)


@login_required
def reject(request, course_id, user_id=None, was_enrolled=False):
    user = request.user
    ci = RequestContext(request)
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')

    course = get_object_or_404(Course, pk=course_id)
    if not course.is_creator(user) and not course.is_teacher(user):
        raise Http404('This course does not belong to you')

    if request.method == 'POST':
        reject_ids = request.POST.getlist('check')
    else:
        reject_ids = user_id
    if not reject_ids:
        return my_render_to_response('yaksh/course_detail.html', {'course': course},
                                            context_instance=ci)
    users = User.objects.filter(id__in=reject_ids)
    course.reject(was_enrolled, *users)
    return course_detail(request, course_id)


@login_required
def toggle_course_status(request, course_id):
    user = request.user
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')

    course = get_object_or_404(Course, pk=course_id)
    if not course.is_creator(user) and not course.is_teacher(user):
        raise Http404('This course does not belong to you')

    if course.active:
        course.deactivate()
    else:
        course.activate()
    course.save()
    return course_detail(request, course_id)


@login_required
def show_statistics(request, questionpaper_id, attempt_number=None):
    user = request.user
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page')
    attempt_numbers = AnswerPaper.objects.get_attempt_numbers(questionpaper_id)
    quiz = get_object_or_404(QuestionPaper, pk=questionpaper_id).quiz
    if attempt_number is None:
        context = {'quiz': quiz, 'attempts': attempt_numbers,
                   'questionpaper_id': questionpaper_id}
        return my_render_to_response('yaksh/statistics_question.html', context,
                                     context_instance=RequestContext(request))
    total_attempt = AnswerPaper.objects.get_count(questionpaper_id,
                                                  attempt_number)
    if not AnswerPaper.objects.has_attempt(questionpaper_id, attempt_number):
        return my_redirect('/exam/manage/')
    question_stats = AnswerPaper.objects.get_question_statistics(
        questionpaper_id, attempt_number
    )
    context = {'question_stats': question_stats, 'quiz': quiz,
               'questionpaper_id': questionpaper_id,
               'attempts': attempt_numbers, 'total': total_attempt}
    return my_render_to_response('yaksh/statistics_question.html', context,
                                 context_instance=RequestContext(request))


@login_required
def monitor(request, questionpaper_id=None):
    """Monitor the progress of the papers taken so far."""

    user = request.user
    ci = RequestContext(request)
    if not user.is_authenticated() or not is_moderator(user):
        raise Http404('You are not allowed to view this page!')

    if questionpaper_id is None:
        q_paper = QuestionPaper.objects.filter(Q(quiz__course__creator=user) |
                                               Q(quiz__course__teachers=user),
                                               quiz__is_trial=False
                                               ).distinct()
        context = {'papers': [],
                   'quiz': None,
                   'quizzes': q_paper}
        return my_render_to_response('yaksh/monitor.html', context,
                                     context_instance=ci)
    # quiz_id is not None.
    try:
        q_paper = QuestionPaper.objects.filter(Q(quiz__course__creator=user) |
                                               Q(quiz__course__teachers=user),
                                               quiz__is_trial=False,
                                               id=questionpaper_id).distinct()
    except QuestionPaper.DoesNotExist:
        papers = []
        q_paper = None
        latest_attempts = []
    else:
        latest_attempts = []
        papers = AnswerPaper.objects.filter(question_paper=q_paper).order_by(
                'user__profile__roll_number')
        users = papers.values_list('user').distinct()
        for auser in users:
            last_attempt = papers.filter(user__in=auser).aggregate(
                    last_attempt_num=Max('attempt_number'))
            latest_attempts.append(papers.get(user__in=auser,
                attempt_number=last_attempt['last_attempt_num']))
    context = {'papers': papers, 'quiz': q_paper, 'quizzes': None,
            'latest_attempts': latest_attempts,}
    return my_render_to_response('yaksh/monitor.html', context,
                                 context_instance=ci)


@csrf_exempt
def ajax_questions_filter(request):
    """Ajax call made when filtering displayed questions."""

    user = request.user
    filter_dict = {"user_id": user.id}
    question_type = request.POST.get('question_type')
    marks = request.POST.get('marks')
    language = request.POST.get('language')

    if question_type != "select":
        filter_dict['type'] = str(question_type)

    if marks != "select":
        filter_dict['points'] = marks

    if language != "select":
        filter_dict['language'] = str(language)

    questions = list(Question.objects.filter(**filter_dict))

    return my_render_to_response('yaksh/ajax_question_filter.html',
                                  {'questions': questions})


@login_required
def show_all_questions(request):
    """Show a list of all the questions currently in the database."""

    user = request.user
    ci = RequestContext(request)
    context = {}
    if not is_moderator(user):
        raise Http404("You are not allowed to view this page !")

    if request.method == 'POST':
        if request.POST.get('delete') == 'delete':
            data = request.POST.getlist('question')
            if data is not None:
                questions = Question.objects.filter(id__in=data, user_id=user.id)
                files = FileUpload.objects.filter(question_id__in=questions)
                if files:
                    for file in files:
                        file.remove()
                questions.delete()

        if request.POST.get('upload') == 'upload':
            form = UploadFileForm(request.POST, request.FILES)
            if form.is_valid():
                questions_file = request.FILES['file']
                file_name = questions_file.name.split('.')
                if file_name[-1] == "zip":
                    ques = Question()
                    extract_files(questions_file)
                    ques.read_json("questions_dump.json", user)
                else:
                    message = "Please Upload a ZIP file"
                    context['message'] = message

        if request.POST.get('download') == 'download':
            question_ids = request.POST.getlist('question')
            if question_ids:
                question = Question()
                zip_file = question.dump_questions(question_ids, user)
                response = HttpResponse(content_type='application/zip')
                response['Content-Disposition'] = '''attachment;\
                                          filename={0}_questions.zip'''.format(user)
                zip_file.seek(0)
                response.write(zip_file.read())
                return response
            else:
                context['msg'] = "Please select atleast one question to download"

        if request.POST.get('test') == 'test':
            question_ids = request.POST.getlist("question")
            if question_ids:
                trial_paper = test_mode(user, False, question_ids, None)
                trial_paper.update_total_marks()
                trial_paper.save()
                return my_redirect("/exam/start/1/{0}".format(trial_paper.id))
            else:
                context["msg"] = "Please select atleast one question to test"

    questions = Question.objects.filter(user_id=user.id)
    form = QuestionFilterForm(user=user)
    upload_form = UploadFileForm()
    context['papers'] = []
    context['question'] = None
    context['questions'] = questions
    context['form'] = form
    context['upload_form'] = upload_form
    return my_render_to_response('yaksh/showquestions.html', context,
                                 context_instance=ci)


@login_required
def user_data(request, user_id, questionpaper_id=None):
    """Render user data."""
    current_user = request.user
    if not current_user.is_authenticated() or not is_moderator(current_user):
        raise Http404('You are not allowed to view this page!')
    user = User.objects.get(id=user_id)
    data = AnswerPaper.objects.get_user_data(user, questionpaper_id)

    context = {'data': data}
    return my_render_to_response('yaksh/user_data.html', context,
                                 context_instance=RequestContext(request))


@login_required
def download_csv(request, questionpaper_id):
    user = request.user
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page!')
    quiz = Quiz.objects.get(questionpaper=questionpaper_id)

    if not quiz.course.is_creator(user) and not quiz.course.is_teacher(user):
        raise Http404('The question paper does not belong to your course')
    papers = AnswerPaper.objects.get_latest_attempts(questionpaper_id)
    if not papers:
        return monitor(request, questionpaper_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="{0}.csv"'.format(
                                      (quiz.description).replace('.', ''))
    writer = csv.writer(response)
    header = [
                'name',
                'username',
                'roll_number',
                'institute',
                'marks_obtained',
                'total_marks',
                'percentage',
                'questions',
                'questions_answered',
                'status'
    ]
    writer.writerow(header)
    for paper in papers:
        row = [
                '{0} {1}'.format(paper.user.first_name, paper.user.last_name),
                paper.user.username,
                paper.user.profile.roll_number,
                paper.user.profile.institute,
                paper.marks_obtained,
                paper.question_paper.total_marks,
                paper.percent,
                paper.questions.all(),
                paper.questions_answered.all(),
                paper.status
        ]
        writer.writerow(row)
    return response


@login_required
def grade_user(request, quiz_id=None, user_id=None, attempt_number=None):
    """Present an interface with which we can easily grade a user's papers
    and update all their marks and also give comments for each paper.
    """
    current_user = request.user
    ci = RequestContext(request)
    if not current_user.is_authenticated() or not is_moderator(current_user):
        raise Http404('You are not allowed to view this page!')
    course_details = Course.objects.filter(Q(creator=current_user) |
                                           Q(teachers=current_user),
                                           is_trial=False).distinct()
    context = {"course_details": course_details}
    if quiz_id is not None:
        questionpaper_id = QuestionPaper.objects.filter(quiz_id=quiz_id)\
                                                        .values("id")
        user_details = AnswerPaper.objects\
                                  .get_users_for_questionpaper(questionpaper_id)
        context = {"users": user_details, "quiz_id": quiz_id}
        if user_id is not None:

            attempts = AnswerPaper.objects.get_user_all_attempts\
                                            (questionpaper_id, user_id)
            try:
                if attempt_number is None:
                    attempt_number = attempts[0].attempt_number
            except IndexError:
                raise Http404('No attempts for paper')

            user = User.objects.get(id=user_id)
            data = AnswerPaper.objects.get_user_data(user, questionpaper_id,
                                                     attempt_number
                                                     )

            context = {'data': data, "quiz_id": quiz_id, "users": user_details,
                    "attempts": attempts, "user_id": user_id
                    }
    if request.method == "POST":
        papers = data['papers']
        for paper in papers:
            for question, answers in paper.get_question_answers().iteritems():
                marks = float(request.POST.get('q%d_marks' % question.id, 0))
                answers = answers[-1]
                answers.set_marks(marks)
                answers.save()
            paper.update_marks()
            paper.comments = request.POST.get(
                'comments_%d' % paper.question_paper.id, 'No comments')
            paper.save()


    return my_render_to_response('yaksh/grade_user.html',
                                context, context_instance=ci
                                )


@csrf_exempt
def ajax_questionpaper(request, query):
    """
        During question paper creation, ajax call made to get question details.
    """

    user = request.user
    if query == 'marks':
        question_type = request.POST.get('question_type')
        questions = Question.objects.filter(type=question_type, user=user)
        marks = questions.values_list('points').distinct()
        return my_render_to_response('yaksh/ajax_marks.html', {'marks': marks})
    elif query == 'questions':
        question_type = request.POST['question_type']
        marks_selected = request.POST['marks']
        fixed_questions = request.POST.getlist('fixed_list[]')
        fixed_question_list = ",".join(fixed_questions).split(',')
        random_questions = request.POST.getlist('random_list[]')
        random_question_list = ",".join(random_questions).split(',')
        question_list = fixed_question_list + random_question_list
        questions = list(Question.objects.filter(type=question_type,
                                            points=marks_selected, user=user))
        questions = [question for question in questions \
                if not str(question.id) in question_list]
        return my_render_to_response('yaksh/ajax_questions.html',
                              {'questions': questions})


@login_required
def design_questionpaper(request):
    user = request.user
    ci = RequestContext(request)

    if not is_moderator(user):
        raise Http404('You are not allowed to view this page!')

    if request.method == 'POST':
        fixed_questions = request.POST.getlist('fixed')
        random_questions = request.POST.getlist('random')
        random_number = request.POST.getlist('number')
        is_shuffle = request.POST.get('shuffle_questions', False)
        if is_shuffle == 'on':
            is_shuffle = True

        question_paper = QuestionPaper(shuffle_questions=is_shuffle)
        quiz = Quiz.objects.order_by("-id")[0]
        tot_marks = 0
        question_paper.quiz = quiz
        question_paper.total_marks = tot_marks
        question_paper.save()
        if fixed_questions:
            fixed_questions_ids = ",".join(fixed_questions)
            fixed_questions_ids_list = fixed_questions_ids.split(',')
            for question_id in fixed_questions_ids_list:
                question_paper.fixed_questions.add(question_id)
        if random_questions:
            for random_question, num in zip(random_questions, random_number):
                qid = random_question.split(',')[0]
                question = Question.objects.get(id=int(qid))
                marks = question.points
                question_set = QuestionSet(marks=marks, num_questions=num)
                question_set.save()
                for question_id in random_question.split(','):
                    question_set.questions.add(question_id)
                    question_paper.random_questions.add(question_set)
        question_paper.update_total_marks()
        question_paper.save()
        return my_redirect('/exam/manage/courses')
    else:
        form = RandomQuestionForm()
        context = {'form': form, 'questionpaper':True}
        return my_render_to_response('yaksh/design_questionpaper.html',
                                     context, context_instance=ci)

@login_required
def view_profile(request):
    """ view moderators and users profile """
    user = request.user
    ci = RequestContext(request)

    context = {}
    if has_profile(user):
        return my_render_to_response('yaksh/view_profile.html', {'user':user})
    else:
        form = ProfileForm(user=user)
        msg = True
        context['form'] = form
        context['msg'] = msg
        return my_render_to_response('yaksh/editprofile.html', context,
                                    context_instance=ci)


@login_required
def edit_profile(request):
    """ edit profile details facility for moderator and students """

    context = {}
    user = request.user
    ci = RequestContext(request)

    if has_profile(user):
        profile = Profile.objects.get(user_id=user.id)
    else:
        profile = None

    if request.method == 'POST':
        form = ProfileForm(request.POST, user=user, instance=profile)
        if form.is_valid():
            form_data = form.save(commit=False)
            form_data.user = user
            form_data.user.first_name = request.POST['first_name']
            form_data.user.last_name = request.POST['last_name']
            form_data.user.save()
            form_data.save()
            return my_render_to_response('yaksh/profile_updated.html',
                                        context_instance=ci)
        else:
            context['form'] = form
            return my_render_to_response('yaksh/editprofile.html', context,
                                        context_instance=ci)
    else:
        form = ProfileForm(user=user, instance=profile)
        context['form'] = form
        return my_render_to_response('yaksh/editprofile.html', context,
                                    context_instance=ci)


@login_required
def search_teacher(request, course_id):
    """ search teachers for the course """
    user = request.user
    ci = RequestContext(request)

    if not is_moderator(user):
        raise Http404('You are not allowed to view this page!')

    context = {}
    course = get_object_or_404(Course, pk=course_id)
    context['course'] = course

    if user != course.creator and user not in course.teachers.all():
       raise Http404('You are not allowed to view this page!')

    if request.method == 'POST':
        u_name = request.POST.get('uname')
        if not len(u_name) == 0:
            teachers = User.objects.filter(Q(username__icontains=u_name)|
                Q(first_name__icontains=u_name)|Q(last_name__icontains=u_name)|
                Q(email__icontains=u_name)).exclude(Q(id=user.id)|Q(is_superuser=1)|
                                                    Q(id=course.creator.id))
            context['success'] = True
            context['teachers'] = teachers
                                        
    return my_render_to_response('yaksh/addteacher.html', context,
                                 context_instance=ci)


@login_required
def add_teacher(request, course_id):
    """ add teachers to the course """

    user = request.user
    ci = RequestContext(request)

    if not is_moderator(user):
        raise Http404('You are not allowed to view this page!')

    context = {}
    course = get_object_or_404(Course, pk=course_id)
    if user == course.creator or user in course.teachers.all():
        context['course'] = course
    else:
        raise Http404('You are not allowed to view this page!')

    if request.method == 'POST':
        teacher_ids = request.POST.getlist('check')
        teachers = User.objects.filter(id__in=teacher_ids)
        add_to_group(teachers)
        course.add_teachers(*teachers)
        context['status'] = True
        context['teachers_added'] = teachers
        
    return my_render_to_response('yaksh/addteacher.html', context,
                                    context_instance=ci)


@login_required
def remove_teachers(request, course_id):
    """  remove user from a course """
 
    user = request.user
    course = get_object_or_404(Course, pk=course_id)
    if not is_moderator(user) and (user != course.creator and user not in course.teachers.all()):
        raise Http404('You are not allowed to view this page!')

    if request.method == "POST":
        teacher_ids = request.POST.getlist('remove')
        teachers = User.objects.filter(id__in=teacher_ids)
        course.remove_teachers(*teachers)
    return my_redirect('/exam/manage/courses')


def test_mode(user, godmode=False, questions_list=None, quiz_id=None):
    """creates a trial question paper for the moderators"""

    if questions_list is not None:
        trial_course = Course.objects.create_trial_course(user)
        trial_quiz = Quiz.objects.create_trial_quiz(trial_course, user)
        trial_questionpaper = QuestionPaper.objects\
                                           .create_trial_paper_to_test_questions\
                                            (trial_quiz, questions_list)
    else:
        trial_quiz = Quiz.objects.create_trial_from_quiz(quiz_id, user, godmode)
        trial_questionpaper = QuestionPaper.objects\
                                           .create_trial_paper_to_test_quiz\
                                            (trial_quiz, quiz_id)
    return trial_questionpaper


@login_required
def test_quiz(request, mode, quiz_id):
    """creates a trial quiz for the moderators"""
    godmode = True if mode == "godmode" else False
    current_user = request.user
    quiz = Quiz.objects.get(id=quiz_id)
    if (quiz.is_expired() or not quiz.active) and not godmode:
        return my_redirect('/exam/manage')

    trial_questionpaper = test_mode(current_user, godmode, None, quiz_id)
    return my_redirect("/exam/start/{0}".format(trial_questionpaper.id))


@login_required
def view_answerpaper(request, questionpaper_id):
    user = request.user
    quiz = get_object_or_404(QuestionPaper, pk=questionpaper_id).quiz
    if quiz.view_answerpaper and user in quiz.course.students.all():
        data = AnswerPaper.objects.get_user_data(user, questionpaper_id)
        context = {'data': data, 'quiz': quiz}
        return my_render_to_response('yaksh/view_answerpaper.html', context)
    else:
        return my_redirect('/exam/quizzes/')


@login_required
def create_demo_course(request):
    """ creates a demo course for user """
    user = request.user
    ci = RequestContext(request)
    if not is_moderator(user):
        raise("You are not allowed to view this page")
    demo_course = Course()
    success = demo_course.create_demo(user)
    if success:
        msg = "Created Demo course successfully"
    else:
        msg = "Demo course already created"
    context = {'msg': msg}
    return my_render_to_response('manage.html', context, context_instance=ci)


@login_required
def grader(request, extra_context=None):
    user = request.user
    if not is_moderator(user):
        raise Http404('You are not allowed to view this page!')
    courses = Course.objects.filter(is_trial=False)
    user_courses = list(courses.filter(creator=user)) + list(courses.filter(teachers=user))
    context = {'courses': user_courses}
    if extra_context:
        context.update(extra_context)
    return my_render_to_response('yaksh/regrade.html', context)


@login_required
def regrade(request, course_id, question_id=None, answerpaper_id=None, questionpaper_id=None):
    user = request.user
    course = get_object_or_404(Course, pk=course_id)
    if not is_moderator(user) or (user != course.creator and user not in course.teachers.all()):
        raise Http404('You are not allowed to view this page!')
    details = []
    if answerpaper_id is not None and question_id is None:
        answerpaper = get_object_or_404(AnswerPaper, pk=answerpaper_id)
        for question in answerpaper.questions.all():
            details.append(answerpaper.regrade(question.id))
    if questionpaper_id is not None and question_id is not None:
        answerpapers = AnswerPaper.objects.filter(questions=question_id,
                question_paper_id=questionpaper_id)
        for answerpaper in answerpapers:
            details.append(answerpaper.regrade(question_id))
    if answerpaper_id is not None and question_id is not None:
        answerpaper = get_object_or_404(AnswerPaper, pk=answerpaper_id)
        details.append(answerpaper.regrade(question_id))
    return grader(request, extra_context={'details': details})
