@echo off
rem Start the GMS web dashboard without connecting to the Stormshield firewall.
rem Same as: run_gms_web.bat --no-sns-autoconnect  (extra arguments are passed on).
rem The firewall can still be connected later from the dashboard's Firewall section.
call "%~dp0run_gms_web.bat" --no-sns-autoconnect %*
exit /b %ERRORLEVEL%
