from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole


class IsStaff(BasePermission):
    message = "Staff access is required."

    def has_permission(self, request, view) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == UserRole.STAFF
        )


class IsMember(BasePermission):
    message = "Member access is required."

    def has_permission(self, request, view) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == UserRole.MEMBER
        )