"""Application-wide constants and the production/test timing switch."""

import sys
from zoneinfo import ZoneInfo


# Streamlit passes script arguments after ``--``.  For example:
# ``streamlit run run_timer_app.py -- --test``.
TESTING_MODE = "--test" in sys.argv
TIME_UNIT = "seconds" if TESTING_MODE else "minutes"
REFRESH_INTERVAL = 1.0

DEFAULT_INITIAL_ANESTHESIA = 45
DEFAULT_SUBSEQUENT_ANESTHESIA = 30
DEFAULT_ANESTHESIA_DELAY = 5
DEFAULT_NOTIFICATION_SOUND_ENABLED = True
DEFAULT_NOTIFICATION_SOUND = "Chime"
NOTIFICATION_SOUND_OPTIONS = ["Chime", "Beep", "Double beep"]
ANESTHESIA_DOSE_VOLUME_ML_PER_G = 0.01

FIXED_BOARD_DURATION = 10
FIXED_SHOCK_DURATION = 60
FIXED_RESUSCITATION_DURATION = 20

INITIAL_MOUSE_COUNT = 8
WARNING_UNITS = 1
APP_TIMEZONE = "America/New_York"
STATE_VERSION = "lab_multitimer_v61_refactored"

UNIT_SECONDS = 1.0 if TIME_UNIT == "seconds" else 60.0
UNIT_SHORT = "s" if TIME_UNIT == "seconds" else "m"
UNIT_LABEL = "sec" if TIME_UNIT == "seconds" else "min"
UNIT_WORD = "seconds" if TIME_UNIT == "seconds" else "minutes"
TEST_WEIGHT_MIN_G = 22.0
TEST_WEIGHT_MAX_G = 35.0

APP_TZ = ZoneInfo(APP_TIMEZONE)
RUNNING_ROW_COLUMNS = [1.38, 1.14, 0.74, 3.22, 1.96, 0.18, 1.58]
RUNNING_ACTION_COLUMNS = [1.0, 0.28]
HEADER_COLUMNS = [1.02, 4.10, 0.90, 0.88, 1.42, 1.22, 0.88]
CONFIGURATION_COLUMNS = [0.58, 3.52, 1.58, 0.58]
