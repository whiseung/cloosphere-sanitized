import logging
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserModel, Users
from open_webui.utils.auth import verify_password
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, String, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# DB MODEL
####################


class Auth(Base):
    __tablename__ = "auth"

    id = Column(String, primary_key=True)
    email = Column(String)
    password = Column(Text)
    active = Column(Boolean)


class AuthModel(BaseModel):
    id: str
    email: str
    password: str
    active: bool = True


####################
# Forms
####################


class Token(BaseModel):
    token: str
    token_type: str


class ApiKey(BaseModel):
    api_key: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    profile_image_url: str


class SigninResponse(Token, UserResponse):
    pass


class SigninForm(BaseModel):
    email: str
    password: str


class LdapForm(BaseModel):
    user: str
    password: str


class ProfileImageUrlForm(BaseModel):
    profile_image_url: str


class UpdateProfileForm(BaseModel):
    profile_image_url: str
    name: str


class UpdatePasswordForm(BaseModel):
    password: str
    new_password: str


class SignupForm(BaseModel):
    name: str
    email: str
    password: str
    profile_image_url: Optional[str] = "/user.png"


class AddUserForm(SignupForm):
    role: Optional[str] = "pending"


class AuthsTable:
    def insert_new_auth(
        self,
        email: str,
        password: str,
        name: str,
        profile_image_url: str = "/user.png",
        role: str = "pending",
        oauth_sub: Optional[str] = None,
    ) -> Optional[UserModel]:
        with get_db() as db:
            log.info("insert_new_auth")

            # Clean up orphan auth records (auth exists but no matching user)
            orphan_auths = db.query(Auth).filter_by(email=email).all()
            for orphan in orphan_auths:
                if not Users.get_user_by_id(orphan.id):
                    log.warning(
                        f"Cleaning up orphan auth record: id={orphan.id}, email={email}"
                    )
                    db.query(Auth).filter_by(id=orphan.id).delete()

            id = str(uuid.uuid4())

            auth = AuthModel(
                **{"id": id, "email": email, "password": password, "active": True}
            )
            result = Auth(**auth.model_dump())
            db.add(result)

            user = Users.insert_new_user(
                id, name, email, profile_image_url, role, oauth_sub
            )

            db.commit()
            db.refresh(result)

            if result and user:
                return user
            else:
                return None

    def authenticate_user(self, email: str, password: str) -> Optional[UserModel]:
        log.info(f"authenticate_user: {email}")
        try:
            with get_db() as db:
                # Query all auth records for this email to handle orphan records
                auths = db.query(Auth).filter_by(email=email, active=True).all()
                log.info(f"authenticate_user auth records found: {len(auths)}")

                for auth in auths:
                    user = Users.get_user_by_id(auth.id)
                    if not user:
                        # Skip orphan auth record (no matching user)
                        log.warning(
                            f"Skipping orphan auth record: id={auth.id}, email={email}"
                        )
                        continue

                    pwd_match = verify_password(password, auth.password)
                    log.info(f"authenticate_user pwd_match: {pwd_match}")
                    if pwd_match:
                        return user
                    else:
                        return None

                return None
        except Exception as e:
            log.error(f"authenticate_user exception: {e}", exc_info=True)
            return None

    def authenticate_user_by_api_key(self, api_key: str) -> Optional[UserModel]:
        log.info(f"authenticate_user_by_api_key: {api_key}")
        # if no api_key, return None
        if not api_key:
            return None

        try:
            user = Users.get_user_by_api_key(api_key)
            return user if user else None
        except Exception:
            return False

    def authenticate_user_by_trusted_header(self, email: str) -> Optional[UserModel]:
        log.info(f"authenticate_user_by_trusted_header: {email}")
        try:
            with get_db() as db:
                auths = db.query(Auth).filter_by(email=email, active=True).all()
                for auth in auths:
                    user = Users.get_user_by_id(auth.id)
                    if user:
                        return user
                return None
        except Exception:
            return None

    def update_user_password_by_id(self, id: str, new_password: str) -> bool:
        try:
            with get_db() as db:
                result = (
                    db.query(Auth).filter_by(id=id).update({"password": new_password})
                )
                db.commit()
                return True if result == 1 else False
        except Exception:
            return False

    def update_email_by_id(self, id: str, email: str) -> bool:
        try:
            with get_db() as db:
                result = db.query(Auth).filter_by(id=id).update({"email": email})
                db.commit()
                return True if result == 1 else False
        except Exception:
            return False

    def delete_auth_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                # Get the email before deletion to clean up orphan records
                auth = db.query(Auth).filter_by(id=id).first()
                email = auth.email if auth else None

                # Delete User
                result = Users.delete_user_by_id(id)

                if result:
                    # Delete the primary auth record
                    db.query(Auth).filter_by(id=id).delete()

                    # Clean up orphan auth records with the same email
                    if email:
                        db.query(Auth).filter(
                            Auth.email == email,
                            Auth.id != id,
                        ).delete()

                    db.commit()
                    return True
                else:
                    return False
        except Exception:
            return False


Auths = AuthsTable()
