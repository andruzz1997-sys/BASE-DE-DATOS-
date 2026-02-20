from __future__ import annotations

from calendar import monthrange
from io import BytesIO
import os
import sqlite3
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
import sys
from typing import Any, Callable

from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


APP_NAME = "ServiskynetControl"


def has_resource_assets(base_dir: Path) -> bool:
    templates_dir = base_dir / "templates"
    static_dir = base_dir / "static"
    return (
        (templates_dir / "login.html").exists()
        and templates_dir.is_dir()
        and static_dir.is_dir()
    )


def get_resource_base_dir() -> Path:
    script_dir = Path(__file__).resolve().parent
    working_dir = Path.cwd().resolve()
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass))
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "_internal",
                exe_dir,
            ]
        )

    candidates.extend(
        [
            script_dir,
            working_dir,
            script_dir / "_internal",
            working_dir / "_internal",
            script_dir / "dist" / APP_NAME / "_internal",
            working_dir / "dist" / APP_NAME / "_internal",
            script_dir / "BASE DE DATOS",
            working_dir / "BASE DE DATOS",
            script_dir.parent,
            script_dir.parent / "BASE DE DATOS",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if has_resource_assets(resolved):
            return resolved

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent / "_internal"
    return script_dir


def get_data_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        local_appdata = os.getenv("LOCALAPPDATA")
        base_dir = Path(local_appdata) / APP_NAME if local_appdata else Path.home() / APP_NAME
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    return Path(__file__).resolve().parent


RESOURCE_DIR = get_resource_base_dir()
DATA_DIR = get_data_base_dir()
DB_PATH = DATA_DIR / "empresa.db"

if not has_resource_assets(RESOURCE_DIR):
    print(
        "ADVERTENCIA: No se encontraron templates/static en la carpeta esperada.",
        file=sys.stderr,
    )
    print(f"RESOURCE_DIR actual: {RESOURCE_DIR}", file=sys.stderr)


def ensure_db_seeded() -> None:
    bundled_db = RESOURCE_DIR / "empresa.db"
    if not DB_PATH.exists() and bundled_db.exists():
        shutil.copy2(bundled_db, DB_PATH)


ensure_db_seeded()

DEFAULT_PRODUCTS = [
    ("Copias", 200.0),
    ("Escaneo", 500.0),
    ("Impresiones B/N", 300.0),
    ("Impresiones Color", 700.0),
]

DEFAULT_USERS = [
    ("admin", "Pisoton5920", "admin"),
    ("usuario", "usuario123", "usuario"),
]

VALID_MOVEMENT_TYPES = {"INGRESO", "RETIRO", "RECOLECCION", "AJUSTE"}
SALE_PAYMENT_CASH = "EFECTIVO"
SALE_PAYMENT_TRANSFER = "TRANSFERENCIA"
VALID_SALE_PAYMENT_METHODS = {SALE_PAYMENT_CASH, SALE_PAYMENT_TRANSFER}


app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.config["SECRET_KEY"] = "serviskynet-cambiar-clave-segura"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    conn.execute("PRAGMA busy_timeout = 15000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'usuario')),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                default_price REAL NOT NULL CHECK(default_price >= 0)
            );

            CREATE TABLE IF NOT EXISTS daily_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_date TEXT NOT NULL UNIQUE,
                opening_base REAL NOT NULL CHECK(opening_base >= 0)
            );

            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_date TEXT NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                total_amount REAL NOT NULL CHECK(total_amount >= 0),
                payment_method TEXT NOT NULL DEFAULT 'EFECTIVO' CHECK(payment_method IN ('EFECTIVO', 'TRANSFERENCIA')),
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);

            CREATE TABLE IF NOT EXISTS envelope_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                move_date TEXT NOT NULL,
                move_type TEXT NOT NULL CHECK(move_type IN ('INGRESO', 'RETIRO', 'RECOLECCION', 'AJUSTE')),
                amount REAL NOT NULL CHECK(amount >= 0),
                note TEXT DEFAULT '',
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_envelope_move_date ON envelope_movements(move_date);

            CREATE TABLE IF NOT EXISTS envelope_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL UNIQUE,
                week_end TEXT NOT NULL,
                actual_amount REAL NOT NULL CHECK(actual_amount >= 0),
                note TEXT DEFAULT '',
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS certificates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cert_date TEXT NOT NULL,
                certificate_type TEXT NOT NULL,
                matricula_number TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
                total_amount REAL NOT NULL CHECK(total_amount >= 0),
                payment_method TEXT NOT NULL DEFAULT 'EFECTIVO' CHECK(payment_method IN ('EFECTIVO', 'TRANSFERENCIA')),
                note TEXT DEFAULT '',
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_cert_date ON certificates(cert_date);

            CREATE TABLE IF NOT EXISTS internet_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,
                service_name TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount >= 0),
                note TEXT DEFAULT '',
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_internet_record_date ON internet_records(record_date);

            CREATE TABLE IF NOT EXISTS daily_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                close_date TEXT NOT NULL,
                opening_base REAL NOT NULL DEFAULT 0 CHECK(opening_base >= 0),
                sales_count INTEGER NOT NULL DEFAULT 0 CHECK(sales_count >= 0),
                sales_total REAL NOT NULL DEFAULT 0 CHECK(sales_total >= 0),
                certificates_count INTEGER NOT NULL DEFAULT 0 CHECK(certificates_count >= 0),
                certificates_total REAL NOT NULL DEFAULT 0 CHECK(certificates_total >= 0),
                withdrawals_total REAL NOT NULL DEFAULT 0 CHECK(withdrawals_total >= 0),
                income_total REAL NOT NULL DEFAULT 0 CHECK(income_total >= 0),
                adjustment_total REAL NOT NULL DEFAULT 0 CHECK(adjustment_total >= 0),
                collection_total REAL NOT NULL DEFAULT 0 CHECK(collection_total >= 0),
                net_total REAL NOT NULL DEFAULT 0 CHECK(net_total >= 0),
                note TEXT DEFAULT '',
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_closures_date ON daily_closures(close_date);
            """
        )

        ensure_column(
            conn,
            "sales",
            "created_by_user_id",
            "created_by_user_id INTEGER REFERENCES users(id)",
        )
        ensure_column(
            conn,
            "envelope_movements",
            "created_by_user_id",
            "created_by_user_id INTEGER REFERENCES users(id)",
        )
        ensure_column(
            conn,
            "envelope_checks",
            "created_by_user_id",
            "created_by_user_id INTEGER REFERENCES users(id)",
        )
        ensure_column(
            conn,
            "daily_base",
            "is_closed",
            "is_closed INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "daily_base",
            "closure_id",
            "closure_id INTEGER",
        )
        ensure_column(
            conn,
            "sales",
            "is_closed",
            "is_closed INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "sales",
            "closure_id",
            "closure_id INTEGER",
        )
        ensure_column(
            conn,
            "sales",
            "payment_method",
            "payment_method TEXT NOT NULL DEFAULT 'EFECTIVO'",
        )
        ensure_column(
            conn,
            "certificates",
            "quantity",
            "quantity INTEGER NOT NULL DEFAULT 1",
        )
        ensure_column(
            conn,
            "certificates",
            "payment_method",
            "payment_method TEXT NOT NULL DEFAULT 'EFECTIVO'",
        )
        ensure_column(
            conn,
            "certificates",
            "is_closed",
            "is_closed INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "certificates",
            "closure_id",
            "closure_id INTEGER",
        )
        ensure_column(
            conn,
            "envelope_movements",
            "is_closed",
            "is_closed INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "envelope_movements",
            "closure_id",
            "closure_id INTEGER",
        )

        conn.executemany(
            """
            INSERT OR IGNORE INTO products (name, default_price)
            VALUES (?, ?)
            """,
            DEFAULT_PRODUCTS,
        )

        conn.execute(
            """
            UPDATE sales
            SET payment_method = 'EFECTIVO'
            WHERE payment_method IS NULL OR trim(payment_method) = ''
            """
        )
        conn.execute(
            """
            UPDATE sales
            SET payment_method = 'TRANSFERENCIA'
            WHERE upper(trim(payment_method)) IN ('TRANSFERENCIA', 'NEQUI')
            """
        )
        conn.execute(
            """
            UPDATE sales
            SET payment_method = 'EFECTIVO'
            WHERE upper(trim(payment_method)) NOT IN ('EFECTIVO', 'TRANSFERENCIA')
            """
        )
        conn.execute(
            """
            UPDATE certificates
            SET payment_method = 'EFECTIVO'
            WHERE payment_method IS NULL OR trim(payment_method) = ''
            """
        )
        conn.execute(
            """
            UPDATE certificates
            SET payment_method = 'TRANSFERENCIA'
            WHERE upper(trim(payment_method)) IN ('TRANSFERENCIA', 'NEQUI')
            """
        )
        conn.execute(
            """
            UPDATE certificates
            SET payment_method = 'EFECTIVO'
            WHERE upper(trim(payment_method)) NOT IN ('EFECTIVO', 'TRANSFERENCIA')
            """
        )

        for username, password, role in DEFAULT_USERS:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (username, password_hash, role)
                VALUES (?, ?, ?)
                """,
                (username, generate_password_hash(password), role),
            )


def parse_date(value: str, field_name: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        return parsed.isoformat()
    except Exception as exc:
        raise ValueError(f"Fecha invalida en {field_name}.") from exc


def parse_positive_int(value: str, field_name: str) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} debe ser un numero entero.") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} debe ser mayor que cero.")
    return parsed


def parse_non_negative_int(value: str, field_name: str) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} debe ser un numero entero.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} no puede ser negativo.")
    return parsed


def parse_non_negative_float(value: str, field_name: str) -> float:
    raw = (value or "").strip()
    if not raw:
        raise ValueError(f"{field_name} debe ser un numero valido.")

    normalized = raw.replace(" ", "").replace("$", "").replace("\u00A0", "")

    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        if normalized.count(",") == 1:
            left, right = normalized.split(",")
            if len(right) <= 2:
                normalized = left.replace(".", "") + "." + right
            else:
                normalized = left + right
        else:
            parts = normalized.split(",")
            if len(parts[-1]) <= 2:
                normalized = "".join(parts[:-1]) + "." + parts[-1]
            else:
                normalized = "".join(parts)
    elif "." in normalized:
        if normalized.count(".") == 1:
            left, right = normalized.split(".")
            if len(right) == 3 and left.isdigit() and right.isdigit():
                normalized = left + right
        else:
            parts = normalized.split(".")
            if len(parts[-1]) <= 2:
                normalized = "".join(parts[:-1]) + "." + parts[-1]
            else:
                normalized = "".join(parts)

    try:
        parsed = float(normalized)
    except Exception as exc:
        raise ValueError(f"{field_name} debe ser un numero valido.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} no puede ser negativo.")
    return round(parsed, 2)


def parse_sale_payment_method(value: str) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        return SALE_PAYMENT_CASH
    if normalized in VALID_SALE_PAYMENT_METHODS:
        return normalized
    if normalized == "NEQUI":
        return SALE_PAYMENT_TRANSFER
    raise ValueError("Metodo de pago invalido para la venta.")


def get_monday(any_day: date) -> date:
    return any_day - timedelta(days=any_day.weekday())


def week_range_from_start(week_start: str) -> tuple[str, str]:
    start = datetime.strptime(week_start, "%Y-%m-%d").date()
    monday = get_monday(start)
    end = monday + timedelta(days=6)
    return monday.isoformat(), end.isoformat()


def format_money(value: float) -> str:
    rendered = f"{value:,.2f}"
    rendered = rendered.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"${rendered}"


@app.template_filter("money")
def money_filter(value: Any) -> str:
    try:
        return format_money(float(value or 0))
    except Exception:
        return "$0,00"


def get_current_user() -> dict[str, Any] | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return {
        "id": user_id,
        "username": session.get("username"),
        "role": session.get("role"),
    }


def is_admin_user() -> bool:
    return session.get("role") == "admin"


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not get_current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*allowed_roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if not user:
                return redirect(url_for("login"))
            if user["role"] not in allowed_roles:
                flash("No tienes permisos para esta accion.", "danger")
                return redirect(url_for("index"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


@app.context_processor
def inject_user_context() -> dict[str, Any]:
    user = get_current_user()
    return {
        "is_logged_in": user is not None,
        "is_admin": user is not None and user["role"] == "admin",
        "current_role": user["role"] if user else None,
        "current_username": user["username"] if user else None,
    }


def redirect_to_next(default_endpoint: str) -> Any:
    next_path = (
        (request.form.get("next", "") or request.args.get("next", "") or "").strip()
    )
    if next_path.startswith("/"):
        return redirect(next_path)
    return redirect(url_for(default_endpoint))


def resolve_closure_actor_user_id(
    conn: sqlite3.Connection,
    preferred_user_id: int | None = None,
) -> int | None:
    if preferred_user_id is not None:
        user_row = conn.execute(
            "SELECT id FROM users WHERE id = ? AND COALESCE(is_active, 1) = 1",
            (preferred_user_id,),
        ).fetchone()
        if user_row:
            return int(user_row["id"])

    admin_row = conn.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'admin' AND COALESCE(is_active, 1) = 1
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()
    if admin_row:
        return int(admin_row["id"])

    fallback_row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if fallback_row:
        return int(fallback_row["id"])
    return None


def close_open_day_records(
    conn: sqlite3.Connection,
    close_date: str,
    created_by_user_id: int | None,
    note: str = "",
    raise_if_empty: bool = True,
) -> int | None:
    base_row = conn.execute(
        """
        SELECT id, opening_base
        FROM daily_base
        WHERE day_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (close_date,),
    ).fetchone()

    sales_row = conn.execute(
        """
        SELECT
            COUNT(*) AS records_count,
            COALESCE(
                SUM(
                    CASE
                        WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                        ELSE total_amount
                    END
                ),
                0
            ) AS total_amount
        FROM sales
        WHERE sale_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (close_date,),
    ).fetchone()

    certificates_row = conn.execute(
        """
        SELECT
            COUNT(*) AS records_count,
            COALESCE(SUM(total_amount), 0) AS total_amount
        FROM certificates
        WHERE cert_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (close_date,),
    ).fetchone()

    movements_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN move_type = 'RETIRO' THEN amount ELSE 0 END), 0) AS withdrawals_total,
            COALESCE(SUM(CASE WHEN move_type = 'INGRESO' THEN amount ELSE 0 END), 0) AS income_total,
            COALESCE(SUM(CASE WHEN move_type = 'AJUSTE' THEN amount ELSE 0 END), 0) AS adjustment_total,
            COALESCE(SUM(CASE WHEN move_type = 'RECOLECCION' THEN amount ELSE 0 END), 0) AS collection_total
        FROM envelope_movements
        WHERE move_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (close_date,),
    ).fetchone()

    opening_base = float(base_row["opening_base"] if base_row else 0.0)
    sales_count = int(sales_row["records_count"] or 0)
    sales_total = round(float(sales_row["total_amount"] or 0.0), 2)
    certificates_count = int(certificates_row["records_count"] or 0)
    certificates_total = round(float(certificates_row["total_amount"] or 0.0), 2)
    withdrawals_total = round(float(movements_row["withdrawals_total"] or 0.0), 2)
    income_total = round(float(movements_row["income_total"] or 0.0), 2)
    adjustment_total = round(float(movements_row["adjustment_total"] or 0.0), 2)
    collection_total = round(float(movements_row["collection_total"] or 0.0), 2)

    has_data = any(
        [
            opening_base > 0,
            sales_count > 0,
            certificates_count > 0,
            withdrawals_total > 0,
            income_total > 0,
            adjustment_total > 0,
            collection_total > 0,
        ]
    )
    if not has_data:
        if raise_if_empty:
            raise ValueError("No hay datos abiertos para guardar en esa fecha.")
        return None

    net_total = round(
        opening_base
        + sales_total
        + certificates_total
        + income_total
        + adjustment_total
        - withdrawals_total
        - collection_total,
        2,
    )

    closure_cursor = conn.execute(
        """
        INSERT INTO daily_closures(
            close_date,
            opening_base,
            sales_count,
            sales_total,
            certificates_count,
            certificates_total,
            withdrawals_total,
            income_total,
            adjustment_total,
            collection_total,
            net_total,
            note,
            created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            close_date,
            opening_base,
            sales_count,
            sales_total,
            certificates_count,
            certificates_total,
            withdrawals_total,
            income_total,
            adjustment_total,
            collection_total,
            net_total,
            (note or "").strip(),
            created_by_user_id,
        ),
    )
    closure_id = int(closure_cursor.lastrowid)

    conn.execute(
        """
        UPDATE sales
        SET is_closed = 1, closure_id = ?
        WHERE sale_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (closure_id, close_date),
    )
    conn.execute(
        """
        UPDATE certificates
        SET is_closed = 1, closure_id = ?
        WHERE cert_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (closure_id, close_date),
    )
    conn.execute(
        """
        UPDATE envelope_movements
        SET is_closed = 1, closure_id = ?
        WHERE move_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (closure_id, close_date),
    )
    conn.execute(
        """
        UPDATE daily_base
        SET is_closed = 1, closure_id = ?
        WHERE day_date = ? AND COALESCE(is_closed, 0) = 0
        """,
        (closure_id, close_date),
    )

    return closure_id


def close_pending_open_days(preferred_user_id: int | None = None) -> int:
    today_iso = date.today().isoformat()
    automatic_note = "Cierre automatico por cambio de fecha."

    with get_connection() as conn:
        actor_user_id = resolve_closure_actor_user_id(conn, preferred_user_id)
        pending_rows = conn.execute(
            """
            SELECT day_date AS close_date
            FROM daily_base
            WHERE COALESCE(is_closed, 0) = 0 AND day_date < ?
            UNION
            SELECT sale_date AS close_date
            FROM sales
            WHERE COALESCE(is_closed, 0) = 0 AND sale_date < ?
            UNION
            SELECT cert_date AS close_date
            FROM certificates
            WHERE COALESCE(is_closed, 0) = 0 AND cert_date < ?
            UNION
            SELECT move_date AS close_date
            FROM envelope_movements
            WHERE COALESCE(is_closed, 0) = 0 AND move_date < ?
            ORDER BY close_date
            """,
            (today_iso, today_iso, today_iso, today_iso),
        ).fetchall()

        closed_days = 0
        for row in pending_rows:
            closure_id = close_open_day_records(
                conn=conn,
                close_date=row["close_date"],
                created_by_user_id=actor_user_id,
                note=automatic_note,
                raise_if_empty=False,
            )
            if closure_id is not None:
                closed_days += 1

    return closed_days


@app.before_request
def auto_close_pending_open_days() -> None:
    if request.endpoint == "static":
        return None

    user = get_current_user()
    if not user:
        return None

    try:
        close_pending_open_days(preferred_user_id=user["id"])
    except Exception:
        app.logger.exception("No se pudo ejecutar el cierre automatico diario.")
    return None


def fetch_dashboard_data() -> dict[str, Any]:
    today = date.today()
    today_iso = today.isoformat()
    week_start = get_monday(today).isoformat()
    week_end = (get_monday(today) + timedelta(days=6)).isoformat()

    with get_connection() as conn:
        products = conn.execute(
            "SELECT id, name, default_price FROM products ORDER BY name"
        ).fetchall()

        today_sales_total = conn.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM sales
            WHERE sale_date = ? AND COALESCE(is_closed, 0) = 0
            """,
            (today_iso,),
        ).fetchone()["total"]

        today_sales = conn.execute(
            """
            SELECT
                id,
                sale_date,
                product_name,
                quantity,
                unit_price,
                total_amount,
                COALESCE(payment_method, 'EFECTIVO') AS payment_method
            FROM sales
            WHERE sale_date = ? AND COALESCE(is_closed, 0) = 0
            ORDER BY id DESC
            LIMIT 20
            """,
            (today_iso,),
        ).fetchall()

        today_certificates_total = conn.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM certificates
            WHERE cert_date = ? AND COALESCE(is_closed, 0) = 0
            """,
            (today_iso,),
        ).fetchone()["total"]
        today_transfer_certificates_total = conn.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM certificates
            WHERE
                cert_date = ?
                AND COALESCE(is_closed, 0) = 0
                AND COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA'
            """,
            (today_iso,),
        ).fetchone()["total"]
        today_cash_certificates_total = (
            float(today_certificates_total or 0.0)
            - float(today_transfer_certificates_total or 0.0)
        )

        today_certificates = conn.execute(
            """
            SELECT
                id,
                cert_date,
                certificate_type,
                matricula_number,
                quantity,
                total_amount,
                COALESCE(payment_method, 'EFECTIVO') AS payment_method,
                note
            FROM certificates
            WHERE cert_date = ? AND COALESCE(is_closed, 0) = 0
            ORDER BY id DESC
            LIMIT 20
            """,
            (today_iso,),
        ).fetchall()

        base_row = conn.execute(
            "SELECT opening_base FROM daily_base WHERE day_date = ? AND COALESCE(is_closed, 0) = 0",
            (today_iso,),
        ).fetchone()
        today_base = base_row["opening_base"] if base_row else 0.0

        today_transfer_sales_total = conn.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM sales
            WHERE
                sale_date = ?
                AND COALESCE(is_closed, 0) = 0
                AND COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA'
            """,
            (today_iso,),
        ).fetchone()["total"]
        today_cash_sales_total = today_sales_total - today_transfer_sales_total

        envelope_balance = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN move_type IN ('INGRESO', 'AJUSTE') THEN amount ELSE 0 END), 0)
                + COALESCE(
                    (
                        SELECT SUM(
                            CASE
                                WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                                ELSE total_amount
                            END
                        )
                        FROM sales
                        WHERE COALESCE(is_closed, 0) = 0
                    ),
                    0
                )
                - COALESCE(SUM(CASE WHEN move_type IN ('RETIRO', 'RECOLECCION') THEN amount ELSE 0 END), 0)
                AS balance
            FROM envelope_movements
            WHERE COALESCE(is_closed, 0) = 0
            """
        ).fetchone()["balance"]

        week_summary = conn.execute(
            """
            SELECT
                COALESCE(
                    (
                        SELECT SUM(
                            CASE
                                WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                                ELSE total_amount
                            END
                        )
                        FROM sales
                        WHERE sale_date BETWEEN ? AND ?
                    ),
                    0
                ) AS sales_total,
                COALESCE(
                    (
                        SELECT SUM(
                            CASE
                                WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN total_amount
                                ELSE 0
                            END
                        )
                        FROM sales
                        WHERE sale_date BETWEEN ? AND ?
                    ),
                    0
                ) AS transfer_sales_total,
                COALESCE(SUM(CASE WHEN move_type = 'INGRESO' THEN amount ELSE 0 END), 0) AS income_total,
                COALESCE(SUM(CASE WHEN move_type = 'RETIRO' THEN amount ELSE 0 END), 0) AS withdrawal_total,
                COALESCE(SUM(CASE WHEN move_type = 'RECOLECCION' THEN amount ELSE 0 END), 0) AS collection_total,
                COALESCE(SUM(CASE WHEN move_type = 'AJUSTE' THEN amount ELSE 0 END), 0) AS adjustment_total
            FROM envelope_movements
            WHERE move_date BETWEEN ? AND ?
            """,
            (week_start, week_end, week_start, week_end, week_start, week_end),
        ).fetchone()

        check_row = conn.execute(
            """
            SELECT actual_amount
            FROM envelope_checks
            WHERE week_start = ?
            """,
            (week_start,),
        ).fetchone()

        recent_sales = conn.execute(
            """
            SELECT
                s.id,
                s.sale_date,
                s.product_name,
                s.quantity,
                s.unit_price,
                s.total_amount,
                COALESCE(s.payment_method, 'EFECTIVO') AS payment_method,
                COALESCE(d.opening_base, 0) AS opening_base
            FROM sales s
            LEFT JOIN daily_base d ON d.day_date = s.sale_date AND COALESCE(d.is_closed, 0) = 0
            WHERE COALESCE(s.is_closed, 0) = 0
            ORDER BY s.sale_date DESC, s.id DESC
            LIMIT 20
            """
        ).fetchall()

        recent_certificates = conn.execute(
            """
            SELECT cert_date, matricula_number, quantity, total_amount, note
            FROM certificates
            WHERE COALESCE(is_closed, 0) = 0
            ORDER BY cert_date DESC, id DESC
            LIMIT 20
            """
        ).fetchall()

        recent_movements = conn.execute(
            """
            SELECT move_date, move_type, amount, note
            FROM envelope_movements
            WHERE COALESCE(is_closed, 0) = 0
            ORDER BY move_date DESC, id DESC
            LIMIT 20
            """
        ).fetchall()

        recent_withdrawals = conn.execute(
            """
            SELECT id, move_date, amount, note
            FROM envelope_movements
            WHERE move_type = 'RETIRO' AND COALESCE(is_closed, 0) = 0
            ORDER BY move_date DESC, id DESC
            LIMIT 30
            """
        ).fetchall()

        latest_checks = conn.execute(
            """
            SELECT week_start, week_end, actual_amount, note
            FROM envelope_checks
            ORDER BY week_start DESC
            LIMIT 10
            """
        ).fetchall()

    weekly_expected = (
        week_summary["sales_total"]
        + week_summary["income_total"]
        + week_summary["adjustment_total"]
        - week_summary["withdrawal_total"]
        - week_summary["collection_total"]
    )
    weekly_actual = check_row["actual_amount"] if check_row else None
    weekly_difference = (
        round(weekly_actual - weekly_expected, 2) if weekly_actual is not None else None
    )

    return {
        "today": today_iso,
        "week_start": week_start,
        "week_end": week_end,
        "products": products,
        "today_sales_total": round(today_sales_total, 2),
        "today_cash_sales_total": round(today_cash_sales_total, 2),
        "today_transfer_sales_total": round(today_transfer_sales_total, 2),
        "today_sales": today_sales,
        "today_certificates_total": round(today_certificates_total, 2),
        "today_cash_certificates_total": round(today_cash_certificates_total, 2),
        "today_transfer_certificates_total": round(today_transfer_certificates_total, 2),
        "today_certificates": today_certificates,
        "today_base": round(today_base, 2),
        "today_cash_total": round(today_cash_sales_total + today_base, 2),
        "envelope_balance": round(envelope_balance, 2),
        "week_summary": week_summary,
        "weekly_expected": round(weekly_expected, 2),
        "weekly_actual": weekly_actual,
        "weekly_difference": weekly_difference,
        "recent_sales": recent_sales,
        "recent_certificates": recent_certificates,
        "recent_movements": recent_movements,
        "recent_withdrawals": recent_withdrawals,
        "latest_checks": latest_checks,
    }


def aggregate_periods(start_date: str, end_date: str, mode: str) -> list[dict[str, Any]]:
    if mode not in {"weekly", "fortnightly", "monthly"}:
        raise ValueError("Modo de agregado invalido.")

    if mode == "weekly":
        sales_sql = """
            SELECT
                strftime('%Y', sale_date) AS y,
                strftime('%W', sale_date) AS p,
                MIN(sale_date) AS period_start,
                MAX(sale_date) AS period_end,
                SUM(
                    CASE
                        WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                        ELSE total_amount
                    END
                ) AS sales_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY y, p
            ORDER BY y, p
        """
        movements_sql = """
            SELECT
                strftime('%Y', move_date) AS y,
                strftime('%W', move_date) AS p,
                SUM(CASE WHEN move_type = 'INGRESO' THEN amount ELSE 0 END) AS income_total,
                SUM(CASE WHEN move_type = 'RETIRO' THEN amount ELSE 0 END) AS withdrawal_total,
                SUM(CASE WHEN move_type = 'RECOLECCION' THEN amount ELSE 0 END) AS collection_total,
                SUM(CASE WHEN move_type = 'AJUSTE' THEN amount ELSE 0 END) AS adjustment_total
            FROM envelope_movements
            WHERE move_date BETWEEN ? AND ?
            GROUP BY y, p
            ORDER BY y, p
        """
        checks_sql = """
            SELECT
                strftime('%Y', week_start) AS y,
                strftime('%W', week_start) AS p,
                actual_amount
            FROM envelope_checks
            WHERE week_start BETWEEN ? AND ?
        """
        label_fn = lambda row: f"Semana {row['p']}-{row['y']}"
    elif mode == "fortnightly":
        sales_sql = """
            SELECT
                strftime('%Y', sale_date) AS y,
                strftime('%m', sale_date) AS m,
                CASE WHEN CAST(strftime('%d', sale_date) AS INTEGER) <= 15 THEN '1' ELSE '2' END AS p,
                MIN(sale_date) AS period_start,
                MAX(sale_date) AS period_end,
                SUM(
                    CASE
                        WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                        ELSE total_amount
                    END
                ) AS sales_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY y, m, p
            ORDER BY y, m, p
        """
        movements_sql = """
            SELECT
                strftime('%Y', move_date) AS y,
                strftime('%m', move_date) AS m,
                CASE WHEN CAST(strftime('%d', move_date) AS INTEGER) <= 15 THEN '1' ELSE '2' END AS p,
                SUM(CASE WHEN move_type = 'INGRESO' THEN amount ELSE 0 END) AS income_total,
                SUM(CASE WHEN move_type = 'RETIRO' THEN amount ELSE 0 END) AS withdrawal_total,
                SUM(CASE WHEN move_type = 'RECOLECCION' THEN amount ELSE 0 END) AS collection_total,
                SUM(CASE WHEN move_type = 'AJUSTE' THEN amount ELSE 0 END) AS adjustment_total
            FROM envelope_movements
            WHERE move_date BETWEEN ? AND ?
            GROUP BY y, m, p
            ORDER BY y, m, p
        """
        checks_sql = ""
        label_fn = lambda row: f"{'1ra' if row['p'] == '1' else '2da'} quincena {row['m']}/{row['y']}"
    else:
        sales_sql = """
            SELECT
                strftime('%Y', sale_date) AS y,
                strftime('%m', sale_date) AS p,
                MIN(sale_date) AS period_start,
                MAX(sale_date) AS period_end,
                SUM(
                    CASE
                        WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                        ELSE total_amount
                    END
                ) AS sales_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY y, p
            ORDER BY y, p
        """
        movements_sql = """
            SELECT
                strftime('%Y', move_date) AS y,
                strftime('%m', move_date) AS p,
                SUM(CASE WHEN move_type = 'INGRESO' THEN amount ELSE 0 END) AS income_total,
                SUM(CASE WHEN move_type = 'RETIRO' THEN amount ELSE 0 END) AS withdrawal_total,
                SUM(CASE WHEN move_type = 'RECOLECCION' THEN amount ELSE 0 END) AS collection_total,
                SUM(CASE WHEN move_type = 'AJUSTE' THEN amount ELSE 0 END) AS adjustment_total
            FROM envelope_movements
            WHERE move_date BETWEEN ? AND ?
            GROUP BY y, p
            ORDER BY y, p
        """
        checks_sql = ""
        label_fn = lambda row: f"{row['p']}/{row['y']}"

    combined: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
        lambda: {
            "sales_total": 0.0,
            "income_total": 0.0,
            "withdrawal_total": 0.0,
            "collection_total": 0.0,
            "adjustment_total": 0.0,
            "actual_amount": None,
            "period_start": None,
            "period_end": None,
            "label": "",
        }
    )

    with get_connection() as conn:
        sales_rows = conn.execute(sales_sql, (start_date, end_date)).fetchall()
        movement_rows = conn.execute(movements_sql, (start_date, end_date)).fetchall()
        checks_rows = conn.execute(checks_sql, (start_date, end_date)).fetchall() if checks_sql else []

    for row in sales_rows:
        if mode == "fortnightly":
            key = (row["y"], row["m"], row["p"])
        else:
            key = (row["y"], row["p"])
        bucket = combined[key]
        bucket["sales_total"] = row["sales_total"] or 0.0
        bucket["period_start"] = row["period_start"]
        bucket["period_end"] = row["period_end"]
        bucket["label"] = label_fn(row)

    for row in movement_rows:
        if mode == "fortnightly":
            key = (row["y"], row["m"], row["p"])
        else:
            key = (row["y"], row["p"])
        bucket = combined[key]
        bucket["income_total"] = row["income_total"] or 0.0
        bucket["withdrawal_total"] = row["withdrawal_total"] or 0.0
        bucket["collection_total"] = row["collection_total"] or 0.0
        bucket["adjustment_total"] = row["adjustment_total"] or 0.0
        if not bucket["label"]:
            bucket["label"] = label_fn(row)

    for row in checks_rows:
        key = (row["y"], row["p"])
        bucket = combined[key]
        bucket["actual_amount"] = row["actual_amount"]
        if not bucket["label"]:
            bucket["label"] = label_fn(row)

    results: list[dict[str, Any]] = []
    for key in sorted(combined.keys()):
        bucket = combined[key]
        expected = (
            bucket["sales_total"]
            + bucket["income_total"]
            + bucket["adjustment_total"]
            - bucket["withdrawal_total"]
            - bucket["collection_total"]
        )
        actual = bucket["actual_amount"]
        difference = round(actual - expected, 2) if actual is not None else None
        results.append(
            {
                "label": bucket["label"],
                "period_start": bucket["period_start"],
                "period_end": bucket["period_end"],
                "sales_total": round(bucket["sales_total"], 2),
                "income_total": round(bucket["income_total"], 2),
                "withdrawal_total": round(bucket["withdrawal_total"], 2),
                "collection_total": round(bucket["collection_total"], 2),
                "adjustment_total": round(bucket["adjustment_total"], 2),
                "expected_balance": round(expected, 2),
                "actual_amount": actual,
                "difference": difference,
            }
        )
    return results


def get_fortnight_range(any_day: date) -> tuple[str, str]:
    if any_day.day <= 15:
        start = any_day.replace(day=1)
        end = any_day.replace(day=15)
    else:
        start = any_day.replace(day=16)
        end = any_day.replace(day=monthrange(any_day.year, any_day.month)[1])
    return start.isoformat(), end.isoformat()


def get_month_range(any_day: date) -> tuple[str, str]:
    start = any_day.replace(day=1)
    end = any_day.replace(day=monthrange(any_day.year, any_day.month)[1])
    return start.isoformat(), end.isoformat()


def fetch_certificate_current_period_totals(
    reference_day: date | None = None,
) -> dict[str, dict[str, Any]]:
    today_ref = reference_day or date.today()
    week_start = get_monday(today_ref).isoformat()
    week_end = (get_monday(today_ref) + timedelta(days=6)).isoformat()
    fortnight_start, fortnight_end = get_fortnight_range(today_ref)
    month_start, month_end = get_month_range(today_ref)

    period_ranges = {
        "weekly": {
            "label": "Semanal",
            "range_label": f"{week_start} a {week_end}",
            "start": week_start,
            "end": week_end,
        },
        "fortnightly": {
            "label": "Quincenal",
            "range_label": f"{fortnight_start} a {fortnight_end}",
            "start": fortnight_start,
            "end": fortnight_end,
        },
        "monthly": {
            "label": "Mensual",
            "range_label": f"{month_start} a {month_end}",
            "start": month_start,
            "end": month_end,
        },
    }

    summary_sql = """
        SELECT
            COUNT(*) AS records_count,
            COALESCE(SUM(quantity), 0) AS quantity_total,
            COALESCE(SUM(total_amount), 0) AS amount_total
        FROM certificates
        WHERE cert_date BETWEEN ? AND ?
    """

    with get_connection() as conn:
        for key, info in period_ranges.items():
            row = conn.execute(summary_sql, (info["start"], info["end"])).fetchone()
            info["records_count"] = int(row["records_count"] or 0)
            info["quantity_total"] = int(row["quantity_total"] or 0)
            info["amount_total"] = round(float(row["amount_total"] or 0.0), 2)

    return period_ranges


def fetch_sales_certificate_statistics(start_date: str, end_date: str) -> dict[str, Any]:
    with get_connection() as conn:
        sales_summary = conn.execute(
            """
            SELECT
                COUNT(*) AS records_count,
                COALESCE(SUM(quantity), 0) AS units_total,
                COALESCE(SUM(total_amount), 0) AS amount_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            """,
            (start_date, end_date),
        ).fetchone()

        certificates_summary = conn.execute(
            """
            SELECT
                COUNT(*) AS records_count,
                COALESCE(SUM(quantity), 0) AS units_total,
                COALESCE(SUM(total_amount), 0) AS amount_total
            FROM certificates
            WHERE cert_date BETWEEN ? AND ?
            """,
            (start_date, end_date),
        ).fetchone()

        sales_payment_breakdown = conn.execute(
            """
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 1
                            ELSE 0
                        END
                    ),
                    0
                ) AS transfer_records_count,
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN total_amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS transfer_amount_total,
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                            ELSE 1
                        END
                    ),
                    0
                ) AS cash_records_count,
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                            ELSE total_amount
                        END
                    ),
                    0
                ) AS cash_amount_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            """,
            (start_date, end_date),
        ).fetchone()

        top_products = conn.execute(
            """
            SELECT
                product_name,
                SUM(quantity) AS qty_total,
                SUM(total_amount) AS amount_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY product_name
            ORDER BY qty_total DESC, amount_total DESC
            LIMIT 10
            """,
            (start_date, end_date),
        ).fetchall()

        top_certificate_types = conn.execute(
            """
            SELECT
                certificate_type,
                COUNT(*) AS records_count,
                COALESCE(SUM(quantity), 0) AS qty_total,
                COALESCE(SUM(total_amount), 0) AS amount_total
            FROM certificates
            WHERE cert_date BETWEEN ? AND ?
            GROUP BY certificate_type
            ORDER BY records_count DESC, amount_total DESC
            LIMIT 10
            """,
            (start_date, end_date),
        ).fetchall()

        sales_by_day = conn.execute(
            """
            SELECT
                sale_date AS day_date,
                COUNT(*) AS records_count,
                COALESCE(SUM(quantity), 0) AS qty_total,
                COALESCE(SUM(total_amount), 0) AS amount_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY sale_date
            ORDER BY sale_date DESC
            """,
            (start_date, end_date),
        ).fetchall()

        cert_by_day = conn.execute(
            """
            SELECT
                cert_date AS day_date,
                COUNT(*) AS records_count,
                COALESCE(SUM(quantity), 0) AS qty_total,
                COALESCE(SUM(total_amount), 0) AS amount_total
            FROM certificates
            WHERE cert_date BETWEEN ? AND ?
            GROUP BY cert_date
            ORDER BY cert_date DESC
            """,
            (start_date, end_date),
        ).fetchall()

    sales_records = int(sales_summary["records_count"] or 0)
    sales_units = int(sales_summary["units_total"] or 0)
    sales_amount = round(float(sales_summary["amount_total"] or 0.0), 2)
    sales_average = round(sales_amount / sales_records, 2) if sales_records else 0.0
    sales_transfer_records = int(sales_payment_breakdown["transfer_records_count"] or 0)
    sales_transfer_amount = round(float(sales_payment_breakdown["transfer_amount_total"] or 0.0), 2)
    sales_cash_records = int(sales_payment_breakdown["cash_records_count"] or 0)
    sales_cash_amount = round(float(sales_payment_breakdown["cash_amount_total"] or 0.0), 2)

    cert_records = int(certificates_summary["records_count"] or 0)
    cert_units = int(certificates_summary["units_total"] or 0)
    cert_amount = round(float(certificates_summary["amount_total"] or 0.0), 2)
    cert_average = round(cert_amount / cert_records, 2) if cert_records else 0.0

    daily_map: dict[str, dict[str, Any]] = {}
    for row in sales_by_day:
        day_key = row["day_date"]
        daily_map[day_key] = {
            "day_date": day_key,
            "sales_records": int(row["records_count"] or 0),
            "sales_qty": int(row["qty_total"] or 0),
            "sales_amount": round(float(row["amount_total"] or 0.0), 2),
            "cert_records": 0,
            "cert_qty": 0,
            "cert_amount": 0.0,
            "total_amount": 0.0,
        }

    for row in cert_by_day:
        day_key = row["day_date"]
        bucket = daily_map.get(day_key)
        if not bucket:
            bucket = {
                "day_date": day_key,
                "sales_records": 0,
                "sales_qty": 0,
                "sales_amount": 0.0,
                "cert_records": 0,
                "cert_qty": 0,
                "cert_amount": 0.0,
                "total_amount": 0.0,
            }
            daily_map[day_key] = bucket
        bucket["cert_records"] = int(row["records_count"] or 0)
        bucket["cert_qty"] = int(row["qty_total"] or 0)
        bucket["cert_amount"] = round(float(row["amount_total"] or 0.0), 2)

    for item in daily_map.values():
        item["total_amount"] = round(item["sales_amount"] + item["cert_amount"], 2)

    daily_rows = sorted(daily_map.values(), key=lambda item: item["day_date"], reverse=True)

    return {
        "sales": {
            "records_count": sales_records,
            "units_total": sales_units,
            "amount_total": sales_amount,
            "average_ticket": sales_average,
            "cash_records_count": sales_cash_records,
            "cash_amount_total": sales_cash_amount,
            "transfer_records_count": sales_transfer_records,
            "transfer_amount_total": sales_transfer_amount,
        },
        "certificates": {
            "records_count": cert_records,
            "units_total": cert_units,
            "amount_total": cert_amount,
            "average_ticket": cert_average,
        },
        "combined": {
            "records_count": sales_records + cert_records,
            "units_total": sales_units + cert_units,
            "amount_total": round(sales_amount + cert_amount, 2),
        },
        "top_products": top_products,
        "top_certificate_types": top_certificate_types,
        "daily_rows": daily_rows,
    }


def build_statistics_pdf(start_date: str, end_date: str, stats: dict[str, Any]) -> BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 40

    def write_line(text: str, bold: bool = False, gap: int = 15) -> None:
        nonlocal y
        if y < 45:
            pdf.showPage()
            y = height - 40
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        pdf.drawString(40, y, text)
        y -= gap

    now_rendered = datetime.now().strftime("%Y-%m-%d %H:%M")

    write_line("SERVISKYNET TELECOMUNICACIONES S.A.S.", bold=True, gap=18)
    write_line("Reporte de estadisticas de ingresos", bold=True, gap=18)
    write_line(f"Periodo analizado: {start_date} a {end_date}")
    write_line(f"Generado: {now_rendered}")
    write_line("")

    write_line("Resumen de Ventas", bold=True)
    write_line(f"Registros: {stats['sales']['records_count']}")
    write_line(f"Unidades vendidas: {stats['sales']['units_total']}")
    write_line(f"Ingreso total ventas: {format_money(stats['sales']['amount_total'])}")
    write_line(
        f"Ventas en efectivo: {stats['sales']['cash_records_count']} | {format_money(stats['sales']['cash_amount_total'])}"
    )
    write_line(
        f"Ventas por transferencia: {stats['sales']['transfer_records_count']} | {format_money(stats['sales']['transfer_amount_total'])}"
    )
    write_line(f"Promedio por venta: {format_money(stats['sales']['average_ticket'])}")
    write_line("")

    write_line("Resumen de Certificados", bold=True)
    write_line(f"Registros: {stats['certificates']['records_count']}")
    write_line(f"Cantidad total certificados: {stats['certificates']['units_total']}")
    write_line(
        f"Ingreso total certificados: {format_money(stats['certificates']['amount_total'])}"
    )
    write_line(
        f"Promedio por certificado: {format_money(stats['certificates']['average_ticket'])}"
    )
    write_line("")

    write_line("Resumen Combinado", bold=True)
    write_line(f"Registros totales: {stats['combined']['records_count']}")
    write_line(f"Unidades totales: {stats['combined']['units_total']}")
    write_line(f"Ingreso total general: {format_money(stats['combined']['amount_total'])}")
    write_line("")

    write_line("Top 10 Productos Vendidos", bold=True)
    if stats["top_products"]:
        for row in stats["top_products"]:
            write_line(
                f"- {row['product_name']}: {int(row['qty_total'] or 0)} und | {format_money(row['amount_total'] or 0)}"
            )
    else:
        write_line("- Sin datos en el rango seleccionado.")
    write_line("")

    write_line("Top 10 Tipos de Certificado", bold=True)
    if stats["top_certificate_types"]:
        for row in stats["top_certificate_types"]:
            write_line(
                f"- {row['certificate_type']}: {int(row['records_count'] or 0)} reg | {format_money(row['amount_total'] or 0)}"
            )
    else:
        write_line("- Sin datos en el rango seleccionado.")

    pdf.save()
    buffer.seek(0)
    return buffer


def recompute_closure_totals(conn: sqlite3.Connection, closure_id: int) -> None:
    closure = conn.execute(
        "SELECT id FROM daily_closures WHERE id = ?",
        (closure_id,),
    ).fetchone()
    if not closure:
        raise ValueError("No se encontro la cuenta guardada indicada.")

    base_row = conn.execute(
        """
        SELECT COALESCE(SUM(opening_base), 0) AS opening_base
        FROM daily_base
        WHERE closure_id = ?
        """,
        (closure_id,),
    ).fetchone()
    sales_row = conn.execute(
        """
        SELECT
            COUNT(*) AS sales_count,
            COALESCE(
                SUM(
                    CASE
                        WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                        ELSE total_amount
                    END
                ),
                0
            ) AS sales_total
        FROM sales
        WHERE closure_id = ?
        """,
        (closure_id,),
    ).fetchone()
    cert_row = conn.execute(
        """
        SELECT
            COUNT(*) AS certificates_count,
            COALESCE(SUM(total_amount), 0) AS certificates_total
        FROM certificates
        WHERE closure_id = ?
        """,
        (closure_id,),
    ).fetchone()
    move_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN move_type = 'RETIRO' THEN amount ELSE 0 END), 0) AS withdrawals_total,
            COALESCE(SUM(CASE WHEN move_type = 'INGRESO' THEN amount ELSE 0 END), 0) AS income_total,
            COALESCE(SUM(CASE WHEN move_type = 'AJUSTE' THEN amount ELSE 0 END), 0) AS adjustment_total,
            COALESCE(SUM(CASE WHEN move_type = 'RECOLECCION' THEN amount ELSE 0 END), 0) AS collection_total
        FROM envelope_movements
        WHERE closure_id = ?
        """,
        (closure_id,),
    ).fetchone()

    opening_base = round(float(base_row["opening_base"] or 0.0), 2)
    sales_count = int(sales_row["sales_count"] or 0)
    sales_total = round(float(sales_row["sales_total"] or 0.0), 2)
    certificates_count = int(cert_row["certificates_count"] or 0)
    certificates_total = round(float(cert_row["certificates_total"] or 0.0), 2)
    withdrawals_total = round(float(move_row["withdrawals_total"] or 0.0), 2)
    income_total = round(float(move_row["income_total"] or 0.0), 2)
    adjustment_total = round(float(move_row["adjustment_total"] or 0.0), 2)
    collection_total = round(float(move_row["collection_total"] or 0.0), 2)

    net_total = round(
        opening_base
        + sales_total
        + certificates_total
        + income_total
        + adjustment_total
        - withdrawals_total
        - collection_total,
        2,
    )

    conn.execute(
        """
        UPDATE daily_closures
        SET
            opening_base = ?,
            sales_count = ?,
            sales_total = ?,
            certificates_count = ?,
            certificates_total = ?,
            withdrawals_total = ?,
            income_total = ?,
            adjustment_total = ?,
            collection_total = ?,
            net_total = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            opening_base,
            sales_count,
            sales_total,
            certificates_count,
            certificates_total,
            withdrawals_total,
            income_total,
            adjustment_total,
            collection_total,
            net_total,
            closure_id,
        ),
    )


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if get_current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username", "") or "").strip()
        password = request.form.get("password", "") or ""

        with get_connection() as conn:
            user_row = conn.execute(
                """
                SELECT id, username, password_hash, role
                FROM users
                WHERE username = ? AND is_active = 1
                """,
                (username,),
            ).fetchone()

        if user_row and check_password_hash(user_row["password_hash"], password):
            session.clear()
            session["user_id"] = user_row["id"]
            session["username"] = user_row["username"]
            session["role"] = user_row["role"]
            flash("\u00a1Bienvenido! Has iniciado sesion exitosamente", "success")
            return redirect(url_for("index"))

        flash("Usuario o contrase\u00f1a incorrectos.", "danger")

    return render_template("login.html")


@app.get("/logout")
@login_required
def logout() -> Any:
    session.clear()
    flash("Sesion cerrada.", "success")
    return redirect(url_for("login"))


@app.route("/cambiar-contrasena", methods=["GET", "POST"])
@roles_required("admin")
def change_password() -> Any:
    selected_user_id = ""

    if request.method == "POST":
        selected_user_id = (request.form.get("target_user_id", "") or "").strip()
        new_password = request.form.get("new_password", "") or ""
        confirm_password = request.form.get("confirm_password", "") or ""

        try:
            if not selected_user_id:
                raise ValueError("Debes seleccionar el usuario.")
            if len(new_password) < 8:
                raise ValueError("La nueva contrasena debe tener al menos 8 caracteres.")
            if new_password != confirm_password:
                raise ValueError("La confirmacion de contrasena no coincide.")

            target_user_id = parse_positive_int(selected_user_id, "usuario")

            with get_connection() as conn:
                user_row = conn.execute(
                    """
                    SELECT id, username, role, password_hash
                    FROM users
                    WHERE id = ? AND is_active = 1
                    """,
                    (target_user_id,),
                ).fetchone()

                if not user_row or user_row["role"] not in {"admin", "usuario"}:
                    raise ValueError("No se encontro el usuario indicado.")
                if check_password_hash(user_row["password_hash"], new_password):
                    raise ValueError(
                        "La nueva contrasena debe ser diferente a la actual."
                    )

                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_password), target_user_id),
                )

            flash(
                f"Contrasena actualizada para {user_row['username']} ({user_row['role']}).",
                "success",
            )
            return redirect(url_for("change_password"))
        except Exception as exc:
            flash(str(exc), "danger")

    with get_connection() as conn:
        users = conn.execute(
            """
            SELECT id, username, role
            FROM users
            WHERE is_active = 1 AND role IN ('admin', 'usuario')
            ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, username
            """
        ).fetchall()

    return render_template(
        "cambiar_contrasena.html",
        users=users,
        selected_user_id=selected_user_id,
    )


@app.route("/")
@login_required
def index() -> Any:
    data = fetch_dashboard_data()
    return render_template("index.html", data=data)


@app.get("/certificados-operacion")
@roles_required("admin", "usuario")
def certificates_operation_page() -> Any:
    data = fetch_dashboard_data()
    return render_template("certificados_operacion.html", data=data)


@app.get("/retiros-sobre")
@roles_required("admin", "usuario")
def withdrawals_operation_page() -> Any:
    data = fetch_dashboard_data()
    return render_template("retiros_operacion.html", data=data)


@app.post("/registrar-base")
@roles_required("admin", "usuario")
def register_base() -> Any:
    try:
        day_date = parse_date(request.form.get("day_date", ""), "fecha de base")
        opening_base = parse_non_negative_float(
            request.form.get("opening_base", ""), "base inicial"
        )
        success_message = "Base inicial guardada correctamente."
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id, COALESCE(is_closed, 0) AS is_closed FROM daily_base WHERE day_date = ?",
                (day_date,),
            ).fetchone()
            if existing:
                if int(existing["is_closed"]) == 1:
                    raise ValueError(
                        "La base de esa fecha ya fue cerrada y no se puede modificar desde Operacion Diaria."
                    )
                if not is_admin_user():
                    raise ValueError(
                        "Ya existe una base registrada para esa fecha. Solo el administrador puede modificar o eliminar la base."
                    )

                conn.execute(
                    """
                    UPDATE daily_base
                    SET opening_base = ?
                    WHERE id = ?
                    """,
                    (opening_base, existing["id"]),
                )
                success_message = "Base inicial actualizada correctamente."
            else:
                conn.execute(
                    "INSERT INTO daily_base(day_date, opening_base) VALUES (?, ?)",
                    (day_date, opening_base),
                )
        flash(success_message, "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("index"))


@app.post("/eliminar-base")
@roles_required("admin")
def delete_base() -> Any:
    try:
        day_date = parse_date(request.form.get("day_date", ""), "fecha de base")
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id, COALESCE(is_closed, 0) AS is_closed FROM daily_base WHERE day_date = ?",
                (day_date,),
            ).fetchone()

            if not existing:
                raise ValueError("No existe una base registrada para esa fecha.")
            if int(existing["is_closed"]) == 1:
                raise ValueError(
                    "La base de esa fecha ya fue cerrada y no se puede eliminar desde Operacion Diaria."
                )

            conn.execute("DELETE FROM daily_base WHERE id = ?", (existing["id"],))

        flash("Base inicial eliminada correctamente.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("index"))


@app.post("/guardar-cuenta-dia")
@roles_required("usuario")
def save_daily_account() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        close_date = parse_date(request.form.get("close_date", ""), "fecha de cierre")
        note = (request.form.get("note", "") or "").strip()

        with get_connection() as conn:
            close_open_day_records(
                conn=conn,
                close_date=close_date,
                created_by_user_id=user["id"],
                note=note,
                raise_if_empty=True,
            )

        flash("Cuenta del dia guardada correctamente. Se reiniciaron los contadores abiertos.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("index"))


@app.post("/registrar-venta")
@roles_required("admin", "usuario")
def register_sale() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        sale_date = parse_date(request.form.get("sale_date", ""), "fecha de venta")
        product_name = (request.form.get("product_name", "") or "").strip()
        quantity_raw = (request.form.get("quantity", "") or "").strip()
        quantity = parse_positive_int(quantity_raw, "cantidad") if quantity_raw else 1
        unit_price = parse_non_negative_float(
            request.form.get("unit_price", ""), "precio unitario"
        )
        payment_method = parse_sale_payment_method(request.form.get("payment_method", ""))

        if not product_name:
            raise ValueError("Debes indicar el producto o servicio.")

        total_amount = round(quantity * unit_price, 2)
        with get_connection() as conn:
            if user["role"] == "admin":
                product_row = conn.execute(
                    "SELECT id FROM products WHERE lower(name) = lower(?)",
                    (product_name,),
                ).fetchone()
                if not product_row:
                    conn.execute(
                        """
                        INSERT INTO products(name, default_price)
                        VALUES (?, ?)
                        """,
                        (product_name, unit_price),
                    )

            conn.execute(
                """
                INSERT INTO sales(
                    sale_date,
                    product_name,
                    quantity,
                    unit_price,
                    total_amount,
                    payment_method,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale_date,
                    product_name,
                    quantity,
                    unit_price,
                    total_amount,
                    payment_method,
                    user["id"],
                ),
            )
        flash("Venta registrada correctamente.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("index"))


@app.post("/ventas/<int:sale_id>/actualizar")
@roles_required("admin")
def update_sale(sale_id: int) -> Any:
    try:
        sale_date = parse_date(request.form.get("sale_date", ""), "fecha de venta")
        product_name = (request.form.get("product_name", "") or "").strip()
        quantity = parse_positive_int(request.form.get("quantity", ""), "cantidad")
        unit_price = parse_non_negative_float(
            request.form.get("unit_price", ""), "precio unitario"
        )
        payment_method = parse_sale_payment_method(request.form.get("payment_method", ""))

        if not product_name:
            raise ValueError("Debes indicar el producto o servicio.")

        total_amount = round(quantity * unit_price, 2)
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM sales WHERE id = ?",
                (sale_id,),
            ).fetchone()
            if not existing:
                raise ValueError("No se encontro la venta indicada.")

            product_row = conn.execute(
                "SELECT id FROM products WHERE lower(name) = lower(?)",
                (product_name,),
            ).fetchone()
            if not product_row:
                conn.execute(
                    """
                    INSERT INTO products(name, default_price)
                    VALUES (?, ?)
                    """,
                    (product_name, unit_price),
                )

            conn.execute(
                """
                UPDATE sales
                SET
                    sale_date = ?,
                    product_name = ?,
                    quantity = ?,
                    unit_price = ?,
                    total_amount = ?,
                    payment_method = ?
                WHERE id = ?
                """,
                (
                    sale_date,
                    product_name,
                    quantity,
                    unit_price,
                    total_amount,
                    payment_method,
                    sale_id,
                ),
            )
        flash("Venta actualizada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("index")


@app.post("/ventas/<int:sale_id>/eliminar")
@roles_required("admin")
def delete_sale(sale_id: int) -> Any:
    try:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM sales WHERE id = ?",
                (sale_id,),
            ).fetchone()
            if not existing:
                raise ValueError("No se encontro la venta indicada.")
            conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
        flash("Venta eliminada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("index")


@app.post("/registrar-certificado")
@roles_required("admin", "usuario")
def register_certificate_daily() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        cert_date = parse_date(request.form.get("cert_date", ""), "fecha certificado")
        matricula_number = (request.form.get("matricula_number", "") or "").strip()
        quantity_raw = (request.form.get("quantity", "") or "").strip()
        quantity = parse_positive_int(quantity_raw, "cantidad") if quantity_raw else 1
        total_amount = parse_non_negative_float(
            request.form.get("total_amount", ""), "valor certificado"
        )
        payment_method = parse_sale_payment_method(request.form.get("payment_method", ""))
        note = (request.form.get("note", "") or "").strip()
        certificate_type = (
            request.form.get("certificate_type", "") or "Certificado de tradicion y libertad"
        ).strip()

        if not matricula_number:
            raise ValueError("Debes indicar el numero de matricula.")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO certificates(
                    cert_date,
                    certificate_type,
                    matricula_number,
                    quantity,
                    total_amount,
                    payment_method,
                    note,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cert_date,
                    certificate_type,
                    matricula_number,
                    quantity,
                    total_amount,
                    payment_method,
                    note,
                    user["id"],
                ),
            )
        flash("Certificado registrado correctamente.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("certificates_operation_page")


@app.post("/registrar-retiro")
@roles_required("admin", "usuario")
def register_withdrawal() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        move_date = parse_date(request.form.get("move_date", ""), "fecha retiro")
        amount = parse_non_negative_float(request.form.get("amount", ""), "monto retiro")
        note = (request.form.get("note", "") or "").strip()

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO envelope_movements(move_date, move_type, amount, note, created_by_user_id)
                VALUES (?, 'RETIRO', ?, ?, ?)
                """,
                (move_date, amount, note, user["id"]),
            )
        flash("Retiro registrado correctamente.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("withdrawals_operation_page")


@app.post("/registrar-movimiento")
@roles_required("admin")
def register_envelope_movement() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        move_date = parse_date(request.form.get("move_date", ""), "fecha de movimiento")
        move_type = (request.form.get("move_type", "") or "").strip().upper()
        amount = parse_non_negative_float(request.form.get("amount", ""), "monto")
        note = (request.form.get("note", "") or "").strip()

        if move_type not in VALID_MOVEMENT_TYPES:
            raise ValueError("Tipo de movimiento invalido.")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO envelope_movements(move_date, move_type, amount, note, created_by_user_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (move_date, move_type, amount, note, user["id"]),
            )
        flash("Movimiento del sobre registrado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("index"))


@app.post("/movimientos/<int:movement_id>/actualizar")
@roles_required("admin")
def update_withdrawal_movement(movement_id: int) -> Any:
    try:
        move_date = parse_date(request.form.get("move_date", ""), "fecha retiro")
        amount = parse_non_negative_float(request.form.get("amount", ""), "monto retiro")
        note = (request.form.get("note", "") or "").strip()

        with get_connection() as conn:
            result = conn.execute(
                """
                UPDATE envelope_movements
                SET move_date = ?, amount = ?, note = ?
                WHERE id = ? AND move_type = 'RETIRO'
                """,
                (move_date, amount, note, movement_id),
            )
            if result.rowcount == 0:
                raise ValueError("No se encontro el retiro indicado.")
        flash("Retiro actualizado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("withdrawals_operation_page")


@app.post("/movimientos/<int:movement_id>/eliminar")
@roles_required("admin")
def delete_withdrawal_movement(movement_id: int) -> Any:
    try:
        with get_connection() as conn:
            result = conn.execute(
                "DELETE FROM envelope_movements WHERE id = ? AND move_type = 'RETIRO'",
                (movement_id,),
            )
            if result.rowcount == 0:
                raise ValueError("No se encontro el retiro indicado.")
        flash("Retiro eliminado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("withdrawals_operation_page")


@app.post("/registrar-verificacion")
@roles_required("admin")
def register_envelope_check() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        week_start = parse_date(
            request.form.get("week_start", ""), "inicio de semana para verificacion"
        )
        actual_amount = parse_non_negative_float(
            request.form.get("actual_amount", ""), "monto real del sobre"
        )
        note = (request.form.get("note", "") or "").strip()
        start, end = week_range_from_start(week_start)

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO envelope_checks(
                    week_start,
                    week_end,
                    actual_amount,
                    note,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(week_start) DO UPDATE SET
                    week_end = excluded.week_end,
                    actual_amount = excluded.actual_amount,
                    note = excluded.note,
                    created_by_user_id = excluded.created_by_user_id
                """,
                (start, end, actual_amount, note, user["id"]),
            )
        flash("Verificacion semanal guardada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("index"))


@app.route("/reportes")
@roles_required("admin")
def reports() -> Any:
    today = date.today()
    default_start = (today - timedelta(days=90)).isoformat()
    start_date = request.args.get("start_date", default_start)
    end_date = request.args.get("end_date", today.isoformat())

    try:
        start_date = parse_date(start_date, "fecha inicial")
        end_date = parse_date(end_date, "fecha final")
        if start_date > end_date:
            raise ValueError("La fecha inicial no puede ser mayor a la fecha final.")
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("reports"))

    with get_connection() as conn:
        totals = conn.execute(
            """
            SELECT
                COALESCE((SELECT SUM(total_amount) FROM sales WHERE sale_date BETWEEN ? AND ?), 0) AS sales_total,
                COALESCE(
                    (
                        SELECT SUM(
                            CASE
                                WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                                ELSE total_amount
                            END
                        )
                        FROM sales
                        WHERE sale_date BETWEEN ? AND ?
                    ),
                    0
                ) AS cash_sales_total,
                COALESCE(
                    (
                        SELECT SUM(
                            CASE
                                WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN total_amount
                                ELSE 0
                            END
                        )
                        FROM sales
                        WHERE sale_date BETWEEN ? AND ?
                    ),
                    0
                ) AS transfer_sales_total,
                COALESCE((SELECT SUM(opening_base) FROM daily_base WHERE day_date BETWEEN ? AND ?), 0) AS base_total,
                COALESCE((SELECT SUM(amount) FROM envelope_movements WHERE move_type = 'INGRESO' AND move_date BETWEEN ? AND ?), 0) AS income_total,
                COALESCE((SELECT SUM(amount) FROM envelope_movements WHERE move_type = 'AJUSTE' AND move_date BETWEEN ? AND ?), 0) AS adjustments_total,
                COALESCE((SELECT SUM(amount) FROM envelope_movements WHERE move_type = 'RETIRO' AND move_date BETWEEN ? AND ?), 0) AS withdrawals_total,
                COALESCE((SELECT SUM(amount) FROM envelope_movements WHERE move_type = 'RECOLECCION' AND move_date BETWEEN ? AND ?), 0) AS collections_total
            """,
            (
                start_date,
                end_date,
                start_date,
                end_date,
                start_date,
                end_date,
                start_date,
                end_date,
                start_date,
                end_date,
                start_date,
                end_date,
                start_date,
                end_date,
                start_date,
                end_date,
            ),
        ).fetchone()

        top_products = conn.execute(
            """
            SELECT
                product_name,
                SUM(quantity) AS qty_total,
                SUM(total_amount) AS amount_total
            FROM sales
            WHERE sale_date BETWEEN ? AND ?
            GROUP BY product_name
            ORDER BY qty_total DESC, amount_total DESC
            LIMIT 10
            """,
            (start_date, end_date),
        ).fetchall()

    weekly = aggregate_periods(start_date, end_date, "weekly")
    fortnightly = aggregate_periods(start_date, end_date, "fortnightly")
    monthly = aggregate_periods(start_date, end_date, "monthly")

    envelope_estimated = (
        totals["cash_sales_total"]
        + totals["income_total"]
        + totals["adjustments_total"]
        - totals["withdrawals_total"]
        - totals["collections_total"]
    )

    return render_template(
        "reportes.html",
        start_date=start_date,
        end_date=end_date,
        totals=totals,
        envelope_estimated=round(envelope_estimated, 2),
        top_products=top_products,
        weekly=weekly,
        fortnightly=fortnightly,
        monthly=monthly,
    )


@app.get("/estadisticas")
@roles_required("admin")
def statistics_page() -> Any:
    today = date.today()
    default_start = (today - timedelta(days=90)).isoformat()
    start_date = request.args.get("start_date", default_start)
    end_date = request.args.get("end_date", today.isoformat())

    try:
        start_date = parse_date(start_date, "fecha inicial")
        end_date = parse_date(end_date, "fecha final")
        if start_date > end_date:
            raise ValueError("La fecha inicial no puede ser mayor a la fecha final.")
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("statistics_page"))

    stats = fetch_sales_certificate_statistics(start_date, end_date)

    return render_template(
        "estadisticas.html",
        start_date=start_date,
        end_date=end_date,
        stats=stats,
    )


@app.get("/estadisticas/pdf")
@roles_required("admin")
def statistics_pdf() -> Any:
    today = date.today()
    default_start = (today - timedelta(days=90)).isoformat()
    start_date = request.args.get("start_date", default_start)
    end_date = request.args.get("end_date", today.isoformat())

    try:
        start_date = parse_date(start_date, "fecha inicial")
        end_date = parse_date(end_date, "fecha final")
        if start_date > end_date:
            raise ValueError("La fecha inicial no puede ser mayor a la fecha final.")
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("statistics_page"))

    stats = fetch_sales_certificate_statistics(start_date, end_date)
    try:
        pdf_buffer = build_statistics_pdf(start_date, end_date, stats)
    except ImportError:
        flash(
            "Para generar PDF instala reportlab. Ejecuta: pip install -r requirements.txt",
            "danger",
        )
        return redirect(
            url_for("statistics_page", start_date=start_date, end_date=end_date)
        )

    filename = f"estadisticas_{start_date}_a_{end_date}.pdf"
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.get("/cuentas-guardadas")
@roles_required("admin")
def saved_accounts_page() -> Any:
    filter_date_raw = (request.args.get("filter_date", "") or "").strip()
    filter_date = ""
    if filter_date_raw:
        try:
            filter_date = parse_date(filter_date_raw, "fecha de busqueda")
        except Exception as exc:
            flash(str(exc), "danger")
            return redirect(url_for("saved_accounts_page"))

    with get_connection() as conn:
        query = """
            SELECT
                c.id,
                c.close_date,
                c.opening_base,
                c.sales_count,
                c.sales_total,
                c.certificates_count,
                c.certificates_total,
                c.withdrawals_total,
                c.income_total,
                c.adjustment_total,
                c.collection_total,
                c.net_total,
                c.note,
                c.created_at,
                c.updated_at,
                u.username AS created_by
            FROM daily_closures c
            LEFT JOIN users u ON u.id = c.created_by_user_id
        """
        params: tuple[Any, ...] = ()
        if filter_date:
            query += " WHERE c.close_date = ?"
            params = (filter_date,)
        query += " ORDER BY c.close_date DESC, c.id DESC"
        closures = conn.execute(query, params).fetchall()

    return render_template(
        "cuentas_guardadas.html",
        closures=closures,
        filter_date=filter_date,
    )


@app.get("/cuentas-guardadas/<int:closure_id>")
@roles_required("admin")
def saved_account_detail_page(closure_id: int) -> Any:
    with get_connection() as conn:
        closure = conn.execute(
            """
            SELECT
                c.id,
                c.close_date,
                c.opening_base,
                c.sales_count,
                c.sales_total,
                c.certificates_count,
                c.certificates_total,
                c.withdrawals_total,
                c.income_total,
                c.adjustment_total,
                c.collection_total,
                c.net_total,
                c.note,
                c.created_at,
                c.updated_at,
                u.username AS created_by
            FROM daily_closures c
            LEFT JOIN users u ON u.id = c.created_by_user_id
            WHERE c.id = ?
            """,
            (closure_id,),
        ).fetchone()
        if not closure:
            flash("No se encontro la cuenta guardada indicada.", "danger")
            return redirect(url_for("saved_accounts_page"))

        sales = conn.execute(
            """
            SELECT
                id,
                sale_date,
                product_name,
                quantity,
                unit_price,
                total_amount
            FROM sales
            WHERE closure_id = ?
            ORDER BY id DESC
            """,
            (closure_id,),
        ).fetchall()

    return render_template(
        "cuenta_guardada_detalle.html",
        closure=closure,
        sales=sales,
    )


@app.post("/cuentas-guardadas/<int:closure_id>/actualizar")
@roles_required("admin")
def update_saved_account(closure_id: int) -> Any:
    try:
        note = (request.form.get("note", "") or "").strip()

        with get_connection() as conn:
            result = conn.execute(
                """
                UPDATE daily_closures
                SET
                    note = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    note,
                    closure_id,
                ),
            )
            if result.rowcount == 0:
                raise ValueError("No se encontro la cuenta guardada indicada.")
        flash("Cuenta guardada actualizada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("saved_account_detail_page", closure_id=closure_id))


@app.post("/cuentas-guardadas/<int:closure_id>/ventas/<int:sale_id>/actualizar")
@roles_required("admin")
def update_saved_account_sale(closure_id: int, sale_id: int) -> Any:
    try:
        product_name = (request.form.get("product_name", "") or "").strip()
        quantity = parse_positive_int(request.form.get("quantity", ""), "cantidad")
        unit_price = parse_non_negative_float(
            request.form.get("unit_price", ""), "precio unitario"
        )
        if not product_name:
            raise ValueError("Debes indicar el producto o servicio.")

        total_amount = round(quantity * unit_price, 2)

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM sales WHERE id = ? AND closure_id = ?",
                (sale_id, closure_id),
            ).fetchone()
            if not existing:
                raise ValueError("No se encontro la venta indicada para esta cuenta.")

            product_row = conn.execute(
                "SELECT id FROM products WHERE lower(name) = lower(?)",
                (product_name,),
            ).fetchone()
            if not product_row:
                conn.execute(
                    "INSERT INTO products(name, default_price) VALUES (?, ?)",
                    (product_name, unit_price),
                )

            conn.execute(
                """
                UPDATE sales
                SET product_name = ?, quantity = ?, unit_price = ?, total_amount = ?
                WHERE id = ? AND closure_id = ?
                """,
                (product_name, quantity, unit_price, total_amount, sale_id, closure_id),
            )
            recompute_closure_totals(conn, closure_id)
        flash("Venta actualizada en la cuenta guardada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("saved_account_detail_page", closure_id=closure_id))


@app.post("/cuentas-guardadas/<int:closure_id>/ventas/<int:sale_id>/eliminar")
@roles_required("admin")
def delete_saved_account_sale(closure_id: int, sale_id: int) -> Any:
    try:
        with get_connection() as conn:
            result = conn.execute(
                "DELETE FROM sales WHERE id = ? AND closure_id = ?",
                (sale_id, closure_id),
            )
            if result.rowcount == 0:
                raise ValueError("No se encontro la venta indicada para esta cuenta.")
            recompute_closure_totals(conn, closure_id)
        flash("Venta eliminada de la cuenta guardada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("saved_account_detail_page", closure_id=closure_id))


@app.post("/cuentas-guardadas/<int:closure_id>/eliminar")
@roles_required("admin")
def delete_saved_account(closure_id: int) -> Any:
    try:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM daily_closures WHERE id = ?",
                (closure_id,),
            ).fetchone()
            if not existing:
                raise ValueError("No se encontro la cuenta guardada indicada.")

            conn.execute("DELETE FROM sales WHERE closure_id = ?", (closure_id,))
            conn.execute("DELETE FROM certificates WHERE closure_id = ?", (closure_id,))
            conn.execute(
                "DELETE FROM envelope_movements WHERE closure_id = ?",
                (closure_id,),
            )
            conn.execute("DELETE FROM daily_base WHERE closure_id = ?", (closure_id,))
            conn.execute("DELETE FROM daily_closures WHERE id = ?", (closure_id,))
        flash("Cuenta guardada eliminada.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("saved_accounts_page"))


@app.get("/productos")
@roles_required("admin")
def products_page() -> Any:
    with get_connection() as conn:
        products = conn.execute(
            """
            SELECT
                p.id,
                p.name,
                p.default_price,
                COALESCE(SUM(s.quantity), 0) AS qty_sold
            FROM products p
            LEFT JOIN sales s ON s.product_name = p.name
            GROUP BY p.id, p.name, p.default_price
            ORDER BY p.name
            """
        ).fetchall()

    return render_template("productos.html", products=products)


@app.post("/productos/agregar")
@roles_required("admin")
def add_product() -> Any:
    try:
        name = (request.form.get("name", "") or "").strip()
        default_price = parse_non_negative_float(
            request.form.get("default_price", ""), "precio base"
        )
        if not name:
            raise ValueError("Debes escribir el nombre del producto.")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO products(name, default_price)
                VALUES (?, ?)
                """,
                (name, default_price),
            )
        flash("Producto agregado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("products_page"))


@app.post("/productos/<int:product_id>/actualizar")
@roles_required("admin")
def update_product(product_id: int) -> Any:
    try:
        name = (request.form.get("name", "") or "").strip()
        default_price = parse_non_negative_float(
            request.form.get("default_price", ""), "precio base"
        )
        if not name:
            raise ValueError("Debes escribir el nombre del producto.")

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE products
                SET name = ?, default_price = ?
                WHERE id = ?
                """,
                (name, default_price, product_id),
            )
        flash("Producto actualizado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("products_page"))


@app.post("/productos/<int:product_id>/eliminar")
@roles_required("admin")
def delete_product(product_id: int) -> Any:
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        flash("Producto eliminado del catalogo.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("products_page"))


@app.get("/certificados")
@roles_required("admin")
def certificates_page() -> Any:
    filter_date_raw = (request.args.get("filter_date", "") or "").strip()
    filter_date = ""
    if filter_date_raw:
        try:
            filter_date = parse_date(filter_date_raw, "fecha de busqueda")
        except Exception as exc:
            flash(str(exc), "danger")
            return redirect(url_for("certificates_page"))

    with get_connection() as conn:
        cert_query = """
            SELECT
                c.id,
                c.cert_date,
                c.certificate_type,
                c.matricula_number,
                c.quantity,
                c.total_amount,
                COALESCE(c.payment_method, 'EFECTIVO') AS payment_method,
                c.note,
                u.username AS created_by
            FROM certificates c
            LEFT JOIN users u ON u.id = c.created_by_user_id
        """
        cert_params: tuple[Any, ...] = ()
        if filter_date:
            cert_query += " WHERE c.cert_date = ?"
            cert_params = (filter_date,)
        cert_query += " ORDER BY c.cert_date DESC, c.id DESC"
        certificates = conn.execute(cert_query, cert_params).fetchall()

        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                COALESCE(SUM(quantity), 0) AS total_quantity,
                COALESCE(SUM(total_amount), 0) AS total_amount
            FROM certificates
            """
        ).fetchone()
        payment_totals_query = """
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN 0
                            ELSE total_amount
                        END
                    ),
                    0
                ) AS cash_total,
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(payment_method, 'EFECTIVO') = 'TRANSFERENCIA' THEN total_amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS transfer_total
            FROM certificates
        """
        payment_totals_params: tuple[Any, ...] = ()
        if filter_date:
            payment_totals_query += " WHERE cert_date = ?"
            payment_totals_params = (filter_date,)
        certificate_payment_totals = conn.execute(
            payment_totals_query,
            payment_totals_params,
        ).fetchone()
        day_totals = None
        accumulated_up_to = None
        if filter_date:
            day_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS day_count,
                    COALESCE(SUM(quantity), 0) AS day_quantity,
                    COALESCE(SUM(total_amount), 0) AS day_amount
                FROM certificates
                WHERE cert_date = ?
                """,
                (filter_date,),
            ).fetchone()
            accumulated_up_to = conn.execute(
                """
                SELECT COALESCE(SUM(total_amount), 0) AS accumulated_amount
                FROM certificates
                WHERE cert_date <= ?
                """,
                (filter_date,),
            ).fetchone()["accumulated_amount"]

    period_totals = fetch_certificate_current_period_totals()

    return render_template(
        "certificados.html",
        certificates=certificates,
        totals=totals,
        period_totals=period_totals,
        filter_date=filter_date,
        day_totals=day_totals,
        accumulated_up_to=round(float(accumulated_up_to or 0.0), 2)
        if accumulated_up_to is not None
        else None,
        certificate_payment_totals=certificate_payment_totals,
        today=date.today().isoformat(),
    )


@app.post("/certificados/registrar")
@roles_required("admin")
def add_certificate() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        cert_date = parse_date(request.form.get("cert_date", ""), "fecha")
        certificate_type = (request.form.get("certificate_type", "") or "").strip()
        matricula_number = (request.form.get("matricula_number", "") or "").strip()
        quantity = parse_positive_int(request.form.get("quantity", ""), "cantidad")
        total_amount = parse_non_negative_float(
            request.form.get("total_amount", ""), "valor total"
        )
        payment_method = parse_sale_payment_method(request.form.get("payment_method", ""))
        note = (request.form.get("note", "") or "").strip()

        if not certificate_type:
            raise ValueError("Debes indicar el tipo de certificado.")
        if not matricula_number:
            raise ValueError("Debes indicar el numero de matricula.")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO certificates(
                    cert_date,
                    certificate_type,
                    matricula_number,
                    quantity,
                    total_amount,
                    payment_method,
                    note,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cert_date,
                    certificate_type,
                    matricula_number,
                    quantity,
                    total_amount,
                    payment_method,
                    note,
                    user["id"],
                ),
            )
        flash("Certificado registrado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("certificates_page"))


@app.post("/certificados/<int:certificate_id>/actualizar")
@roles_required("admin")
def update_certificate(certificate_id: int) -> Any:
    try:
        cert_date = parse_date(request.form.get("cert_date", ""), "fecha")
        certificate_type = (request.form.get("certificate_type", "") or "").strip()
        matricula_number = (request.form.get("matricula_number", "") or "").strip()
        quantity = parse_positive_int(request.form.get("quantity", ""), "cantidad")
        total_amount = parse_non_negative_float(
            request.form.get("total_amount", ""), "valor total"
        )
        payment_method = parse_sale_payment_method(request.form.get("payment_method", ""))
        note = (request.form.get("note", "") or "").strip()

        if not certificate_type:
            raise ValueError("Debes indicar el tipo de certificado.")
        if not matricula_number:
            raise ValueError("Debes indicar el numero de matricula.")

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE certificates
                SET
                    cert_date = ?,
                    certificate_type = ?,
                    matricula_number = ?,
                    quantity = ?,
                    total_amount = ?,
                    payment_method = ?,
                    note = ?
                WHERE id = ?
                """,
                (
                    cert_date,
                    certificate_type,
                    matricula_number,
                    quantity,
                    total_amount,
                    payment_method,
                    note,
                    certificate_id,
                ),
            )
        flash("Certificado actualizado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("certificates_page")


@app.post("/certificados/<int:certificate_id>/eliminar")
@roles_required("admin")
def delete_certificate(certificate_id: int) -> Any:
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM certificates WHERE id = ?", (certificate_id,))
        flash("Certificado eliminado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect_to_next("certificates_page")


@app.get("/internet")
@roles_required("admin")
def internet_page() -> Any:
    with get_connection() as conn:
        records = conn.execute(
            """
            SELECT
                i.id,
                i.record_date,
                i.service_name,
                i.amount,
                i.note,
                u.username AS created_by
            FROM internet_records i
            LEFT JOIN users u ON u.id = i.created_by_user_id
            ORDER BY i.record_date DESC, i.id DESC
            """
        ).fetchall()
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                COALESCE(SUM(amount), 0) AS total_amount
            FROM internet_records
            """
        ).fetchone()

    return render_template(
        "internet.html",
        records=records,
        totals=totals,
        today=date.today().isoformat(),
    )


@app.post("/internet/registrar")
@roles_required("admin")
def add_internet_record() -> Any:
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))

        record_date = parse_date(request.form.get("record_date", ""), "fecha")
        service_name = (request.form.get("service_name", "") or "").strip()
        amount = parse_non_negative_float(request.form.get("amount", ""), "valor")
        note = (request.form.get("note", "") or "").strip()

        if not service_name:
            raise ValueError("Debes indicar el concepto o servicio.")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO internet_records(
                    record_date,
                    service_name,
                    amount,
                    note,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (record_date, service_name, amount, note, user["id"]),
            )
        flash("Registro de internet guardado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("internet_page"))


@app.post("/internet/<int:record_id>/actualizar")
@roles_required("admin")
def update_internet_record(record_id: int) -> Any:
    try:
        record_date = parse_date(request.form.get("record_date", ""), "fecha")
        service_name = (request.form.get("service_name", "") or "").strip()
        amount = parse_non_negative_float(request.form.get("amount", ""), "valor")
        note = (request.form.get("note", "") or "").strip()

        if not service_name:
            raise ValueError("Debes indicar el concepto o servicio.")

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE internet_records
                SET record_date = ?, service_name = ?, amount = ?, note = ?
                WHERE id = ?
                """,
                (record_date, service_name, amount, note, record_id),
            )
        flash("Registro de internet actualizado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("internet_page"))


@app.post("/internet/<int:record_id>/eliminar")
@roles_required("admin")
def delete_internet_record(record_id: int) -> Any:
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM internet_records WHERE id = ?", (record_id,))
        flash("Registro de internet eliminado.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("internet_page"))


init_db()


def _read_int_env(var_name: str, default_value: int, min_value: int = 1) -> int:
    raw = os.getenv(var_name, str(default_value)).strip()
    try:
        parsed = int(raw)
    except Exception:
        return default_value
    return parsed if parsed >= min_value else default_value


def run_server() -> None:
    host = (os.getenv("SERVISKYNET_HOST", "127.0.0.1") or "127.0.0.1").strip()
    port = _read_int_env("SERVISKYNET_PORT", 5000)
    threads = _read_int_env("SERVISKYNET_THREADS", 8, min_value=2)

    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=port, debug=False, use_reloader=False)
        return

    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    run_server()
