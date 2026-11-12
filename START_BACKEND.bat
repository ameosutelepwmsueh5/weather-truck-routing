@echo off
cd /d "%~dp0backend"
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt
python manage.py runserver
pause
