from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, String, Text, Float, Numeric, ARRAY
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic import BaseModel
from uuid import uuid4
from typing import Optional, List
import os
import boto3
from botocore.client import Config

DATABASE_URL = os.getenv("DATABASE_URL")

VK_ACCESS_KEY_ID     = os.getenv("VK_ACCESS_KEY_ID")
VK_SECRET_ACCESS_KEY = os.getenv("VK_SECRET_ACCESS_KEY")
VK_BUCKET            = os.getenv("VK_BUCKET", "sofiva-products")
VK_ENDPOINT          = os.getenv("VK_ENDPOINT", "https://hb.vkcs.cloud")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

ALLOWED_IPS = {"95.27.149.212"}

# =====================
# S3 CLIENT
# =====================

s3 = boto3.client(
    "s3",
    endpoint_url=VK_ENDPOINT,
    aws_access_key_id=VK_ACCESS_KEY_ID,
    aws_secret_access_key=VK_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="ru-msk",
)

def s3_public_url(filename: str) -> str:
    """Постоянная публичная ссылка на файл в VK Cloud S3."""
    return f"{VK_ENDPOINT}/{VK_BUCKET}/{filename}"

def s3_upload(filename: str, data: bytes, content_type: str) -> None:
    s3.put_object(
        Bucket=VK_BUCKET,
        Key=filename,
        Body=data,
        ContentType=content_type,
        ACL="public-read",
    )

def s3_delete(filename: str) -> None:
    s3.delete_object(Bucket=VK_BUCKET, Key=filename)


# =====================
# НАСТРОЙКА ДОСТУПА
# =====================

ACCESS = {
    "POST /requests": True,
    "GET /requests": False,
    "PATCH /requests/{id}/status": False,
    "DELETE /requests/{id}": False,
    "GET /docs": False,
    "GET /redoc": False,
    "GET /openapi.json": False,

    "GET /products": True,
    "GET /products/{id}": True,
    "POST /products": False,
    "PATCH /products/{id}": False,
    "DELETE /products/{id}": False,

    "POST /upload": False,
}

app = FastAPI()


# =====================
# IP WHITELIST
# =====================

def match_route(method: str, path: str) -> bool:
    for route, is_public in ACCESS.items():
        r_method, r_path = route.split(" ", 1)
        if method != r_method:
            continue
        if path == r_path:
            return is_public
        r_parts = r_path.split("/")
        p_parts = path.split("/")
        if len(r_parts) != len(p_parts):
            continue
        if all(r == p or r.startswith("{") for r, p in zip(r_parts, p_parts)):
            return is_public
    return True


@app.middleware("http")
async def ip_whitelist(request: Request, call_next):
    is_public = match_route(request.method, request.url.path)
    if not is_public:
        client_ip = request.client.host
        if client_ip not in ALLOWED_IPS:
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


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

class RequestModel(Base):
    __tablename__ = "requests"

    id      = Column(String, primary_key=True)
    name    = Column(String)
    phone   = Column(String)
    comment = Column(Text)
    status  = Column(String, default="new")


class Product(Base):
    __tablename__ = "products"

    id       = Column(String, primary_key=True)
    name     = Column(String, nullable=False)
    category = Column(String, nullable=False)
    brand    = Column(String, nullable=False)
    material = Column(String, nullable=False)
    size     = Column(ARRAY(Float), nullable=False)
    weight   = Column(Float, nullable=False)
    price    = Column(Numeric(12, 2), nullable=False)

    # Полные публичные URL из S3
    photo_1 = Column(String, nullable=False)
    photo_2 = Column(String, nullable=True)
    photo_3 = Column(String, nullable=True)
    photo_4 = Column(String, nullable=True)

    # Камень
    stone_type  = Column(String, nullable=True)
    stone_carat = Column(Float, nullable=True)
    stone_shape = Column(String, nullable=True)
    stone_color = Column(String, nullable=True)


Base.metadata.create_all(bind=engine)


# =====================
# HELPERS
# =====================

def product_to_dict(p: Product) -> dict:
    photos = [f for f in [p.photo_1, p.photo_2, p.photo_3, p.photo_4] if f]
    return {
        "id":       p.id,
        "name":     p.name,
        "category": p.category,
        "brand":    p.brand,
        "material": p.material,
        "size":     p.size if isinstance(p.size, list) else p.size,
        "weight":   p.weight,
        "price":    float(p.price),
        "photos":   photos,
        "stone": {
            "type":  p.stone_type,
            "carat": p.stone_carat,
            "shape": p.stone_shape,
            "color": p.stone_color,
        } if p.stone_type else None,
    }


# =====================
# DTO
# =====================

class RequestDTO(BaseModel):
    name: str
    phone: str
    comment: str | None = None


class RequestStatusDTO(BaseModel):
    status: str


class ProductCreateDTO(BaseModel):
    name: str
    category: str
    brand: str
    material: str
    size: List[float]
    weight: float
    price: float

    photo_1: str
    photo_2: Optional[str] = None
    photo_3: Optional[str] = None
    photo_4: Optional[str] = None

    stone_type:  Optional[str]   = None
    stone_carat: Optional[float] = None
    stone_shape: Optional[str]   = None
    stone_color: Optional[str]   = None


class ProductUpdateDTO(BaseModel):
    name:     Optional[str]        = None
    category: Optional[str]        = None
    brand:    Optional[str]        = None
    material: Optional[str]        = None
    size:     Optional[List[float]] = None
    weight:   Optional[float]      = None
    price:    Optional[float]      = None

    photo_1: Optional[str] = None
    photo_2: Optional[str] = None
    photo_3: Optional[str] = None
    photo_4: Optional[str] = None

    stone_type:  Optional[str]   = None
    stone_carat: Optional[float] = None
    stone_shape: Optional[str]   = None
    stone_color: Optional[str]   = None


# =====================
# UPLOAD
# =====================

@app.post("/upload")
async def upload_photo(file: UploadFile = File(...)):
    """Загружает фото в VK Cloud S3, возвращает публичный URL."""
    ext      = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    filename = f"{uuid4()}{ext}"
    data     = await file.read()

    try:
        s3_upload(filename, data, file.content_type or "image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {e}")

    url = s3_public_url(filename)
    return {"filename": filename, "url": url}


# =====================
# REQUESTS ENDPOINTS
# =====================

@app.post("/requests")
def create_request(data: RequestDTO):
    db = SessionLocal()
    try:
        req = RequestModel(
            id=str(uuid4()),
            name=data.name,
            phone=data.phone,
            comment=data.comment,
            status="new",
        )
        db.add(req)
        db.commit()
        return {"ok": True, "id": req.id}
    finally:
        db.close()


@app.get("/requests")
def get_requests():
    db = SessionLocal()
    try:
        return [{
            "id":      r.id,
            "name":    r.name,
            "phone":   r.phone,
            "comment": r.comment,
            "status":  r.status,
        } for r in db.query(RequestModel).all()]
    finally:
        db.close()


@app.patch("/requests/{request_id}/status")
def update_request_status(request_id: str, data: RequestStatusDTO):
    allowed = ["new", "in_progress", "done"]
    if data.status not in allowed:
        raise HTTPException(400, f"Status must be one of: {allowed}")
    db = SessionLocal()
    try:
        req = db.query(RequestModel).filter(RequestModel.id == request_id).first()
        if not req:
            raise HTTPException(404, "Not found")
        req.status = data.status
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.delete("/requests/{request_id}")
def delete_request(request_id: str):
    db = SessionLocal()
    try:
        req = db.query(RequestModel).filter(RequestModel.id == request_id).first()
        if not req:
            raise HTTPException(404, "Not found")
        db.delete(req)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# =====================
# PRODUCTS ENDPOINTS
# =====================

@app.get("/products")
def get_products():
    db = SessionLocal()
    try:
        return [product_to_dict(p) for p in db.query(Product).all()]
    finally:
        db.close()


@app.get("/products/{product_id}")
def get_product(product_id: str):
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(404, "Product not found")
        return product_to_dict(product)
    finally:
        db.close()


@app.post("/products")
def create_product(data: ProductCreateDTO):
    db = SessionLocal()
    try:
        product = Product(id=str(uuid4()), **data.model_dump())
        db.add(product)
        db.commit()
        return {"ok": True, "id": product.id}
    finally:
        db.close()


@app.patch("/products/{product_id}")
def update_product(product_id: str, data: ProductUpdateDTO):
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(404, "Product not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(product, field, value)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.delete("/products/{product_id}")
def delete_product(product_id: str):
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(404, "Product not found")

        # Удаляем файлы из S3
        for url in [product.photo_1, product.photo_2, product.photo_3, product.photo_4]:
            if url:
                # Извлекаем filename из полного URL
                filename = url.split(f"/{VK_BUCKET}/")[-1]
                try:
                    s3_delete(filename)
                except Exception:
                    pass

        db.delete(product)
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