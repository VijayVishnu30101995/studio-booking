from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase,APIRequestFactory

from apps.accounts.permissions import IsMember, IsStaff
from apps.accounts.models import UserRole


User = get_user_model()


class LoginAPITests(APITestCase):
    def setUp(self):
        self.password = "StrongPassword123!"

        self.user = User.objects.create_user(
            username="member1",
            email="member@example.com",
            password=self.password,
            role=UserRole.MEMBER,
        )

        self.url = "/api/auth/login/"

    def test_member_can_login(self):
        response = self.client.post(
            self.url,
            {
                "username": "member1",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn("token", response.data)
        self.assertIn("user", response.data)

        self.assertEqual(
            response.data["user"]["role"],
            UserRole.MEMBER,
        )

        self.assertTrue(
            Token.objects.filter(user=self.user).exists()
        )

    def test_invalid_password_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "username": "member1",
                "password": "WrongPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_nonexistent_user_is_rejected(self):
        response = self.client.post(
            self.url,
            {
                "username": "does-not-exist",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class RolePermissionTests(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.staff = User.objects.create_user(
            username="staff1",
            email="staff@example.com",
            password="StrongPassword123!",
            role=UserRole.STAFF,
        )

        self.member = User.objects.create_user(
            username="member2",
            email="member2@example.com",
            password="StrongPassword123!",
            role=UserRole.MEMBER,
        )

    def test_staff_permission_allows_staff(self):
        request = self.factory.get("/")
        request.user = self.staff

        permission = IsStaff()

        self.assertTrue(
            permission.has_permission(request, None)
        )

    def test_staff_permission_rejects_member(self):
        request = self.factory.get("/")
        request.user = self.member

        permission = IsStaff()

        self.assertFalse(
            permission.has_permission(request, None)
        )

    def test_member_permission_allows_member(self):
        request = self.factory.get("/")
        request.user = self.member

        permission = IsMember()

        self.assertTrue(
            permission.has_permission(request, None)
        )

    def test_member_permission_rejects_staff(self):
        request = self.factory.get("/")
        request.user = self.staff

        permission = IsMember()

        self.assertFalse(
            permission.has_permission(request, None)
        )

# Create your tests here.
