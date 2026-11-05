from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.utils.crypto import constant_time_compare

# Reserved primary key for the virtual emergency super admin. Postgres serial
# PKs start at 1, so this value can never collide with a real auth_user row —
# the account is never written to the database.
EMERGENCY_USER_ID = -1


def is_emergency_user(user):
    return bool(user) and getattr(user, "pk", None) == EMERGENCY_USER_ID


def verify_user_password(user, raw_password):
    """True when raw_password is this account's password. The emergency Super
    Admin has no stored password, so it is checked against its configured hash."""
    if is_emergency_user(user):
        expected_hash = settings.EMERGENCY_SUPERADMIN_PASSWORD_HASH
        return bool(expected_hash) and check_password(raw_password or "", expected_hash)
    return user.check_password(raw_password or "")


def _noop_save(*args, **kwargs):
    # Never persisted — Django's own user_logged_in signal handler calls
    # user.save(update_fields=["last_login"]) on every login, which would
    # otherwise fail since this pk has no matching row to update.
    return None


def _build_virtual_super_admin(username):
    user = User(
        pk=EMERGENCY_USER_ID,
        username=username,
        # A fixed unusable-password marker (not django's set_unusable_password(),
        # which randomizes on every call) so get_session_auth_hash() — which is
        # derived from this value — stays stable between the login request and
        # every later request that reloads the session via get_user() below.
        password="!",
        email="",
        first_name="Emergency",
        last_name="Super Admin",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    user.save = _noop_save
    return user


class EmergencySuperAdminBackend:
    """Break-glass Super Admin access that exists only in configuration
    (EMERGENCY_SUPERADMIN_USERNAME / EMERGENCY_SUPERADMIN_PASSWORD_HASH env
    vars), never as a row in the database. Disabled unless both are set.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        expected_username = settings.EMERGENCY_SUPERADMIN_USERNAME
        expected_hash = settings.EMERGENCY_SUPERADMIN_PASSWORD_HASH

        if not expected_username or not expected_hash:
            return None
        if not username or not password:
            return None
        if not constant_time_compare(username, expected_username):
            return None
        if not check_password(password, expected_hash):
            return None

        return _build_virtual_super_admin(expected_username)

    def get_user(self, user_id):
        if str(user_id) != str(EMERGENCY_USER_ID):
            return None

        expected_username = settings.EMERGENCY_SUPERADMIN_USERNAME
        if not expected_username:
            return None

        return _build_virtual_super_admin(expected_username)
