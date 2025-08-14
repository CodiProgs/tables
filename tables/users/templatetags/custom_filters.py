from django import template
from django.template.defaultfilters import date as date_filter
import datetime

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
    if isinstance(value, (datetime.date, datetime.datetime)):
        return date_filter(value, "d.m.y")
    return value
