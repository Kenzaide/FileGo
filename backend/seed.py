"""Development seed: python seed.py [--reset]

Creates the demo accounts (student = administrator, alex, jamie; password demo123)
and six fake sample files. Development only: do not use these accounts on a real system.
"""
import sys

from app import create_app
from app.seed_data import DEMO_PASSWORD, reset_all, seed_demo


def main():
    app = create_app()
    with app.app_context():
        if "--reset" in sys.argv:
            reset_all()
            print("Database reset.")
        users, files = seed_demo()
        print(f"Seeded {users} user(s) and {files} sample file(s).")
        print(f"Demo logins: student (admin), alex, jamie  |  password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
