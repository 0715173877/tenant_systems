from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class SignUpTests(TestCase):
    def test_signup_page_renders(self):
        response = self.client.get(reverse("accounts:signup"))
        self.assertEqual(response.status_code, 200)

    def test_signup_creates_owner_group_user_and_profile(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "newlandlord",
                "first_name": "New",
                "last_name": "Landlord",
                "email": "new@example.com",
                "phone": "+255700000000",
                "password1": "S3cret-pass!",
                "password2": "S3cret-pass!",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))

        user = User.objects.get(username="newlandlord")
        self.assertTrue(user.groups.filter(name="owner").exists())
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.owner_profile.phone, "+255700000000")

    def test_signup_rejects_duplicate_email(self):
        User.objects.create_user(
            username="existing", password="pass12345", email="dup@example.com"
        )
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "another",
                "email": "dup@example.com",
                "password1": "S3cret-pass!",
                "password2": "S3cret-pass!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="another").exists())
