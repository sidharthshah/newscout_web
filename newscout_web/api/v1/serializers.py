from rest_framework import serializers
from core.models import (Category, Article, BaseUserProfile, Source, BookmarkArticle,
                              ArtilcleLike, HashTag, ArticleMedia, Menu, SubMenu,
                              Devices, Notification,TrendingArticle, Advertisement,
                              Campaign, AdGroup, AdType)
from django.contrib.auth import authenticate
from rest_framework import exceptions
from rest_framework.validators import UniqueValidator
from rest_framework.authtoken.models import Token
try:
    from urllib import urlencode, quote
except:
    from urllib.parse import urlencode, quote


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name')


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ('name', 'id')

class HashTagSerializer(serializers.ModelSerializer):
    count = serializers.IntegerField(default=1)
    class Meta:
        model = HashTag
        fields = ('id','name','count')


class ArticleMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleMedia
        fields = '__all__'


class ArticleSerializer(serializers.ModelSerializer):
    article_media = ArticleMediaSerializer(source='articlemedia_set', many=True)
    is_book_mark = serializers.ReadOnlyField()
    isLike = serializers.ReadOnlyField()

    class Meta:
        model = Article
        fields = ('id', 'title', 'source', 'category', 'hash_tags','source_url',
                  'cover_image', 'blurb', 'published_on', 'is_book_mark',
                  'isLike','article_media', 'category_id', 'domain')

    source = serializers.ReadOnlyField(source='source.name')
    category = serializers.ReadOnlyField(source='category.name')
    category_id = serializers.ReadOnlyField(source='category.id')
    domain = serializers.ReadOnlyField(source='domain.domain_id')
    hash_tags = HashTagSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super(ArticleSerializer, self).__init__(*args, **kwargs)
        if self.context.get("hash_tags_list"):
            self.fields["hash_tags"] = serializers.SerializerMethodField()

    def get_hash_tags(self, instance):
        return list(instance.hash_tags.all().values_list("name", flat=True))


class UserSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=200, required=True, validators=[
        UniqueValidator(queryset=BaseUserProfile.objects.all(),
                        message="User with this email already exist")],)
    password = serializers.CharField(max_length=200, required=True)
    first_name = serializers.CharField(max_length=200, required=True)
    last_name = serializers.CharField(max_length=200, required=True)

    def create(self, validated_data):
        user = BaseUserProfile(**validated_data)
        user.set_password(validated_data["password"])
        user.username = validated_data["email"]
        user.save()
        token, _ = Token.objects.get_or_create(user=user)
        return user


class LoginUserSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        user = authenticate(username=data["email"], password=data["password"])
        if user:
            return user
        raise exceptions.AuthenticationFailed('User inactive or deleted')


class BaseUserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BaseUserProfile
        fields = ('id','passion', 'first_name', 'last_name')

    passion = CategorySerializer(many=True)


class BookmarkArticleSerializer(serializers.ModelSerializer):
    status = serializers.IntegerField(default=1)
    class Meta:
        model = BookmarkArticle
        fields = ('id', 'article', 'status')


class ArtilcleLikeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArtilcleLike
        fields = ('id', 'article', 'is_like')


class SubMenuSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubMenu
        fields = ('name', 'category_id', 'hash_tags')

    hash_tags = HashTagSerializer(many=True)
    name = serializers.SerializerMethodField()
    category_id = serializers.SerializerMethodField()

    def get_name(self, instance):
        return instance.name.name

    def get_category_id(self, instance):
        return instance.name.id


class MenuSerializer(serializers.ModelSerializer):
    class Meta:
        model = Menu
        fields = ('name', 'category_id', 'submenu')

    name = serializers.SerializerMethodField()
    category_id = serializers.SerializerMethodField()
    submenu = SubMenuSerializer(many=True)

    def get_name(self, instance):
        return instance.name.name

    def get_category_id(self, instance):
        return instance.name.id


class DevicesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Devices
        fields = ('device_name',)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ('breaking_news', 'daily_edition', 'personalized',)

class TrendingArticleSerializer(serializers.ModelSerializer):
    articles = ArticleSerializer(read_only=True, many=True, context={"hash_tags_list": True})
    domain = serializers.ReadOnlyField(source='domain.domain_id')

    class Meta:
        model = TrendingArticle
        fields = '__all__'


class ArticleCreateUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Article
        fields = ('title', 'source', 'category', 'source_url',
                  'cover_image', 'blurb', 'published_on', 'spam', 'domain')

    def to_internal_value(self, data):
        internal_value = super(ArticleCreateUpdateSerializer, self).to_internal_value(data)
        hash_tags = data.get("hash_tags")
        article_media = data.get("article_media")
        internal_value.update({
            "hash_tags": hash_tags,
            "article_media": article_media
        })
        return internal_value

    def create(self, validated_data):
        hash_tags = validated_data.pop("hash_tags")
        article_media = validated_data.pop("article_media")
        article = Article.objects.create(**validated_data)

        if hash_tags:
            hash_tags = [HashTag.objects.get_or_create(name=name)[0] for name in hash_tags]
            article.hash_tags.add(*hash_tags)
            article.save()

        if article_media:
            article_media = [ArticleMedia.objects.create(
                article=article,
                category=am["category"],
                url=am["url"],
                video_url=am["video_url"]
            ) for am in article_media]

        return article

    def update(self, instance, validated_data):
        hash_tags = validated_data.pop("hash_tags")
        article_media = validated_data.pop("article_media")

        instance.title = validated_data.get("title", instance.title)
        instance.source = validated_data.get("source", instance.source)
        instance.category = validated_data.get("category", instance.category)
        instance.domain = validated_data.get("domain", instance.domain)
        instance.source_url = validated_data.get("source_url", instance.source_url)
        instance.cover_image = validated_data.get("cover_image", instance.cover_image)
        instance.blurb = validated_data.get("blurb", instance.blurb)
        instance.published_on = validated_data.get("published_on", instance.published_on)
        instance.spam = validated_data.get("spam", instance.spam)
        instance.save()

        if hash_tags:
            hash_tags = [HashTag.objects.get_or_create(name=name)[0] for name in hash_tags]
            instance.hash_tags.clear()
            instance.hash_tags.add(*hash_tags)
            instance.save()

        if article_media:
            article_media = [ArticleMedia.objects.get_or_create(
                article=instance,
                category=am["category"],
                url=am["url"],
                video_url=am["video_url"]
            )[0] for am in article_media]

        return instance


class AdvertisementSerializer(serializers.ModelSerializer):

    class Meta:
        model = Advertisement
        fields = ('id', 'ad_text', 'media', 'ad_url')

    ad_url = serializers.SerializerMethodField()

    def get_ad_url(self, instance):
        request = self.context.get("request")
        host = request.META.get("HTTP_HOST")
        utm_source = "NewsCout"
        utm_medium = request.GET.get("category") or " ".join(instance.adgroup.category.all().values_list('name', flat=True))
        utm_campaign = instance.adgroup.campaign.name
        params = urlencode({"utm_source": utm_source, "utm_medium": utm_medium, "utm_campaign": utm_campaign})
        if "&" in instance.ad_url:
            ad_url = instance.ad_url + params
        else:
            ad_url = quote(instance.ad_url + "?" + params)
        print(ad_url)
        url = "http://" + host + "/getad-redirect/?url={0}&aid={1}".format(ad_url, instance.id)
        return url


class CampaignSerializer(serializers.ModelSerializer):

    class Meta:
        model = Campaign
        fields = '__all__'


class CampaignNameIdSerializer(serializers.ModelSerializer):

    class Meta:
        model = Campaign
        fields = ('id', 'name')


class AdGroupSerializer(serializers.ModelSerializer):
    category = CategorySerializer(many=True, read_only=True)
    
    class Meta:
        model = AdGroup
        fields = '__all__'


class GetAdGroupSerializer(serializers.ModelSerializer):
    category = CategorySerializer(many=True, read_only=True)
    campaign = CampaignNameIdSerializer()

    class Meta:
        model = AdGroup
        fields = '__all__'


class AdTypeSerializer(serializers.ModelSerializer):

    class Meta:
        model = AdType
        fields = '__all__'


class GetAdSerializer(serializers.ModelSerializer):
    adgroup = GetAdGroupSerializer(read_only=True)
    ad_type = AdTypeSerializer()

    class Meta:
        model = Advertisement
        fields = ('id', 'adgroup', 'ad_type', 'ad_text', 'ad_url', 'media', 'is_active', 'impsn_limit')


class AdSerializer(serializers.ModelSerializer):

    class Meta:
        model = Advertisement
        fields = ('id', 'adgroup', 'ad_type', 'ad_text', 'ad_url', 'media', 'is_active', 'impsn_limit')


class AdCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Advertisement
        fields = ('id', 'adgroup', 'ad_type', 'ad_text', 'ad_url', 'is_active', 'impsn_limit')
