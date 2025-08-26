import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python"))

from cantor_runtime import CantorScalingRuntime

runtime = CantorScalingRuntime()

print("Done")