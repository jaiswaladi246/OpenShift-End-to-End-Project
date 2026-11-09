# The OpenShift Python S2I image runs gunicorn with this module when gunicorn is installed.
from app import app as application  # noqa: F401
