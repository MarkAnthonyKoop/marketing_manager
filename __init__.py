"""marketing_manager — an AI marketing manager that runs your social toolkit.

The top-level orchestrator of the marketing stack. A chatbot REPL (powered by
the `claude` CLI under the hood) plans and executes marketing work by driving
`social_publisher` and the per-platform `*_manager` packages; plus engines for
scheduled posts and drip campaigns, and a history log.

    from marketing_manager import brain, campaigns, schedule, publish
    brain.ask("draft a launch post and dry-run it to all working platforms")

CLI: `python3 -m marketing_manager chat` (and post/schedule/campaign/scrape/
history). See README.md.
"""
from . import brain, campaigns, publish, schedule, scrape, store, timing

__all__ = ["brain", "campaigns", "schedule", "publish", "scrape", "store", "timing"]
__version__ = "0.1.0"
