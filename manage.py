"""Admin CLI for account management.

Useful when self-service registration is disabled (ALLOW_REGISTRATION=false)
and accounts must be provisioned manually.

Usage:
    python manage.py create-user --username janedoe --password "S3cure!" --display "Jane Doe" [--school "X" --role admin]
    python manage.py set-role --username janedoe --role admin
    python manage.py reset-password --username janedoe --password "NewPass1"
    python manage.py list-users
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402
from app import models  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Face Attendance admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-user", help="Create a teacher/admin account")
    p_create.add_argument("--username", required=True)
    p_create.add_argument("--password", required=True)
    p_create.add_argument("--display", required=True, help="Display name")
    p_create.add_argument("--school", default="")
    p_create.add_argument("--role", choices=["teacher", "admin"], default="teacher")

    p_role = sub.add_parser("set-role", help="Change a user's role")
    p_role.add_argument("--username", required=True)
    p_role.add_argument("--role", choices=["teacher", "admin"], required=True)

    p_reset = sub.add_parser("reset-password", help="Reset a user's password")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", required=True)

    sub.add_parser("list-users", help="List all accounts")

    args = parser.parse_args()
    app = create_app()
    db = app.db

    if args.command == "create-user":
        user = models.get_user_by_username(db, args.username.lower())
        if user:
            print(f"user '{args.username}' already exists", file=sys.stderr)
            sys.exit(1)
        user_id = models.create_user(
            db,
            args.username.lower(),
            args.password,
            args.display,
            args.school,
            role=args.role,
        )
        print(f"created {args.role} user '{args.username}' (id={user_id})")

    elif args.command == "set-role":
        user = models.get_user_by_username(db, args.username.lower())
        if not user:
            print(f"user '{args.username}' not found", file=sys.stderr)
            sys.exit(1)
        models.set_user_role(db, user.id, args.role)
        print(f"user '{args.username}' is now {args.role}")

    elif args.command == "reset-password":
        user = models.get_user_by_username(db, args.username.lower())
        if not user:
            print(f"user '{args.username}' not found", file=sys.stderr)
            sys.exit(1)
        from werkzeug.security import generate_password_hash
        from app.database import users
        from sqlalchemy import update

        sess = db.session
        sess.execute(
            update(users).where(users.c.id == user.id).values(
                password_hash=generate_password_hash(args.password)
            )
        )
        sess.commit()
        print(f"password reset for '{args.username}'")

    elif args.command == "list-users":
        from app.database import users as users_tbl
        from sqlalchemy import select

        rows = db.session.execute(
            select(users_tbl.c.id, users_tbl.c.username, users_tbl.c.display_name, users_tbl.c.role)
            .order_by(users_tbl.c.id)
        ).all()
        for r in rows:
            print(f"{r.id}\t{r.username}\t{r.role}\t{r.display_name}")


if __name__ == "__main__":
    main()
