import os
import time

SCHEDULER_SLEEP_SECONDS = int(os.getenv("SCHEDULER_SLEEP_SECONDS") or 60)

def run_scheduler():
    while True:
        try:
            print("Nothing to do!")
            pass
            #TODO: do some work
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(SCHEDULER_SLEEP_SECONDS)  # 1 minute

if __name__ == "__main__":
    print("Starting scheduler...")
    run_scheduler()