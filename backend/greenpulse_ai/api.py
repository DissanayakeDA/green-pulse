"""Dashboard API: the HTTP side of the bridge, used by the Next.js dashboard (dashboard/).

    GET  /api/health
    GET  /api/devices                          devices seen so far, most recent first
    GET  /api/devices/{id}                     live status: readings, Plant Doctor advice, watering
    GET  /api/devices/{id}/history?hours=24    chart data
    GET  /api/devices/{id}/pump/events?hours=24  pump activity log, newest first
    POST /api/devices/{id}/chat                ask the Chat Agent a question
    POST /api/devices/{id}/pump/water          one manual pulse (the same as Node-RED's "Water now")
    PUT  /api/devices/{id}/pump/auto           the auto-watering switch
    PUT  /api/devices/{id}/plant               which plant this device watches

    GET    /api/plants                         built-in and added plant profiles, with the devices using each
    POST   /api/plants/suggest                 the Plant Profile Agent drafts a profile from a name (not saved)
    POST   /api/plants                         save a profile (it must pass the checkpoint)
    PUT    /api/plants/{key}                   change an added profile
    DELETE /api/plants/{key}                   remove an added profile

    GET    /api/alerts                         who gets email alerts, and the emails sent lately
    POST   /api/alerts/recipients              add an address; it is sent a 6-digit code
    POST   /api/alerts/recipients/{id}/verify  confirm the address with its code
    POST   /api/alerts/recipients/{id}/code    send a new code
    PUT    /api/alerts/recipients/{id}         which emails it gets
    DELETE /api/alerts/recipients/{id}         stop all emails to it
    POST   /api/alerts/recipients/{id}/test    send a test email

    GET  /api/auth/me                          who is signed in (or null), and whether registration is open
    POST /api/auth/register                    create an account with the registration code, and sign in
    POST /api/auth/login                       sign in
    POST /api/auth/logout                      sign out

The bridge serves it on API_HOST:API_PORT (default 127.0.0.1:8000), next to the MQTT loop. It is
meant to be reached only through the Next.js server, which proxies /api/* to it. With accounts (the
bridge always passes them), everything except /api/auth/* needs the session cookie set at sign-in.
"""

from __future__ import annotations

import logging
import threading
from typing import Annotated, Literal, Protocol

import uvicorn
from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .accounts import SESSION_COOKIE, SESSION_DAYS, Accounts, AccountsError
from .agents.chat import ChatAgent, ChatAnswer, ChatTurn
from .agents.profile import PlantProfileAgent, ProfileDraft
from .alerts import AlertCenter, AlertsError
from .device_state import DeviceStore
from .plant_library import PlantLibrary
from .plant_profiles import Range

log = logging.getLogger("greenpulse.api")

# Device IDs end up in MQTT topics, so only plain names are accepted (no "/", "+" or "#").
DeviceId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
PlantKey = Annotated[str, Path(pattern=r"^[a-z0-9_-]{1,64}$")]
RecipientId = Annotated[str, Path(pattern=r"^[0-9a-f]{8}$")]


class PumpControls(Protocol):
    def water_now(self, device_id: str) -> float: ...

    def set_auto_watering(self, device_id: str, enabled: bool) -> None: ...


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


class AutoWatering(BaseModel):
    enabled: bool


class PlantName(BaseModel):
    name: str = Field(min_length=2, max_length=60)


class PlantInput(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    scientific_name: str = Field("", max_length=80)
    moisture: Range
    temperature: Range
    humidity: Range
    care_notes: str = Field("", max_length=400)
    source: Literal["ai", "custom"] = "custom"

    def ranges(self) -> dict[str, Range]:
        return {"moisture": self.moisture, "temperature": self.temperature, "humidity": self.humidity}


class PlantChoice(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")


class NewRecipient(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class SignUpCode(BaseModel):
    code: str = Field(pattern=r"^\s*\d{6}\s*$")


class RecipientPrefs(BaseModel):
    alerts: bool
    min_priority: Literal["high", "critical"]
    daily: bool


class Registration(BaseModel):
    name: str = Field(max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    code: str = Field(max_length=100)


class SignIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


def create_app(
    store: DeviceStore,
    chat: ChatAgent,
    controls: PumpControls | None,
    default_device: str,
    info: dict | None = None,
    plants: PlantLibrary | None = None,
    profile_agent: PlantProfileAgent | None = None,
    alerts: AlertCenter | None = None,
    accounts: Accounts | None = None,
) -> FastAPI:
    app = FastAPI(title="GreenPulse dashboard API", docs_url="/api/docs", openapi_url="/api/openapi.json")

    if accounts is not None:

        @app.middleware("http")
        async def require_sign_in(request: Request, call_next):
            """Everything but /api/auth/* needs a signed-in session. Without accounts (tests) all is open."""
            if not request.url.path.startswith("/api/auth/"):
                if accounts.account_for(request.cookies.get(SESSION_COOKIE)) is None:
                    return JSONResponse({"detail": "Sign in to use the GreenPulse dashboard."}, status_code=401)
            return await call_next(request)
    plants = plants or PlantLibrary(default_key=store.profile_for(default_device).key)
    profile_agent = profile_agent or PlantProfileAgent()

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "default_device": default_device, "llm": chat.model, **(info or {})}

    @app.get("/api/devices")
    def devices() -> dict:
        seen = store.devices()
        if not any(d["device_id"] == default_device for d in seen):
            seen.append({"device_id": default_device, "online": False, "last_seen": None})
        return {"devices": seen}

    @app.get("/api/devices/{device_id}")
    def device(device_id: DeviceId) -> dict:
        return store.snapshot(device_id)

    @app.get("/api/devices/{device_id}/history")
    def history(device_id: DeviceId, hours: Annotated[float, Query(gt=0, le=24)] = 24) -> dict:
        return store.history(device_id, hours)

    @app.get("/api/devices/{device_id}/pump/events")
    def pump_events(device_id: DeviceId, hours: Annotated[float, Query(gt=0, le=24)] = 24) -> dict:
        events = store.pump_events(device_id, hours)
        return {"device_id": device_id, "hours": hours, "events": [e.as_dict() for e in reversed(events)]}

    @app.post("/api/devices/{device_id}/chat")
    def ask(device_id: DeviceId, request: ChatRequest) -> ChatAnswer:
        # A plain def: FastAPI runs it in a worker thread, so a slow LLM never blocks other requests.
        return chat.ask(device_id, request.message.strip(), request.history)

    @app.post("/api/devices/{device_id}/pump/water")
    def water(device_id: DeviceId) -> dict:
        duration = _controls(controls).water_now(device_id)
        log.info("%s  Water now (Next.js dashboard), %g s", device_id, duration)
        return {"ok": True, "duration_s": duration}

    @app.put("/api/devices/{device_id}/pump/auto")
    def auto(device_id: DeviceId, body: AutoWatering) -> dict:
        _controls(controls).set_auto_watering(device_id, body.enabled)
        return {"ok": True, "auto_enabled": body.enabled}

    # ------------------------------------------------------------------ plant profiles

    @app.put("/api/devices/{device_id}/plant")
    def assign_plant(device_id: DeviceId, body: PlantChoice) -> dict:
        # The next reading (within about 10 s) is analysed straight away against the new plant.
        try:
            return plants.assign(device_id, body.key).as_dict()
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from None

    @app.get("/api/plants")
    def list_plants() -> dict:
        known = {d["device_id"] for d in store.devices()} | {default_device}
        in_use = {device: plants.assigned_key(device) for device in known}
        return {
            "default": plants.default_key,
            "plants": [
                {**p.as_dict(), "devices": sorted(d for d, key in in_use.items() if key == p.key)} for p in plants.profiles()
            ],
        }

    @app.post("/api/plants/suggest")
    def suggest_plant(body: PlantName) -> ProfileDraft:
        return profile_agent.draft(body.name)

    @app.post("/api/plants")
    def add_plant(body: PlantInput) -> dict:
        try:
            profile = plants.add(body.name, body.ranges(), body.care_notes, body.scientific_name, body.source)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        log.info("Plant profile added: %s (%s)", profile.name, profile.key)
        return profile.as_dict()

    @app.put("/api/plants/{key}")
    def update_plant(key: PlantKey, body: PlantInput) -> dict:
        try:
            return plants.update(key, body.name, body.ranges(), body.care_notes, body.scientific_name, body.source).as_dict()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from None

    @app.delete("/api/plants/{key}")
    def delete_plant(key: PlantKey) -> dict:
        try:
            moved = plants.delete(key)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from None
        return {"ok": True, "moved_to_default": moved}

    # ------------------------------------------------------------------ email alerts
    # Plain defs: sending a code or a test email waits for the mail server, in a worker thread.

    @app.exception_handler(AlertsError)
    def alerts_error(request: Request, exc: AlertsError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/alerts")
    def alert_overview() -> dict:
        return _alerts(alerts).overview()

    @app.post("/api/alerts/recipients", status_code=201)
    def add_recipient(body: NewRecipient) -> dict:
        return _alerts(alerts).add(body.email)

    @app.post("/api/alerts/recipients/{recipient_id}/verify")
    def verify_recipient(recipient_id: RecipientId, body: SignUpCode) -> dict:
        return _alerts(alerts).verify(recipient_id, body.code)

    @app.post("/api/alerts/recipients/{recipient_id}/code")
    def resend_code(recipient_id: RecipientId) -> dict:
        return _alerts(alerts).resend_code(recipient_id)

    @app.put("/api/alerts/recipients/{recipient_id}")
    def update_recipient(recipient_id: RecipientId, body: RecipientPrefs) -> dict:
        return _alerts(alerts).update(recipient_id, body.alerts, body.min_priority, body.daily)

    @app.delete("/api/alerts/recipients/{recipient_id}")
    def remove_recipient(recipient_id: RecipientId) -> dict:
        _alerts(alerts).remove(recipient_id)
        return {"ok": True}

    @app.post("/api/alerts/recipients/{recipient_id}/test")
    def send_test_email(recipient_id: RecipientId) -> dict:
        _alerts(alerts).send_test(recipient_id)
        return {"ok": True}

    # ------------------------------------------------------------------ dashboard accounts
    # Plain defs: password hashing is slow on purpose, so it runs in a worker thread.

    @app.exception_handler(AccountsError)
    def accounts_error(request: Request, exc: AccountsError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/auth/me")
    def me(request: Request) -> dict:
        account = accounts.account_for(request.cookies.get(SESSION_COOKIE)) if accounts else None
        return {
            "account": account.public() if account else None,
            "registration_open": bool(accounts and accounts.registration_open),
        }

    @app.post("/api/auth/register", status_code=201)
    def register(body: Registration, request: Request, response: Response) -> dict:
        account, token = _accounts(accounts).register(body.name, body.email, body.password, body.code)
        _set_session(response, request, token)
        return {"account": account.public()}

    @app.post("/api/auth/login")
    def login(body: SignIn, request: Request, response: Response) -> dict:
        account, token = _accounts(accounts).sign_in(body.email, body.password)
        _set_session(response, request, token)
        return {"account": account.public()}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict:
        if accounts:
            accounts.sign_out(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    return app


def _controls(controls: PumpControls | None) -> PumpControls:
    if controls is None:
        raise HTTPException(503, "Pump controls are not available")
    return controls


def _alerts(alerts: AlertCenter | None) -> AlertCenter:
    if alerts is None:
        raise HTTPException(503, "Email alerts are not available")
    return alerts


def _accounts(accounts: Accounts | None) -> Accounts:
    if accounts is None:
        raise HTTPException(503, "Dashboard accounts are not available")
    return accounts


def _set_session(response: Response, request: Request, token: str) -> None:
    # Secure when the browser came in over HTTPS (Nginx sets X-Forwarded-Proto and Next.js passes it on);
    # plain http://localhost while developing.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https",
    )


def serve_in_background(app: FastAPI, host: str, port: int) -> threading.Thread:
    """Run the API in a daemon thread; the MQTT loop keeps the main thread."""
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, name="dashboard-api", daemon=True)
    thread.start()
    return thread
