# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.http import Http404

from core.models import (Category, Article, Source, BaseUserProfile,
                              BookmarkArticle, ArtilcleLike, HashTag, Menu, Notification, Devices,
                              SocialAccount, Category, CategoryAssociation,
                              TrendingArticle, Domain, Advertisement, DailyDigest,
                              Campaign, AdGroup, AdType)

from rest_framework.authtoken.models import Token

from rest_framework.views import APIView

from .serializers import (CategorySerializer, ArticleSerializer, UserSerializer,
                          SourceSerializer, LoginUserSerializer, BaseUserProfileSerializer,
                          BookmarkArticleSerializer, ArtilcleLikeSerializer, HashTagSerializer,
                          MenuSerializer, NotificationSerializer, TrendingArticleSerializer,
                          ArticleCreateUpdateSerializer, AdvertisementSerializer,
                          CampaignSerializer, AdGroupSerializer, AdSerializer,
                          AdCreateSerializer, GetAdGroupSerializer, AdTypeSerializer, GetAdSerializer)

from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import filters
from newscout_web.constants import SOCIAL_AUTH_PROVIDERS
from django.db.models import Q
from rest_framework.exceptions import APIException
from collections import OrderedDict
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.generics import ListAPIView
from django.views.generic.base import RedirectView
from rest_framework.parsers import JSONParser
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime, timedelta
from django.db.models import Count
import pytz
import uuid
from core.utils import es, ingest_to_elastic, delete_from_elastic
from elasticsearch_dsl import Search
import math
from rest_framework.utils.urls import replace_query_param
from google.auth.transport import requests as grequests
from google.oauth2 import id_token
import facebook
from .exception_handler import (create_error_response,TokenIDMissing, ProviderMissing,
                                SocialAuthTokenException, CampaignNotFoundException,
                                AdGroupNotFoundException, AdvertisementNotFoundException)
import random
import logging
log = logging.getLogger(__name__)


def create_response(response_data):
    """
    method used to create response data in given format
    """
    response = OrderedDict()
    response["header"] = {"status": "1"}
    response["body"] = response_data
    return response


def create_serializer_error_response(errors):
    """
    methos is used to create error response for serializer errors
    """
    error_list = []
    for k, v in errors.items():
        if isinstance(v, dict):
            _, v = v.popitem()
        d = {}
        d["field"] = k
        d["field_error"] = v[0]
        error_list.append(d)
    return OrderedDict({"header": {"status": "0"}, "errors": {
        "errorList": error_list}})


class SignUpAPIView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        user_serializer = UserSerializer(data=request.data)
        if user_serializer.is_valid():
            user = user_serializer.save()
            return Response(create_response(
                {"Msg": "sign up successfully",

                 }))
        else:
            return Response(
                create_serializer_error_response(user_serializer.errors),
                status=403)


class LoginFieldsRequired(APIException):
    """
    api exception for no user found
    """
    status_code = 401
    default_detail = ("username and password are required")
    default_code = "username_and_password"


class LoginAPIView(generics.GenericAPIView):
    serializer_class = LoginUserSerializer
    permission_classes = (AllowAny,)

    def post(self, request, format=None):
        serializer = LoginUserSerializer(data=request.data)
        if not serializer.is_valid():
            res_data = create_serializer_error_response(serializer.errors)
            return Response(res_data, status=403)

        user = BaseUserProfile.objects.filter(email=request.data["email"]).first()
        device_name = request.data["device_name"]
        device_id = request.data["device_id"]
        device = Devices.objects.filter(user=user.id)
        if device:
            device.update(device_name=device_name, device_id=device_id)
        else:
            device, created = Devices.objects.get_or_create(device_name=device_name, device_id=device_id)
            Devices.objects.filter(pk=device.pk).update(user=user)
        notification = NotificationSerializer(Notification.objects.get_or_create(device=device), many=True)
        user_serializer = BaseUserProfileSerializer(user)
        token, _ = Token.objects.get_or_create(user=user)
        data = user_serializer.data
        data["token"] = token.key
        data["breaking_news"] = notification.data[0]['breaking_news']
        data["daily_edition"] = notification.data[0]['daily_edition']
        data["personalized"] = notification.data[0]['personalized']
        response_data = create_response({"user": data})
        return Response(response_data)


class LogoutAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        request.user.auth_token.delete()
        return Response(create_response({"Msg": "User has been logged out"}))


class UserHashTagAPIView(APIView):
    """
    Save new tags and remove older tags based on user selection
    """
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

    def post(self, request, format=None):
        user = self.request.user
        hash_tags = request.data["tags"]
        user_tags = HashTag.objects.filter(name__in=hash_tags)
        if user_tags:
            user.passion.clear()
            user.passion.add(*user_tags)
            return Response(create_response({"Msg" : "Successfully saved tags"}))
        return Response(create_error_response({"Msg" : "Invalid tags"}), status=400)


class CategoryListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None, *args, **kwargs):
        """
        List all news category
        """
        categories = CategorySerializer(Category.objects.all(), many=True)
        return Response(create_response({"categories": categories.data}))

    def post(self, request, format=None):
        """
        Save new category to database
        """
        serializer = CategorySerializer(data=request.data, many=True)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)

    def put(self, request, format=None):
        """
        update category in database
        """
        _id = request.data.get("id")
        obj = Category.objects.get(id=_id)
        serializer = CategorySerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)


class SourceListAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None, *args, **kwargs):
        """
        List all the sources
        """
        source = SourceSerializer(Source.objects.all(), many=True)
        return Response(create_response({"results": source.data}))


class NoarticleFound(APIException):
    """
    api exception for no user found
    """
    status_code = 404
    default_detail = ("Article does not exist")
    default_code = "no_article_found"


class PostpageNumberPagination(CursorPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    ordering = '-created_at'


class ArticleListAPIView(ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = (AllowAny,)
    pagination_class = PostpageNumberPagination
    filter_backends = (filters.OrderingFilter,)
    ordering = ('-published_on',)

    def get_queryset(self):
        q = self.request.GET.get("q","")
        tag = self.request.GET.getlist("tag","")
        category = self.request.GET.getlist("category","")
        source = self.request.GET.getlist("source","")
        queryset = Article.objects.all()

        if source:
            queryset = queryset.filter(source__name__in=source)

        if category:
            queryset = queryset.filter(category__name__in=category)

        if tag:
            queryset = queryset.filter(hash_tags__name__in=tag)

        if q:
            queryset = queryset.filter(Q(title__icontains=q) | Q(full_text__icontains=q))

        return queryset.distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            if serializer.data:
                paginated_response = self.get_paginated_response(serializer.data)
                return Response(create_response(paginated_response.data))
            else:
                return Response(create_error_response({"Msg" : "News Doesn't Exist"}), status=400)

        serializer = self.get_serializer(queryset, many=True)
        return Response(create_response(serializer.data))


class ArticleDetailAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, format=None, *args, **kwargs):
        article_id = self.kwargs.get("article_id", "")

        user = self.request.user
        if article_id:
            article = Article.objects.filter(id=article_id).first()
            if article:
                response_data = ArticleSerializer(article, context={"hash_tags_list": True}).data
                if not user.is_anonymous:
                    book_mark_article = BookmarkArticle.objects.filter(
                        user=user, article=article).first()
                    like_article = ArtilcleLike.objects.filter(
                        user=user, article=article).first()

                    if book_mark_article:
                        response_data["isBookMark"] = True
                    else:
                        response_data["isBookMark"] = False

                    if like_article:
                        response_data["isLike"] = like_article.is_like
                    else:
                        response_data["isLike"] = 2

                return Response(create_response({
                    "article": response_data}))
        raise NoarticleFound

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            article_id = self.request.POST.get("article_id", "")
            is_like = self.request.POST.get("isLike", "")
            user = self.request.user
            article = Article.objects.filter(id=article_id).first()
            if article:
                if is_like and int(is_like) <= 2:
                    article_like, created = ArtilcleLike.objects.get_or_create(
                        user=user, article=article)
                    article_like.is_like = is_like
                    article_like.save()
                    article_obj = ArtilcleLikeSerializer(article_like)
                    return Response(create_response({
                        "Msg": "Article like status changed", "article": article_obj.data
                    }))
                else:
                    return Response(create_error_response({
                        "Msg": "Invalid Input"
                    }))
            else:
                return Response(create_error_response({ "Msg": "News doesn't exist"}), status=400)
        raise Http404


class ArticleBookMarkAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        article_id = self.request.POST.get("article_id", "")
        user = self.request.user
        if article_id:
            article = Article.objects.filter(id=article_id).first()
            if article:
                bookmark_article, created = \
                    BookmarkArticle.objects.get_or_create(user=user,
                                                          article=article)
                if not created:
                    del_bookmark_article = BookmarkArticleSerializer(bookmark_article)
                    del_bookmark = del_bookmark_article.data
                    del_bookmark["status"] = 0
                    bookmark_article.delete()
                    return Response(create_response({
                        "Msg": "Article removed from bookmark list", "bookmark_article": del_bookmark
                    }))
                else:
                    bookmark_article = BookmarkArticleSerializer(bookmark_article)
                    return Response(create_response({
                        "Msg": "Article bookmarked successfully", "bookmark_article": bookmark_article.data
                    }))

        raise NoarticleFound


class ArticleRecommendationsAPIView(APIView):
    permission_classes = (AllowAny,)

    def format_response(self, response):
        results = []
        if response['hits']['hits']:
            for result in response['hits']['hits']:
                results.append(result["_source"])
        return results

    def get(self, request, *args, **kwargs):
        article_id = self.kwargs.get("article_id", "")
        if article_id:
            results = es.search(index='recommendation',body={"query":{"match": {"id": int(article_id)}}})
            if results['hits']['hits']:
                recommendation = results['hits']['hits'][0]['_source']['recommendation']
                search_results = es.search(index='article',body={"query":{"terms": {"id": recommendation}},"size": 25})
                return Response(create_response({
                    "results": self.format_response(search_results)
                }))

        return Response(create_error_response({
            "Msg": "Error generating recommendation"
        }))


class ForgotPasswordAPIView(APIView):
    permission_classes = (AllowAny,)

    def genrate_password(self, password_length=10):
        """
        Returns a random pasword of length password_length.
        """
        random = str(uuid.uuid4())
        random = random.upper()
        random = random.replace("-", "")
        return random[0:password_length]

    def send_mail_to_user(self, email, password, first_name="", last_name=""):
        username = first_name + " " + last_name
        email_subject = 'NewsPost: Forgot Password Request'
        email_body = """
            <html>
                <head>
                </head>
                <body>
                    <p>
                        Hello """ + username + """,<br><br><b>
                        """ + password + """</b> is your new password
                        <br>
                        <br>
                        Thanks,<br>
                        The NewsPost Team<br>
                    </p>
                </body>
            </html>"""

        msg = EmailMultiAlternatives(
            email_subject, '', settings.EMAIL_HOST_USER, [email])
        ebody = email_body
        msg.attach_alternative(ebody, "text/html")
        msg.send(fail_silently=False)

    def post(self, request, *args, **kwargs):
        email = self.request.POST.get("email", "")
        if email:
            user = BaseUserProfile.objects.filter(email=email)
            if user:
                user = user.first()
                password = self.genrate_password()
                self.send_mail_to_user(
                    email, password, user.first_name, user.last_name)
                user.set_password(password)
                user.save()
                return Response(create_response({
                    "Msg": "New password sent to your email"
                }))

        return Response(create_error_response({
            "Msg": "Email Does Not Exist"
        }))


class ChangePasswordAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        password = self.request.POST.get("password", "")
        old_password = self.request.POST.get("old_password", "")
        confirm_password = self.request.POST.get("confirm_password", "")
        user = self.request.user
        if old_password:
            if not user.check_password(old_password):
                msg = "Old Password Does Not Match With User"
                return Response(create_error_response({
                    "Msg": msg
                }))
            if confirm_password != password:
                msg = "Password and Confirm Password does not match"
                return Response(create_error_response({
                    "Msg": msg
                }))
            if old_password == password:
                msg = "New password should not same as Old password"
                return Response(create_error_response({
                    "Msg": msg
                }))
            if user and password:
                user.set_password(password)
                user.save()
                return Response(create_response({
                    "Msg": "Password chnaged successfully"
                }))
            else:
                return Response(create_error_response({
                    "Msg": "Password field is required"
                }))
        else:
            return Response(create_error_response({
                "Msg": "Old Password field is required"
            }))


class BookmarkArticleAPIView(APIView):
    """
    This class is used to get user bookmark list
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user = self.request.user
        bookmark_list = BookmarkArticleSerializer(BookmarkArticle.objects.filter(user=user), many=True)
        return Response(create_response({"results": bookmark_list.data}))


class ArtilcleLikeAPIView(APIView):
    """
    This class is used to get user articles
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        like_list = [0,1]
        user = self.request.user
        article_list = ArtilcleLikeSerializer(ArtilcleLike.objects.filter(user=user, is_like__in=like_list), many=True)
        return Response(create_response({"results": article_list.data}))


class HashTagAPIView(ListAPIView):
    serializer_class = HashTagSerializer
    permission_classes = (AllowAny,)

    def get_queryset(self):
        weekly = self.request.GET.get("weekly","")
        monthly = self.request.GET.get("monthly","")
        end = datetime.utcnow()
        pst = pytz.timezone('Asia/Kolkata')
        end = pst.localize(end)
        utc = pytz.UTC
        end = end.astimezone(utc)
        articles = Article.objects.all()
        queryset = HashTag.objects.all()

        if weekly:
            weekly = int(weekly)
            start = end - timedelta(days=7*weekly)
            hash_tags = articles.filter(published_on__range=(start,end)).values('hash_tags__name').annotate(count=Count('hash_tags')).order_by('-count')[:10]
            for hashtag in hash_tags:
                hashtag['name'] = hashtag.pop('hash_tags__name')
            queryset = hash_tags

        if monthly:
            monthly = int(monthly)
            start = end - timedelta(days=30*monthly)
            hash_tags = articles.filter(published_on__range=(start,end)).values('hash_tags__name').annotate(count=Count('hash_tags')).order_by('-count')[:10]  
            for hashtag in hash_tags:
                hashtag['name'] = hashtag.pop('hash_tags__name')
            queryset = hash_tags

        if not weekly and not monthly:
            start = end - timedelta(days=1)
            hash_tags = articles.filter(published_on__range=(start,end)).values('hash_tags__name').annotate(count=Count('hash_tags')).order_by('-count')[:10]
            for hashtag in hash_tags:
                hashtag['name'] = hashtag.pop('hash_tags__name')
            queryset = hash_tags

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            if serializer.data:
                paginated_response = self.get_paginated_response(serializer.data)
                return Response(create_response(paginated_response.data))
            else:
                return Response(create_error_response({"Msg" : "No trending tags"}), status=400)

        serializer = self.get_serializer(queryset, many=True)
        return Response(create_response(serializer.data))


class ArticleSearchAPI(APIView):
    """
    this view is used for article search and filter
    """
    permission_classes = (AllowAny,)

    def format_response(self, response):
        results = []
        filters = {}
        if response.hits.hits:
            for result in response.hits.hits:
                results.append(result["_source"])

            if response.aggregations.category.buckets:
                filters["category"] = response.aggregations.category.buckets._l_

            if response.aggregations.source.buckets:
                filters["source"] = response.aggregations.source.buckets._l_

            if response.aggregations.hash_tags.buckets:
                filters["hash_tags"] = response.aggregations.hash_tags.buckets._l_
        return results, filters

    def get(self, request):
        page = self.request.GET.get("page", "1")

        if page.isdigit():
            page = int(page)
        else:
            page = 1

        size = self.request.GET.get("rows", "20")
        if size.isdigit():
            size = int(size)
        else:
            size = 20

        query = self.request.GET.get("q", "")
        source = self.request.GET.getlist("source", [])
        category = self.request.GET.getlist("category", [])
        domain = self.request.GET.getlist("domain", [])
        tags = self.request.GET.getlist("tag", [])
        sort = self.request.GET.get("sort", "desc")

        if not domain:
            return Response(create_serializer_error_response({"domain": ["Domain id is required"]}))

        sr = Search(using=es, index="article")

        # generate elastic search query
        must_query = {}
        should_query = []

        if query:
            query = query.lower()
            must_query = {"multi_match": {"query": query,"fields": ["title", "blurb"]}}

        if tags:
            tags = [tag.lower().replace("-", " ") for tag in tags]
            for tag in tags:
                sq = {"match_phrase": {"hash_tags" : tag}}
                should_query.append(sq)

        if must_query:
            sr = sr.query("bool", must=must_query)

        if should_query:
            if len(should_query) > 1:
                sr = sr.filter("bool", should=should_query)
            else:
                sr = sr.filter("bool", should=should_query[0])

        if domain:
            sr = sr.filter("terms", domain=list(domain))

        if category:
            cat_objs = Category.objects.filter(id__in=category)
            category = cat_objs.values_list("id", flat=True)
            cat_assn_objs = CategoryAssociation.objects.filter(parent_cat__in=cat_objs).values_list("child_cat__id", flat=True)
            if cat_assn_objs:
                new_category = set(list(cat_assn_objs) + list(category))
                sr = sr.filter("terms", category_id=list(new_category))
            else:
                if category:
                    sr = sr.filter("terms", category_id=list(category))

        if source:
            source = [s.lower() for s in source]
            sr = sr.filter("terms", source=source)

        sr = sr.sort({"article_score" : {"order" : sort}})
        sr = sr.sort({"published_on" : {"order" : sort}})

        # pagination
        start = (page - 1) * size
        end = start + size
        sr = sr[start:end]

        #generate facets
        sr.aggs.bucket("category", "terms", field="category.keyword")
        sr.aggs.bucket("source", "terms", field="source.keyword")
        sr.aggs.bucket("hash_tags", "terms", field="hash_tags.keyword", size=50)

        # execute query
        response = sr.execute()

        results, filters = self.format_response(response)
        count = response["hits"]["total"]
        total_pages = math.ceil(count / size)

        url = request.build_absolute_uri()
        if end < count:
            next_page = page + 1
            next_url = replace_query_param(url, "page", next_page)
        else:
            next_url = None

        if page != 1:
            previous_page = page - 1
            previous_url = replace_query_param(url, "page", previous_page)
        else:
            previous_url = None

        data = {
            "results": results,
            "filters": filters,
            "count": count,
            "total_pages": total_pages,
            "current_page": page,
            "next": next_url,
            "previous": previous_url
        }

        return Response(create_response(data))


class MenuAPIView(APIView):
    """
    This Api will return all the menus
    """
    permission_classes = (AllowAny,)

    def get(self, request):
        domain = self.request.GET.get("domain")
        if not domain:
            return Response(create_error_response({"domain": ["Domain id is required"]}))

        domain_obj = Domain.objects.filter(domain_id=domain).first()
        if not domain_obj:
            return Response(create_error_response({"domain": ["Domain id is required"]}))

        menus = MenuSerializer(Menu.objects.filter(domain=domain_obj), many=True)
        menus_list = menus.data
        new_menulist = []
        for menu in menus_list:
            menu_dict = {}
            menu_dict['heading'] = menu
            new_menulist.append(menu_dict)

        return Response(create_response({'results' : new_menulist}))


class DevicesAPIView(APIView):
    """
    this api will add device_id and device_name
    """
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        user = self.request.user
        device_id = self.request.POST.get("device_id", "")
        device_name = self.request.POST.get("device_name", "")
        if not user.is_anonymous and device_id and device_name:
            user_device = Devices.objects.filter(user=user.pk)
            if user_device:
                user_device.update(device_id=device_id, device_name=device_name, user=user.id)
                return Response(create_response({"Msg": "Device successfully created"}))
            elif not user_device:
                get, created = Devices.objects.get_or_create(device_id=device_id, device_name=device_name, user=user.id)
                if created:
                    return Response(create_response({"Msg": "Device successfully created"}))
                else:
                    return Response(create_response({"Msg": "Device already exist"}))
        elif device_id and device_name:
            get, created = Devices.objects.get_or_create(device_id=device_id, device_name=device_name)
            if created:
                return Response(create_response({"Msg": "Device successfully created"}))
            else:
                return Response(create_response({"Msg": "Device already exist"}))
        else:
            return Response(create_error_response({"Msg": "device_id and device_name field are required"}))


class NotificationAPIView(APIView):
    """
    this api will add notification data
    """
    permission_classes = (AllowAny,)

    def post(self, request):
        device_id = request.data["device_id"]
        device_name = request.data["device_name"]
        breaking_news = request.data["breaking_news"]
        daily_edition = request.data["daily_edition"]
        personalized = request.data["personalized"]

        device = Devices.objects.get(device_id=device_id, device_name=device_name)
        if breaking_news and daily_edition and personalized and device:
            notification = Notification.objects.filter(device=device)
            if notification:
                notification.update(breaking_news=breaking_news, daily_edition=daily_edition, personalized=personalized)
                return Response(create_response({"Msg": "Notification updated successfully"}))
            Notification.objects.create(breaking_news=breaking_news, daily_edition=daily_edition, personalized=personalized, device=device)
            return Response(create_response({"Msg": "Notification created successfully"}))
        else:
            return Response(create_error_response({"Msg": "device_id, device_name, breaking_news, daily_edition and personalized are required"}))

    def get(self, request):
        device_id = request.GET.get("device_id")
        device_name = request.GET.get("device_name")
        device = Devices.objects.filter(device_id=device_id, device_name=device_name).first()
        if device:
            notification = NotificationSerializer(Notification.objects.fitler(device=device), many=True)
            return Response(create_response(notification.data))
        return Response(create_error_response({"Msg": "Invalid device_id or device_name"}))


class SocialLoginView(generics.GenericAPIView):
    """
    this view is used for google social authentication and login
    """
    permission_classes = (AllowAny,)
    serializer_class = BaseUserProfileSerializer

    def decode_google_token(self, token_id):
        """
        this method is used to decode and verify google token
        """
        request = grequests.Request()
        try:
            id_info = id_token.verify_oauth2_token(token_id, request)
            return id_info
        except Exception as e:
            log.debug("error in google token verification {0}".format(e))
            return False

    def get_name_details(self, id_info):
        """
        this methos is used to get first name and last name from id_info
        details
        """
        first_name = last_name = ""
        if "name" in id_info:
            name = id_info.get("name")
            name_list = name.split(" ")
            first_name = name_list[0]
            if len(name_list) > 1:
                last_name = " ".join(name_list[1:])

        if not first_name:
            if "given_name" in id_info:
                first_name = id_info.get("given_name")

        if not last_name:
            if "family_name" in id_info:
                last_name = id_info.get("family_name")

        return first_name, last_name

    def create_user_profile(self, first_name, last_name, username, email,image_url, sid, provider):
        """
        this method is used to create base user profile object for given
        social account
        """
        user = BaseUserProfile.objects.filter(email=email).first()
        created = ""
        if not user:
            user = BaseUserProfile.objects.create(
                first_name=first_name,
                last_name=last_name,
                email=email,
                username=username
            )
            sa_obj, created = SocialAccount.objects.get_or_create(
                social_account_id=sid,
                image_url=image_url,
                user=user,
                provider=provider
            )
            # create_profile_image.delay(sa_obj.id)
        return user, created

    def get_facebook_data(self, token_id):
        """
        this method is used to get facebook user data from given access token
        """
        graph = facebook.GraphAPI(access_token=token_id)
        try:
            res_data = graph.get_object(id='me?fields=email,id,first_name,last_name,name,picture.width(150).height(150)')
            return res_data
        except Exception as e:
            log.debug("error in facebook fetch data: {0}".format(e))
            return False

    def get_facebook_name_details(self, profile_data):
        """
        this method is used to get facebook first_name last_name from profile
        data
        """
        name = first_name = last_name = ""
        if "first_name" in profile_data:
            first_name = profile_data.get("first_name")

        if "last_name" in profile_data:
            last_name = profile_data.get("last_name")

        if "name" in profile_data:
            name = profile_data.get("name")
            name_list = name.split(" ")
            if not first_name:
                first_name = name_list[0]

            if not last_name:
                last_name = " ".join(name[1:])

        return first_name, last_name

    def get_user_serialize_data(self, email, device_id, device_name):
        """
        this method will return customize user data
        """
        user = BaseUserProfile.objects.filter(email=email).first()
        device = Devices.objects.filter(user=user.id)
        if device:
            device.update(device_name=device_name, device_id=device_id)
        else:
            device, created = Devices.objects.get_or_create(device_name=device_name, device_id=device_id)
            Devices.objects.filter(pk=device.pk).update(user=user)
        notification = NotificationSerializer(Notification.objects.get_or_create(device=device), many=True)
        token, _ = Token.objects.get_or_create(user=user)
        data = BaseUserProfileSerializer(user).data
        data["token"] = token.key
        data["breaking_news"] = notification.data[0]['breaking_news']
        data["daily_edition"] = notification.data[0]['daily_edition']
        data["personalized"] = notification.data[0]['personalized']

        return data

    def post(self, request, *args, **kwargs):
        """
        this is post method for collection google social auth data
        and generate authentication api token for user
        """
        token_id = request.data.get("token_id")
        provider = request.data.get("provider")
        device_id = request.data.get("device_id")
        device_name = request.data.get("device_name")

        if not token_id:
            raise TokenIDMissing()

        if not provider:
            raise ProviderMissing()

        if not device_id:
            return Response(create_error_response({"Msg": "device_id is missing or Invalid device_id"}))

        if not device_name:
            return Response(create_error_response({"Msg": "device_name is missing or Invalid device_name"}))

        if provider not in SOCIAL_AUTH_PROVIDERS:
            raise ProviderMissing()

        if provider == "google":
            id_info = self.decode_google_token(token_id)
            if not id_info:
                raise SocialAuthTokenException()

            first_name, last_name = self.get_name_details(id_info)

            email = id_info.get("email", "")
            if not email:
                raise SocialAuthTokenException()

            username = email.split("@")[0]

            google_id = id_info.get("sub", "")
            image_url = id_info.get("picture", "")

            user, created = self.create_user_profile(
                first_name, last_name, username, email, image_url, google_id, provider)

            user_data = self.get_user_serialize_data(email, device_id, device_name)

            return Response(create_response({"user": user_data}))

        if provider == "facebook":
            profile_data = self.get_facebook_data(token_id)
            if not profile_data:
                raise SocialAuthTokenException()

            first_name, last_name = self.get_facebook_name_details(
                profile_data)

            email = profile_data.get("email")
            if not email:
                raise SocialAuthTokenException()

            username = username = email.split("@")[0]
            facebook_id = profile_data.get("id", "")
            image_url = ""
            if "picture" in profile_data:
                if "data" in profile_data["picture"]:
                    image_url = profile_data["picture"]["data"]["url"]

            user, created = self.create_user_profile(
                first_name, last_name, username, email, image_url, facebook_id, provider)

            user_data = self.get_user_serialize_data(email, device_id, device_name)

            return Response(create_response({"user": user_data}))

        raise ProviderMissing()


class TrendingArticleAPIView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, format=None, *args, **kwargs):
        """
        List all the trending articles
        """
        source = TrendingArticleSerializer(TrendingArticle.objects.all(), many=True)
        return Response(create_response({"results": source.data}))


class ArticleCreateUpdateView(APIView):
    """
    Article create update view
    """
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = ArticleCreateUpdateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)

    def put(self, request):
        _id = request.data.get("id")
        obj = Article.objects.get(id=_id)
        serializer = ArticleCreateUpdateSerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)


class CategoryBulkUpdate(APIView):
    """
    update whole bunch of articles in one go
    """
    permission_classes = (AllowAny,)

    def get_tags(self, tags):
        """
        this method will return tag name from tags objects
        """
        tag_list = []
        for tag in tags:
            tag_list.append(tag["name"])
        return tag_list

    def post(self, request):
        category_id = request.data['categories']
        category = Category.objects.get(id=category_id)
        for article_id in request.data['articles']:
            current = Article.objects.get(id=article_id)
            current.category = category
            current.save()
            serializer = ArticleSerializer(current)
            json_data = serializer.data
            delete_from_elastic([json_data], "article", "article", "id")

            if json_data["hash_tags"]:
                tag_list = self.get_tags(json_data["hash_tags"])
                json_data["hash_tags"] = tag_list
            ingest_to_elastic([json_data], "article", "article", "id")
        return Response({"ok": "cool"})


class GetAds(APIView):
    """
    this api is used to get active ads
    """
    permission_classes = (AllowAny,)

    def get(self, request):
        ads = Advertisement.objects.filter(is_active=True)
        ad = ads[random.randint(0, len(ads)-1)]
        ad.delivered += 1
        ad.save()
        ad_serializer = AdvertisementSerializer(ad, context={"request": request})
        return Response(create_response(ad_serializer.data))


class AdRedirectView(RedirectView):
    """
    this view is used to redirect given add url
    """

    def get_redirect_url(self, *args, **kwargs):
        aid = self.request.GET.get("aid")
        ad_url = self.request.GET.get("url")
        ad = Advertisement.objects.filter(id=aid).first()
        if ad:
            ad.click_count += 1
            ad.save()
            return ad_url
        return Http404


class GetDailyDigestView(ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = (AllowAny,)

    def format_response(self, response):
        results = []
        if response.hits.hits:
            for result in response.hits.hits:
                results.append(result["_source"])
        return results

    def get_queryset(self):
        device_id = self.request.GET.get("device_id","")
        queryset = Devices.objects.filter(device_id=device_id).first()
        if not queryset:
            return queryset

        dd = DailyDigest.objects.filter(device=queryset).first()
        if not dd:
            return queryset

        return dd.articles.all().order_by("-published_on")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        if not queryset:
            sr = Search(using=es, index="article")
            sort = "desc"
            sr = sr.sort({"article_score" : {"order" : sort}})
            sr = sr.sort({"published_on" : {"order" : sort}})
            sr = sr[0:20]
            response = sr.execute()
            results = self.format_response(response)
            return Response(create_response({"results": results}))

        serializer = self.get_serializer(queryset, many=True)
        if serializer.data:
            return Response(create_response(serializer.data))
        else:
            return Response(create_error_response({"Msg" : "Daily Digest Doesn't Exist"}), status=400)


class CampaignCategoriesListView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, format=None, *args, **kwargs):
        """
        List all news category
        """
        categories = CategorySerializer(Category.objects.all(), many=True)
        campaigns = CampaignSerializer(Campaign.objects.all(), many=True)
        return Response(create_response({"categories": categories.data, "campaigns": campaigns.data}))


class CampaignView(APIView):
    """
    this view is used to create,update,list and delete Campaign's
    """
    permission_classes = (AllowAny,)

    def get(self, request):
        """
        get list of all campaigns
        """
        campaign_objs = Campaign.objects.all().order_by('-id')
        serializer = CampaignSerializer(campaign_objs, many=True)
        return Response(create_response(serializer.data))

    def post(self, request):
        """
        create new campaign
        """
        serializer = CampaignSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)

    def put(self, request):
        """
        update existing campaign
        """
        _id = request.data.get("id")
        obj = Campaign.objects.get(id=_id)
        serializer = CampaignSerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)


class CampaignDeleteView(APIView):
    """
    this view is used to delete Campaign's
    """
    permission_classes = (AllowAny,)

    def delete(self, request, cid):
        """
        delete existing campaign
        """
        obj = Campaign.objects.filter(id=cid).first()
        if not obj:
            raise CampaignNotFoundException()
        obj.delete()
        return Response(create_response({"Msg": "Campaign deleted successfully"}), status=200)


class AdGroupView(APIView):
    """
    this view is used to create,update,list and delete AdGroup's
    """
    permission_classes = (AllowAny,)

    def get(self, request):
        """
        get list of all adgroups
        """
        adgroup_objs = AdGroup.objects.all().order_by('-id')
        serializer = GetAdGroupSerializer(adgroup_objs, many=True)
        return Response(create_response(serializer.data))

    def post(self, request):
        """
        create new campaign
        """
        categories = request.data.pop("category", None)
        serializer = AdGroupSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.save()
            for cat in categories:
                cat_obj = Category.objects.get(id=cat)
                data.category.add(cat_obj)
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)

    def put(self, request):
        """
        update existing adGroup
        """
        _id = request.data.get("id")
        categories = request.data.get("category")
        obj = AdGroup.objects.get(id=_id)
        serializer = AdGroupSerializer(obj, data=request.data)
        if serializer.is_valid():
            data = serializer.save()
            data.category.clear()
            for cat in categories:
                cat_obj = Category.objects.get(id=cat)
                data.category.add(cat_obj)
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)


class AdGroupDeleteView(APIView):
    """
    this view is used to delete AdGroup's
    """
    permission_classes = (AllowAny,)

    def delete(self, request, cid):
        """
        delete existing AdGroup
        """
        obj = AdGroup.objects.filter(id=cid).first()
        if not obj:
            raise AdGroupNotFoundException()
        obj.delete()
        return Response(create_response({"Msg": "AdGroup deleted successfully"}), status=200)


class GroupTypeListView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, format=None, *args, **kwargs):
        """
        List all news category
        """
        groups = GetAdGroupSerializer(AdGroup.objects.all(), many=True)
        types = AdTypeSerializer(AdType.objects.all(), many=True)
        return Response(create_response({"groups": groups.data, "types": types.data}))


class AdvertisementView(APIView):
    """
    this view is used to create, list and update advertisement
    """
    permission_classes = (AllowAny,)

    def get(self, request):
        """
        get list of all Advertisements
        """
        advertisement_objs = Advertisement.objects.all().order_by('-id')
        serializer = GetAdSerializer(advertisement_objs, many=True)
        return Response(create_response(serializer.data))

    def post(self, request):
        """
        create new Advertisement
        """
        file_obj = request.data['file']
        serializer = AdCreateSerializer(data=request.data)
        if serializer.is_valid():
            ad = serializer.save()
            ad.media = file_obj
            ad.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)

    def put(self, request):
        """
        update existing Advertisement
        """
        _id = request.data.get("id")
        file_obj = request.data['file']
        obj = Advertisement.objects.get(id=_id)
        if file_obj:
            obj.media = file_obj
            obj.save
        serializer = AdCreateSerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(create_response(serializer.data))
        return Response(create_error_response(serializer.errors), status=400)


class AdvertisementDeleteView(APIView):
    """
    this view is used to delete Advertisement's
    """
    permission_classes = (AllowAny,)

    def delete(self, request, cid):
        """
        delete existing Advertisement
        """
        obj = Advertisement.objects.filter(id=cid).first()
        if not obj:
            raise AdvertisementNotFoundException()
        obj.delete()
        return Response(create_response({"Msg": "Advertisement deleted successfully"}), status=200)
