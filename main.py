import os
import shutil
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Form, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"sslmode": "require"}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

UPLOAD_DIR = "/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# DATABASE MODELS
# =========================

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


class TokenDB(Base):
    __tablename__ = "tokens"
    token = Column(String, primary_key=True)
    username = Column(String, nullable=False)


class BrandDB(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    image = Column(String, nullable=False)

    cars = relationship("CarDB", back_populates="brand")


class CarDB(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True)

    name = Column(String, nullable=False)
    transmission = Column(String, nullable=False)
    seats = Column(Integer, nullable=False)
    fuel_type = Column(String, nullable=False)

    car_image = Column(String, nullable=False)

    rating = Column(Float, default=0)
    reviews_count = Column(String, default="0")
    horsepower = Column(String, nullable=False)
    max_speed = Column(String, nullable=False)
    characteristics = Column(String, nullable=False)

    price_per_hour = Column(Integer, nullable=False)
    price_per_day = Column(Integer, nullable=False)

    location = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)

    is_favorite = Column(Integer, default=0)

    brand_id = Column(Integer, ForeignKey("brands.id"))
    brand = relationship("BrandDB", back_populates="cars")


class OrderDB(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    status = Column(String, default="new")   # new | in_progress | done
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    items = relationship("OrderItemDB", back_populates="order", cascade="all, delete-orphan")


class OrderItemDB(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False)
    rent_type = Column(String, nullable=False)   # "hour" | "day"
    quantity = Column(Integer, default=1)

    order = relationship("OrderDB", back_populates="items")
    car = relationship("CarDB")


# =========================
# SCHEMAS
# =========================

class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str


class ProfileResponse(BaseModel):
    username: str


class BrandResponse(BaseModel):
    id: int
    name: str
    image: str
    count: int


class Car(BaseModel):
    id: int | None = None
    name: str
    brand: str
    brand_image: str
    transmission: str
    seats: int
    fuel_type: str
    car_image: str
    rating: float
    reviews_count: str
    horsepower: str
    max_speed: str
    characteristics: str
    price_per_hour: int
    price_per_day: int
    location: str
    lat: float
    lng: float
    is_favorite: bool

    model_config = ConfigDict(from_attributes=True)


# --- Order schemas ---

class OrderItemRequest(BaseModel):
    car_id: int
    rent_type: str   # "hour" | "day"
    quantity: int = 1


class OrderRequest(BaseModel):
    name: str
    phone: str
    comment: str | None = None
    items: list[OrderItemRequest]


class OrderItemResponse(BaseModel):
    car_id: int
    car_name: str
    car_image: str
    rent_type: str
    quantity: int
    price_per_hour: int
    price_per_day: int


class OrderResponse(BaseModel):
    id: int
    name: str
    phone: str
    comment: str | None
    status: str
    created_at: datetime
    items: list[OrderItemResponse]


# =========================
# AUTH
# =========================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def get_current_user(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401)

    token = authorization.split(" ")[1]
    db = SessionLocal()

    try:
        token_db = db.query(TokenDB).filter(TokenDB.token == token).first()
        if not token_db:
            raise HTTPException(status_code=401)
        return token_db.username
    finally:
        db.close()


# =========================
# AUTH ENDPOINTS
# =========================

@app.post("/auth/register", response_model=AuthResponse)
def register(data: AuthRequest):
    db = SessionLocal()
    try:
        user = UserDB(
            username=data.username,
            password_hash=hash_password(data.password)
        )
        db.add(user)
        db.commit()

        token = str(uuid4())
        db.add(TokenDB(token=token, username=user.username))
        db.commit()

        return {"token": token, "username": user.username}

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="User exists")
    finally:
        db.close()


@app.post("/auth/login", response_model=AuthResponse)
def login(data: AuthRequest):
    db = SessionLocal()
    try:
        user = db.query(UserDB).filter(UserDB.username == data.username).first()

        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401)

        token = str(uuid4())
        db.add(TokenDB(token=token, username=user.username))
        db.commit()

        return {"token": token, "username": user.username}
    finally:
        db.close()


# =========================
# BRAND ENDPOINTS
# =========================

@app.post("/brands", response_model=BrandResponse)
def create_brand(
    name: str = Form(...),
    image: UploadFile = File(...)
):
    db = SessionLocal()
    try:
        existing = db.query(BrandDB).filter(BrandDB.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Brand exists")

        filename = f"{uuid4()}_{image.filename}"
        path = os.path.join(UPLOAD_DIR, filename)

        with open(path, "wb") as f:
            shutil.copyfileobj(image.file, f)

        brand = BrandDB(
            name=name,
            image=f"/uploads/{filename}"
        )

        db.add(brand)
        db.commit()
        db.refresh(brand)

        return {
            "id": brand.id,
            "name": brand.name,
            "image": brand.image,
            "count": 0
        }

    finally:
        db.close()


@app.get("/brands", response_model=list[BrandResponse])
def get_brands():
    db = SessionLocal()
    try:
        brands = db.query(BrandDB).all()

        return [
            {
                "id": b.id,
                "name": b.name,
                "image": b.image,
                "count": len(b.cars)
            }
            for b in brands
        ]

    finally:
        db.close()


# =========================
# CAR ENDPOINTS
# =========================

@app.post("/cars", response_model=Car)
def create_car(
    name: str = Form(...),
    brand_id: int = Form(...),
    transmission: str = Form(...),
    seats: int = Form(...),
    fuel_type: str = Form(...),
    car_image: UploadFile = File(...),
    horsepower: str = Form(...),
    max_speed: str = Form(...),
    characteristics: str = Form(...),
    price_per_hour: int = Form(...),
    price_per_day: int = Form(...),
    location: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...)
):
    db = SessionLocal()

    try:
        brand = db.query(BrandDB).filter(BrandDB.id == brand_id).first()
        if not brand:
            raise HTTPException(status_code=404, detail="Brand not found")

        filename = f"{uuid4()}_{car_image.filename}"
        path = os.path.join(UPLOAD_DIR, filename)

        with open(path, "wb") as f:
            shutil.copyfileobj(car_image.file, f)

        car = CarDB(
            name=name,
            transmission=transmission,
            seats=seats,
            fuel_type=fuel_type,
            car_image=f"/uploads/{filename}",
            horsepower=horsepower,
            max_speed=max_speed,
            characteristics=characteristics,
            price_per_hour=price_per_hour,
            price_per_day=price_per_day,
            location=location,
            lat=lat,
            lng=lng,
            brand_id=brand.id
        )

        db.add(car)
        db.commit()
        db.refresh(car)

        return Car(
            id=car.id,
            name=car.name,
            brand=brand.name,
            brand_image=brand.image,
            transmission=car.transmission,
            seats=car.seats,
            fuel_type=car.fuel_type,
            car_image=car.car_image,
            rating=car.rating,
            reviews_count=car.reviews_count,
            horsepower=car.horsepower,
            max_speed=car.max_speed,
            characteristics=car.characteristics,
            price_per_hour=car.price_per_hour,
            price_per_day=car.price_per_day,
            location=car.location,
            lat=car.lat,
            lng=car.lng,
            is_favorite=False
        )

    finally:
        db.close()


@app.get("/cars", response_model=list[Car])
def get_cars():
    db = SessionLocal()
    try:
        cars = db.query(CarDB).all()

        return [
            Car(
                id=c.id,
                name=c.name,
                brand=c.brand.name if c.brand else "",
                brand_image=c.brand.image if c.brand else "",
                transmission=c.transmission,
                seats=c.seats,
                fuel_type=c.fuel_type,
                car_image=c.car_image,
                rating=c.rating,
                reviews_count=c.reviews_count,
                horsepower=c.horsepower,
                max_speed=c.max_speed,
                characteristics=c.characteristics,
                price_per_hour=c.price_per_hour,
                price_per_day=c.price_per_day,
                location=c.location,
                lat=c.lat,
                lng=c.lng,
                is_favorite=bool(c.is_favorite)
            )
            for c in cars
        ]

    finally:
        db.close()


@app.get("/cars/{car_id}", response_model=Car)
def get_car(car_id: int):
    db = SessionLocal()
    try:
        c = db.query(CarDB).filter(CarDB.id == car_id).first()

        if not c:
            raise HTTPException(status_code=404)

        return Car(
            id=c.id,
            name=c.name,
            brand=c.brand.name if c.brand else "",
            brand_image=c.brand.image if c.brand else "",
            transmission=c.transmission,
            seats=c.seats,
            fuel_type=c.fuel_type,
            car_image=c.car_image,
            rating=c.rating,
            reviews_count=c.reviews_count,
            horsepower=c.horsepower,
            max_speed=c.max_speed,
            characteristics=c.characteristics,
            price_per_hour=c.price_per_hour,
            price_per_day=c.price_per_day,
            location=c.location,
            lat=c.lat,
            lng=c.lng,
            is_favorite=bool(c.is_favorite)
        )

    finally:
        db.close()


# =========================
# ORDER ENDPOINTS
# =========================

def _build_order_response(order: OrderDB) -> OrderResponse:
    items = []
    for item in order.items:
        car = item.car
        items.append(OrderItemResponse(
            car_id=car.id,
            car_name=car.name,
            car_image=car.car_image,
            rent_type=item.rent_type,
            quantity=item.quantity,
            price_per_hour=car.price_per_hour,
            price_per_day=car.price_per_day,
        ))

    return OrderResponse(
        id=order.id,
        name=order.name,
        phone=order.phone,
        comment=order.comment,
        status=order.status,
        created_at=order.created_at,
        items=items,
    )


@app.post("/orders", response_model=OrderResponse, status_code=201)
def create_order(data: OrderRequest):
    """Создать заявку из корзины. Авторизация не требуется."""
    if not data.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    db = SessionLocal()
    try:
        # Проверяем, что все автомобили существуют
        car_ids = [i.car_id for i in data.items]
        cars_in_db = db.query(CarDB).filter(CarDB.id.in_(car_ids)).all()
        found_ids = {c.id for c in cars_in_db}
        missing = set(car_ids) - found_ids
        if missing:
            raise HTTPException(status_code=404, detail=f"Cars not found: {missing}")

        # Валидация rent_type
        for item in data.items:
            if item.rent_type not in ("hour", "day"):
                raise HTTPException(
                    status_code=400,
                    detail=f"rent_type must be 'hour' or 'day', got '{item.rent_type}'"
                )

        order = OrderDB(
            name=data.name,
            phone=data.phone,
            comment=data.comment,
        )
        db.add(order)
        db.flush()  # получаем order.id до commit

        for item in data.items:
            db.add(OrderItemDB(
                order_id=order.id,
                car_id=item.car_id,
                rent_type=item.rent_type,
                quantity=item.quantity,
            ))

        db.commit()
        db.refresh(order)

        return _build_order_response(order)

    finally:
        db.close()


@app.get("/orders", response_model=list[OrderResponse])
def get_orders(_: str = Depends(get_current_user)):
    """Список всех заявок — только для авторизованных (админ)."""
    db = SessionLocal()
    try:
        orders = db.query(OrderDB).order_by(OrderDB.created_at.desc()).all()
        return [_build_order_response(o) for o in orders]
    finally:
        db.close()


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, _: str = Depends(get_current_user)):
    """Получить конкретную заявку — только для авторизованных."""
    db = SessionLocal()
    try:
        order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return _build_order_response(order)
    finally:
        db.close()


@app.patch("/orders/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    status: str,
    _: str = Depends(get_current_user)
):
    """Сменить статус заявки: new → in_progress → done."""
    if status not in ("new", "in_progress", "done"):
        raise HTTPException(status_code=400, detail="Invalid status")

    db = SessionLocal()
    try:
        order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        order.status = status
        db.commit()
        db.refresh(order)

        return _build_order_response(order)
    finally:
        db.close()


@app.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int, _: str = Depends(get_current_user)):
    """Удалить заявку — только для авторизованных."""
    db = SessionLocal()
    try:
        order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        db.delete(order)
        db.commit()
    finally:
        db.close()


# =========================
# PROFILE
# =========================

@app.get("/profile", response_model=ProfileResponse)
def get_profile(user: str = Depends(get_current_user)):
    return {"username": user}