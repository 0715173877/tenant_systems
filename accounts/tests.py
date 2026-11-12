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


class PasswordChangeTests(TestCase):
    """Any signed-in user can set a new password from their profile page."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="changer",
            password="old-pass-123",
            email="changer@example.com",
        )

    def _post(self, **overrides):
        payload = {
            "old_password": "old-pass-123",
            "new_password1": "N3w-pass-456!",
            "new_password2": "N3w-pass-456!",
        }
        payload.update(overrides)
        return self.client.post(reverse("accounts:password_change"), payload)

    def test_requires_login(self):
        response = self.client.get(reverse("accounts:password_change"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_page_renders_password_fields(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="old_password"')
        self.assertContains(response, 'name="new_password1"')
        self.assertContains(response, 'name="new_password2"')

    def test_wrong_current_password_is_rejected(self):
        self.client.force_login(self.user)
        response = self._post(old_password="not-my-password")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-123"))

    def test_mismatched_confirmation_is_rejected(self):
        self.client.force_login(self.user)
        response = self._post(new_password2="Different-pass-789!")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-123"))

    def test_password_changes_and_user_stays_signed_in(self):
        self.client.force_login(self.user)
        response = self._post()
        # Staff/non-owner accounts land back on the dashboard.
        self.assertRedirects(response, reverse("dashboard"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("N3w-pass-456!"))
        # update_session_auth_hash() must keep the current session valid.
        self.assertEqual(
            self.client.get(reverse("dashboard")).status_code, 200
        )

    def test_owner_is_sent_back_to_owner_profile(self):
        from django.contrib.auth.models import Group

        owner_group, _ = Group.objects.get_or_create(name="owner")
        self.user.groups.add(owner_group)
        self.client.force_login(self.user)
        response = self._post()
        self.assertRedirects(
            response, reverse("properties:owner_profile"),
            fetch_redirect_response=False,
        )

    def test_legacy_password_change_url_redirects(self):
        response = self.client.get("/accounts/password_change/")
        self.assertRedirects(
            response,
            reverse("accounts:password_change"),
            fetch_redirect_response=False,
        )

    def test_tenant_is_sent_back_to_portal_profile(self):
        from django.contrib.auth.models import Group

        tenant_group, _ = Group.objects.get_or_create(name="tenant")
        self.user.groups.add(tenant_group)
        self.client.force_login(self.user)
        response = self._post()
        self.assertRedirects(
            response, reverse("portal:profile"), fetch_redirect_response=False
        )
