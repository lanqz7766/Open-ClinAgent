"""Administrator-only account operations; never return password material."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from clinagent.gateway.auth import ClinAgentAuthStore


class CreateAccount(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=160)
    organization: str = Field(default="", max_length=200)
    role: Literal["radiologist", "resident", "researcher"] = "radiologist"
    password: SecretStr


class AccountStatus(BaseModel):
    status: Literal["active", "suspended"]


class TemporaryPassword(BaseModel):
    password: SecretStr


def account_management_router(store: ClinAgentAuthStore) -> APIRouter:
    def administrator(request: Request):
        user = getattr(request.state, "current_user", None)
        if not user:
            raise HTTPException(401, "Authentication required.")
        if user["role"] != "admin" or user["account_setup_required"]:
            raise HTTPException(404, "Resource not found.")
        return user

    router = APIRouter(prefix="/api/auth/admin", dependencies=[Depends(administrator)])

    def audit(request: Request, action: str, target: str):
        store.record_audit(user_id=request.state.current_user["id"], action=action,
                           resource="account:" + target, status="200", request=request)

    @router.get("/users")
    def users():
        return {"ok": True, "users": store.list_users()}

    @router.post("/users")
    def create_account(payload: CreateAccount, request: Request):
        try:
            user = store.provision_user(**payload.model_dump(exclude={"password"}), password=payload.password.get_secret_value())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit(request, "account_provisioned", user["id"])
        return {"ok": True, "user": user}

    @router.patch("/users/{user_id}/status")
    def set_status(user_id: str, payload: AccountStatus, request: Request):
        try:
            user = store.set_user_status(user_id, payload.status)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit(request, "account_" + ("suspended" if payload.status == "suspended" else "enabled"), user_id)
        return {"ok": True, "user": user}

    @router.post("/users/{user_id}/password")
    def reset_password(user_id: str, payload: TemporaryPassword, request: Request):
        target = store.get_user(user_id)
        if not target:
            raise HTTPException(404, "Account not found.")
        if target["role"] == "admin":
            raise HTTPException(400, "Use account settings or the operator CLI for administrator passwords.")
        try:
            user = store.set_temporary_password(user_id, payload.password.get_secret_value())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit(request, "account_password_reset", user_id)
        return {"ok": True, "user": user}

    return router
