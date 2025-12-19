import sys
from pathlib import Path

# Add the package source to the Python path for testing
package_src = Path(__file__).parent / "packages" / "idempotency-lib" / "src"
sys.path.insert(0, str(package_src))
