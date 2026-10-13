import sys
from slowapi import Limiter
from slowapi.util import get_remote_address

is_testing = "pytest" in sys.modules or any("pytest" in arg for arg in sys.argv)
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"], enabled=not is_testing)
