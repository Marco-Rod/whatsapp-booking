"""Prepara Bella Studio con datos ficticios sin borrar registros ni enviar mensajes."""
import argparse
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def run(day):
    os.chdir(ROOT / "backend")
    from app.core.database import Session, engine
    from app.demo_seed import seed_demo
    try:
        async with Session() as session:
            business_id = await seed_demo(session, day)
        print(f"Bella Studio | {day} | America/Mexico_City")
        print(f"VITE_BUSINESS_ID={business_id}")
        print("Agenda ficticia preparada: 5 citas base (4 confirmadas, 1 cancelada).")
        print("Las citas existentes se conservan; no se simularon envíos ni eventos Calendar.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    from app.demo_seed import parse_day
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="today", help="today o YYYY-MM-DD, hora de Ciudad de México")
    args = parser.parse_args()
    try:
        day = parse_day(args.date)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        asyncio.run(run(day))
    except ValueError as exc:
        parser.exit(1, f"No se aplicó el seed: {exc}\n")
    except OSError:
        parser.exit(1, "No se pudo conectar con PostgreSQL. Inicia la base y revisa DATABASE_URL.\n")
