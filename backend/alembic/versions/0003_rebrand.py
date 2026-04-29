"""rebrand: operators, channels, contacts, transmissions, cipher_keys

Revision ID: 0003_rebrand
Revises: 0002_phase4
Create Date: 2026-04-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_rebrand"
down_revision: Union[str, Sequence[str], None] = "0002_phase4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename enum values (Postgres 10+)
    op.execute("ALTER TYPE presencerole RENAME VALUE 'warden' TO 'controller'")
    op.execute("ALTER TYPE presencerole RENAME VALUE 'moderator' TO 'relay'")
    op.execute("ALTER TYPE presencerole RENAME VALUE 'attendant' TO 'listener'")
    # 2. Rename enum type
    op.execute("ALTER TYPE presencerole RENAME TO contactrole")
    # 3. Column renames (before table renames)
    op.execute("ALTER TABLE presences RENAME COLUMN seance_id TO channel_id")
    op.execute("ALTER TABLE presences RENAME COLUMN sigil TO callsign")
    op.execute("ALTER TABLE presences RENAME COLUMN seeker_id TO operator_id")
    op.execute("ALTER TABLE whispers RENAME COLUMN seance_id TO channel_id")
    op.execute("ALTER TABLE whispers RENAME COLUMN sigil TO callsign")
    op.execute("ALTER TABLE whispers RENAME COLUMN seeker_id TO operator_id")
    op.execute("ALTER TABLE seances RENAME COLUMN is_sealed TO is_encrypted")
    op.execute("ALTER TABLE seances RENAME COLUMN whisper_ttl_seconds TO transmission_ttl_seconds")
    op.execute("ALTER TABLE invites RENAME COLUMN seance_id TO channel_id")
    # 4. Rename tables
    op.rename_table("seekers", "operators")
    op.rename_table("seances", "channels")
    op.rename_table("presences", "contacts")
    op.rename_table("whispers", "transmissions")
    op.rename_table("invites", "cipher_keys")
    # 5. Rename indexes
    op.execute("ALTER INDEX ix_seekers_id RENAME TO ix_operators_id")
    op.execute("ALTER INDEX ix_seekers_email RENAME TO ix_operators_email")
    op.execute("ALTER INDEX ix_seances_id RENAME TO ix_channels_id")
    op.execute("ALTER INDEX ix_seances_name RENAME TO ix_channels_name")
    op.execute("ALTER INDEX ix_whispers_id RENAME TO ix_transmissions_id")
    op.execute("ALTER INDEX ix_whispers_seance_id_id RENAME TO ix_transmissions_channel_id_id")
    # 6. Rename unique constraint
    op.execute(
        "ALTER TABLE contacts RENAME CONSTRAINT uq_presence_seance_sigil TO uq_contact_channel_callsign"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE contacts RENAME CONSTRAINT uq_contact_channel_callsign TO uq_presence_seance_sigil"
    )
    op.execute("ALTER INDEX ix_transmissions_channel_id_id RENAME TO ix_whispers_seance_id_id")
    op.execute("ALTER INDEX ix_transmissions_id RENAME TO ix_whispers_id")
    op.execute("ALTER INDEX ix_channels_name RENAME TO ix_seances_name")
    op.execute("ALTER INDEX ix_channels_id RENAME TO ix_seances_id")
    op.execute("ALTER INDEX ix_operators_email RENAME TO ix_seekers_email")
    op.execute("ALTER INDEX ix_operators_id RENAME TO ix_seekers_id")
    op.rename_table("cipher_keys", "invites")
    op.rename_table("transmissions", "whispers")
    op.rename_table("contacts", "presences")
    op.rename_table("channels", "seances")
    op.rename_table("operators", "seekers")
    op.execute("ALTER TABLE invites RENAME COLUMN channel_id TO seance_id")
    op.execute("ALTER TABLE seances RENAME COLUMN transmission_ttl_seconds TO whisper_ttl_seconds")
    op.execute("ALTER TABLE seances RENAME COLUMN is_encrypted TO is_sealed")
    op.execute("ALTER TABLE whispers RENAME COLUMN operator_id TO seeker_id")
    op.execute("ALTER TABLE whispers RENAME COLUMN callsign TO sigil")
    op.execute("ALTER TABLE whispers RENAME COLUMN channel_id TO seance_id")
    op.execute("ALTER TABLE presences RENAME COLUMN callsign TO sigil")
    op.execute("ALTER TABLE presences RENAME COLUMN channel_id TO seance_id")
    op.execute("ALTER TABLE presences RENAME COLUMN operator_id TO seeker_id")
    op.execute("ALTER TYPE contactrole RENAME TO presencerole")
    op.execute("ALTER TYPE presencerole RENAME VALUE 'listener' TO 'attendant'")
    op.execute("ALTER TYPE presencerole RENAME VALUE 'relay' TO 'moderator'")
    op.execute("ALTER TYPE presencerole RENAME VALUE 'controller' TO 'warden'")
