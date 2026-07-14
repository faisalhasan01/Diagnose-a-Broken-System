@echo off
echo Starting Django Order Performance Analyzer...
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python manage.py runserver
pause
