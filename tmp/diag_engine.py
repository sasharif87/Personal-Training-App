import sys
import os

# Add the bootstrap directory to path
sys.path.append(r"e:\Personal training app\Scripts\boot strap")

try:
    from engine import Engine
    print("SUCCESS: Imported Engine")
except ImportError as e:
    print(f"FAILURE: Could not import Engine: {e}")
    sys.exit(1)

# Test instantiation and connection
url = "http://192.168.50.46:11434"
print(f"Testing connection to {url}...")
engine = Engine(url=url)

ok, models, msg = engine.test()
if ok:
    print(f"SUCCESS: {msg}")
    print(f"Available models: {models}")
    
    # Check model resolution
    print("\nModel Map:")
    engine.print_model_map()
else:
    print(f"FAILURE: {msg}")
