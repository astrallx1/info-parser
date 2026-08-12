import os
import threading

from topicparser import store, notify, i18n, paths, tuning
from topicparser.pipeline import run, RunCancelled


def _md_filename(day=None, run_id=None) -> str:
    """Name the export after the RUN it holds — one run's topics per file, and a folder
    of them stays sorted and tells you when each was captured.

    `run_id` is that run's timestamp. Falling back to TODAY named yesterday's restored
    feed after today, which is the same resolve-at-the-wrong-moment trap the export
    scope itself was fixed for: the contents are the last run, so the name must be too.
    Only a run with no id (or none at all) falls back to today."""
    from datetime import date, datetime
    if run_id:
        try:
            return f"topics-{datetime.fromisoformat(run_id).date().isoformat()}.md"
        except (TypeError, ValueError):
            pass
    return f"topics-{(day or date.today()).isoformat()}.md"


def _topics_ready(n: int) -> str:
    """The run-finished banner's count. Declension is a per-language rule now (see
    i18n.plural) — the count used to read wrong in Ukrainian for most N."""
    return i18n.plural("topics_ready", n)


def _has_sources(cfg):
    """True when a profile config has at least one source selected."""
    x = cfg.get("x", {}) or {}
    g = cfg.get("github", {}) or {}
    f = cfg.get("feeds", {}) or {}
    return bool(x.get("accounts") or x.get("lists") or x.get("searches")
                or g.get("topics") or f.get("urls"))


class Api:
    def __init__(self, *, profiles, build_collectors, build_client,
                 threshold, x_days, gh_days, feed_days=None, stagnant_days=21,
                 min_velocity=50,
                 batch_size=120, off_interest=None, profiles_path=None,
                 prompt_loader=None,
                 group_prompt_loader=None, dedup_prompt_loader=None,
                 xgate_prompt_loader=None, feedgate_prompt_loader=None,
                 debug_dir=None, cookies_path=None):
        self._profiles = profiles
        self._build_collectors = build_collectors
        self._build_client = build_client
        self._threshold = threshold
        self._x_days = x_days
        self._feed_days = feed_days
        self._gh_days = gh_days
        self._stagnant_days = stagnant_days
        self._min_velocity = min_velocity
        self._batch_size = batch_size
        self._off_interest = off_interest or set()
        self._profiles_path = profiles_path
        self._prompt_loader = prompt_loader
        self._group_prompt_loader = group_prompt_loader
        self._dedup_prompt_loader = dedup_prompt_loader
        self._xgate_prompt_loader = xgate_prompt_loader
        self._feedgate_prompt_loader = feedgate_prompt_loader
        self._debug_dir = debug_dir
        self._cookies_path = cookies_path
        self._running = False
        self._run_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._phase = ""               # current coarse run phase, pulled by the UI
        self._last_topic_ids = set()   # ids from the most recent run -> the .md scope
        self._last_alerts = []         # that run's trending alerts -> the .md's lead block

    def get_strings(self):
        """Every user-visible string for the UI, out of the SAME catalogue Python
        reads. One source, so the two halves of the app cannot drift apart."""
        return {"lang": i18n.default_lang(), "strings": i18n.strings()}

    def get_profiles(self):
        return self._profiles

    def save_profiles(self, data):
        from topicparser import config
        errs = config.validate_profiles(data)
        if errs:
            return {"errors": errs}
        self._profiles = data
        if self._profiles_path:
            config.save_profiles(self._profiles_path, data)
        return {"ok": True}

    # --- profiles: create / rename / delete -------------------------------------
    # A profile is a yaml entry AND a `<name>.txt` prompt; the two must never drift,
    # because a profile with no prompt scores on the ranker's stub and still produces
    # a plausible-looking feed. Every path here moves both or neither.
    def _write_profiles(self, profiles):
        from topicparser import config
        data = {"profiles": profiles}
        errs = config.validate_profiles(data)
        if errs:
            return {"errors": errs}
        self._profiles = data
        if self._profiles_path:
            config.save_profiles(self._profiles_path, data)
        return {"ok": True}

    def add_profile(self, name):
        from topicparser import config, prompts_loader
        errs = config.validate_profile_name(name)
        profiles = dict((self._profiles or {}).get("profiles") or {})
        if name in profiles:
            errs = errs + [i18n.t("err.profile_exists", name=name)]
        if errs:
            return {"errors": errs}
        # the starter prompt matters: an empty textarea tells a new user nothing, and
        # an empty FILE would put the scorer on its stub without saying so
        errs = prompts_loader.save_profile_prompt(
            name, prompts_loader.read_prompt("_starter") or "SCORE every signal 0-100.")
        if errs:
            return {"errors": errs}
        profiles[name] = {"github": {"topics": []},
                          "x": {"accounts": [], "lists": [], "searches": []}}
        return self._write_profiles(profiles)

    def rename_profile(self, old, new):
        from topicparser import config, prompts_loader
        profiles = dict((self._profiles or {}).get("profiles") or {})
        errs = config.validate_profile_name(new)
        if old not in profiles:
            errs.append(i18n.t("err.no_such_profile", name=old))
        if new in profiles:
            errs.append(i18n.t("err.profile_exists", name=new))
        if errs:
            return {"errors": errs}
        # COPY, write, then delete. The move used to run first, so a failing yaml
        # write left `<old>.txt` deleted while the config still named `old` — and a
        # profile whose prompt is gone scores on the ranker's stub. Ordered this way,
        # any failure leaves an orphan prompt instead, which costs nothing.
        # (`add_profile` writes its prompt FIRST for the same reason: an orphan file
        # is harmless, a profile without rules is not.)
        errs = prompts_loader.copy_profile_prompt(old, new)
        if errs:
            return {"errors": errs}
        profiles = {(new if k == old else k): v for k, v in profiles.items()}
        res = self._write_profiles(profiles)
        if res.get("errors"):
            prompts_loader.delete_profile_prompt(new)     # undo the copy
            return res
        prompts_loader.delete_profile_prompt(old)
        return res

    def delete_profile(self, name):
        from topicparser import prompts_loader
        profiles = dict((self._profiles or {}).get("profiles") or {})
        if name not in profiles:
            return {"errors": [i18n.t("err.no_such_profile", name=name)]}
        if len(profiles) == 1:
            # an app with no profile can do nothing, and the config would fail to
            # validate on the next load — refuse instead of writing it
            return {"errors": [i18n.t("err.last_profile")]}
        profiles.pop(name)
        res = self._write_profiles(profiles)
        if res.get("ok"):
            prompts_loader.delete_profile_prompt(name)
        return res

    # --- prompts ----------------------------------------------------------------
    def list_prompts(self):
        from topicparser import prompts_loader
        names = list((self._profiles or {}).get("profiles") or {})
        return prompts_loader.list_prompts(names)

    def get_prompt(self, name):
        from topicparser import prompts_loader
        editable = name not in prompts_loader.SHARED_PROMPTS
        return {"name": name, "editable": editable,
                "has_backup": prompts_loader.has_backup(name),
                "text": prompts_loader.read_prompt(name)}

    def _writable_prompt(self, name):
        """The names save/restore accept: a profile's own prompt, or `_meta`. Returns
        an error list. `_meta` is NOT a profile, so a bare profile-name check rejected
        it and its Save could never succeed, even though the screen offered an editor."""
        from topicparser import prompts_loader
        if name in prompts_loader.SHARED_PROMPTS:
            return [i18n.t("err.prompt_readonly", name=name)]
        if name in prompts_loader.EDITABLE_EXTRAS:
            return []
        if name not in ((self._profiles or {}).get("profiles") or {}):
            return [i18n.t("err.no_such_profile", name=name)]
        return []

    def save_prompt(self, name, text):
        from topicparser import prompts_loader
        errs = self._writable_prompt(name)
        if errs:
            return {"errors": errs}
        errs = prompts_loader.save_profile_prompt(name, text)
        return {"errors": errs} if errs else {"ok": True}

    def restore_prompt(self, name):
        """Put back the version a save replaced. The editor's way out of a bad edit —
        these files are months of tuning and had no undo of any kind."""
        from topicparser import prompts_loader
        errs = self._writable_prompt(name)
        if errs:
            return {"errors": errs}
        errs = prompts_loader.restore_profile_prompt(name)
        if errs:
            return {"errors": errs}
        return {"ok": True, "text": prompts_loader.read_prompt(name)}

    # --- first-run setup --------------------------------------------------------
    # Two API keys and an X session. None of them can be supplied by someone who does
    # not edit dotfiles, which is where most people would have given up.
    SETTABLE = ("GITHUB_TOKEN", "OPENAI_API_KEY", "LLM_MODEL", "APP_LANG")

    def _env_path(self):
        return paths.resolve(".env")

    def _env_value(self, name):
        """The key as the RUN would see it: the `.env` file, then the environment.

        The pipeline reads `os.environ`, so `GITHUB_TOKEN=… python main.py` is a
        perfectly configured app — but every UI check read the FILE alone, so the
        first-run guide opened over a working install and `check_keys` refused to
        start the run, naming both keys as rejected."""
        import os

        from topicparser import settings
        return settings.read_env(self._env_path()).get(name) or os.environ.get(name)

    def get_settings(self):
        """Masked values only. The window is local, but a key on screen ends up in a
        screenshot eventually, and nothing here needs the real thing."""
        from topicparser import settings
        env = settings.read_env(self._env_path())
        return {**{k: settings.mask(env.get(k, "")) for k in
                   ("GITHUB_TOKEN", "OPENAI_API_KEY")},
                "LLM_MODEL": env.get("LLM_MODEL", "gpt-4.1-mini"),
                "has": {k: bool(env.get(k)) for k in self.SETTABLE}}

    def save_settings(self, values):
        from topicparser import settings
        values = values or {}
        unknown = [k for k in values if k not in self.SETTABLE]
        if unknown:
            # this screen writes `.env`; it must not become a way to set any variable
            return {"errors": [i18n.t("err.unknown_setting",
                                      names=", ".join(unknown))]}
        # a blank field means "leave it" — the UI shows masked values, so an untouched
        # field comes back empty and would otherwise wipe a working key
        keep = {k: v for k, v in values.items() if str(v or "").strip()}
        if keep:
            settings.write_env(self._env_path(), keep)
        return {"ok": True}

    # --- tuning knobs -------------------------------------------------------------
    # They used to be `.env`-only AND frozen at construction, so changing how the tool
    # judges meant finding a dotfile and restarting. `tuning.py` declares them once;
    # the screen renders that declaration and the run resolves through it, so the
    # screen cannot promise a number the run does not use.
    def _tuning_defaults(self):
        """What this Api was built with — the fallback when `.env` says nothing.

        An EMPTY value is dropped rather than passed on. `off_interest` is an empty set
        when nobody supplies one, and handing `""` down as a "default" outranks whatever
        `tuning.py` declares: back when `OFF_INTEREST` shipped with a non-empty default,
        that is exactly what turned the filter off without saying so.
        """
        built = {"SCORE_THRESHOLD": self._threshold,
                 "X_FRESH_DAYS": self._x_days,
                 "FEED_FRESH_DAYS": self._feed_days,
                 "GH_FRESH_DAYS": self._gh_days,
                 "TRACK_STAGNANT_DAYS": self._stagnant_days,
                 "TREND_MIN_VELOCITY": self._min_velocity,
                 "OFF_INTEREST": ", ".join(sorted(self._off_interest))}
        return {k: v for k, v in built.items() if v not in (None, "")}

    def _tuning(self):
        return tuning.read(self._tuning_defaults())

    def get_tuning(self):
        return {"values": self._tuning(),
                "knobs": [{"name": k.name, "kind": k.kind, "default": k.default,
                           "min": k.minimum, "max": k.maximum} for k in tuning.KNOBS]}

    def save_tuning(self, values):
        from topicparser import settings
        # the WHOLE body holds the lock, not just the flag read: checking under the
        # lock and then writing outside it only moves the window, since run_parser
        # takes the same lock to set the flag and would start mid-write
        with self._run_lock:
            if self._running:
                # half the run would use the old numbers and half the new ones, and
                # the debug log would record neither
                return {"errors": [i18n.t("error.run_in_flight")]}
            errs = tuning.validate(values or {})
            if errs:
                return {"errors": errs}
            settings.write_env(self._env_path(), tuning.for_env(values or {}))
            return {"ok": True}

    def _has_cookies(self):
        import json
        import os
        path = paths.resolve(self._cookies_path or "./cookies.json")
        if not os.path.exists(path):
            return False
        try:
            with open(path, encoding="utf-8") as f:
                names = {c.get("name") for c in (json.load(f).get("cookies") or [])}
            return {"auth_token", "ct0"} <= names
        except (OSError, ValueError):
            return False

    def setup_state(self):
        """What is still missing, and whether the app can do anything at all yet.

        X is OPTIONAL: without cookies the run is GitHub-only, which is a perfectly
        good first experience and skips the fiddliest step. Only the keys block."""
        missing = [k for k in ("GITHUB_TOKEN", "OPENAI_API_KEY")
                   if not self._env_value(k)]
        blocking = list(missing)
        if not self._has_cookies():
            missing.append("cookies")
        return {"missing": missing, "needs_onboarding": bool(blocking)}

    def import_cookies(self, text):
        """Take a Cookie-Editor export pasted into a box and write cookies.json."""
        import json

        from import_cookies import convert
        try:
            raw = json.loads(text or "")
        except ValueError:
            return {"errors": [i18n.t("err.cookies_not_json")]}
        try:
            state = convert(raw)
        except (TypeError, ValueError, KeyError, AttributeError):
            return {"errors": [i18n.t("err.cookies_not_export")]}
        names = {c["name"] for c in state["cookies"]}
        if not {"auth_token", "ct0"} <= names:
            # writing it anyway would produce a login redirect much later, in the
            # middle of a 15-minute run, and read as "X is broken"
            return {"errors": [i18n.t("err.cookies_missing_auth")]}
        path = paths.resolve(self._cookies_path or "./cookies.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        try:
            os.chmod(path, 0o600)
        except (OSError, NameError):
            pass          # a live X session in plain text: keep it off other accounts
        return {"ok": True, "count": len(state["cookies"])}

    # one cheap read-only endpoint per key: a token that is merely SAVED tells the
    # user nothing, and a wrong one otherwise surfaces 15 minutes into a run
    _PROBES = {
        "GITHUB_TOKEN": ("https://api.github.com/user",
                         lambda k: {"Authorization": f"Bearer {k}"}),
        "OPENAI_API_KEY": ("https://api.openai.com/v1/models",
                           lambda k: {"Authorization": f"Bearer {k}"}),
    }

    def verify_key(self, name):
        import requests

        probe = self._PROBES.get(name)
        if not probe:
            return {"errors": [i18n.t("err.cannot_verify", name=name)]}
        key = self._env_value(name)
        if not key:
            return {"errors": [i18n.t("err.nothing_to_verify")], "missing": True}
        url, headers = probe
        # `unreachable` = the probe could not reach a verdict, which is NOT the same
        # answer as "this key is bad" even though both are an error on screen. Only
        # check_keys reads it; the Verify button reports either one the same way.
        try:
            r = requests.get(url, headers=headers(key), timeout=10)
        except Exception as e:
            return {"errors": [str(e)], "unreachable": True}
        if r.status_code != 200:
            return {"errors": [i18n.t("err.key_rejected", status=r.status_code)],
                    # 401 is the ONLY status that judges the key: both probes answer a
                    # bad key with it. 403 does not — GitHub returns it for a secondary
                    # rate limit, an SSO-unauthorised token and an IP allowlist, and
                    # OpenAI for an unsupported region. A valid key on a bad day must
                    # not read as a bad key.
                    "unreachable": r.status_code != 401}
        try:
            body = r.json()
        except ValueError:
            body = {}
        detail = body.get("login") or f"{len(body.get('data') or [])} models"
        return {"ok": True, "detail": detail}

    def check_keys(self):
        """Are the saved keys actually USABLE — not merely present?

        `setup_state` only asks whether a key is non-empty, which is how placeholder
        text sat in `.env` for a day: the app read as configured, the guide stayed
        shut, and a run would have spent a 15-minute scrape before dying on the first
        scoring call. The UI calls this right before it starts a run.

        It never raises and never refuses on doubt: a dead network reports "fine", so
        the worst case is the old behaviour rather than a run the user cannot start.
        That promise was only in this docstring — `verify_key` returned the same shape
        for "no route to host" as for a 401, so one DNS blip named both keys as
        rejected and the UI refused to start the run, blaming the keys.
        """
        rejected = []
        for name in ("GITHUB_TOKEN", "OPENAI_API_KEY"):
            try:
                out = self.verify_key(name)
                # `missing` is deliberately NOT excused here. It is not doubt — it is
                # the state the first-run guide exists to fix, and letting the run
                # start on it spends the whole scrape before the first paid call dies.
                # Only `unreachable` (a dead network, a 403 rate limit) is doubt.
                if not out.get("ok") and not out.get("unreachable"):
                    rejected.append(name)
            except Exception:
                pass
        return {"ok": not rejected, "rejected": rejected}

    def test_prompt(self, name, text):
        """Score a past run's signals with a CANDIDATE prompt, without saving it.

        A full run costs ~15 minutes of scraping plus every paid call, so this is the
        only affordable way to see what an edit does. The candidate is assembled with
        the shared rules exactly as a real run assembles them — testing the profile
        text alone would measure something the pipeline never sends."""
        import os

        from topicparser import prompts_loader, replay
        if name in prompts_loader.SHARED_PROMPTS:
            return {"errors": [i18n.t("err.prompt_readonly", name=name)]}
        if not (text or "").strip():
            return {"errors": [i18n.t("err.prompt_empty")]}

        path = replay.latest_debug_run(self._debug_dir or "")
        is_sample = path is None
        if is_sample:
            # a fresh install has no run of its own, and the editor is exactly where
            # a new user needs feedback most — so one scrubbed run ships with the app
            path = os.path.join(paths.bundle_dir(), "topicparser", "sample",
                                "run-sample.json")
            if not os.path.exists(path):
                return {"errors": [i18n.t("err.no_run_to_test")]}

        system = f"{prompts_loader.load_base()}\n\n{text.strip()}".strip()
        try:
            # resolved HERE, like `run_parser` does: reading the threshold the `Api`
            # was CONSTRUCTED with counted `passed` against the old bar until a restart
            out = replay.score_with(path, name, system, self._build_client(),
                                    threshold=self._tuning()["SCORE_THRESHOLD"])
        except Exception as e:
            return {"errors": [str(e)]}
        out["is_sample"] = is_sample
        return out

    def run_parser(self, selection):
        # selection: { profileName: {github:{topics}, x:{accounts,lists,searches},
        #                              feeds:{urls}} },
        # carrying only the sources the user checked. Profiles with nothing checked
        # are dropped; each surviving profile is still scored by its own prompt.
        # Check and set under one lock. They used to be two statements with nothing
        # between them, so two bridge threads (a double click) could both pass the
        # check and both start scraping — twice the cost of the most expensive thing
        # here, with two sets of writes interleaved.
        with self._run_lock:
            if self._running:
                return {"error": i18n.t("err.already_running")}
            self._running = True
        self._cancel_event.clear()   # a prior Stop must not cancel this new run
        self._phase = i18n.t("run.working")
        # Set per outcome, and ONLY once a run actually starts: a refused call used to
        # fire "run finished" for a run that never happened.
        note = None
        try:
            profiles = {n: cfg for n, cfg in (selection or {}).items() if _has_sources(cfg)}
            if not profiles:
                return {"error": i18n.t("err.no_sources_selected")}
            # resolved HERE, not at construction, so a knob saved in Settings reaches
            # this run instead of waiting for a restart
            t = self._tuning()
            result = run(selected=list(profiles.keys()), profiles=profiles,
                         collectors=self._build_collectors(), client=self._build_client(),
                         threshold=t["SCORE_THRESHOLD"], x_days=t["X_FRESH_DAYS"],
                         gh_days=t["GH_FRESH_DAYS"],
                         feed_days=t["FEED_FRESH_DAYS"],
                         stagnant_days=t["TRACK_STAGNANT_DAYS"],
                         min_velocity=t["TREND_MIN_VELOCITY"],
                         batch_size=self._batch_size,
                         off_interest=tuning.off_interest_terms(t),
                         prompt_loader=self._prompt_loader,
                         group_prompt_loader=self._group_prompt_loader,
                         dedup_prompt_loader=self._dedup_prompt_loader,
                         xgate_prompt_loader=self._xgate_prompt_loader,
                         feedgate_prompt_loader=self._feedgate_prompt_loader,
                         debug_dir=self._debug_dir,
                         cancel_event=self._cancel_event,
                         progress=self._set_phase)
            topics = result.get("topics", []) if isinstance(result, dict) else (result or [])
            if isinstance(result, dict):    # one run = one .md: remember this run's scope
                self._last_topic_ids = {t["id"] for t in topics
                                        if isinstance(t, dict) and "id" in t}
                self._last_alerts = result.get("alerts", []) or []
            n = len(topics)
            alerts = len(self._last_alerts) if isinstance(result, dict) else 0
            msg = _topics_ready(n) + (i18n.t("run.trending_suffix", n=alerts) if alerts else "")
            note = ("Info Parser", msg)
            return result
        except RunCancelled as e:
            # Stop is not a failure: the profiles that finished are already in the DB,
            # so hand their topics to the feed instead of showing an empty screen and
            # letting cross-run dedup bury them on the next run.
            note = ("Info Parser", i18n.t("run.cancelled"))
            topics = list(e.topics or [])
            self._last_topic_ids = {t["id"] for t in topics
                                    if isinstance(t, dict) and "id" in t}
            self._last_alerts = list(e.alerts or [])
            return {"cancelled": True, "topics": topics,
                    "alerts": self._last_alerts, "warnings": list(e.warnings or [])}
        except Exception as e:
            note = ("Info Parser", i18n.t("run.error", error=e))
            return {"error": str(e)}
        finally:
            self._running = False
            self._phase = ""
            try:
                store.checkpoint()   # land this run's writes in topics.db, not the -wal sidecar
            except Exception:
                pass          # a checkpoint failure must never affect the run outcome
            try:
                if note is not None:      # nothing ran -> nothing to announce
                    notify.send(note[0], note[1])
            except Exception:
                pass          # a notification must never affect the run outcome

    def _set_phase(self, msg):
        """Record the current coarse run phase. The pipeline calls this from the
        background run thread; the UI PULLS it via get_phase() on a timer. Pull
        (JS -> Python) is pywebview's reliable direction — pushing from Python via
        evaluate_js across threads is not, so we don't."""
        self._phase = msg

    def get_phase(self):
        """The current run phase text for the UI status line ("" when idle)."""
        return self._phase

    def is_running(self):
        """True while a run() is in flight — the close-warning hook in main.py
        checks this to warn before the window closes mid-run."""
        return self._running

    def stop(self):
        """Cooperative cancel: sets a flag the running pipeline checks between
        collectors/profiles. Does not kill anything mid-network-call."""
        self._cancel_event.set()
        return True

    def set_kept(self, topic_id, kept):
        store.set_kept(int(topic_id), bool(kept)); return True

    def get_saved_topics(self):
        """The last run's topics, read back from the DB so the feed survives a
        restart. The screen used to draw only what `run_parser` returned, so closing
        the app emptied it and killed the `.md` button while sixty days of topics sat
        in the database, reachable by nothing. Also re-arms `_last_topic_ids`, which
        is memory-only and is what scopes the export to one run."""
        topics = store.get_last_run_topics()
        self._last_topic_ids = {t["id"] for t in topics}
        return {"topics": topics}

    def _md_topics(self):
        """The .md scope = only the most recent run's topics that are still kept
        (one run = one .md), not every topic accumulated in the DB."""
        # the last run is the last run: this used to filter by the freshness windows
        # the Api was CONSTRUCTED with, while every other knob resolves at run time
        topics = store.get_last_run_topics()
        return [t for t in topics if t.get("kept", 1) and t["id"] in self._last_topic_ids]

    def get_tracked(self):
        return store.get_tracked_detail()

    # --- wiping the database ------------------------------------------------------
    # The owner asked for this as a Settings button. It removes shown topics (so
    # cross-run dedup starts over), the watchlist, the star history trending is built
    # from, and the ban list. The UI shows these counts in the confirmation.
    def db_stats(self):
        return store.count_all()

    def reset_database(self, parts=None):
        """`parts` = {"topics":bool, "tracked":bool, "banned":bool}; everything by
        default. The UI ticks these in a dialog, so a wipe never has to be all or
        nothing — the watchlist is months of star measurements and is usually worth
        keeping when the point was only to clear shown topics before a verify run."""
        # the wipe itself holds the run lock, or a run starting between the check and
        # the delete lands half its writes after it
        with self._run_lock:
            if self._running:
                return {"errors": [i18n.t("error.run_in_flight")]}
            p = parts or {}
            topics = p.get("topics", True)
            tracked = p.get("tracked", True)
            banned = p.get("banned", True)
            if not (topics or tracked or banned):
                return {"errors": [i18n.t("err.nothing_selected")]}
            backup = store.reset_all(topics=topics, tracked=tracked, banned=banned)
            if topics:
                self._last_topic_ids = set()   # those rows are gone, nothing to export
                self._last_alerts = []         # a list everywhere else; None reached export
            return {"ok": True, "backup": backup}

    def open_url(self, url):
        """Open a link in the OS browser — http/https ONLY. Every link here started
        life on a scraped page, and `webbrowser.open` hands an arbitrary scheme to the
        platform opener (`open` on macOS, ShellExecute on Windows), which will happily
        run `file://` or a registered custom scheme. Refuse instead of guessing."""
        import webbrowser
        if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            return False
        webbrowser.open(url)
        return True

    def unwatch_repo(self, repo):
        store.remove_tracked_repo(repo); return True

    @staticmethod
    def _repo_id(value: str) -> str:
        """Accept a full github.com URL or a bare owner/repo -> owner/repo, lowercased.

        GitHub itself is case-insensitive, and the ban was not: it was stored as typed
        but `prefilter.drop_banned` compares it to the signal title exactly, so a ban
        entered as `OpenAI/Whisper` never matched `openai/whisper` and the repo came
        back next run. `store.ban_repo` already lowercased for the `kept` half."""
        v = (value or "").strip().rstrip("/").lower()
        for pre in ("https://github.com/", "http://github.com/", "github.com/"):
            if v.startswith(pre):
                v = v[len(pre):]; break
        return v

    def ban_repo(self, value):
        store.ban_repo(self._repo_id(value)); return True

    def unban_repo(self, repo):
        store.unban_repo(self._repo_id(repo)); return True

    def list_banned(self):
        return store.list_banned()

    def _ask_save_path(self, run_id=None):
        import webview
        w = webview.windows[0]
        res = w.create_file_dialog(webview.SAVE_DIALOG,
                                   save_filename=_md_filename(run_id=run_id))
        if isinstance(res, (list, tuple)):
            return res[0] if res else None
        return res

    def save_md(self, path=None):
        from topicparser import export
        kept = self._md_topics()
        # Nothing kept from the last run means there is no file to write. Refuse BEFORE
        # the save dialog: asking where to put a file and only then declining is worse
        # than not asking. The UI keeps the button disabled until a run produces topics;
        # this is the same guard on the Python side.
        if not kept:
            return {"ok": False, "empty": True}
        if path is None:
            path = self._ask_save_path(run_id=next((t.get("run_id") for t in kept
                                                    if t.get("run_id")), None))
            if not path:
                return {"ok": False, "cancelled": True}
        export.write_markdown(kept, path, alerts=self._last_alerts)
        return {"ok": True, "path": path}
