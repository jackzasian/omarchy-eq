"""Put lib/ on the path for the test modules."""
import os
import sys

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
if LIB not in sys.path:
    sys.path.insert(0, LIB)
