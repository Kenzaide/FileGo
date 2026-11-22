import click
from sqlalchemy import select

from .auth import hash_password
from .extensions import db
from .models import User
from .validators import check_password, clean_name, clean_username
from .errors import ApiError


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--username", prompt="Username")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(name, username, password):
        """Create an administrator account."""
        try:
            name = clean_name(name)
            username = clean_username(username)
            check_password(password)
        except ApiError as e:
            raise click.ClickException(e.message)
        if db.session.scalar(select(User.id).where(User.username == username)):
            raise click.ClickException("That username already exists.")
        db.session.add(
            User(name=name, username=username, password_hash=hash_password(password), role="admin")
        )
        db.session.commit()
        click.echo(f"Administrator '{username}' created.")

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def reset_password(username, password):
        """Set a new password for a user and sign them out everywhere."""
        user = db.session.scalar(select(User).where(User.username == username.lower()))
        if user is None:
            raise click.ClickException("No such user.")
        try:
            check_password(password)
        except ApiError as e:
            raise click.ClickException(e.message)
        from .auth import delete_user_sessions

        user.password_hash = hash_password(password)
        user.must_change_password = False
        delete_user_sessions(user.id)
        db.session.commit()
        click.echo("Password updated.")
