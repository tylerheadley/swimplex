"""
run_model.py — Run Swimplex_time.mod on a generated .dat file.

Usage:
    python3 model/run_model.py [--dat PATH] [--home-team TEAM] [--solver SOLVER]

Defaults:
    --dat        data/2025-26/best_performances_men.dat
    --home-team  value from param home_team in the .dat file
    --solver     gurobi
"""

import argparse
import os
import time
import sys
import json
import threading
import psutil

from amplpy import AMPL, add_to_path
add_to_path("/Applications/AMPL")

class MemoryTracker:
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.process  = psutil.Process(os.getpid())
        self.samples  = []           # list of (elapsed_s, rss_mb)
        self.checkpoints = {}        # name → rss_mb
        self._stop    = threading.Event()
        self._thread  = None
        self._t0      = None

    def _poll(self):
        while not self._stop.is_set():
            rss_mb = self.process.memory_info().rss / 1024 ** 2
            self.samples.append((time.perf_counter() - self._t0, rss_mb))
            time.sleep(self.interval)

    def start(self):
        self._t0 = time.perf_counter()
        self.samples.clear()
        self.checkpoints.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def checkpoint(self, name: str):
        rss_mb = self.process.memory_info().rss / 1024 ** 2
        elapsed = time.perf_counter() - self._t0
        self.checkpoints[name] = {"rss_mb": rss_mb, "elapsed_s": elapsed}
        print(f"  ✓ [{elapsed:6.1f}s]  {name:<30} {rss_mb:.1f} MB")

    def stop(self):
        self._stop.set()
        self._thread.join()

    # ── Reporting ─────────────────────────────────────────────────────────────
    def report(self):
        if not self.samples:
            print("No samples recorded.")
            return

        times, rss_vals = zip(*self.samples)
        baseline = rss_vals[0]
        peak     = max(rss_vals)

        print("\n" + "=" * 50)
        print("  MEMORY REPORT (psutil RSS)")
        print("=" * 50)
        print(f"  Baseline : {baseline:.1f} MB")
        print(f"  Peak     : {peak:.1f} MB")
        print(f"  Delta    : {peak - baseline:.1f} MB")
        print(f"  Duration : {times[-1]:.1f} s")

        if self.checkpoints:
            print("\n  ── Checkpoints ──────────────────────────────")
            prev = baseline
            for name, data in self.checkpoints.items():
                delta = data["rss_mb"] - prev
                sign  = "+" if delta >= 0 else ""
                print(f"  {name:<30} {data['rss_mb']:6.1f} MB  ({sign}{delta:.1f} MB)  @ {data['elapsed_s']:.4f}s")
                prev  = data["rss_mb"]
        print("=" * 50)

    def plot(self, save_path: str = "model/memory_usage.png"):
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed — skipping plot.")
            return

        times, rss_vals = zip(*self.samples)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(times, rss_vals, color="#2563eb", linewidth=1.5, label="RSS (MB)")
        ax.fill_between(times, rss_vals, alpha=0.1, color="#2563eb")

        for name, data in self.checkpoints.items():
            ax.axvline(data["elapsed_s"], color="#dc2626", linestyle="--",
                       linewidth=1, alpha=0.7)
            ax.text(data["elapsed_s"], max(rss_vals) * 0.97, name,
                    rotation=45, fontsize=7, color="#dc2626", ha="right")

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("RSS (MB)")
        ax.set_title("AMPL Model — Peak Memory Usage (psutil)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(save_path, dpi=150)
        print(f"\nPlot saved → {save_path}")
        plt.show()



REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_FILE  = os.path.join(REPO_ROOT, "model", "Swimplex_time.mod")
DEFAULT_DAT = os.path.join(REPO_ROOT, "data", "2025-26", "best_performances_men.dat")

def parse_args():
    p = argparse.ArgumentParser(description="Run Swimplex AMPL model")
    p.add_argument("--dat",       default=DEFAULT_DAT, help="Path to .dat file")
    p.add_argument("--home-team", default=None,        help="Override home_team param")
    p.add_argument("--solver",    default="gurobi",    help="AMPL solver name")
    p.add_argument("--output",    default="model_test",    help="Pickled output name")
    return p.parse_args()


def main():

    tracker = MemoryTracker(interval=0.0000001)
    tracker.start()
    tracker.checkpoint("baseline")

    args = parse_args()

    if not os.path.isfile(args.dat):
        sys.exit(f"ERROR: dat file not found: {args.dat}")
    if not os.path.isfile(MOD_FILE):
        sys.exit(f"ERROR: mod file not found: {MOD_FILE}")

    print(f"Model : {MOD_FILE}")
    print(f"Data  : {args.dat}")
    print(f"Solver: {args.solver}")
    tracker.checkpoint("model_dat_load")

    ampl = AMPL()
    ampl.read(MOD_FILE)
    ampl.read_data(args.dat)
    ampl.set_option("solver", args.solver)
    ampl.set_option("gurobi_options", "iisfind=1 outlev=1")
    ampl.set_option("gurobi_options", "mipgap=0.01")

    if args.home_team:
        ampl.param["home_team"] = args.home_team
        print(f"home_team overridden → {args.home_team}")

    home_team = ampl.param["home_team"].value()
    print(f"home_team : {home_team}\n")
    ampl.eval("objective AdversaryResponse;")
    tracker.checkpoint("Pre-solve")
    ampl.solve()
    tracker.checkpoint("solved")
    solve_result = ampl.get_value("solve_result")
    print(f"\nSolve result: {solve_result}")

    if solve_result == "infeasible":
        print("\n--- INFEASIBILITY DETECTED ---")
        ampl.eval("suffix iis OUT;")
        ampl.set_option("gurobi_options", "iisfind=1 outlev=1")
        for name, con in ampl.get_constraints():
            for index, instance in con:
                iis_values = instance.get_values("iis").toList()
                if iis_values and iis_values[0] != "non":
                    print(f"  Conflict: {name}[{index}]")
        return

    obj_val = ampl.get_value("TotalPoints")
    print(f"Objective (TotalPoints): {obj_val:.1f}")

    # ── Relay placements ──────────────────────────────────────────────────────
    try:
        placement_values = ampl.get_variable("placement").get_values().to_dict()
        if placement_values:
            print(f"\n{'RELAY EVENT':<25} {'Level':<6} {'Place'}")
            print("-" * 42)
            for (event, level), place in sorted(placement_values.items()):
                print(f"  {event:<23} {level:<6} {int(place)}")
    except Exception as e:
        print(f"(relay placement unavailable: {e})")

    # ── Solo placements ───────────────────────────────────────────────────────
    try:
        solo_place  = ampl.get_variable("placement_solo").get_values().to_dict()
        solo_swims  = ampl.get_variable("athlete_swims_event_solo").get_values().to_dict()
        if solo_place:
            print(f"\n{'SOLO EVENT':<20} {'Athlete':<35} {'Place'}")
            print("-" * 60)
            for (event, athlete), place in sorted(solo_place.items()):
                if solo_swims.get((athlete, event), 0) == 1 or solo_swims.get((event, athlete), 0) == 1:
                    print(f"  {event:<18} {athlete:<35} {int(place)}")
    except Exception as e:
        print(f"(solo placement unavailable: {e})")

    # ── Medley placements ─────────────────────────────────────────────────────
    try:
        med_values = ampl.get_variable("placement_med").get_values().to_dict()
        if med_values:
            print(f"\n{'MEDLEY EVENT':<25} {'Level':<6} {'Place'}")
            print("-" * 42)
            for (event, level), place in sorted(med_values.items()):
                print(f"  {event:<23} {level:<6} {int(place)}")
    except Exception as e:
        print(f"(medley placement unavailable: {e})")

    # ── Roster: who is assigned as a scorer ───────────────────────────────────
    try:
        scorer_values = ampl.get_variable("scorer").get_values().to_dict()
        scorers = [a for (a, t), v in scorer_values.items() if t == home_team and v == 1]
        print(f"\n{'SCORERS for ' + home_team} ({len(scorers)}):")
        for a in sorted(scorers):
            print(f"  {a}")
    except Exception as e:
        print(f"(scorer list unavailable: {e})")

    #Saves solution state as a json
    solution_json = ampl.get_solution()
    with open("solution_state.json", "w") as f:
        json.dump(solution_json, f)
    
    ampl.display("is_scorer")
    ampl.display("scorer_val")

    ampl.close()
    tracker.checkpoint("ampl_closed")

    tracker.stop()
    tracker.report()
    tracker.plot()

if __name__ == "__main__":
    main()
