from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext
from uuid import uuid4
from datetime import datetime, timedelta
import os
import requests

# =====================
# CONFIG
# =====================

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY", "secret")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")

ALGORITHM = "HS256"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================
# MODELS
# =====================

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    username = Column(String, unique=True)
    password = Column(String)


class Request(Base):
    __tablename__ = "requests"

    id = Column(String, primary_key=True)
    name = Column(String)
    phone = Column(String)
    comment = Column(Text)


class Jewelry(Base):
    __tablename__ = "jewelry"

    id = Column(String, primary_key=True)
    image_url = Column(String)


Base.metadata.create_all(bind=engine)


# =====================
# UTILS
# =====================

def hash_password(p): return pwd_context.hash(p)
def verify_password(p, h): return pwd_context.verify(p, h)

def create_token(user_id: str):
    return jwt.encode(
        {"sub": user_id, "exp": datetime.utcnow() + timedelta(days=7)},
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user(token: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(401, "Invalid token")


# =====================
# AUTH DTO
# =====================

class AuthDTO(BaseModel):
    username: str
    password: str


# =====================
# REQUEST DTO
# =====================

class RequestDTO(BaseModel):
    name: str
    phone: str
    comment: str | None = None


# =====================
# AUTH
# =====================

@app.post("/auth/register")
def register(data: AuthDTO):
    db = SessionLocal()

    try:
        exists = db.query(User).filter(User.username == data.username).first()
        if exists:
            raise HTTPException(400, "User exists")

        user = User(
            id=str(uuid4()),
            username=data.username,
            password=hash_password(data.password)
        )

        db.add(user)
        db.commit()

        return {"ok": True}

    finally:
        db.close()


@app.post("/auth/login")
def login(data: AuthDTO):
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.username == data.username).first()

        if not user or not verify_password(data.password, user.password):
            raise HTTPException(400, "Invalid credentials")

        return {
            "token": create_token(user.id)
        }

    finally:
        db.close()


@app.get("/auth/me")
def me(user_id=Depends(get_user)):
    return {"user_id": user_id}


# =====================
# REQUESTS
# =====================

@app.post("/requests")
def create_request(data: RequestDTO):
    db = SessionLocal()

    try:
        req = Request(
            id=str(uuid4()),
            name=data.name,
            phone=data.phone,
            comment=data.comment
        )

        db.add(req)
        db.commit()

        return {"ok": True}

    finally:
        db.close()


@app.get("/requests")
def get_requests():
    db = SessionLocal()

    try:
        return db.query(Request).all()

    finally:
        db.close()


# =====================
# YANDEX DISK UPLOAD
# =====================

def upload_to_yandex(file: UploadFile):
    headers = {"Authorization": f"OAuth {YANDEX_TOKEN}"}

    filename = f"{uuid4()}_{file.filename}"

    r = requests.get(
        "https://cloud-api.yandex.net/v1/disk/resources/upload",
        headers=headers,
        params={"path": f"/jewelry/{filename}", "overwrite": "true"}
    )

    upload_url = r.json()["href"]

    requests.put(upload_url, files={"file": file.file})

    requests.put(
        "https://cloud-api.yandex.net/v1/disk/resources/publish",
        headers=headers,
        params={"path": f"/jewelry/{filename}"}
    )

    info = requests.get(
        "https://cloud-api.yandex.net/v1/disk/resources",
        headers=headers,
        params={"path": f"/jewelry/{filename}"}
    )

    return info.json()["public_url"]


# =====================
# JEWELRY
# =====================

@app.post("/cards/upload")
def upload_card(file: UploadFile = File(...)):
    db = SessionLocal()

    try:
        url = upload_to_yandex(file)

        card = Jewelry(
            id=str(uuid4()),
            image_url=url
        )

        db.add(card)
        db.commit()

        return {"image_url": url}

    finally:
        db.close()


@app.get("/cards")
def get_cards():
    db = SessionLocal()

    try:
        return db.query(Jewelry).all()

    finally:
        db.close()


# =====================
# ROOT
# =====================

@app.get("/")
def root():
    return {"status": "ok"}