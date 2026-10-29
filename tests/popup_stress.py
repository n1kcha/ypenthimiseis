"""Σενάριο αντοχής για το κλείσιμο της υπενθύμισης (τρέχει σε ξεχωριστή διεργασία από το
test_popup_close_does_not_crash_process, γιατί ένα Tcl_Panic σκοτώνει όλη τη διεργασία).

Όπως στην εφαρμογή: το Overlay ζει σε νήμα υπενθυμίσεων, ενώ το κύριο νήμα (όπως το tray)
τρέχει συνεχώς τον GC. Κάθε υπενθύμιση κλείνει με κλικ στα κουμπιά, Enter ή Esc."""
import gc
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


class Eng:
    def __init__(self):
        self.cfg = {"store_name": "Κατάστημα", "sound": False}
        self.calls = []

    def dismiss(self, k):
        self.calls.append(("dismiss", k))

    def snooze(self, k, m):
        self.calls.append(("snooze", k, m))


def main(n: int) -> int:
    done = threading.Event()
    out = {}

    def worker():
        eng = Eng()
        ov = app.Overlay(eng)
        ov.KEY_GUARD_SECONDS = 0
        base = ov.ensure_base()
        fallbacks = []
        for i in range(n):
            mode = ("click_ok", "click_snooze", "enter", "esc")[i % 4]
            ev = {"key": f"k{i}", "title": "Τίτλος " * (i % 7 + 1),
                  "description": "Κείμενο. " * (i * 5), "start": datetime(2026, 10, 29, 12, 0)}

            def act(mode=mode):
                win = ov.root
                if win is None:
                    return
                c = win.winfo_children()[0]
                if mode.startswith("click"):
                    word = "ΕΙΔΑ" if mode == "click_ok" else "λεπτά"
                    it = [t for t in c.find_all()
                          if c.type(t) == "text" and word in c.itemcget(t, "text")][0]
                    x1, y1, x2, y2 = c.bbox(it)
                    x, y = (x1 + x2) // 2, (y1 + y2) // 2
                    c.event_generate("<Motion>", x=x, y=y, warp=True)
                    c.event_generate("<ButtonPress-1>", x=x, y=y)
                    c.event_generate("<ButtonRelease-1>", x=x, y=y)
                    c.event_generate("<Motion>", x=2, y=2)

                    def direct(win=win, it=it):
                        # Αν ο δείκτης του συστήματος (CI) «έκλεψε» το κλικ: ο ίδιος
                        # χειριστής κλικ του κουμπιού, μέσα από callback του Tk.
                        if ov.root is win and ov._painter is not None:
                            txt = c.itemcget(it, "text")
                            ov._painter.clicks[txt](None)
                    base.after(1500, direct)
                else:
                    win.focus_force()
                    win.update()
                    win.event_generate("<Return>" if mode == "enter" else "<Escape>", when="tail")

            def fallback(mode=mode):
                if ov.root is not None:  # π.χ. χωρίς εστίαση πληκτρολογίου στο CI
                    fallbacks.append(mode)
                    ov._dismiss()

            base.after(150, act)
            guard = base.after(6000, fallback)
            ov.show(ev, (i % 3 + 1, 3))
            base.after_cancel(guard)
            for _ in range(3):
                ov.pump()
                time.sleep(0.01)
            gc.collect()
        out["calls"], out["fallbacks"] = eng.calls, fallbacks
        done.set()

    t = threading.Thread(target=worker, daemon=True, name="reminders")
    t.start()
    while not done.is_set():
        gc.collect()  # «άλλο νήμα» που τρέχει τον GC, όπως το tray
        time.sleep(0.005)
    t.join()
    gc.collect()
    clicks = sum(1 for m in out["fallbacks"] if m.startswith("click"))
    print(f"calls={len(out['calls'])} click_fallbacks={clicks} key_fallbacks="
          f"{len(out['fallbacks']) - clicks} first={out['calls'][:4]}")
    print("ALIVE")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
