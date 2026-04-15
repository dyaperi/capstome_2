from flask import session


class RoleService:
    ADMIN_ANALYST = "admin_analyst"
    CLIENT = "client"

    @classmethod
    def current_role(cls) -> str:
        return session.get("role", cls.CLIENT)

    @classmethod
    def is_staff(cls) -> bool:
        return cls.current_role() == cls.ADMIN_ANALYST

    @classmethod
    def is_client(cls) -> bool:
        return cls.current_role() == cls.CLIENT
