from django import template
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()


class StyleManager:
    _styles = set()

    @classmethod
    def add_style(cls, href):
        cls._styles.add(href)

    @classmethod
    def get_styles(cls):
        return sorted(cls._styles)


@register.simple_tag
def add_style(href):
    StyleManager.add_style(href)
    return ""


@register.simple_tag
def render_styles():
    styles = "\n".join(
        f'<link rel="stylesheet" href="{static(style)}">'
        for style in StyleManager.get_styles()
    )
    return mark_safe(styles)


class ScriptManager:
    _scripts = set()

    @classmethod
    def add_script(cls, src, module=False):
        cls._scripts.add((src, module))

    @classmethod
    def get_scripts(cls):
        return sorted(cls._scripts)


@register.simple_tag
def add_script(src, module=False):
    ScriptManager.add_script(src, module)
    return ""


@register.simple_tag
def render_scripts():
    scripts = "\n".join(
        f'<script {"type=module" if is_module else ""} src="{static(src)}" {"defer" if not is_module else ""}></script>'
        for src, is_module in ScriptManager.get_scripts()
    )
    return mark_safe(scripts)
