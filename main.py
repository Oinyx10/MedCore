# main.py - Clean minimal version - March 2025 compatible
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from pydantic import BaseModel
import random
from typing import List

# Database
DATABASE_URL = "sqlite:///hospital.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Models (only the ones your frontend really uses)
class Bed(Base):
    __tablename__ = "beds"
    id = Column(Integer, primary_key=True)
    block = Column(String)
    type = Column(String)
    total = Column(Integer)
    available = Column(Integer)

class QueueToken(Base):
    __tablename__ = "queue_tokens"
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True)
    patient_name = Column(String)
    department = Column(String)
    est_wait_min = Column(Integer)

class MedicineStock(Base):
    __tablename__ = "medicine_stock"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    quantity = Column(Integer)
    threshold = Column(Integer)

class Ambulance(Base):
    __tablename__ = "ambulances"
    id = Column(Integer, primary_key=True)
    number = Column(String)
    location = Column(String)
    eta_min = Column(Integer)

Base.metadata.create_all(engine)

# App
app = FastAPI(title="VitaCare Minimal Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lifespan - seed data once
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        if db.query(Bed).count() == 0:
            print("🌱 Seeding data...")
            db.add_all([
                Bed(block="Main Block", type="ICU", total=42, available=19),
                Bed(block="East Wing", type="General", total=120, available=67),
                Bed(block="Pediatric", type="ICU", total=18, available=4),
            ])
            db.add_all([
                QueueToken(token="A-47", patient_name="Rahul Verma", department="Cardiology", est_wait_min=9),
                QueueToken(token="A-48", patient_name="Meera Patel", department="General", est_wait_min=14),
            ])
            db.add_all([
                MedicineStock(name="Paracetamol 500mg", quantity=18, threshold=30),
                MedicineStock(name="Amoxicillin 250mg", quantity=142, threshold=50),
                MedicineStock(name="Insulin Vial", quantity=3, threshold=10),
            ])
            db.add_all([
                Ambulance(number="AMB-392", location="2.4 km away", eta_min=4),
                Ambulance(number="AMB-401", location="5.1 km away", eta_min=11),
            ])
            db.commit()
            print("✅ Data seeded")
    finally:
        db.close()
    yield

app.router.lifespan_context = lifespan

# WebSocket managers
class ConnectionManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        for d in disconnected:
            self.disconnect(d)

queue_m = ConnectionManager()
bed_m   = ConnectionManager()
stock_m = ConnectionManager()
amb_m   = ConnectionManager()

# ─── Endpoints your frontend calls ───────────────────────────────

@app.get("/api/queue")
def get_queue(db: Session = Depends(get_db)):
    return [
        {"token": t.token, "patient_name": t.patient_name, "department": t.department, "est_wait_min": t.est_wait_min}
        for t in db.query(QueueToken).all()
    ]

@app.post("/api/queue/scan")
async def scan(db: Session = Depends(get_db)):
    token = f"A-{random.randint(50, 999)}"
    new = QueueToken(token=token, patient_name="New Patient", department="General", est_wait_min=random.randint(5, 30))
    db.add(new)
    db.commit()
    await queue_m.broadcast({"type": "new_token", "token": token})
    return {"token": token}

@app.websocket("/ws/queue")
async def ws_queue(ws: WebSocket):
    await queue_m.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        queue_m.disconnect(ws)

@app.get("/api/beds")
def get_beds(db: Session = Depends(get_db)):
    return [
        {"id": b.id, "block": b.block, "type": b.type, "available": b.available, "total": b.total}
        for b in db.query(Bed).all()
    ]

@app.websocket("/ws/beds")
async def ws_beds(ws: WebSocket):
    await bed_m.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        bed_m.disconnect(ws)

@app.get("/api/stock")
def get_stock(db: Session = Depends(get_db)):
    items = db.query(MedicineStock).all()
    return [
        {"name": s.name, "quantity": s.quantity, "status": "LOW" if s.quantity < s.threshold else "OK"}
        for s in items
    ]

@app.websocket("/ws/stock")
async def ws_stock(ws: WebSocket):
    await stock_m.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        stock_m.disconnect(ws)

@app.get("/api/ambulances")
def get_ambulances(db: Session = Depends(get_db)):
    return [
        {"number": a.number, "location": a.location, "eta_min": a.eta_min}
        for a in db.query(Ambulance).all()
    ]

@app.websocket("/ws/ambulance")
async def ws_ambulance(ws: WebSocket):
    await amb_m.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        amb_m.disconnect(ws)

# Minimal stubs for remaining endpoints
@app.post("/api/prescriptions")
async def prescriptions(): return {"message": "Prescription sent"}

@app.post("/api/symptoms/check")
async def symptoms(): return {"possible_conditions": ["Viral Fever"], "recommendation": "See doctor"}

@app.get("/api/patients/{pid}/history")
async def history(pid: str): return {"name": "Sample", "last_visit": "2026-03"}

@app.get("/api/opd/slots")
async def opd_slots(): return [{"time": "10:00", "booked": False}]

@app.post("/api/opd/book")
async def book_opd(): return {"message": "Booked"}

@app.get("/api/blood/search")
async def blood(group: str = Query(...)): return {"donors": ["Bank"]}

@app.get("/api/navigation/directions")
async def nav(): return {"directions": ["Walk straight"]}

# Run
if __name__ == "__main__":
    import uvicorn
    print("Starting server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)