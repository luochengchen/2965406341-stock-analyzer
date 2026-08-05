#!/bin/bash
export FLASK_APP=web_app.py
gunicorn web_app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
