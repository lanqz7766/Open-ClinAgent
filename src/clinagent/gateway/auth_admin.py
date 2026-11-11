from __future__ import annotations

import argparse
import getpass
import json
import sys

from clinagent.gateway.auth import ClinAgentAuthStore
from clinagent.gateway.email_delivery import ClinAgentEmailSender
from clinagent.platform.config import load_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ClinAgent account administration")
    commands = parser.add_subparsers(dest="command", required=True)
    invite = commands.add_parser("invite", help="Create a single-use physician preview invitation")
    invite.add_argument("--email", required=True)
    invite.add_argument("--name", required=True)
    invite.add_argument("--organization", default="")
    invite.add_argument(
        "--role",
        choices=("radiologist", "resident", "researcher", "admin"),
        default="radiologist",
    )
    invite.add_argument("--expires-hours", type=int, default=72)
    invite.add_argument("--print-link", action="store_true", help="Print the secret link instead of sending email")
    create = commands.add_parser("create-user", help="Create a permanent account with first-login setup")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--organization", default="")
    create.add_argument("--role", choices=("radiologist", "resident", "researcher", "admin"), default="radiologist")
    create.add_argument("--password-stdin", action="store_true", help="Read the initial password from standard input")
    commands.add_parser("list-users", help="List accounts without password material")
    status = commands.add_parser("set-status", help="Enable or suspend a non-administrator account")
    status.add_argument("--email", required=True)
    status.add_argument("--status", required=True, choices=("active", "suspended"))
    reset = commands.add_parser("reset-password", help="Set an initial password and revoke existing sessions")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-stdin", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_settings()
    store = ClinAgentAuthStore.from_env()
    if args.command != "invite":
        try:
            if args.command == "list-users":
                print(json.dumps(store.list_users(), indent=2))
                return 0
            if args.command in {"create-user", "reset-password"}:
                if args.password_stdin:
                    password = sys.stdin.readline().rstrip("\r\n")
                else:
                    password = getpass.getpass("Initial password (12 or more characters): ")
                    if password != getpass.getpass("Confirm initial password: "):
                        raise ValueError("Passwords do not match.")
            if args.command == "create-user":
                user = store.provision_user(email=args.email, password=password, name=args.name,
                                            organization=args.organization, role=args.role)
            else:
                target = store.get_user_by_email(args.email)
                if not target:
                    raise ValueError("Account not found.")
                user = (store.set_user_status(target["id"], args.status) if args.command == "set-status"
                        else store.set_temporary_password(target["id"], password))
            store.record_audit(user_id=None, action="operator_" + args.command.replace("-", "_"),
                               resource="account:" + user["id"], status="200")
            print(json.dumps(user, indent=2))
            return 0
        except (ValueError, LookupError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    sender = ClinAgentEmailSender.from_env()
    invitation, token = store.create_invitation(
        email=args.email,
        name=args.name,
        organization=args.organization,
        role=args.role,
        expires_hours=args.expires_hours,
    )
    if args.print_link:
        if not sender.settings.public_url:
            raise RuntimeError("CLINAGENT_PUBLIC_URL is required to print an invitation link.")
        print(sender.invitation_url(token))
    else:
        sender.send_invitation(
            email=invitation["email"],
            name=invitation["name"],
            token=token,
            expires_hours=args.expires_hours,
        )
        print(f"Invitation sent to {invitation['email']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
