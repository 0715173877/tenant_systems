from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from properties.models import OwnerProfile

User = get_user_model()


class LandlordSignUpForm(UserCreationForm):
    """
    Registration form for a new landlord (property owner).

    Creates a regular user, adds them to the ``owner`` group, and seeds an
    empty :class:`OwnerProfile` so they can start adding properties straight
    away. Each owner only ever sees the properties they create.
    """

    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True)
    phone = forms.CharField(max_length=20, required=False, help_text="Contact phone number")

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        from django.contrib.auth.models import Group

        user = super().save(commit=False)
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name = self.cleaned_data.get("last_name", "")
        user.email = self.cleaned_data["email"]

        if commit:
            user.save()
            owner_group, _ = Group.objects.get_or_create(name="owner")
            user.groups.add(owner_group)
            OwnerProfile.objects.get_or_create(
                owner=user,
                defaults={
                    "phone": self.cleaned_data.get("phone", ""),
                    "email": self.cleaned_data["email"],
                },
            )
        return user
