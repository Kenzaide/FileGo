@echo off
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File ""%~dp0scripts\allow-firewall.ps1""'"
