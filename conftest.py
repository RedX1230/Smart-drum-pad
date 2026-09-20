import os
import sys

# Make ``import src.<module>`` work when pytest is run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
