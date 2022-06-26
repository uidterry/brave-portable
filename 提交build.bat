@echo off
git tag -d 1.40.107-86
git add .
git commit -m "v1.40.107"
git push
pause
