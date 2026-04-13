import os
from sound_cut.api import run_api

run_api(host="0.0.0.0", port=int(os.environ.get("PORT", 8766)))
