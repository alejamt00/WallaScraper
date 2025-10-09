from db import SessionLocal, User, SavedSearch
from datetime import datetime

def main():
    with SessionLocal() as s:
        users = s.query(User).all()
        if not users:
            print("📭 No hay usuarios en la base de datos.")
            return

        for u in users:
            estado = "✅ activo" if u.active else "⛔ inactivo"
            creado = datetime.fromtimestamp(u.created_at).strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n👤 Usuario {u.id} ({u.username}) - {estado} - creado {creado}")

            if not u.searches:
                print("   📭 Sin búsquedas guardadas")
            else:
                for ss in u.searches:
                    creado_ss = datetime.fromtimestamp(ss.created_at).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"   🔎 [{ss.id}] {ss.query} (guardada {creado_ss})")

if __name__ == "__main__":
    main()

