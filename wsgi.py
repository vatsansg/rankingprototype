"""
Production WSGI entry point for gunicorn / Azure App Service (Oryx expects a root-level
wsgi.py or app.py exposing a WSGI-callable named `app`). web/app.py stays where it is --
this is a two-line shim, not a duplicate of the application.
"""

from web.app import app

if __name__ == "__main__":
    app.run()
