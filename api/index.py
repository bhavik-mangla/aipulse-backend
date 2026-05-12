import os
import sys

# Add the src directory to the Python path so govnotify can be imported
# repo/api/index.py -> repo/src is at ../src
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from govnotify.main import app

# Vercel needs the app object to be exposed at the module level
# We'll use this file as the entrypoint
