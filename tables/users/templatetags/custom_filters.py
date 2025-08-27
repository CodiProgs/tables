from django import template
from django.template.defaultfilters import date as date_filter
import datetime
import locale
from django.utils import timezone

locale.setlocale(locale.LC_ALL, "ru_RU.UTF-8")
locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")

register = template.Library()


@register.filter
def get_attr(obj, attr):
    try:
        return getattr(obj, attr, None)
    except AttributeError:
        return None


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def format_date(value):
    if isinstance(value, (datetime.datetime,)):
        value = timezone.localtime(value)
        return date_filter(value, "d.m.Y")
    elif isinstance(value, datetime.date):
        return date_filter(value, "d.m.Y")
    return value