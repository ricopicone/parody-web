"""Pull an edition back to draft (owner-only) without a rebuild — the reverse
of ``publish_edition``. See that command for details."""
from parody_web.management.commands.publish_edition import Command as _Publish


class Command(_Publish):
    help = "Set an edition's draft flag (make it owner-only again)."
    draft_value = True
