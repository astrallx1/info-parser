class RunCancelled(Exception):
    """Raised at a cancellation checkpoint when the user hit Stop mid-run.

    Carries whatever the run had ALREADY finished. A run costs minutes of scraping
    plus a paid scoring call per profile, and each profile's topics are persisted as
    soon as it is done — so a bare exception meant the profiles that completed were
    written to `shown_topics`, never shown, and then suppressed by cross-run dedup on
    the next run. The payload is what lets the UI render them instead.

    Lives in its own module so both pipeline and ranker can raise/catch it without a
    circular import (pipeline imports ranker). `ranker` raises it with no payload —
    only the pipeline knows what a whole run had gathered.
    """

    def __init__(self, *args, topics=None, alerts=None, warnings=None):
        super().__init__(*args)
        self.topics = topics if topics is not None else []
        self.alerts = alerts if alerts is not None else []
        self.warnings = warnings if warnings is not None else []
