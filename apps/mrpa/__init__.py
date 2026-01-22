"""MobileRPA package."""

import sys as _sys

# Ensure "mrpa" imports resolve when running as "apps.mrpa".
_sys.modules.setdefault("mrpa", _sys.modules[__name__])
