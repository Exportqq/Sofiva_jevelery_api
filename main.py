from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from uuid import uuid4
import os
import requests

DATABASE_URL = os.getenv("DATABASE_URL")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

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
# DTO
# =====================

class RequestDTO(BaseModel):
    name: str
    phone: str
    comment: str | None = None


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