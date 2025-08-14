from django.db import models


def get_model_fields(
    model, excluded_fields=None, custom_verbose_names=None, field_order=None
):
    if excluded_fields is None:
        excluded_fields = []

    if custom_verbose_names is None:
        custom_verbose_names = {}

    fields = []
    for field in model._meta.get_fields():
        if field.name not in excluded_fields and (
            not field.auto_created or field.name == "id"
        ):
            verbose_name = custom_verbose_names.get(
                field.name, getattr(field, "verbose_name", field.name.title())
            )
            fields.append(
                {
                    "name": field.name,
                    "verbose_name": verbose_name,
                    "is_relation": field.is_relation,
                    "is_boolean": isinstance(field, models.BooleanField),
                    "is_date": isinstance(field, models.DateField),
                    "is_datetime": isinstance(field, models.DateTimeField),
                    "is_number": isinstance(
                        field,
                        (
                            models.DecimalField,
                            models.IntegerField,
                            models.FloatField,
                            models.AutoField,
                        ),
                    ),
                    "is_type_sign": hasattr(field, "choices")
                    and field.choices
                    == [
                        ("income", "+"),
                        ("expense", "-"),
                    ],
                    "is_enum_field": hasattr(field, "choices") and bool(field.choices),
                }
            )
    if field_order:
        fields.sort(
            key=lambda f: (
                field_order.index(f["name"])
                if f["name"] in field_order
                else len(field_order)
            )
        )

    return fields
