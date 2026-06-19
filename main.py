from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from uuid import uuid4
import os

DATABASE_URL = os.getenv("DATABASE_URL")

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
# MODEL
# =====================

class Request(Base):
    __tablename__ = "requests"

    id = Column(String, primary_key=True)
    name = Column(String)
    phone = Column(String)
    comment = Column(Text)
    status = Column(String, default="new")


Base.metadata.create_all(bind=engine)

# =====================
# DTO
# =====================

class RequestDTO(BaseModel):
    name: str
    phone: str
    comment: str | None = None


class RequestStatusDTO(BaseModel):
    status: str


# =====================
# 1. СОЗДАНИЕ ЗАЯВКИ
# =====================

@app.post("/requests")
def create_request(data: RequestDTO):
    db = SessionLocal()
    try:
        req = Request(
            id=str(uuid4()),
            name=data.name,
            phone=data.phone,
            comment=data.comment,
            status="new"
        )
        db.add(req)
        db.commit()
        return {"ok": True, "id": req.id}
    finally:
        db.close()


# =====================
# 2. ВСЕ ЗАЯВКИ
# =====================

@app.get("/requests")
def get_requests():
    db = SessionLocal()
    try:
        return db.query(Request).all()
    finally:
        db.close()


# =====================
# 3. ИЗМЕНЕНИЕ СТАТУСА
# =====================

@app.patch("/requests/{request_id}/status")
def update_request_status(request_id: str, data: RequestStatusDTO):
    allowed = ["new", "in_progress", "done"]

    if data.status not in allowed:
        raise HTTPException(400, f"Status must be one of: {allowed}")

    db = SessionLocal()
    try:
        req = db.query(Request).filter(Request.id == request_id).first()

        if not req:
            raise HTTPException(404, "Not found")

        req.status = data.status
        db.commit()

        return {"ok": True}
    finally:
        db.close()


# =====================
# 4. УДАЛЕНИЕ ЗАЯВКИ
# =====================

@app.delete("/requests/{request_id}")
def delete_request(request_id: str):
    db = SessionLocal()
    try:
        req = db.query(Request).filter(Request.id == request_id).first()

        if not req:
            raise HTTPException(404, "Not found")

        db.delete(req)
        db.commit()

        return {"ok": True}
    finally:
        db.close()


# =====================
# ROOT
# =====================

@app.get("/")
def root():
    return {"status": "ok"}